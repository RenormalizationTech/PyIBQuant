"""Recovery never treats missing callbacks as permission to repeat an order."""

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from test_broker import Adapter, drain, status
from test_broker import broker as broker

from pyibquant import BrokerError, OrderWaitError, PaperBroker


def execution(b, *, quantity="1", price="99", exec_id="execution-1"):
    b.enqueue(
        "execution",
        dict(
            exec_id=exec_id,
            client_id=272,
            order_id=10,
            con_id=100,
            currency="USD",
            side="BOT",
            cumulative_quantity=quantity,
            quantity=quantity,
            price=price,
        ),
    )
    drain(b)


def test_wait_wakes_on_partial_fill_then_returns_immutable_terminal(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    with ThreadPoolExecutor() as pool:
        result = pool.submit(broker.wait_order, 10, timeout=1)
        status(broker, "Submitted", ".5", ".5")
        status(broker, "Filled", "1", "0")
        order = result.result(timeout=2)
    assert order["filled"] == "1"
    with pytest.raises(TypeError):
        order["filled"] = "0"


def test_timeout_keeps_partial_evidence_and_does_not_cancel(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100)
    status(broker, "Submitted", ".5", ".5")
    with pytest.raises(OrderWaitError, match="unresolved") as error:
        broker.wait_order(10, timeout=0)
    assert Decimal(error.value.last_order["filled"]) == Decimal(".5")
    broker._adapter.cancel_order.assert_not_called()
    assert broker._adapter.send_order.call_count == 1


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf"), True])
def test_invalid_wait_timeout(broker, timeout):
    with pytest.raises(ValueError):
        broker.wait_order(10, timeout=timeout)


def test_wait_unknown_rejected_and_disconnect_does_not_hide_terminal_evidence(broker):
    with pytest.raises(OrderWaitError, match="Unknown"):
        broker.wait_order(99)
    broker.submit_limit("AAPL", "BUY", 1, 100)
    broker.enqueue("disconnected", dict(message="test disconnect"))
    drain(broker)
    with pytest.raises(OrderWaitError, match="uncertain"):
        broker.wait_order(10)
    status(broker, "Cancelled")
    assert broker.wait_order(10)["status"] == "Cancelled"


def test_restart_retains_missing_intent_without_resending(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    path = broker.journal.path
    broker.close()
    with PaperBroker(Adapter(), path, account="DUABC123") as replacement:
        report = replacement.reconcile()
        assert report.snapshot.complete and not report.clear
        assert len(report.missing_orders) == 1
        assert report.missing_orders[0]["tag"] == "strategy"
        assert replacement.funding()["usable"] is None
        replacement._adapter.send_order.assert_not_called()
        replacement._adapter.cancel_order.assert_not_called()


def test_reconcile_absence_does_not_clear_order_but_observed_execution_resolves_it(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100)
    assert len(broker.reconcile().missing_orders) == 1
    execution(broker)
    assert broker.reconcile().clear


def test_other_client_working_orders_block_recovery_and_cannot_be_canceled(broker):
    broker.enqueue(
        "order",
        dict(
            order_id=8,
            client_id=400,
            order_ref="pyibquant:other",
            quantity="1",
            filled="0",
            status="Submitted",
            tag="strategy",
        ),
    )
    drain(broker)
    report = broker.reconcile()
    assert not report.clear and len(report.foreign_orders) == 1
    assert broker.cancel_owned_orders(tag="strategy") == ()
    broker._adapter.cancel_order.assert_not_called()
    with pytest.raises(BrokerError, match="outstanding"):
        broker.submit_limit("AAPL", "BUY", 1, 100)


def test_bulk_cancel_exact_tag_fill_race_and_repeat_is_noop(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    assert broker.cancel_owned_orders(tag="other") == ()
    broker._adapter.cancel_order.side_effect = lambda oid: broker.enqueue(
        "order_status",
        dict(order_id=oid, client_id=272, status="Filled", filled="1", remaining="0"),
    )
    results = broker.cancel_owned_orders(tag="strategy", timeout=1)
    assert results[0]["status"] == "Filled"
    assert broker.cancel_owned_orders(tag="strategy") == ()
    broker._adapter.cancel_order.assert_called_once_with(10)


def test_ledger_requires_executions_and_keeps_fees_unknown_until_reported(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    status(broker, "Filled", "1", "0")
    assert not broker.strategy_ledger("strategy").complete
    execution(broker)
    execution(broker)  # duplicate callback, not a second fill
    ledger = broker.strategy_ledger("strategy")
    assert ledger.complete and ledger.positions == ((100, Decimal(1)),)
    assert ledger.cash_flow == -99 and ledger.execution_count == 1
    assert ledger.commissions is None
    broker.enqueue("fee", dict(exec_id="execution-1", commission=".35", fee_currency="USD"))
    drain(broker)
    assert broker.strategy_ledger("strategy").commissions == Decimal(".35")
    assert broker.strategy_ledger("other").positions == ()
    path = broker.journal.path
    broker.close()
    with PaperBroker(Adapter(), path, account="DUABC123") as replacement:
        assert replacement.strategy_ledger("strategy") == broker.strategy_ledger("strategy")


def test_conflicting_execution_cannot_establish_strategy_ownership(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    execution(broker, price="0")
    ledger = broker.strategy_ledger("strategy")
    assert not ledger.complete and ledger.positions == ()


def test_export_masks_account_and_does_not_invent_open_position_profit(broker, tmp_path):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    execution(broker)
    path = broker.export_strategy("strategy", tmp_path / "audit.json")
    result = json.loads(path.read_text())
    assert "DUABC123" not in path.read_text()
    assert result["ledger"]["realized_pnl"] is None
    assert result["ledger"]["cash_flow"] == "-99"
    assert len(result["orders"]) == len(result["executions"]) == 1
    assert path.stat().st_mode & 0o777 == 0o600


def test_flat_strategy_profit_requires_all_fills_and_known_usd_fees(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    execution(broker)
    broker._record("fee", dict(exec_id="execution-1", commission=".35", fee_currency="USD"))
    broker._record(
        "intent",
        dict(
            order_id=11,
            client_id=272,
            order_ref="pyibquant:close",
            tag="strategy",
            con_id=100,
            side="SELL",
            quantity="1",
            filled="0",
            status="PendingSubmit",
        ),
    )
    broker._record(
        "execution",
        dict(
            exec_id="execution-2",
            order_id=11,
            client_id=272,
            con_id=100,
            currency="USD",
            side="SLD",
            quantity="1",
            price="101",
            cumulative_quantity="1",
        ),
    )
    ledger = broker.strategy_ledger("strategy")
    assert ledger.complete and ledger.cash_flow == 2
    assert ledger.to_dict()["realized_pnl"] is None
    broker._record("fee", dict(exec_id="execution-2", commission=".35", fee_currency="USD"))
    assert broker.strategy_ledger("strategy").to_dict()["realized_pnl"] == "1.30"


def test_unconfirmed_cancel_keeps_identity_and_never_resends(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100, tag="strategy")
    with pytest.raises(OrderWaitError, match="unresolved"):
        broker.cancel_owned_orders(tag="strategy", timeout=0)
    assert broker.snapshot().orders[0]["status"] == "PendingSubmit"
    assert broker.funding()["usable"] is None
    broker._adapter.cancel_order.assert_called_once_with(10)
    broker._adapter.send_order.assert_called_once()

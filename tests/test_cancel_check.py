"""Cancellation checks distinguish a cancel, a fill, a rejection and uncertainty."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_broker import broker as broker
from test_broker import drain, status
from test_paper_runner import feed, quote

from pyibquant import BrokerError, OrderWaitError
from pyibquant.trading.cancel_check import (
    CancellationPlan,
    check_tag,
    execute_check,
    execute_disconnect_check,
    finish_check,
    flat_preflight,
    make_plan,
)
from pyibquant.trading.profile import PaperProfile


def test_disconnect_after_send_retains_one_intent_and_never_cancels_or_retries(broker, plan):
    def disconnect():
        broker._adapter.isConnected.return_value = False
        broker.enqueue("disconnected", dict(message="injected socket loss"))
        drain(broker)

    broker._adapter.disconnect = Mock(side_effect=disconnect)
    original = broker._adapter.send_order
    result = execute_disconnect_check(broker, plan)
    assert result["outcome"] == "disconnected_after_send" and result["needs_recovery"]
    assert not result["passed"] and result["send_attempts"] == 1
    assert result["status"] == "UnknownSend"
    assert broker._adapter.send_order is original
    original.assert_called_once()
    broker._adapter.cancel_order.assert_not_called()
    assert broker.funding()["pending_owned_order"]
    with pytest.raises(BrokerError, match="already has an order"):
        execute_disconnect_check(broker, plan)
    original.assert_called_once()


def test_disconnect_recovery_missing_order_blocks_cancellation_and_replacement(broker, plan):
    broker._adapter.disconnect = Mock()
    execute_disconnect_check(broker, plan)
    with pytest.raises(BrokerError, match="remains missing"):
        finish_check(broker, plan.check_id)
    broker._adapter.cancel_order.assert_not_called()
    broker._adapter.send_order.assert_called_once()


def test_disconnect_recovery_observes_original_then_cancels_exact_order(broker, plan):
    broker._adapter.disconnect = Mock()
    execute_disconnect_check(broker, plan)
    original_refresh = broker._adapter.refresh

    def refresh(account):
        original_refresh(account)
        broker.enqueue("order", dict(
            account=broker.account, order_id=10, client_id=272, status="Submitted",
            order_ref="pyibquant:" + plan.check_id, filled="0", remaining="1",
        ))
        drain(broker)

    broker._adapter.refresh = refresh
    cancel(broker)
    result = finish_check(broker, plan.check_id)
    assert result["passed"] and result["acknowledged"] and result["flat"]
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_called_once_with(10)


def test_transport_failure_before_injection_remains_unconfirmed_without_an_extra_send(broker, plan):
    broker._adapter.send_order.side_effect = OSError("original socket write failed")
    broker._adapter.disconnect = Mock()
    with pytest.raises(BrokerError, match="unknown"):
        execute_disconnect_check(broker, plan)
    broker._adapter.send_order.assert_called_once()
    broker._adapter.disconnect.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()


@pytest.fixture
def plan(broker):
    return CancellationPlan(
        "a" * 32, "AAPL", 100, Decimal("98"), Decimal("100"), Decimal("100.02"), datetime.now(UTC)
    )


@pytest.fixture(autouse=True)
def fast_waits(broker, monkeypatch):
    ticks = count()
    monkeypatch.setattr("pyibquant.trading.cancel_check.monotonic", lambda: next(ticks))
    broker.wait_for_update = Mock(side_effect=lambda *args, **kwargs: broker.snapshot())


def acknowledge(broker):
    broker._adapter.send_order.side_effect = lambda *args: status(broker, "Submitted")


def cancel(broker):
    broker._adapter.cancel_order.side_effect = lambda oid: broker.enqueue(
        "order_status",
        dict(order_id=oid, client_id=272, status="Cancelled", filled="0", remaining="0"),
    )


def fill(broker):
    broker._record(
        "execution",
        dict(
            exec_id="fill-1",
            client_id=272,
            order_id=10,
            con_id=100,
            side="BOT",
            currency="USD",
            quantity="1",
            cumulative_quantity="1",
            price="98",
        ),
    )
    broker._record("fee", dict(exec_id="fill-1", commission="1", fee_currency="USD"))
    broker.enqueue(
        "order_status", dict(order_id=10, client_id=272, status="Filled", filled="1", remaining="0")
    )
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue("position", dict(con_id=100, symbol="AAPL", quantity="1"))
        drain(broker)

    broker._adapter.refresh = refresh


def test_acknowledged_unfilled_cancel_passes_and_repeat_never_resubmits(broker, plan):
    acknowledge(broker)
    cancel(broker)
    result = execute_check(broker, plan)
    assert result["passed"] and result["outcome"] == "canceled_unfilled"
    assert result["status"] == "Cancelled" and result["filled"] == "0"
    assert result["flat"] and result["reconciled"] and not result["pending_owned_order"]
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_called_once_with(10)
    assert finish_check(broker, plan.check_id)["passed"]
    broker._adapter.cancel_order.assert_called_once_with(10)
    with pytest.raises(BrokerError, match="already has an order"):
        execute_check(broker, plan)
    broker._adapter.send_order.assert_called_once()


@pytest.mark.parametrize("when", ["before_ack", "cancel_race"])
def test_fill_is_reported_and_retained_without_reversal(broker, plan, when):
    if when == "before_ack":
        broker._adapter.send_order.side_effect = lambda *args: fill(broker)
    else:
        acknowledge(broker)
        broker._adapter.cancel_order.side_effect = lambda oid: fill(broker)
    result = execute_check(broker, plan)
    assert not result["passed"] and result["outcome"] == "fill_observed"
    assert result["filled"] == "1" and not result["flat"]
    assert broker.snapshot().positions[0]["quantity"] == "1"
    broker._adapter.send_order.assert_called_once()
    assert result["ledger"]["positions"] == [{"con_id": 100, "quantity": "1"}]


def test_missing_acknowledgment_does_not_pass_even_if_cleanup_cancels(broker, plan):
    cancel(broker)
    result = execute_check(broker, plan)
    assert not result["passed"] and not result["acknowledged"]
    assert result["status"] == "Cancelled" and result["filled"] == "0"
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_called_once()


def test_rejected_order_is_not_a_successful_cancel(broker, plan):
    broker._adapter.send_order.side_effect = lambda *args: status(broker, "Inactive")
    result = execute_check(broker, plan)
    assert not result["passed"] and result["status"] == "Inactive"
    broker._adapter.cancel_order.assert_not_called()
    broker._adapter.send_order.assert_called_once()


def test_unconfirmed_cancel_retains_identity_and_reservation(broker, plan):
    acknowledge(broker)
    original = broker.wait_order
    broker.wait_order = Mock(side_effect=lambda oid, **kwargs: original(oid, timeout=0))
    with pytest.raises(OrderWaitError):
        execute_check(broker, plan)
    assert broker.funding()["pending_owned_order"]
    assert broker.snapshot().orders[0]["order_ref"] == "pyibquant:" + plan.check_id
    broker._adapter.send_order.assert_called_once()
    # Recovery can cancel the original order after communication returns.
    cancel(broker)
    broker.wait_order = original
    assert finish_check(broker, plan.check_id)["passed"]
    broker._adapter.send_order.assert_called_once()


def test_interrupted_wait_still_cleans_up_only_this_check(broker, plan):
    acknowledge(broker)
    cancel(broker)
    broker.wait_for_update.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        execute_check(broker, plan)
    assert broker.snapshot().orders[0]["status"] == "Cancelled"
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_called_once_with(10)


def test_partial_fill_canceled_remainder_is_not_an_unfilled_cancel(broker, plan):
    acknowledge(broker)

    def partial(oid):
        broker._record(
            "execution",
            dict(
                exec_id="partial",
                client_id=272,
                order_id=oid,
                con_id=100,
                side="BOT",
                currency="USD",
                quantity=".5",
                cumulative_quantity=".5",
                price="98",
            ),
        )
        broker.enqueue(
            "order_status",
            dict(
                order_id=oid,
                client_id=272,
                status="Cancelled",
                filled=".5",
                remaining=".5",
            ),
        )

    broker._adapter.cancel_order.side_effect = partial
    result = execute_check(broker, plan)
    assert not result["passed"] and result["outcome"] == "fill_observed"
    assert result["filled"] == "0.5"
    broker._adapter.send_order.assert_called_once()


def test_cleanup_never_cancels_a_different_tag(broker, plan):
    acknowledge(broker)
    original = cancel
    original(broker)
    cancel_target = broker._adapter.cancel_order.side_effect

    def cancel_with_unrelated(oid):
        broker._record(
            "intent",
            dict(
                order_id=20,
                client_id=272,
                order_ref="pyibquant:other",
                tag="unrelated",
                status="Submitted",
                quantity="1",
                filled="0",
                remaining="1",
            ),
        )
        cancel_target(oid)

    broker._adapter.cancel_order.side_effect = cancel_with_unrelated
    result = execute_check(broker, plan)
    assert not result["passed"] and not result["reconciled"]
    broker._adapter.cancel_order.assert_called_once_with(10)
    assert next(o for o in broker.snapshot().orders if o["order_id"] == 20)["status"] == "Submitted"


def test_unknown_send_is_cleaned_up_without_a_second_submission(broker, plan):
    broker._adapter.send_order.side_effect = OSError("socket write outcome unknown")
    cancel(broker)
    with pytest.raises(BrokerError, match="Send outcome unknown"):
        execute_check(broker, plan)
    assert broker.snapshot().orders[0]["status"] == "Cancelled"
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_called_once_with(10)


def test_readonly_recovery_does_not_cancel_and_unknown_check_does_not_submit(broker, plan):
    acknowledge(broker)
    broker.submit_limit("AAPL", "BUY", 1, 98, tag=plan.tag, key=plan.check_id)
    broker.readonly = True
    result = finish_check(broker, plan.check_id)
    assert not result["passed"] and not result["order_transmission"]
    broker._adapter.cancel_order.assert_not_called()
    with pytest.raises(BrokerError, match="Expected one"):
        finish_check(broker, "b" * 32)
    broker._adapter.send_order.assert_called_once()


@pytest.mark.parametrize("change", ["readonly", "stale", "position", "foreign_order", "identity"])
def test_execution_preconditions_block_before_any_send(broker, plan, change):
    if change == "readonly":
        broker.readonly = True
    elif change == "stale":
        plan = replace(plan, checked_at=datetime.now(UTC) - timedelta(seconds=11))
    elif change == "identity":
        broker._adapter.resolve.return_value.conId = 101
    else:
        original = broker._adapter.refresh

        def refresh(account):
            original(account)
            if change == "position":
                broker.enqueue("position", dict(con_id=100, quantity="1"))
            else:
                broker.enqueue("order", dict(order_id=20, client_id=400, status="Submitted"))
            drain(broker)

        broker._adapter.refresh = refresh
    with pytest.raises(BrokerError):
        execute_check(broker, plan)
    broker._adapter.send_order.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()


def test_plan_uses_fresh_provider_session_and_cash_budget(broker):
    at = datetime.now(UTC)
    series = feed()
    series.asset_type, series.currency = "equity", "USD"
    series.sessions = [dict(regular=True, start=at.timestamp() - 60, end=at.timestamp() + 60)]
    flat_preflight(broker)
    result = make_plan(broker, series, quote(at), at=at)
    assert result.limit_price == Decimal("98.00") and result.symbol == "AAPL"
    assert result.to_dict()["quantity"] == 1
    broker._adapter.send_order.assert_not_called()


@pytest.mark.parametrize("change", ["session", "stale", "delayed", "funds", "asset", "cap"])
def test_invalid_market_or_funding_evidence_cannot_build_a_plan(broker, change):
    at = datetime.now(UTC)
    series = feed()
    series.asset_type, series.currency = "equity", "USD"
    series.sessions = [dict(regular=True, start=at.timestamp() - 60, end=at.timestamp() + 60)]
    q = quote(at)
    if change == "session":
        series.sessions = []
    elif change == "stale":
        q = quote(at - timedelta(seconds=11))
    elif change == "delayed":
        q.is_delayed = True
    elif change == "funds":
        broker._record("value", dict(tag="SettledCash", currency="USD", value="99"))
    elif change == "asset":
        series.asset_type = "OPT"
    else:
        broker.max_order_value = Decimal("50")
    with pytest.raises(BrokerError):
        make_plan(broker, series, q, at=at)
    broker._adapter.send_order.assert_not_called()


@pytest.mark.parametrize("value", ["", "../bad", "a" * 31, "A" * 32, None])
def test_check_ids_are_exact_and_path_safe(value):
    with pytest.raises(ValueError):
        check_tag(value)


def test_default_cli_preflight_has_no_order_or_cancel_path(broker, tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "paper_cancel_example",
        Path(__file__).resolve().parents[1] / "examples/paper_cancel_check.py",
    )
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    broker.readonly = True
    at = datetime.now(UTC)
    series = feed()
    series.asset_type, series.currency = "equity", "USD"
    series.sessions = [dict(regular=True, start=at.timestamp() - 60, end=at.timestamp() + 60)]
    stream = Mock()
    stream.latest.return_value = quote(at)
    market = Mock()
    market.bars.return_value = series
    market.stream_quote.return_value = nullcontext(stream)
    connect = Mock(return_value=nullcontext(broker))
    monkeypatch.setattr(example.PaperBroker, "ibkr", connect)
    monkeypatch.setattr(example.Market, "ibkr", Mock(return_value=nullcontext(market)))
    monkeypatch.setattr(
        example.PaperProfile, "load", lambda _: PaperProfile(journal=broker.journal.path)
    )
    monkeypatch.setattr("sys.argv", ["paper_cancel_check.py"])
    monkeypatch.chdir(tmp_path)
    example.main()
    assert connect.call_args.kwargs["readonly"] is True
    assert connect.call_args.kwargs["paper_confirmed"] is False
    assert len(list(tmp_path.glob("charts/paper/cancel-checks/*/plan.json"))) == 1
    for path in tmp_path.glob("charts/paper/cancel-checks/*/*.json"):
        assert "DUABC123" not in path.read_text()
    assert not any(e["kind"] == "intent" for e in broker.journal.events())
    broker._adapter.send_order.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()

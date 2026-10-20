"""Quiet P&L is confirmed only by unchanged fresh, flat USD account evidence."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from test_broker import broker as broker
from test_broker import drain
from test_paper_runner import advance, feed, quote, running

from pyibquant import BrokerError, PaperBroker
from pyibquant.trading.runner import EquityRunner


def prime(broker):
    stamp = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    broker._record("pnl", dict(request_id=1, daily="0", unrealized="0", realized="0"), stamp)
    broker._record("pnl_validated", dict(request_id=1))
    assert broker._pnl_reference is not None
    broker.refresh_pnl = Mock(side_effect=BrokerError("Fresh P&L not delivered"))
    return stamp


def test_quiet_flat_zero_is_confirmed_without_renewing_or_restamping_pnl(broker):
    original = prime(broker)
    calls = broker._adapter.calls
    result = broker.refresh_risk()
    assert broker._adapter.calls == calls + 1
    assert result.pnl["risk_source"] == "flat_account_reconciliation"
    assert result.pnl["received_at"] == original
    assert result.pnl["risk_confirmed_at"] != original
    assert EquityRunner._fresh_pnl(result, datetime.now(UTC)) == 0
    assert broker.snapshot().pnl["received_at"] == original
    assert "risk_confirmed_at" not in broker.snapshot().pnl
    assert broker._validated_pnl["daily"] == "0"
    broker.refresh_pnl.assert_not_called()
    broker._adapter.send_order.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()


def test_runner_can_make_a_new_decision_with_confirmed_flat_risk(broker, monkeypatch):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    monkeypatch.setattr("pyibquant.broker.now", lambda: at.isoformat())
    broker.refresh_risk = PaperBroker.refresh_risk.__get__(broker)
    broker.refresh_pnl = Mock(side_effect=BrokerError("No replacement P&L callback"))
    broker.submit_limit = Mock(return_value=10)
    assert runner.step(series, quote(at), at=at) == 10
    assert runner.status == "running" and runner._pnl_baseline == 0
    broker.refresh_pnl.assert_not_called()
    broker.submit_limit.assert_called_once()
    runner.stop()


@pytest.mark.parametrize(
    "change",
    [
        "position",
        "unknown_position",
        "cash",
        "net_value",
        "foreign_cash",
        "working_order",
        "execution",
        "fee",
    ],
)
def test_changed_or_unknown_account_evidence_requires_real_pnl(broker, change):
    prime(broker)
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        if change in {"position", "unknown_position"}:
            broker.enqueue(
                "position", dict(con_id=100, quantity="1" if change == "position" else None)
            )
        elif change in {"cash", "net_value", "foreign_cash"}:
            tag = "NetLiquidation" if change == "net_value" else "CashBalance"
            broker.enqueue(
                "value",
                dict(tag=tag, currency="EUR" if change == "foreign_cash" else "USD", value="99"),
            )
        elif change == "working_order":
            broker.enqueue("order", dict(order_id=20, client_id=400, status="Submitted"))
        elif change == "execution":
            broker.enqueue(
                "execution",
                dict(
                    exec_id="new",
                    order_id=20,
                    client_id=400,
                    con_id=100,
                    quantity="1",
                    cumulative_quantity="1",
                    price="100",
                    side="BOT",
                ),
            )
        elif change == "fee":
            broker.enqueue("fee", dict(exec_id="late", commission="1", fee_currency="USD"))
        drain(broker)

    broker._adapter.refresh = refresh
    with pytest.raises(BrokerError, match="not delivered"):
        broker.refresh_risk()
    broker.refresh_pnl.assert_called_once()
    broker._adapter.send_order.assert_not_called()


def test_duplicate_execution_download_does_not_change_economic_proof(broker):
    fill = dict(
        exec_id="old",
        order_id=20,
        client_id=400,
        con_id=100,
        quantity="1",
        cumulative_quantity="1",
        price="100",
        side="BOT",
        currency="USD",
    )
    broker._record("execution", fill)
    prime(broker)
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue("execution", {**fill, "quantity": "1.0", "price": "100.00"})
        drain(broker)

    broker._adapter.refresh = refresh
    assert broker.refresh_risk().pnl["risk_source"] == "flat_account_reconciliation"
    broker.refresh_pnl.assert_not_called()


def test_missing_reference_or_failed_account_refresh_never_reuses_old_pnl(broker):
    broker.refresh_pnl = Mock(side_effect=BrokerError("No risk data"))
    with pytest.raises(BrokerError, match="No risk data"):
        broker.refresh_risk()
    prime(broker)
    broker._adapter.refresh = Mock(side_effect=BrokerError("Account disconnected"))
    with pytest.raises(BrokerError, match="disconnected"):
        broker.refresh_risk()
    broker.refresh_pnl.assert_not_called()


def test_pnl_change_invalidates_the_flat_reference(broker):
    prime(broker)
    broker._record("pnl", dict(request_id=1, daily="-1", unrealized="0", realized="-1"))
    assert broker._pnl_reference is None
    with pytest.raises(BrokerError, match="not delivered"):
        broker.refresh_risk()


def test_flat_confirmation_cannot_carry_yesterdays_daily_pnl_forward(broker):
    stamp = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    broker._record("pnl", dict(request_id=1, daily="0", unrealized="0", realized="0"), stamp)
    broker._record("pnl_validated", dict(request_id=1))
    broker.refresh_pnl = Mock(side_effect=BrokerError("Need today's P&L"))
    with pytest.raises(BrokerError, match="today"):
        broker.refresh_risk()


def test_initial_subscription_is_validated_without_a_replacement_request(broker, monkeypatch):
    monkeypatch.setattr("pyibquant.broker.PNL_SETTLE_SECONDS", 0)
    broker._adapter._pnl_id = 7
    broker._adapter.request_pnl = Mock(
        side_effect=AssertionError("Do not cancel initial subscription")
    )
    broker._record("pnl", dict(request_id=7, daily="0", unrealized="0", realized="0"))
    result = broker.refresh_pnl(renew=False)
    assert result.pnl["validated"] and result.pnl["request_id"] == 7
    broker._adapter.request_pnl.assert_not_called()


def test_conflicting_candidate_cannot_be_bypassed_with_flat_confirmation(broker):
    prime(broker)
    # A new unvalidated subscription candidate does not replace the trusted sample.
    broker._record("pnl", dict(request_id=2, daily="999", unrealized="0", realized="999"))
    with pytest.raises(BrokerError, match="not delivered"):
        broker.refresh_risk()
    assert broker._validated_pnl["daily"] == "0"


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan")])
def test_invalid_risk_refresh_timeout(broker, timeout):
    with pytest.raises(ValueError):
        broker.refresh_risk(timeout=timeout)


def save_reference(broker, monkeypatch):
    monkeypatch.setattr('pyibquant.broker.PNL_SETTLE_SECONDS', 0)
    broker._adapter._pnl_id = 7
    broker._record('pnl', dict(request_id=7, daily='0', unrealized='0', realized='0'))
    broker.refresh_pnl(renew=False)
    assert broker._prior_flat_risk is not None


def reopen(broker):
    from test_broker import Adapter

    path = broker.journal.path
    broker.close()
    adapter = Adapter()
    adapter._pnl_id = 7
    result = PaperBroker(adapter, path, account='DUABC123', readonly=True)
    adapter.refresh(result.account)
    result.wait_ready(0.5)
    return result


def test_saved_preflight_can_confirm_flat_risk_on_a_new_connection(broker, monkeypatch):
    save_reference(broker, monkeypatch)
    stamp = broker.snapshot().pnl['received_at']
    with reopen(broker) as current:
        assert not current.snapshot().pnl and not current._validated_pnl
        result = current.refresh_pnl(renew=False, timeout=0.001)
        assert result.pnl['risk_source'] == 'flat_account_reconciliation'
        assert result.pnl['received_at'] == stamp
        assert not current.snapshot().pnl  # Not replayed as a new broker callback.
        assert EquityRunner._fresh_pnl(result, datetime.now(UTC)) == 0
        assert current.refresh_risk().pnl['risk_source'] == 'flat_account_reconciliation'
        current._adapter.send_order.assert_not_called()
        current._adapter.cancel_order.assert_not_called()


@pytest.mark.parametrize('change', ['cash', 'position', 'order', 'fee', 'date', 'candidate'])
def test_saved_flat_reference_cannot_bypass_changed_or_old_evidence(broker, monkeypatch, change):
    save_reference(broker, monkeypatch)
    with reopen(broker) as current:
        original = current._adapter.refresh

        def refresh(account):
            original(account)
            if change == 'cash':
                current.enqueue('value', dict(tag='CashBalance', currency='USD', value='999'))
            elif change == 'position':
                current.enqueue('position', dict(con_id=100, quantity='1'))
            elif change == 'order':
                current.enqueue('order', dict(order_id=99, client_id=400, status='Submitted'))
            elif change == 'fee':
                current.enqueue('fee', dict(exec_id='late', commission='1', fee_currency='USD'))
            elif change == 'candidate':
                current.enqueue(
                    'pnl', dict(request_id=8, daily='-30', unrealized='0', realized='-30')
                )
            drain(current)

        current._adapter.refresh = refresh
        if change == 'date':
            current._prior_flat_risk['pnl']['received_at'] = (
                datetime.now(UTC) - timedelta(days=1)
            ).isoformat()
        with pytest.raises(BrokerError, match='timed out'):
            current.refresh_pnl(renew=False, timeout=0.001)
        assert not current._validated_pnl
        current._adapter.send_order.assert_not_called()


def test_legacy_preflight_evidence_is_recovered_without_replaying_current_pnl(broker, monkeypatch):
    save_reference(broker, monkeypatch)
    broker.journal.db.execute("DELETE FROM events WHERE kind='pnl_flat_reference'")
    broker.journal.db.commit()
    with reopen(broker) as current:
        assert current._prior_flat_risk['recovered_validation_sequence'] > 0
        assert not current.snapshot().pnl
        result = current.refresh_pnl(renew=False, timeout=0.001)
        assert result.pnl['risk_source'] == 'flat_account_reconciliation'
        assert not current.snapshot().pnl


def test_account_change_during_pnl_settling_cannot_create_a_flat_reference(broker, monkeypatch):
    monkeypatch.setattr('pyibquant.broker.PNL_SETTLE_SECONDS', 0)
    broker._adapter._pnl_id = 7
    broker._record('pnl', dict(request_id=7, daily='0', unrealized='0', realized='0'))
    broker._record('value', dict(tag='CashBalance', currency='USD', value='999'))
    broker.refresh_pnl(renew=False)
    assert broker._pnl_reference is None and broker._prior_flat_risk is None


def test_stale_active_startup_sample_uses_fresh_flat_confirmation(broker, monkeypatch):
    from pyibquant.trading.runner import RunnerConfig

    monkeypatch.setattr('pyibquant.broker.PNL_SETTLE_SECONDS', 0)
    broker._adapter._pnl_id = 7
    broker._record('pnl', dict(request_id=7, daily='0', unrealized='0', realized='0'))
    # The callback's account reference remains anchored to its original receipt.
    old = (datetime.now(UTC) - timedelta(seconds=20)).isoformat()
    broker._pnl['received_at'] = old
    series = feed()
    runner = EquityRunner(broker, RunnerConfig('AAPL', window=2, dry_run=False))
    runner.start(series)
    assert runner.status == 'running' and runner._pnl_baseline == 0
    assert broker.snapshot().pnl['received_at'] == old
    assert any(e['kind'] == 'pnl_risk_confirmation' for e in broker.journal.events())
    broker._adapter.send_order.assert_not_called()
    runner.stop()

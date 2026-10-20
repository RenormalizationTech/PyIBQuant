"""Durable checkpoints preserve risk and order identity across Python restarts."""

import os
import subprocess
import sys
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_broker import Adapter, drain
from test_broker import broker as broker
from test_paper_runner import T, advance, feed, quote, running

from pyibquant import BrokerError, PaperBroker
from pyibquant.trading.runner import EquityRunner


def test_restore_is_paused_preserves_configuration_and_requires_explicit_resume(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner.pause("test restart")
    runner._lease.release()  # Simulate OS releasing the lease on process exit.
    path, run_id = broker.journal.path, runner.run_id
    broker.close()
    with PaperBroker(
        Adapter(), path, account="DUABC123", readonly=False, paper_confirmed=True
    ) as b:
        restored = EquityRunner.restore(b, run_id)
        assert restored.status == "paused" and restored.run_id == run_id
        assert asdict(restored.config) == asdict(runner.config)
        assert restored._pnl_baseline == 0 and restored._seen == runner._seen
        assert not b.snapshot().complete and not b.snapshot().values
        assert restored.step(series, quote(), at=T) is None
        b._adapter.send_order.assert_not_called()
        b._adapter.cancel_order.assert_not_called()


def test_filled_holdings_survive_restart_without_adoption_or_an_automatic_order(broker):
    runner = running(broker, feed(), dry=False)
    broker.submit_limit("AAPL", "BUY", 1, 100, tag=runner.run_id)
    broker._record(
        "execution",
        dict(
            exec_id="owned-buy",
            order_id=10,
            client_id=272,
            con_id=100,
            symbol="AAPL",
            currency="USD",
            side="BOT",
            quantity="1",
            price="100",
            cumulative_quantity="1",
        ),
    )
    runner._lease.release()
    path, run_id = broker.journal.path, runner.run_id
    broker.close()
    adapter = Adapter()
    with PaperBroker(adapter, path, account="DUABC123", readonly=False, paper_confirmed=True) as b:
        restored = EquityRunner.restore(b, run_id)
        original = adapter.refresh

        def refresh(account):
            original(account)
            b.enqueue("position", dict(con_id=100, symbol="AAPL", quantity="1"))
            drain(b)

        adapter.refresh = refresh
        b._record("pnl", dict(daily="0"), T.isoformat())
        b._record("pnl_validated", dict(request_id=None))
        restored.resume(feed(), at=T)
        assert restored._orders == 1 and dict(b.strategy_ledger(run_id).positions)[100] == 1
        adapter.send_order.assert_not_called()
        restored.stop()


def test_process_exit_releases_the_run_lease(tmp_path):
    from pyibquant.trading.checkpoint import RunLease

    path = tmp_path / "journal.sqlite3"
    code = (
        "from pyibquant.trading.checkpoint import RunLease; import sys; "
        f"from pathlib import Path; lease=RunLease(Path({str(path)!r}), 'test-run'); "
        "lease.acquire(); print('ready', flush=True); sys.stdin.read(1)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    lease = RunLease(path, "test-run")
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(BrokerError, match="still owns"):
            lease.acquire()
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
    lease.acquire()
    lease.release()


def test_intent_after_checkpoint_consumes_budget_and_blocks_resume_even_if_download_missing(broker):
    runner = running(broker, feed(), dry=False)
    broker._adapter.send_order.side_effect = OSError("crash after socket write")
    with pytest.raises(BrokerError, match="unknown"):
        broker.submit_limit("AAPL", "BUY", 1, 100, tag=runner.run_id)
    restored = EquityRunner.restore(broker, runner.run_id)
    assert restored._orders == 1
    with pytest.raises(BrokerError, match="uncertain"):
        restored.resume(feed(), at=T)
    assert broker._adapter.send_order.call_count == 1
    runner.stop()


def test_restore_can_be_inspected_readonly_but_not_armed(broker):
    runner = running(broker, feed(), dry=False)
    broker.readonly = True
    restored = EquityRunner.restore(broker, runner.run_id)
    with pytest.raises(BrokerError, match="explicitly enabled"):
        restored.resume(feed(), at=T)
    with pytest.raises(BrokerError, match="explicitly enabled"):
        restored.flatten(feed(), quote(), at=T)
    broker._adapter.send_order.assert_not_called()
    runner.stop()


def test_two_local_runners_cannot_execute_one_run(broker):
    original = running(broker, feed(), dry=False)
    second = EquityRunner.restore(broker, original.run_id)
    with pytest.raises(BrokerError, match="still owns"):
        second.resume(feed(), at=T)
    assert second.status == "paused"
    original.stop()
    with pytest.raises(BrokerError, match="changed after restore"):
        second.resume(feed(), at=T)
    second = EquityRunner.restore(broker, original.run_id)
    second.resume(feed(), at=T)
    assert second.status == "running"
    second.stop()


def test_unreplayed_intent_from_another_process_prevents_resuming_stale_state(broker):
    runner = running(broker, feed(), dry=False)
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    broker.journal.append(
        broker.session,
        broker.account,
        T.isoformat(),
        "intent",
        dict(
            order_id=99,
            client_id=272,
            tag=runner.run_id,
            order_ref="pyibquant:unknown-other-process",
            status="UnknownSend",
            filled="0",
            quantity="1",
        ),
    )
    with pytest.raises(BrokerError, match="reopen the broker"):
        restored.resume(feed(), at=T)
    assert restored.status == "paused"
    broker._adapter.send_order.assert_not_called()


def test_restore_cannot_reset_loss_or_order_limits(broker):
    runner = running(broker, feed(), dry=False)
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    broker._record("pnl", dict(daily="-26"), T.isoformat())
    with pytest.raises(BrokerError, match="loss"):
        restored.resume(feed(), at=T)
    assert restored._pnl_baseline == 0
    broker._record("pnl", dict(daily="0"), T.isoformat())
    for oid in range(10, 14):
        broker._record(
            "intent",
            dict(
                order_id=oid,
                client_id=272,
                tag=runner.run_id,
                order_ref=f"pyibquant:{oid}",
                filled="0",
                status="Cancelled",
            ),
        )
    with pytest.raises(BrokerError, match="order limit"):
        restored.resume(feed(), at=T)


def test_restore_never_adopts_external_holdings(broker):
    runner = running(broker, feed(), dry=False)
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue("position", dict(con_id=100, symbol="AAPL", quantity="1"))
        drain(broker)

    broker._adapter.refresh = refresh
    with pytest.raises(BrokerError, match="holdings differ"):
        restored.resume(feed(), at=T)
    broker._adapter.send_order.assert_not_called()


def test_resume_rearms_at_newest_candle_and_does_not_repeat_the_last_decision(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    restored.resume(series, at=at)
    broker.submit_limit = Mock()
    restored.step(series, quote(at), at=at)
    broker.submit_limit.assert_not_called()
    restored.stop()


def test_recovery_refuses_new_day_changed_contract_and_older_feed(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    with pytest.raises(BrokerError, match="trading date"):
        restored.resume(series, at=T + timedelta(days=1))
    series.instrument_id = 999
    with pytest.raises(BrokerError, match="selected live"):
        restored.resume(series, at=T)
    series.instrument_id = 100
    restored._seen = T + timedelta(minutes=1)
    with pytest.raises(BrokerError, match="behind"):
        restored.resume(series, at=T)


def test_recovered_run_retains_its_original_notional_cap(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner._order_cap = Decimal("99")
    runner.stop()
    broker.max_order_value = Decimal("1000")
    restored = EquityRunner.restore(broker, runner.run_id)
    restored.resume(series, at=T)
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    broker.submit_limit = Mock()
    restored.step(series, quote(at), at=at)
    assert restored.status == "paused" and "persisted" in restored.reason
    broker.submit_limit.assert_not_called()
    restored.stop()


def test_checkpoint_is_durable_before_a_decision_can_submit(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())

    def submit(*args, **kwargs):
        restored = EquityRunner.restore(broker, runner.run_id)
        assert restored._seen == series.snapshot()[-1].timestamp
        return 10

    broker.submit_limit = Mock(side_effect=submit)
    runner.step(series, quote(at), at=at)
    broker.submit_limit.assert_called_once()
    runner.stop()


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 99),
        ("orders", -1),
        ("pnl_baseline", None),
        ("instrument_id", None),
        ("last_seen", "2026-10-19T14:00:00"),
    ],
)
def test_corrupt_checkpoint_is_not_partially_restored(broker, field, value):
    runner = running(broker, feed(), dry=False)
    runner.stop()
    checkpoint = [
        e["payload"] for e in broker.journal.events() if e["kind"] == "runner_checkpoint"
    ][-1]
    broker._record("runner_checkpoint", {**checkpoint, field: value})
    with pytest.raises(BrokerError, match="Invalid runner checkpoint"):
        EquityRunner.restore(broker, runner.run_id)


def test_legacy_runs_without_complete_risk_state_are_reporting_only(broker):
    with pytest.raises(BrokerError, match="legacy runs"):
        EquityRunner.restore(broker, "a" * 32)

"""Quiet-account P&L recovery keeps loss limits and data freshness requirements."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event
from unittest.mock import Mock

import pytest
from test_broker import broker as broker
from test_paper_runner import T, advance, feed, quote, running

from pyibquant import BrokerError
from pyibquant.trading.runner import EquityRunner, RunnerConfig


@pytest.fixture(autouse=True)
def immediate_settling(monkeypatch):
    monkeypatch.setattr("pyibquant.broker.PNL_SETTLE_SECONDS", 0)


def test_readonly_pnl_refresh_requires_new_valid_generation(broker):
    broker.readonly = True
    broker._record("pnl", dict(request_id=1, daily="12"), T.isoformat())

    def request(account):
        broker.enqueue("pnl", dict(request_id=1, daily="999"))
        broker.enqueue("pnl", dict(request_id=2, daily="12"))
        return 2

    broker._adapter.request_pnl = Mock(side_effect=request)
    snapshot = broker.refresh_pnl(timeout=0.1)
    assert snapshot.pnl["request_id"] == 2 and snapshot.pnl["daily"] == "12"
    broker._adapter.send_order.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()


def test_transient_all_zero_callback_cannot_be_used_as_a_loss_sample(broker):
    broker._record("pnl", dict(request_id=1, daily="1283", unrealized="0", realized="7253"))
    requested = Event()

    def request(account):
        broker.enqueue("pnl", dict(request_id=2, daily="0", unrealized="0", realized="0"))
        requested.set()
        return 2

    broker._adapter.request_pnl = Mock(side_effect=request)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(broker.refresh_pnl, timeout=1)
        assert requested.wait(1)
        broker._queue.join()
        assert not future.done()
        assert broker.snapshot().pnl["validated"] is False
        broker.enqueue("pnl", dict(request_id=2, daily="1281", unrealized="0", realized="7251"))
        snapshot = future.result(timeout=2)
    assert snapshot.pnl["daily"] == "1281" and snapshot.pnl["validated"]
    broker._adapter.send_order.assert_not_called()


def test_unconfirmed_zero_times_out_and_cannot_be_reused_on_resume(broker):
    broker._record("pnl", dict(request_id=1, daily="1283", unrealized="0", realized="7253"))
    broker._record("pnl_validated", dict(request_id=1))
    broker._adapter.request_pnl = Mock(
        side_effect=lambda account: (
            broker.enqueue("pnl", dict(request_id=2, daily="0", unrealized="0", realized="0")),
            2,
        )[1]
    )
    with pytest.raises(BrokerError, match="unconfirmed all-zero"):
        broker.refresh_pnl(timeout=0.001)
    snapshot = broker.snapshot()
    assert EquityRunner._fresh_pnl(snapshot, datetime.now(UTC)) is None
    # Another renewal cannot treat the rejected zero as the trusted prior value.
    broker._adapter.request_pnl = Mock(
        side_effect=lambda account: (
            broker.enqueue("pnl", dict(request_id=3, daily="0", unrealized="0", realized="0")),
            3,
        )[1]
    )
    with pytest.raises(BrokerError, match="unconfirmed all-zero"):
        broker.refresh_pnl(timeout=0.001)


def test_real_zero_is_accepted_after_a_confirming_callback(broker):
    broker._record("pnl", dict(request_id=1, daily="12", unrealized="0", realized="12"))

    def request(account):
        for _ in range(2):
            broker.enqueue("pnl", dict(request_id=2, daily="0", unrealized="0", realized="0"))
        return 2

    broker._adapter.request_pnl = Mock(side_effect=request)
    snapshot = broker.refresh_pnl(timeout=0.1)
    assert snapshot.pnl["daily"] == "0" and snapshot.pnl["validated"]


def test_initial_nonzero_callback_burst_is_collected_before_validation(broker, monkeypatch):
    monkeypatch.setattr("pyibquant.broker.PNL_SETTLE_SECONDS", 0.03)
    requested = Event()

    def request(account):
        broker.enqueue("pnl", dict(request_id=2, daily="-148"))
        requested.set()
        return 2

    broker._adapter.request_pnl = Mock(side_effect=request)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(broker.refresh_pnl, timeout=1)
        assert requested.wait(1)
        broker._queue.join()
        assert not future.done()
        broker.enqueue("pnl", dict(request_id=2, daily="1283"))
        assert future.result(timeout=2).pnl["daily"] == "1283"


def test_execution_start_validates_the_baseline_even_if_initial_pnl_looks_fresh(broker):
    broker._record("pnl", dict(daily="0"), T.isoformat())

    def refresh(**kwargs):
        broker._record("pnl", dict(daily="1283"), T.isoformat())
        broker._record("pnl_validated", dict(request_id=None))
        return broker.snapshot()

    broker.refresh_pnl = Mock(side_effect=refresh)
    runner = EquityRunner(broker, RunnerConfig("AAPL", window=2, dry_run=False))
    runner.start(feed(), at=T)
    assert runner._pnl_baseline == 1283
    broker.refresh_pnl.assert_called_once()


def test_execution_start_waits_for_missing_initial_pnl(broker):
    assert not broker.snapshot().pnl

    def refresh(**kwargs):
        broker._record("pnl", dict(request_id=7, daily="0"), T.isoformat())
        broker._record("pnl_validated", dict(request_id=7))
        return broker.snapshot()

    broker.refresh_pnl = Mock(side_effect=refresh)
    runner = EquityRunner(broker, RunnerConfig("AAPL", window=2, dry_run=False))
    runner.start(feed(), at=T)
    assert runner.status == "running" and runner._pnl_baseline == 0
    broker.refresh_pnl.assert_called_once_with(renew=False)
    broker._adapter.send_order.assert_not_called()
    runner.stop()


def test_missing_initial_pnl_timeout_keeps_runner_stopped(broker):
    broker.refresh_pnl = Mock(side_effect=BrokerError("Fresh P&L timed out"))
    runner = EquityRunner(broker, RunnerConfig("AAPL", window=2, dry_run=False))
    with pytest.raises(BrokerError, match="timed out"):
        runner.start(feed(), at=T)
    assert runner.status == "stopped" and runner._pnl_baseline is None
    broker.refresh_pnl.assert_called_once_with(renew=False)
    broker._adapter.send_order.assert_not_called()
    assert not any(e["kind"] == "runner_start" for e in broker.journal.events())


def test_recorded_false_stop_case_has_only_a_two_dollar_loss(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner._pnl_baseline = Decimal("1283.1478079999997")
    at = advance(series)
    broker.refresh_pnl = Mock(side_effect=lambda: refreshed_pnl(broker, at, "1281.0007309999983"))
    broker.submit_limit = Mock(return_value=10)
    assert runner.step(series, quote(at), at=at) == 10
    assert runner.status == "running"
    assert runner._pnl_baseline == Decimal("1283.1478079999997")


@pytest.mark.parametrize("daily", [None, "NaN", "1.7976931348623157e308"])
def test_pnl_refresh_unset_values_cannot_unlock_risk_checks(broker, daily):
    broker._adapter.request_pnl = Mock(
        side_effect=lambda account: (broker.enqueue("pnl", dict(request_id=2, daily=daily)), 2)[1]
    )
    with pytest.raises(BrokerError, match="timed out"):
        broker.refresh_pnl(timeout=0.001)
    broker._adapter.send_order.assert_not_called()


def test_pnl_refresh_timeout_does_not_retimestamp_the_previous_sample(broker):
    broker._record("pnl", dict(request_id=1, daily="12"), T.isoformat())
    old = dict(broker.snapshot().pnl)
    broker._adapter.request_pnl = Mock(return_value=2)
    with pytest.raises(BrokerError, match="timed out"):
        broker.refresh_pnl(timeout=0.001)
    assert dict(broker.snapshot().pnl) == old


def test_pnl_refresh_disconnect_stops_wait_without_trades(broker):
    def request(account):
        broker.enqueue("disconnected", dict(message="test disconnect"))
        return 2

    broker._adapter.request_pnl = Mock(side_effect=request)
    with pytest.raises(BrokerError, match="uncertain"):
        broker.refresh_pnl(timeout=0.1)
    broker._adapter.send_order.assert_not_called()


def test_pnl_transport_failure_reports_broker_error_without_changing_old_sample(broker):
    old = dict(broker.snapshot().pnl)
    broker._adapter.request_pnl = Mock(side_effect=OSError("socket write"))
    with pytest.raises(BrokerError, match="renewal failed"):
        broker.refresh_pnl()
    assert dict(broker.snapshot().pnl) == old
    broker._adapter.send_order.assert_not_called()


def refreshed_pnl(broker, at, daily):
    broker._record("pnl", dict(daily=daily), at.isoformat())
    return broker.snapshot()


def test_flat_account_stale_pnl_refresh_allows_next_candle_without_resetting_baseline(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    broker.refresh_pnl = Mock(side_effect=lambda: refreshed_pnl(broker, at, "-5"))
    broker.submit_limit = Mock(return_value=10)
    assert runner.step(series, quote(at), at=at) == 10
    assert runner.status == "running" and runner._pnl_baseline == 0
    broker.refresh_pnl.assert_called_once()
    broker.submit_limit.assert_called_once()


def test_refreshed_pnl_loss_still_blocks_an_order(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    broker.refresh_pnl = Mock(side_effect=lambda: refreshed_pnl(broker, at, "-26"))
    broker.submit_limit = Mock()
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused" and "loss" in runner.reason
    assert runner._pnl_baseline == 0
    broker.submit_limit.assert_not_called()


def test_pnl_refresh_failure_pauses_and_is_not_retried_by_the_paused_run(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    broker.refresh_pnl = Mock(side_effect=BrokerError("refresh timed out"))
    broker.submit_limit = Mock()
    runner.step(series, quote(at), at=at)
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused" and "refresh timed out" in runner.reason
    broker.refresh_pnl.assert_called_once()
    broker.submit_limit.assert_not_called()


def test_stale_response_and_invalid_timestamp_never_pass_as_fresh_pnl(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    broker.refresh_pnl = Mock(return_value=broker.snapshot())
    broker.submit_limit = Mock()
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused"
    broker.submit_limit.assert_not_called()
    broker._record("pnl", dict(daily="0"), "invalid timestamp")
    assert runner._fresh_pnl(broker.snapshot(), at) is None


def test_resume_renews_quiet_pnl_without_rebasing_loss_limit(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner.pause()
    at = advance(series)
    broker.refresh_pnl = Mock(side_effect=lambda: refreshed_pnl(broker, at, "-5"))
    runner.resume(series, at=at)
    assert runner.status == "running" and runner._pnl_baseline == 0


def test_refresh_delay_cannot_make_old_quotes_eligible(broker, monkeypatch):
    import pyibquant.trading.runner as module

    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    late = at + timedelta(seconds=16)

    real_datetime = module.datetime

    class ClockType(type):
        def __instancecheck__(cls, value):
            return isinstance(value, real_datetime)

    class Clock(metaclass=ClockType):
        @staticmethod
        def now(zone):
            return at if broker.refresh_pnl.call_count == 0 else late

        fromisoformat = real_datetime.fromisoformat

    broker.refresh_pnl = Mock(side_effect=lambda: refreshed_pnl(broker, late, "0"))
    broker.submit_limit = Mock()
    monkeypatch.setattr(module, "datetime", Clock)
    runner.step(series, quote(at))
    assert runner.status == "paused" and "became stale" in runner.reason
    broker.submit_limit.assert_not_called()

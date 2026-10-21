"""Completed-bar runner timing and controls; no broker orders are transmitted."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_broker import broker as broker

from pyibquant import Bar, BarSeries, BrokerError
from pyibquant.trading.runner import EquityRunner, RunnerConfig

T = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)


def feed():
    series = BarSeries("AAPL", "1min", live=True)
    series.instrument_id = 100
    series.connection_state = "subscribed"
    for minute in (-2, -1, 0):
        price = 100 + minute
        series.update(Bar(T + timedelta(minutes=minute), price, price, price, price, 1))
    series.last_live_update = T
    series.sessions = [
        dict(
            start=(T - timedelta(minutes=30)).timestamp(),
            end=(T + timedelta(hours=6)).timestamp(),
            regular=True,
        )
    ]
    return series


def quote(at=T):
    return SimpleNamespace(
        instrument=SimpleNamespace(symbol="AAPL", instrument_id=100),
        market_data_type="live",
        is_delayed=False,
        crossed=False,
        status="active",
        bid=100,
        ask=100.02,
        field_received_at=(("bid", at), ("ask", at)),
    )


def advance(series, at=T + timedelta(minutes=1, seconds=1)):
    series.update(Bar(T + timedelta(minutes=1), 101, 101, 101, 101, 1))
    series.last_live_update = at
    return at


def running(broker, series, *, dry=True):
    broker._record("pnl", dict(daily="0", unrealized="0", realized="0"), T.isoformat())
    broker._record("pnl_validated", dict(request_id=None))
    broker.refresh_pnl = Mock(side_effect=lambda **kwargs: broker.snapshot())
    broker.refresh_risk = Mock(side_effect=lambda: broker.refresh_pnl())
    runner = EquityRunner(broker, RunnerConfig("AAPL", window=2, dry_run=dry))
    runner.start(series, at=T)
    return runner


def test_warmup_does_not_submit_and_one_completed_bar_decides_once(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    broker.submit_limit = Mock(return_value=10)
    assert runner.step(series, quote(), at=T) is None
    broker.submit_limit.assert_not_called()
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    assert runner.step(series, quote(at), at=at) == 10
    assert runner.step(series, quote(at), at=at) is None
    broker.submit_limit.assert_called_once()
    args = broker.submit_limit.call_args.args
    assert args[:3] == ("AAPL", "BUY", 1)
    # The in-progress 101 bar is excluded; the signal close is the completed 100.
    signals = [e["payload"] for e in broker.journal.events() if e["kind"] == "signal"]
    assert signals[-1]["close"] == 100


def test_dry_run_logs_target_without_calling_order_api(broker):
    series = feed()
    runner = running(broker, series)
    broker.submit_limit = Mock()
    at = advance(series)
    runner.step(series, quote(at), at=at)
    broker.submit_limit.assert_not_called()
    assert any(e["kind"] == "signal" for e in broker.journal.events())


@pytest.mark.parametrize(
    "failure",
    ["bar_stale", "quote_stale", "delayed", "session", "disconnect", "mismatch", "missed_boundary"],
)
def test_bad_live_inputs_pause_without_orders(broker, failure):
    series = feed()
    runner = running(broker, series)
    broker.submit_limit = Mock()
    at = advance(series)
    q = quote(at)
    if failure == "bar_stale":
        series.last_live_update = T - timedelta(minutes=10)
    elif failure == "quote_stale":
        q = quote(T)
    elif failure == "delayed":
        q.market_data_type = "delayed"
    elif failure == "session":
        series.sessions = []
    elif failure == "disconnect":
        series.connection_state = "disconnected"
    elif failure == "mismatch":
        q.instrument.instrument_id = 999
    else:
        series.update(Bar(T + timedelta(minutes=2), 102, 102, 102, 102, 1))
        at += timedelta(minutes=1)
        series.last_live_update = at
        q = quote(at)
    runner.step(series, q, at=at)
    assert runner.status == "paused"
    broker.submit_limit.assert_not_called()


def test_pause_stop_do_not_cancel_or_liquidate(broker):
    series = feed()
    runner = running(broker, series)
    runner.pause()
    runner.step(series, quote(), at=T)
    runner.stop()
    broker._adapter.send_order.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()


def test_execution_refuses_existing_holdings_and_missing_pnl(broker):
    series = feed()
    runner = EquityRunner(broker, RunnerConfig("AAPL", window=2, dry_run=False))
    with pytest.raises(BrokerError, match="P&L"):
        runner.start(series, at=T)
    broker._record("pnl", dict(daily="0"), T.isoformat())
    broker._record("position", dict(symbol="AAPL", con_id=100, quantity="1"))
    with pytest.raises(BrokerError, match="flat"):
        runner.start(series, at=T)


def test_account_session_loss_limit_blocks_submission(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    broker.submit_limit = Mock()
    at = advance(series)
    broker._record("pnl", dict(daily="-26"), at.isoformat())
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused" and "loss" in runner.reason
    broker.submit_limit.assert_not_called()


def test_broker_failure_pauses_without_retrying(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    broker.submit_limit = Mock(side_effect=BrokerError("unresolved send"))
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    runner.step(series, quote(at), at=at)
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused"
    broker.submit_limit.assert_called_once()


def test_runner_accepts_real_quote_stream_active_state(broker):
    from pyibquant.quotes import QuoteInstrument, _QuoteState

    series = feed()
    runner = running(broker, series)
    at = advance(series)
    instrument = QuoteInstrument(
        "AAPL", 100, "equity", "USD", "SMART", "NASDAQ", "AAPL", "", 1, None, None, None
    )
    state = _QuoteState(instrument, "live", streaming=True)
    state.actual_type = "live"
    state.tick(1, 100)
    state.tick(2, 100.02)
    state.receipts = {"bid": at, "ask": at}
    runner.step(series, state.snapshot(), at=at)
    assert runner.status == "running"
    assert any(e["kind"] == "signal" for e in broker.journal.events())


def test_unknown_position_quantity_cannot_be_treated_as_flat(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    broker.submit_limit = Mock()
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    broker._record("position", dict(symbol="AAPL", con_id=100, quantity=None))
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused" and "unknown" in runner.reason
    broker.submit_limit.assert_not_called()


def test_resume_skips_pause_bars_and_preserves_limits(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner._orders = 2
    runner.pause()
    at = advance(series)
    broker._record("pnl", dict(daily="-5"), at.isoformat())
    runner.resume(series, at=at)
    assert runner.status == "running" and runner._orders == 2
    assert runner._pnl_baseline == 0
    broker.submit_limit = Mock()
    runner.step(series, quote(at), at=at)
    broker.submit_limit.assert_not_called()


def test_resume_cannot_reset_loss_limit_or_daily_baseline(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner.pause()
    broker._record("pnl", dict(daily="-26"), T.isoformat())
    with pytest.raises(BrokerError, match="loss"):
        runner.resume(series, at=T)
    with pytest.raises(BrokerError, match="already started"):
        runner.start(series, at=T)
    with pytest.raises(BrokerError, match="trading date"):
        runner.resume(series, at=T + timedelta(days=1))
    assert runner.status == "paused" and runner._pnl_baseline == 0


def test_resume_requires_resolved_orders(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    runner.pause()
    broker.submit_limit("AAPL", "BUY", 1, 100, tag=runner.run_id)
    with pytest.raises(BrokerError, match="uncertain"):
        runner.resume(series, at=T)
    assert runner.status == "paused"


def test_external_share_is_never_treated_as_strategy_owned(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    broker._record("position", dict(symbol="AAPL", con_id=100, quantity="1"))
    broker.submit_limit = Mock()
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused" and "strategy-owned" in runner.reason
    broker.submit_limit.assert_not_called()


def preserve_position_refresh(broker, quantity):
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue("position", dict(symbol="AAPL", con_id=100, quantity=quantity))
        broker._queue.join()

    broker._adapter.refresh = refresh


def test_flatten_refuses_external_share_and_keeps_runner_paused(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    preserve_position_refresh(broker, "1")
    with pytest.raises(BrokerError, match="holdings differ"):
        runner.flatten(series, quote(), at=T)
    assert runner.status == "paused"
    broker._adapter.send_order.assert_not_called()


def test_flatten_submits_only_run_owned_quantity_and_waits_for_explicit_confirmation(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    broker.submit_limit("AAPL", "BUY", 1, 100, tag=runner.run_id)
    broker._record(
        "execution",
        dict(
            exec_id="buy-fill",
            client_id=272,
            order_id=10,
            con_id=100,
            currency="USD",
            side="BOT",
            cumulative_quantity="1",
            quantity="1",
            price="100",
        ),
    )
    preserve_position_refresh(broker, "1")
    broker._adapter.allocate_id.return_value = 11
    assert runner.flatten(series, quote(), at=T) == 11
    assert runner.status == "paused" and runner._pnl_baseline == 0
    assert broker.snapshot().orders[-1]["side"] == "SELL"
    assert broker.snapshot().orders[-1]["quantity"] == "1"
    assert broker.snapshot().orders[-1]["status"] == "PendingSubmit"
    with pytest.raises(BrokerError, match="uncertain"):
        runner.flatten(series, quote(), at=T)
    assert broker._adapter.send_order.call_count == 2  # one buy, one close


def test_flatten_requires_fresh_quote_and_observation_cannot_trade(broker):
    series = feed()
    runner = running(broker, series)
    with pytest.raises(BrokerError, match="execution run"):
        runner.flatten(series, quote(), at=T)
    runner = running(broker, series, dry=False)
    broker.submit_limit("AAPL", "BUY", 1, 100, tag=runner.run_id)
    broker._record(
        "execution",
        dict(
            exec_id="buy-fill",
            client_id=272,
            order_id=10,
            con_id=100,
            currency="USD",
            side="BOT",
            cumulative_quantity="1",
            quantity="1",
            price="100",
        ),
    )
    preserve_position_refresh(broker, "1")
    with pytest.raises(BrokerError, match="fresh"):
        runner.flatten(series, quote(T - timedelta(minutes=1)), at=T)
    assert broker._adapter.send_order.call_count == 1


def test_restored_run_can_plan_readonly_and_flatten_without_invalidating_its_checkpoint(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    broker.submit_limit("AAPL", "BUY", 1, 100, tag=runner.run_id)
    broker._record("execution", dict(
        exec_id="owned", order_id=10, client_id=272, con_id=100,
        currency="USD", side="BOT", quantity="1", price="100", cumulative_quantity="1",
    ))
    preserve_position_refresh(broker, "1")
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    checkpoint = restored._restored_checkpoint
    broker.readonly = True
    plan = restored.flatten_plan(series, quote(), at=T)
    assert plan["quantity"] == 1 and plan["side"] == "SELL"
    assert restored.status == "paused" and restored._restored_checkpoint == checkpoint
    assert restored._pnl_baseline == 0 and restored._orders == 1
    assert broker._adapter.send_order.call_count == 1
    broker.readonly = False
    broker._adapter.allocate_id.return_value = 11
    assert restored.flatten(series, quote(), at=T) == 11
    assert restored._pnl_baseline == 0 and restored._orders == 2
    assert restored._restored_checkpoint is None
    restored.stop()


def moving_clock(monkeypatch, *times):
    real_datetime = datetime
    ticks = iter(times)

    class ClockType(type):
        def __instancecheck__(cls, value):
            return isinstance(value, real_datetime)

    class Clock(metaclass=ClockType):
        fromisoformat = staticmethod(real_datetime.fromisoformat)

        @staticmethod
        def now(tz=None):
            return next(ticks, times[-1])

    monkeypatch.setattr('pyibquant.trading.runner.datetime', Clock)


def test_callback_during_account_snapshot_is_not_a_future_bar(broker, monkeypatch):
    series = feed()
    runner = running(broker, series)
    at = advance(series)
    original = broker.snapshot

    def snapshot():
        result = original()
        series.last_live_update = at + timedelta(milliseconds=100)
        return result

    broker.snapshot = Mock(side_effect=snapshot)
    moving_clock(monkeypatch, at, at + timedelta(milliseconds=200))
    runner.step(series, quote(at))
    assert runner.status == 'running'
    assert any(e['kind'] == 'signal' for e in broker.journal.events())
    broker._adapter.send_order.assert_not_called()


def test_callback_after_risk_refresh_is_not_a_future_bar(broker, monkeypatch):
    series = feed()
    runner = running(broker, series, dry=False)
    at = advance(series)

    def risk(snapshot, checked_at, **kwargs):
        broker._record('pnl', dict(daily='0'), (at + timedelta(milliseconds=100)).isoformat())
        series.last_live_update = at + timedelta(milliseconds=200)
        return broker.snapshot(), at + timedelta(milliseconds=100)

    runner._risk_snapshot = Mock(side_effect=risk)
    broker.submit_limit = Mock(return_value=10)
    moving_clock(monkeypatch, at, at, at + timedelta(milliseconds=300))
    assert runner.step(series, quote(at)) == 10
    assert runner.status == 'running'
    broker.submit_limit.assert_called_once()
    broker._adapter.send_order.assert_not_called()
    runner.stop()


@pytest.mark.parametrize('age', [None, 16, -1])
def test_bad_bar_age_still_pauses_with_timestamp_evidence(broker, age):
    series = feed()
    runner = running(broker, series)
    at = advance(series)
    series.last_live_update = at - timedelta(seconds=age) if age is not None else None
    runner.step(series, quote(at), at=at)
    assert runner.status == 'paused' and 'No fresh live bar callback' in runner.reason
    event = [e for e in broker.journal.events() if e['kind'] == 'runner_feed_check_failed'][-1]
    assert event['payload']['age'] == age
    assert event['payload']['checked_at'] == at.isoformat()
    broker._adapter.send_order.assert_not_called()


def test_resume_samples_clock_after_live_receipt(broker, monkeypatch):
    series = feed()
    runner = running(broker, series)
    runner.pause()
    at = advance(series)
    series.last_live_update = at + timedelta(milliseconds=100)
    moving_clock(monkeypatch, at, at + timedelta(milliseconds=200))
    runner.resume(series)
    assert runner.status == 'running'
    broker._adapter.send_order.assert_not_called()
    runner.stop()

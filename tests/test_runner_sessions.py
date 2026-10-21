"""Explicit daily rollovers preserve ownership, configuration and lifetime order caps."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from test_broker import broker as broker
from test_paper_runner import T, feed, quote, running

from pyibquant import Bar, BrokerError
from pyibquant.trading.runner import EquityRunner


def next_feed():
    series = feed()
    series._bars.clear()
    at = T + timedelta(days=1)
    for minute in (-2, -1, 0):
        stamp = at + timedelta(minutes=minute)
        series.update(Bar(stamp, 100 + minute, 100 + minute, 100 + minute, 100 + minute, 1))
    series.last_live_update = at
    series.sessions = [dict(start=(at - timedelta(hours=1)).timestamp(),
                            end=(at + timedelta(hours=6)).timestamp(), regular=True)]
    return series, at


def prepare(broker):
    original = running(broker, feed(), dry=False)
    original.stop()
    restored = EquityRunner.restore(broker, original.run_id)
    series, at = next_feed()
    broker._record("pnl", dict(daily="-50", unrealized="0", realized="-50"), at.isoformat())
    broker._record("pnl_validated", dict(request_id=None))
    return restored, series, at


def test_next_day_is_opt_in_and_does_not_repeat_overnight_decisions(broker):
    runner, series, at = prepare(broker)
    with pytest.raises(BrokerError, match="trading date"):
        runner.resume(series, at=at)
    assert runner._pnl_baseline == 0
    runner.resume(series, at=at, new_session=True)
    assert runner._pnl_baseline == -50 and runner._day == at.date().isoformat()
    broker.submit_limit = Mock()
    runner.step(series, quote(at), at=at)
    broker.submit_limit.assert_not_called()
    runner.stop()
    again = EquityRunner.restore(broker, runner.run_id)
    assert again._pnl_baseline == -50 and again._day == runner._day


def test_rollover_never_resets_exhausted_order_budget(broker):
    runner, series, at = prepare(broker)
    runner._orders = runner.config.max_orders
    with pytest.raises(BrokerError, match="order limit"):
        runner.resume(series, at=at, new_session=True)
    assert runner._pnl_baseline == 0 and runner._day == T.date().isoformat()
    broker._adapter.send_order.assert_not_called()


def test_rollover_cannot_reset_same_day_loss(broker):
    runner, _, _ = prepare(broker)
    with pytest.raises(BrokerError, match="later trading date"):
        runner.resume(feed(), at=T, new_session=True)


def test_rollover_requires_fresh_pnl_and_current_session_feed(broker):
    runner, series, at = prepare(broker)
    broker._record("pnl", dict(daily="0"), T.isoformat())
    with pytest.raises(BrokerError, match="P&L"):
        runner.resume(series, at=at, new_session=True)
    assert runner._pnl_baseline == 0
    broker._record("pnl", dict(daily="0"), at.isoformat())
    series.sessions = []
    with pytest.raises(BrokerError, match="regular session"):
        runner.resume(series, at=at, new_session=True)


def test_rollover_still_rejects_unresolved_orders(broker):
    runner, series, at = prepare(broker)
    broker.submit_limit("AAPL", "BUY", 1, 100, tag=runner.run_id)
    with pytest.raises(BrokerError, match="uncertain"):
        runner.resume(series, at=at, new_session=True)
    assert runner._pnl_baseline == 0 and runner.status == "paused"


def test_resume_skips_candle_completed_while_reconciliation_blocks(broker, monkeypatch):
    from dataclasses import replace

    from test_paper_runner import advance, moving_clock

    series = feed()
    runner = running(broker, series, dry=False)
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    later = T + timedelta(minutes=1, seconds=1)
    moving_clock(monkeypatch, T, T, later)
    original = broker.reconcile
    def reconcile():
        report = original()
        at = advance(series, later)
        broker._record("pnl", dict(daily="0"), at.isoformat())
        return replace(report, snapshot=broker.snapshot())
    broker.reconcile = reconcile
    restored.resume(series)
    broker.submit_limit = Mock()
    restored.step(series, quote(later), at=later)
    broker.submit_limit.assert_not_called()
    restored.stop()

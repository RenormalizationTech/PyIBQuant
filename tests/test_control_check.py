"""Execution control-check orchestration cannot reset risk or create order intents."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from test_broker import broker as broker
from test_paper_runner import T, advance, feed, quote, running

from pyibquant import BrokerError
from pyibquant.trading.control_check import RunnerControlCheck


def test_pause_skips_boundary_then_resume_preserves_state_and_requires_new_signal(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    check = RunnerControlCheck(runner)
    assert check.tick(series, elapsed=0, at=T) is None
    runner._log("signal", target=0)
    assert check.tick(series, elapsed=1, at=T) == "paused"
    state = runner._pnl_baseline, runner._orders, runner.config
    at = advance(series, at=T + timedelta(seconds=65))
    broker._record("pnl", dict(daily="0"), at.isoformat())
    runner.step(series, quote(at), at=at)
    assert runner.status == "paused"
    assert check.tick(series, elapsed=65, at=at) is None
    assert check.tick(series, elapsed=66, at=at) == "resumed"
    assert (runner._pnl_baseline, runner._orders, runner.config) == state
    assert runner._seen == series.snapshot()[-1].timestamp
    assert not check.passed
    runner._log("signal", target=0)
    assert check.tick(series, elapsed=67, at=at) == "passed" and check.passed
    assert check.tick(series, elapsed=68, at=at) is None
    broker._adapter.send_order.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()
    runner.stop()


def test_control_check_waits_for_outstanding_order_before_pausing(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    check = RunnerControlCheck(runner)
    runner._log("signal", target=1)
    broker.funding = Mock(return_value={"pending_owned_order": True})
    assert check.tick(series, elapsed=1, at=T) is None
    assert check.phase == "waiting_signal" and runner.status == "running"
    runner.stop()


@pytest.mark.parametrize("change", ["baseline", "orders", "configuration", "signal", "cursor"])
def test_changed_paused_state_blocks_resume(broker, change):
    series = feed()
    runner = running(broker, series, dry=False)
    check = RunnerControlCheck(runner)
    runner._log("signal", target=0)
    check.tick(series, elapsed=0, at=T)
    if change == "baseline":
        runner._pnl_baseline = -10
    elif change == "orders":
        runner._orders += 1
    elif change == "configuration":
        runner.config = replace(runner.config, max_orders=100)
    elif change == "signal":
        runner._log("signal", target=1)
    else:
        runner._seen += timedelta(minutes=1)
    with pytest.raises(BrokerError, match="changed while"):
        check.tick(series, elapsed=70, at=T)
    assert runner.status == "paused"
    broker._adapter.send_order.assert_not_called()
    runner.stop()


def test_unexpected_risk_pause_is_not_automatically_resumed(broker):
    series = feed()
    runner = running(broker, series, dry=False)
    check = RunnerControlCheck(runner)
    runner.pause("loss cap")
    with pytest.raises(BrokerError, match="loss cap"):
        check.tick(series, elapsed=1, at=T)
    assert runner.status == "paused"
    runner.stop()

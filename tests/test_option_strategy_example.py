"""Quiet BBO refresh obtains new provider data without weakening freshness checks."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "option_strategy_example",
    Path(__file__).resolve().parents[1] / "examples/paper_option_strategy.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def setup():
    at = datetime.now(UTC)
    quote = SimpleNamespace(status="active", market_data_type="live", is_delayed=False,
        crossed=False, bid=3, ask=3.15, sequence=1,
        field_received_at=(("bid", at-timedelta(seconds=20)), ("ask", at-timedelta(seconds=20))))
    stream = Mock()
    stream.latest.return_value = quote
    fresh = Mock()
    fresh.latest.return_value = SimpleNamespace(**{**vars(quote),
        "field_received_at": (("bid", at), ("ask", at))})
    market, stack = Mock(), Mock()
    stack.enter_context.return_value = fresh
    runner = SimpleNamespace(status="running", _seen=at-timedelta(minutes=1),
        config=SimpleNamespace(max_data_age=15), _log=Mock())
    series = Mock()
    series.snapshot.return_value = [SimpleNamespace(timestamp=at)]
    return market, stack, stream, fresh, runner, series


def test_quiet_decision_replaces_only_the_data_subscription():
    market, stack, stream, fresh, runner, series = setup()
    old_receipts = stream.latest().field_received_at
    assert example.refresh_quiet_quote(market, "selector", stack, stream, runner, series) is fresh
    stream.close.assert_called_once()
    market.stream_quote.assert_called_once_with("selector")
    assert stream.latest().field_received_at == old_receipts
    assert fresh.latest().field_received_at != old_receipts


@pytest.mark.parametrize(
    "failure", ["delayed", "crossed", "disconnected", "missing", "no_boundary"],
)
def test_invalid_or_nondecision_inputs_never_trigger_subscription_retry(failure):
    market, stack, stream, _, runner, series = setup()
    q = stream.latest()
    if failure == "delayed":
        q.is_delayed = True
    elif failure == "crossed":
        q.crossed = True
    elif failure == "disconnected":
        q.status = "disconnected"
    elif failure == "missing":
        q.field_received_at = ()
    else:
        runner._seen = series.snapshot()[0].timestamp
    assert example.refresh_quiet_quote(market, "selector", stack, stream, runner, series) is stream
    market.stream_quote.assert_not_called()
    stream.close.assert_not_called()

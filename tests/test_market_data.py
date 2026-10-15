from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import Bar, BarSeries
from pyibquant.data.providers.ibkr import IBKRProvider, normalize_bar
from pyibquant.errors import ConnectionError, DataError, RequestTimeout
from pyibquant.visualization.chart import ChartSession, render_chart


def raw_bar(timestamp="1792071000", close=101):
    return SimpleNamespace(date=timestamp, open=100, high=102, low=99, close=close, volume=50)


@pytest.fixture
def provider():
    result = IBKRProvider("127.0.0.1", 7497, 71, 0.01)
    result.isConnected = Mock(return_value=True)
    result.cancelHistoricalData = Mock()
    return result


def resolve_contract(provider):
    def details(req_id, contract):
        provider.contractDetails(req_id, SimpleNamespace(contract=contract))
        provider.contractDetailsEnd(req_id)

    provider.reqContractDetails = Mock(side_effect=details)


def test_normalizes_epoch_and_daily_dates():
    assert normalize_bar(raw_bar("0"), "1min").timestamp == datetime(1970, 1, 1, tzinfo=UTC)
    assert normalize_bar(raw_bar("20261015"), "1d").timestamp == date(2026, 10, 15)
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar(datetime(2026, 10, 15), 1, 1, 1, 1, 1)
    with pytest.raises(ValueError, match="finite"):
        normalize_bar(raw_bar(close=float("nan")), "1min")


def test_historical_request_and_late_updates(provider):
    resolve_contract(provider)

    def history(req_id, *args):
        provider.historicalData(req_id, raw_bar())
        provider.historicalDataEnd(req_id, "", "")

    provider.reqHistoricalData = Mock(side_effect=history)
    series = provider.bars(" aapl ", interval="1min", duration="1D", live=True)
    args = provider.reqHistoricalData.call_args.args
    assert args[2:9] == ("", "1 D", "1 min", "TRADES", 1, 2, True)
    assert series.symbol == "AAPL"
    assert len(series) == 1
    provider.historicalDataUpdate(args[0], raw_bar(close=102))
    assert len(series) == 1
    assert series.snapshot()[0].close == 102
    provider.historicalDataUpdate(args[0], raw_bar("1792071060", close=103))
    assert len(series) == 2
    provider.connectionClosed()
    assert series.error == "IBKR connection closed"


def test_data_permission_failure_is_immediate_and_cancels(provider):
    resolve_contract(provider)
    provider.reqHistoricalData = Mock(
        side_effect=lambda req_id, *args: provider.error(req_id, 0, 162, "No permissions")
    )
    with pytest.raises(DataError, match="162.*No permissions"):
        provider.bars("AAPL", live=True)
    provider.cancelHistoricalData.assert_called_once()
    assert not provider._requests


def test_warning_does_not_discard_bars(provider):
    resolve_contract(provider)

    def history(req_id, *args):
        provider.error(req_id, 0, 2188, "Additional subscription required")
        provider.historicalData(req_id, raw_bar())
        provider.historicalDataEnd(req_id, "", "")

    provider.reqHistoricalData = Mock(side_effect=history)
    series = provider.bars("AAPL")
    assert len(series) == 1
    assert "2188" in series.warnings[0]
    assert not provider._requests


def test_timeout_cancels_and_removes_request(provider):
    resolve_contract(provider)
    provider.reqHistoricalData = Mock()
    with pytest.raises(RequestTimeout):
        provider.bars("AAPL", live=True)
    provider.cancelHistoricalData.assert_called_once()
    assert not provider._requests


def test_ambiguous_contract_and_invalid_query(provider):
    provider.reqContractDetails = Mock(
        side_effect=lambda req_id, contract: provider.contractDetailsEnd(req_id)
    )
    with pytest.raises(DataError, match="primary_exchange"):
        provider.bars("AAPL")
    with pytest.raises(ValueError, match="interval"):
        provider.bars("AAPL", interval="bogus")
    with pytest.raises(ValueError, match="duration"):
        provider.bars("AAPL", duration="0 D")
    provider.isConnected.return_value = False
    with pytest.raises(ConnectionError):
        provider.bars("AAPL")


def test_empty_history_is_an_error(provider):
    resolve_contract(provider)
    provider.reqHistoricalData = Mock(
        side_effect=lambda req_id, *args: provider.historicalDataEnd(req_id, "", "")
    )
    with pytest.raises(DataError, match="No bars"):
        provider.bars("AAPL")


def test_chart_export_is_safe_and_snapshot_is_not_labelled_live(tmp_path):
    series = BarSeries('</script><script>alert("x")</script>', "1d", live=True)
    series.update(normalize_bar(raw_bar("20261015"), "1d"))
    series.error = "<untrusted provider message>"
    path = series.plot(tmp_path / "chart.html", open_browser=False)
    html = path.read_text()
    assert '</script><script>alert("x")</script>' not in html
    assert "\\u003c" in html
    assert '"live": false' in html
    assert '"time": "2026-10-15"' in html
    assert "const liveEndpoint = false;" in html
    assert "const liveEndpoint = true;" in render_chart(series, live_endpoint=True)
    assert '<canvas id="market-canvas"' in html
    assert "class MarketChart" in html
    assert "<script src=" not in html
    assert "__CHART_SCRIPT__" not in html
    assert "TradingView" not in html
    assert "const controlsEnabled = false;" in html
    assert "const controlsEnabled = true;" in render_chart(series, controls=True)


def test_selection_releases_previous_subscription_after_success():
    original = BarSeries("AAPL", "1min", live=True)
    replacement = BarSeries("SPY", "5min", live=True)
    loader, cancel = Mock(return_value=replacement), Mock()
    session = ChartSession(original, loader, cancel)
    assert session.select("SPY", "5min", "1 D")["symbol"] == "SPY"
    loader.assert_called_once_with("SPY", "5min", "1 D")
    cancel.assert_called_once_with(original)
    assert session.series is replacement


def test_failed_selection_keeps_previous_chart_and_serializes_requests():
    original = BarSeries("AAPL", "1min", live=True)
    loader, cancel = Mock(side_effect=DataError("Unknown symbol")), Mock()
    session = ChartSession(original, loader, cancel)
    with pytest.raises(DataError, match="Unknown symbol"):
        session.select("MISSING", "5min", "1 D")
    assert session.series is original
    cancel.assert_not_called()
    with session._selection_lock, pytest.raises(BlockingIOError):
        session.select("SPY", "5min", "1 D")
    loader.assert_called_once()


def test_cancel_series_does_not_cancel_other_subscriptions(provider):
    first, second = BarSeries("AAPL", "1min", live=True), BarSeries("SPY", "1min", live=True)
    req_id, _ = provider._new_request(first)
    other_id, _ = provider._new_request(second)
    provider.cancel_bars(first)
    provider.cancelHistoricalData.assert_called_once_with(req_id)
    assert req_id not in provider._requests
    assert other_id in provider._requests

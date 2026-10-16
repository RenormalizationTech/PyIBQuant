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
def provider(monkeypatch):
    monkeypatch.setattr(
        "pyibquant.data.providers.ibkr.current_time",
        lambda: datetime(2026, 10, 15, 16, tzinfo=UTC).timestamp(),
    )
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


@pytest.mark.parametrize(
    ("interval", "size", "timestamp"),
    [("2h", "2 hours", "1792071000"), ("4h", "4 hours", "1792071000"),
     ("1w", "1 week", "20261012")],
)
def test_coarser_native_intervals_and_live_replacement(provider, interval, size, timestamp):
    resolve_contract(provider)

    def history(req_id, *args):
        provider.historicalData(req_id, raw_bar(timestamp))
        provider.historicalDataEnd(req_id, "", "")

    provider.reqHistoricalData = Mock(side_effect=history)
    series = provider.bars("AAPL", interval=interval, duration="1 Y", live=True)
    args = provider.reqHistoricalData.call_args.args
    assert args[3:5] == ("2 Y" if interval == "1w" else "1 Y", size)
    provider.historicalDataUpdate(args[0], raw_bar(timestamp, close=102))
    assert len(series) == 1
    assert series.snapshot()[0].close == 102
    if interval == "1w":
        assert series.snapshot()[0].timestamp == date(2026, 10, 12)
        assert series.payload()["bars"][0]["time"] == "2026-10-12"
    else:
        assert series.snapshot()[0].timestamp == datetime.fromtimestamp(int(timestamp), UTC)


def test_yearly_aggregation_replaces_months_and_handles_year_boundary(provider):
    resolve_contract(provider)

    def month(timestamp, opening, high, low, close, volume):
        return SimpleNamespace(
            date=timestamp, open=opening, high=high, low=low, close=close, volume=volume
        )

    def history(req_id, *args):
        # Out-of-order callbacks must still use the chronological open/close.
        provider.historicalData(req_id, month("20261201", 120, 140, 110, 130, 200))
        provider.historicalData(req_id, month("20260101", 100, 125, 90, 120, 100))
        provider.historicalData(req_id, month("20250101", 80, 100, 70, 95, 50))
        provider.historicalDataEnd(req_id, "", "")

    provider.reqHistoricalData = Mock(side_effect=history)
    series = provider.bars("AAPL", interval="1y", duration="10 Y", live=True)
    args = provider.reqHistoricalData.call_args.args
    assert args[3:5] == ("11 Y", "1 month")
    assert series.snapshot() == (
        Bar(date(2025, 1, 1), 80, 100, 70, 95, 50),
        Bar(date(2026, 1, 1), 100, 140, 90, 130, 300),
    )
    correction = month("20261201", 120, 135, 115, 125, 250)
    provider.historicalDataUpdate(args[0], correction)
    provider.historicalDataUpdate(args[0], correction)
    assert series.snapshot()[-1] == Bar(date(2026, 1, 1), 100, 135, 90, 125, 350)
    provider.historicalDataUpdate(args[0], month("20270101", 125, 150, 120, 145, 10))
    assert len(series) == 3
    assert series.snapshot()[-1] == Bar(date(2027, 1, 1), 125, 150, 120, 145, 10)
    assert "may be partial" in series.warnings[0]
    provider.cancel_bars(series)
    provider.cancelHistoricalData.assert_called_once_with(args[0])
    assert not provider._requests


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
    loader.assert_called_once_with("SPY", "5min", "1 D", True)
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


def test_trading_hours_switch_persists_and_failure_keeps_active_hours():
    original = BarSeries("AAPL", "1min", live=True)
    extended = BarSeries("AAPL", "1min", live=True)
    extended.regular_hours = False
    loader = Mock(return_value=extended)
    cancel = Mock()
    session = ChartSession(original, loader, cancel)
    first_id = session.selection_id
    assert session.select("AAPL", "1min", "1 D", False)["regular_hours"] is False
    assert session.selection_id != first_id
    loader.assert_called_once_with("AAPL", "1min", "1 D", False)
    session.select("SPY", "5min", "1 D")
    loader.assert_called_with("SPY", "5min", "1 D", False)
    loader.side_effect = DataError("Unavailable")
    with pytest.raises(DataError):
        session.select("AAPL", "1min", "1 D", True)
    assert session.series is extended
    assert session.payload()["regular_hours"] is False
    assert cancel.call_count == 2
    for invalid in ["false", 0, 1]:
        with pytest.raises(ValueError, match="boolean"):
            session.select("AAPL", "1min", "1 D", invalid)


def test_market_browser_selection_passes_hours_to_provider(monkeypatch):
    from pyibquant import Market

    provider = Mock()
    initial = BarSeries("AAPL", "1min", live=True)
    initial.primary_exchange = "NASDAQ"
    server = Mock()
    monkeypatch.setattr("pyibquant.visualization.chart.serve_chart", server)
    Market(provider).serve(initial, open_browser=False)
    load = server.call_args.kwargs["loader"]
    load("AAPL", "5min", "2 D", False)
    provider.bars.assert_called_once_with(
        "AAPL", interval="5min", duration="2 D", live=True,
        regular_hours=False, primary_exchange="NASDAQ", refresh=False,
    )


def test_cancel_series_does_not_cancel_other_subscriptions(provider):
    first, second = BarSeries("AAPL", "1min", live=True), BarSeries("SPY", "1min", live=True)
    req_id, _ = provider._new_request(first)
    other_id, _ = provider._new_request(second)
    provider.cancel_bars(first)
    provider.cancelHistoricalData.assert_called_once_with(req_id)
    assert req_id not in provider._requests
    assert other_id in provider._requests

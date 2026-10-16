from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import Bar, BarSeries
from pyibquant.data.providers.ibkr import IBKRProvider, calendar_window, normalize_bar
from pyibquant.errors import DataError, RequestTimeout


def raw(stamp, close=101, volume=50):
    return SimpleNamespace(date=stamp, open=100, high=102, low=99, close=close, volume=volume)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        "pyibquant.data.providers.ibkr.current_time",
        lambda: datetime(2026, 10, 15, 16, tzinfo=UTC).timestamp(),
    )
    result = IBKRProvider("127.0.0.1", 7497, 71, 0.01)
    result.isConnected = Mock(return_value=True)
    result.cancelHistoricalData = Mock()
    result._pacer = Mock()

    def details(req_id, contract):
        result.contractDetails(req_id, SimpleNamespace(contract=contract))
        result.contractDetailsEnd(req_id)

    result.reqContractDetails = Mock(side_effect=details)
    return result


def history(provider, rows):
    def respond(req_id, *args):
        for row in rows:
            provider.historicalData(req_id, row)
        provider.historicalDataEnd(req_id, "", "")

    provider.reqHistoricalData = Mock(side_effect=respond)


def test_historical_page_preserves_subscription_and_concurrent_updates(provider):
    history(provider, [raw("1792071000")])
    series = provider.bars("AAPL", live=True)
    live_id = provider.reqHistoricalData.call_args.args[0]

    def older(req_id, *args):
        provider.historicalData(req_id, raw("1792070940"))
        provider.historicalData(req_id, raw("1792070940"))
        provider.historicalData(req_id, raw("1792071000", close=1))
        provider.historicalDataUpdate(live_id, raw("1792071000", close=105))
        provider.historicalDataEnd(req_id, "", "")

    provider.reqHistoricalData = Mock(side_effect=older)
    assert provider.load_older(series) == 1
    args = provider.reqHistoricalData.call_args.args
    assert args[2] == datetime.fromtimestamp(1792071000, UTC).strftime("%Y%m%d %H:%M:%S UTC")
    assert args[3:9] == ("1 W", "1 min", "TRADES", 1, 2, False)
    assert series.snapshot()[-1].close == 105
    assert list(provider._requests) == [live_id]
    provider.cancelHistoricalData.assert_not_called()
    assert not series.history_exhausted


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [(date(2026, 10, 15), "20261015 04:00:00 UTC"), (date(2026, 2, 2), "20260202 05:00:00 UTC")],
)
def test_date_boundary_uses_new_york_midnight_and_contract_settings(provider, stamp, expected):
    series = BarSeries("AAPL", "1d")
    series.regular_hours = False
    series.primary_exchange = "NASDAQ"
    series.update(Bar(stamp, 100, 102, 99, 101, 50))
    history(provider, [])
    provider.load_older(series)
    args = provider.reqHistoricalData.call_args.args
    assert args[2] == expected
    assert args[6] == 0
    assert args[1].primaryExchange == "NASDAQ"
    assert series.history_exhausted


@pytest.mark.parametrize("empty_error", [False, True])
def test_empty_history_stops_further_downloads(provider, empty_error):
    series = BarSeries("AAPL", "1d")
    series.update(Bar(date(2026, 10, 15), 100, 102, 99, 101, 50))
    if empty_error:
        provider.reqHistoricalData = Mock(
            side_effect=lambda req_id, *args: provider.error(
                req_id, 0, 162, "HMDS query returned no data: AAPL@SMART Trades"
            )
        )
    else:
        history(provider, [])
    assert provider.load_older(series) == 0
    assert series.history_exhausted
    assert provider.load_older(series) == 0
    assert provider.reqHistoricalData.call_count == 1
    assert series.error is None
    assert not provider._requests


@pytest.mark.parametrize("timeout", [False, True])
def test_history_failure_retains_chart_and_allows_retry(provider, timeout):
    series = BarSeries("AAPL", "1d", live=True)
    original = Bar(date(2026, 10, 15), 100, 102, 99, 101, 50)
    series.update(original)
    if timeout:
        provider.reqHistoricalData = Mock()
    else:
        provider.reqHistoricalData = Mock(
            side_effect=lambda req_id, *args: provider.error(req_id, 0, 162, "No permissions")
        )
    with pytest.raises(RequestTimeout if timeout else DataError):
        provider.load_older(series)
    assert series.snapshot() == (original,)
    assert series.error is None
    assert not series.history_exhausted
    assert not provider._requests
    provider.cancelHistoricalData.assert_called_once()


def test_yearly_history_fills_partial_year_and_live_updates_keep_added_months(provider):
    history(provider, [raw("20261001", volume=10), raw("20261101", volume=20)])
    series = provider.bars("AAPL", interval="1y", live=True)
    live_id = provider.reqHistoricalData.call_args.args[0]
    history(provider, [raw("20260901", close=103, volume=30), raw("20260101", volume=40)])
    assert provider.load_older(series) == 0  # More source months, still one annual candle.
    assert not series.history_exhausted
    assert series.snapshot()[0].volume == 100
    provider.historicalDataUpdate(live_id, raw("20261101", close=106, volume=25))
    assert series.snapshot()[0].volume == 105
    assert series.snapshot()[0].close == 106
    history(provider, [raw("20251201", volume=50), raw("20260101", volume=1)])
    assert provider.load_older(series) == 1
    assert [bar.timestamp for bar in series.snapshot()] == [date(2025, 1, 1), date(2026, 1, 1)]
    assert series.snapshot()[1].volume == 105
    assert list(provider._requests) == [live_id]


@pytest.mark.parametrize(
    ("interval", "first", "update", "anchor"),
    [
        ("1y", "20261015", "20261016", date(2026, 10, 1)),
        ("1w", "20261015", "20261016", date(2026, 10, 12)),
    ],
)
def test_calendar_period_end_dates_replace_one_period(provider, interval, first, update, anchor):
    assert normalize_bar(raw(first), interval).timestamp == anchor
    history(provider, [raw(first, volume=10)])
    series = provider.bars("AAPL", interval=interval, duration="1 Y", live=True)
    req_id = provider.reqHistoricalData.call_args.args[0]
    provider.historicalDataUpdate(req_id, raw(update, close=106, volume=15))
    assert len(series) == 1
    assert series.snapshot()[0].volume == 15
    assert series.snapshot()[0].close == 106
    if interval == "1y":
        assert list(provider._monthly_bars[series]) == [anchor]


@pytest.mark.parametrize(
    ("interval", "duration", "expected_duration", "floor"),
    [
        ("1y", "1 D", "1 Y", date(2026, 1, 1)),
        ("1y", "1 Y", "2 Y", date(2025, 1, 1)),
        ("1y", "10 Y", "11 Y", date(2016, 1, 1)),
        ("1w", "1 D", "1 Y", date(2026, 10, 12)),
        ("1w", "5 Y", "6 Y", date(2021, 10, 11)),
    ],
)
def test_calendar_requests_cover_complete_starting_periods(
    interval, duration, expected_duration, floor
):
    ending = datetime(2026, 10, 15, 4, tzinfo=UTC)
    assert calendar_window(interval, duration, ending) == (expected_duration, floor)


def test_extra_calendar_source_year_does_not_add_unrequested_candles(provider):
    history(
        provider,
        [
            raw("20241231", volume=100),
            raw("20250131", volume=10),
            raw("20251231", volume=20),
            raw("20261015", volume=30),
        ],
    )
    series = provider.bars("AAPL", interval="1y", duration="1 Y", _end=date(2026, 10, 15))
    assert [bar.timestamp for bar in series.snapshot()] == [date(2025, 1, 1), date(2026, 1, 1)]
    assert [bar.volume for bar in series.snapshot()] == [30, 30]

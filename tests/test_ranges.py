from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock

import pytest
from test_history import provider as provider

from pyibquant import Bar, BarSeries, HistoricalRangeError, Market
from pyibquant.data.history import normalize_range
from pyibquant.data.providers.ibkr import range_duration, range_page_start
from pyibquant.errors import ConnectionError, RequestTimeout


def page(interval, *stamps):
    series = BarSeries('AAPL', interval)
    for index, stamp in enumerate(stamps):
        series.update(Bar(stamp, 100, 110, 90, 100 + index, 10))
    return series


def test_intraday_dates_are_ny_midnights_with_dst_and_datetimes_normalize_to_utc():
    bounds = normalize_range('2026-03-08', '2026-03-09', '1min')
    assert bounds.start == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert bounds.end == datetime(2026, 3, 9, 4, tzinfo=UTC)
    aware = normalize_range('2026-07-06T09:30:00-04:00', '2026-07-06T14:30:00Z', '5min')
    assert aware.start == datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    assert aware.contains(aware.start)
    assert not aware.contains(aware.end)


@pytest.mark.parametrize('start,end,interval', [
    ('2026-01-01', '2026-01-01', '1d'),
    ('2026-01-02', '2026-01-01', '1d'),
    ('2026-01-01T09:30:00', '2026-01-02', '1min'),
    ('2026-01-01T00:00:00Z', '2026-01-02', '1d'),
    ('2026-01-01T00:00:00.5Z', '2026-01-02', '30s'),
    ('bad-date', '2026-01-02', '1min'),
    (1, '2026-01-02', '1min'),
])
def test_invalid_range_boundaries_fail_without_guessing(start, end, interval):
    with pytest.raises(ValueError):
        normalize_range(start, end, interval)


@pytest.mark.parametrize('kwargs', [
    {'start': '2026-01-01'}, {'end': '2026-01-02'},
    {'start': '2026-01-01', 'end': '2026-01-02', 'duration': '1 D'},
    {'start': '2026-01-01', 'end': '2026-01-02', 'live': True},
])
def test_conflicting_or_incomplete_queries_fail_before_provider_io(kwargs):
    broker = Mock()
    with pytest.raises(ValueError):
        Market(broker).bars('AAPL', **kwargs)
    broker.bars.assert_not_called()
    broker.bars_range.assert_not_called()


def test_market_range_dispatch_and_enrichment_end_are_explicit():
    broker = Mock()
    broker.bars_range.return_value = BarSeries('AAPL', '1min')
    market = Market(broker)
    series = market.bars('AAPL', start='2026-01-01', end='2026-01-02', include_sessions=True)
    assert series is broker.bars_range.return_value
    broker.bars.assert_not_called()
    bounds = broker.bars_range.call_args.kwargs['bounds']
    assert bounds == normalize_range('2026-01-01', '2026-01-02', '1min')
    broker.load_sessions.assert_called_once_with(series, before=bounds.end)


def test_default_lookback_is_unchanged():
    broker = Mock()
    Market(broker).bars('AAPL')
    assert broker.bars.call_args.kwargs['duration'] == '1 D'
    broker.bars_range.assert_not_called()


def test_fixed_windows_continue_across_empty_page_and_trim_overlaps(provider):
    end = datetime(2026, 1, 6, tzinfo=UTC)
    start = end - timedelta(days=3)
    provider.bars = Mock(side_effect=[
        page('1min', end - timedelta(days=1), end, start),
        page('1min'),
        page('1min', start - timedelta(seconds=30), start, start, start + timedelta(seconds=60)),
    ])
    result = provider.bars_range(
        'AAPL', interval='1min', bounds=normalize_range(start, end, '1min')
    )
    assert [b.timestamp for b in result.snapshot()] == [start, start + timedelta(seconds=60),
                                                       end - timedelta(days=1)]
    assert [call.kwargs['_end'] for call in provider.bars.call_args_list] == [
        end, end - timedelta(days=1), end - timedelta(days=2)]
    assert result.download_complete and result.download_pages == 3
    assert result.empty_windows == [(start + timedelta(days=1), start + timedelta(days=2))]
    assert result.requested_start == start and result.requested_end == end
    assert result.payload()['download_complete'] is True
    assert 'not independently verified' in result.warnings[-1]


@pytest.mark.parametrize('error', [RequestTimeout('timed out'), ConnectionError('socket lost')])
def test_failed_page_raises_with_partial_data_and_remaining_bounds(provider, error):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=3)
    provider.bars = Mock(side_effect=[page('1min', end - timedelta(hours=1)), error])
    with pytest.raises(HistoricalRangeError) as caught:
        provider.bars_range('AAPL', interval='1min', bounds=normalize_range(start, end, '1min'))
    failure = caught.value
    assert failure.__cause__ is error
    assert len(failure.partial) == 1
    assert failure.partial.download_pages == 1
    assert failure.partial.download_complete is False
    assert failure.partial.status == 'Historical range incomplete'
    assert failure.remaining_start == start
    assert failure.remaining_end == end - timedelta(days=1)
    assert not provider._requests


def test_empty_weekend_range_is_successful_but_not_claimed_gap_free(provider):
    provider.bars = Mock(return_value=BarSeries('AAPL', '1d'))
    result = provider.bars_range('AAPL', interval='1d',
        bounds=normalize_range('2026-01-03', '2026-01-05', '1d'))
    assert len(result) == 0
    assert result.download_complete is True
    assert result.empty_windows == [(date(2026, 1, 3), date(2026, 1, 5))]


def test_future_range_rejected_before_any_request(provider):
    provider.bars = Mock()
    with pytest.raises(ValueError, match='future'):
        provider.bars_range('AAPL', interval='1d',
            bounds=normalize_range('2026-10-15', '2027-01-01', '1d'))
    provider.bars.assert_not_called()


def test_calendar_bars_filter_anchor_dates_and_align_internal_pages(provider):
    lower = range_page_start(date(2026, 1, 7), '1w')
    assert lower.weekday() == 0
    assert range_page_start(date(2026, 6, 1), '1y').month == 1
    assert range_page_start(date(2026, 6, 1), '1y').day == 1
    provider.bars = Mock(return_value=page('1w', date(2026, 1, 5), date(2026, 1, 12)))
    result = provider.bars_range('AAPL', interval='1w',
        bounds=normalize_range('2026-01-06', '2026-01-13', '1w'))
    assert [b.timestamp for b in result.snapshot()] == [date(2026, 1, 12)]


def test_yearly_range_retains_monthly_inputs_and_aggregates_once(provider):
    def monthly_page(*args, **kwargs):
        result = BarSeries('AAPL', '1y')
        monthly = {stamp: Bar(stamp, 100, 110, 90, 102, 50) for stamp in (
            date(2024, 1, 1), date(2025, 1, 1), date(2025, 12, 1))}
        provider._monthly_bars[result] = monthly
        for year in (2024, 2025):
            result.update(provider._year_bar(monthly, year))
        return result

    provider.bars = Mock(side_effect=monthly_page)
    result = provider.bars_range('AAPL', interval='1y',
        bounds=normalize_range('2025-01-01', '2026-01-01', '1y'))
    assert len(result) == 1
    assert result.snapshot()[0].volume == 100
    assert len(provider._monthly_bars[result]) == 2


def test_range_series_cannot_be_extended_outside_its_declared_bounds():
    broker = Mock()
    series = BarSeries('AAPL', '1d')
    series.requested_start = date(2026, 1, 1)
    with pytest.raises(ValueError, match='Fixed-range'):
        Market(broker).load_older(series)
    broker.load_older.assert_not_called()


def test_request_durations_cover_partial_days_and_small_bars_are_bounded():
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert range_duration(start, start + timedelta(hours=25), '1min') == '2 D'
    assert range_duration(start, start + timedelta(seconds=31), '30s') == '60 S'
    assert start - range_page_start(start, '30s') == timedelta(hours=8)


def test_real_request_path_resolves_once_and_cache_hits_avoid_pacing(provider, tmp_path):
    pytest.importorskip('pyarrow')
    from types import SimpleNamespace

    from pyibquant import HistoricalCache

    provider.cache = HistoricalCache(tmp_path)

    def respond(req_id, contract, ending, duration, *args):
        stamp = datetime.strptime(ending, '%Y%m%d %H:%M:%S UTC').replace(tzinfo=UTC)
        provider.historicalData(req_id, SimpleNamespace(
            date=str(int((stamp - timedelta(minutes=1)).timestamp())),
            open=100, high=110, low=90, close=102, volume=50))
        provider.historicalDataEnd(req_id, '', '')

    provider.reqHistoricalData = Mock(side_effect=respond)
    bounds = normalize_range('2026-01-01', '2026-01-03', '1min')
    first = provider.bars_range('AAPL', interval='1min', bounds=bounds)
    assert first.download_pages == 2 and first.download_cached_pages == 0
    assert provider.reqContractDetails.call_count == 1
    assert provider._pacer.acquire.call_count == 2
    provider._pacer.reset_mock()
    provider.reqHistoricalData.reset_mock()
    second = provider.bars_range('AAPL', interval='1min', bounds=bounds)
    assert second.snapshot() == first.snapshot()
    assert second.download_cached_pages == 2
    provider.reqHistoricalData.assert_not_called()
    provider._pacer.acquire.assert_not_called()
    assert provider.reqContractDetails.call_count == 2
    assert second.metadata()['download']['cached_pages'] == 2


def test_metadata_is_json_compatible_and_copied():
    import json

    series = page('1d', date(2026, 1, 2))
    series.requested_start, series.requested_end = date(2026, 1, 1), date(2026, 1, 3)
    series.download_complete = True
    series.empty_windows = [(date(2026, 1, 1), date(2026, 1, 2))]
    series.warnings = ['unverified gap']
    meta = series.metadata()
    assert meta['timestamp_kind'] == 'date' and meta['timestamp_timezone'] is None
    assert meta['query']['boundaries'] == 'start_inclusive_end_exclusive'
    assert meta['coverage']['gaps'] == 'not_verified'
    assert meta['coverage']['bar_finality'] == 'not_verified'
    assert json.loads(json.dumps(meta))['coverage']['rows'] == 1
    meta['warnings'].clear()
    meta['download']['empty_windows'].clear()
    assert series.warnings and series.empty_windows


def test_long_range_download_does_not_block_subscription_cancellation():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    broker = Mock()
    entered, release = Event(), Event()
    market = Market(broker)
    active = BarSeries('SPY', '1min', live=True)
    market._subscriptions[active] = None

    def download(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return BarSeries('AAPL', '1d')

    broker.bars_range.side_effect = download
    with ThreadPoolExecutor(max_workers=2) as workers:
        future = workers.submit(market.bars, 'AAPL', interval='1d',
                                start='2026-01-01', end='2026-01-02')
        try:
            assert entered.wait(1)
            cancel = workers.submit(market.cancel, active)
            cancel.result(timeout=1)
            broker.cancel_bars.assert_called_once_with(active)
        finally:
            release.set()
        assert future.result(timeout=1).symbol == 'AAPL'


def test_yearly_multi_page_ranges_keep_complete_years_without_duplicate_months(provider):
    def response(*args, **kwargs):
        ending = kwargs['_end']
        assert type(ending) is date
        page_series = BarSeries('AAPL', '1y')
        monthly = {}
        for year in range(2014, ending.year):
            for month, close in [(1, 101), (12, 105)]:
                stamp = date(year, month, 1)
                monthly[stamp] = Bar(stamp, 100, 110, 90, close, 50)
        provider._monthly_bars[page_series] = monthly
        for year in {stamp.year for stamp in monthly}:
            page_series.update(provider._year_bar(monthly, year))
        return page_series

    provider.bars = Mock(side_effect=response)
    result = provider.bars_range('AAPL', interval='1y',
        bounds=normalize_range('2015-01-01', '2026-01-01', '1y'))
    assert result.download_pages == 2
    assert [b.timestamp.year for b in result.snapshot()] == list(range(2015, 2026))
    assert all(b.volume == 100 and b.close == 105 for b in result.snapshot())
    assert len(provider._monthly_bars[result]) == 22

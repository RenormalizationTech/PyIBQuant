from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import Bar, BarSeries, Market
from pyibquant.data.providers.ibkr import IBKRProvider
from pyibquant.errors import RequestTimeout


def provider():
    result = IBKRProvider('127.0.0.1', 7497, 71, 0.01)
    result.isConnected = Mock(return_value=True)
    result.cancelHistoricalData = Mock()
    result._pacer = Mock()
    result._resolve = Mock(return_value=object())
    return result


def series():
    result = BarSeries('AAPL', '1min', live=True)
    result.update(Bar(datetime(2026, 11, 27, 14, 30, tzinfo=UTC), 1, 2, 1, 2, 10))
    return result


def test_actual_early_close_and_dst_schedule_normalization():
    broker, bars = provider(), series()

    def respond(req_id, *args):
        regular = args[5] == 1
        broker.historicalSchedule(req_id, '', '', 'US/Eastern', [SimpleNamespace(
            startDateTime='20261127-09:30:00' if regular else '20261127-04:00:00',
            endDateTime='20261127-13:00:00' if regular else '20261127-20:00:00',
            refDate='20261127',
        ), SimpleNamespace(
            startDateTime='20260706-09:30:00', endDateTime='20260706-16:00:00',
            refDate='20260706',
        )])

    broker.reqHistoricalData = Mock(side_effect=respond)
    broker.load_sessions(bars)
    regular = [s for s in bars.sessions if s['regular']]
    assert regular[0]['start'] == datetime(2026, 7, 6, 13, 30, tzinfo=UTC).timestamp()
    assert regular[1]['end'] == datetime(2026, 11, 27, 18, tzinfo=UTC).timestamp()
    assert all(call.args[5] == 'SCHEDULE' for call in broker.reqHistoricalData.call_args_list)
    assert not broker._requests
    broker.load_sessions(bars)
    assert len(bars.sessions) == 4  # Repeated/overlapping pages do not duplicate sessions.
    payload = bars.payload()
    payload['sessions'][0]['start'] = 0
    assert bars.sessions[0]['start'] != 0


@pytest.mark.parametrize('failure', ['timeout', 'timezone', 'backwards'])
def test_schedule_failures_preserve_usable_bars(failure):
    broker, bars = provider(), series()
    previous = bars.snapshot()

    def respond(req_id, *args):
        if failure == 'timeout':
            return
        broker.historicalSchedule(req_id, '', '',
            'Not/AZone' if failure == 'timezone' else 'America/New_York',
            [SimpleNamespace(startDateTime='20261127-16:00:00',
                endDateTime='20261127-09:30:00', refDate='20261127')])

    broker.reqHistoricalData = Mock(side_effect=respond)
    broker.load_sessions(bars)
    assert bars.snapshot() == previous
    assert bars.schedule_error.startswith('Session schedule unavailable:')
    assert not bars.error
    assert not broker._requests
    if failure == 'timeout':
        broker.cancelHistoricalData.assert_called_once()


@pytest.mark.parametrize("include_sessions", [False, True])
def test_market_enrichment_choice_persists_through_history(include_sessions):
    broker, bars = Mock(), series()
    broker.bars.return_value = bars
    market = Market(broker)
    assert market.bars('AAPL', include_sessions=include_sessions) is bars
    assert bars.include_sessions is include_sessions
    assert broker.load_sessions.call_count == int(include_sessions)
    broker.load_older.return_value = 3
    assert market.load_older(bars) == 3
    if include_sessions:
        broker.load_sessions.assert_called_with(bars, before=bars.snapshot()[0].timestamp)
    broker.load_older.side_effect = RequestTimeout('failed')
    with pytest.raises(RequestTimeout):
        market.load_older(bars)
    assert broker.load_sessions.call_count == 2 * int(include_sessions)


def test_historical_and_live_receipt_times_are_distinct():
    bars = series()
    assert bars.last_update is not None
    assert bars.last_live_update is None
    bars.update(bars.snapshot()[0], live=True)
    assert bars.last_live_update == bars.last_update
    assert bars.payload()['last_live_update'].endswith('+00:00')


def test_plain_python_bars_do_not_request_schedules_by_default():
    broker, bars = Mock(), series()
    broker.bars.return_value = bars
    assert Market(broker).bars('AAPL') is bars
    broker.load_sessions.assert_not_called()
    assert not bars.include_sessions
    assert bars.payload()['include_sessions'] is False


@pytest.mark.parametrize('include_sessions', [False, True])
def test_serving_chart_enables_schedule_only_when_requested(monkeypatch, include_sessions):
    broker, bars = Mock(), series()
    replacement = series()
    broker.bars.return_value = replacement
    server = Mock()
    monkeypatch.setattr('pyibquant.visualization.chart.serve_chart', server)
    Market(broker).serve(bars, open_browser=False, include_sessions=include_sessions)
    assert bars.include_sessions is include_sessions
    assert broker.load_sessions.call_count == int(include_sessions)
    load = server.call_args.kwargs['loader']
    assert load('AAPL', '5min', '2 D', True) is replacement
    assert replacement.include_sessions is include_sessions
    assert broker.load_sessions.call_count == 2 * int(include_sessions)


def test_chart_default_enriches_without_duplicate_fetch_for_enriched_series(monkeypatch):
    broker, bars = Mock(), series()
    broker.bars.return_value = bars
    monkeypatch.setattr('pyibquant.visualization.chart.serve_chart', Mock())
    market = Market(broker)
    market.serve(bars, open_browser=False)
    broker.load_sessions.assert_called_once_with(bars)
    broker.load_sessions.reset_mock()
    market.bars('AAPL', include_sessions=True)
    market.serve(bars, open_browser=False)
    broker.load_sessions.assert_called_once_with(bars)


@pytest.mark.parametrize('value', ['false', None, 1])
def test_invalid_enrichment_flag_rejected_before_provider_io(value, monkeypatch):
    broker = Mock()
    monkeypatch.setattr('pyibquant.visualization.chart.serve_chart', Mock())
    market = Market(broker)
    with pytest.raises(ValueError, match='boolean'):
        market.bars('AAPL', include_sessions=value)
    with pytest.raises(ValueError, match='boolean'):
        market.serve(series(), include_sessions=value)
    broker.bars.assert_not_called()
    broker.load_sessions.assert_not_called()

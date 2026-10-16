from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import Bar, BarSeries, Market
from pyibquant.data.providers.ibkr import IBKRProvider
from pyibquant.errors import ConnectionError


def make_provider():
    provider = IBKRProvider('127.0.0.1', 7497, 71, 0.01)
    provider.isConnected = Mock(return_value=True)
    provider.cancelHistoricalData = Mock()
    provider._pacer = Mock()
    provider._resolve = Mock(return_value=SimpleNamespace(conId=1, exchange='SMART',
        primaryExchange='NASDAQ', currency='USD'))
    return provider


def raw(stamp, close=102):
    return SimpleNamespace(date=stamp, open=100, high=110, low=90, close=close, volume=50)


def test_restoration_keeps_identity_history_and_new_callbacks():
    broker = make_provider()
    target = BarSeries('AAPL', '1min', live=True)
    target.duration = '6 M'
    target.regular_hours = False
    target.primary_exchange = 'NASDAQ'
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    oldest = Bar(now - timedelta(days=30), 1, 2, 1, 2, 10)
    stale = Bar(now - timedelta(minutes=5), 100, 110, 90, 100, 20)
    target.update(oldest)
    target.update(stale)

    def respond(req_id, *args):
        broker.historicalData(req_id, raw(str(int(stale.timestamp.timestamp())), close=104))
        broker.historicalData(req_id, raw(str(int(now.timestamp()))))
        broker.historicalDataEnd(req_id, '', '')

    broker.reqHistoricalData = Mock(side_effect=respond)
    broker.restore_series(target)
    req_id = broker.reqHistoricalData.call_args.args[0]
    assert broker._requests[req_id].series is target
    assert target.snapshot()[0] == oldest
    assert target.snapshot()[1].close == 104
    assert target.duration == '6 M'
    assert target.regular_hours is False
    assert target.connection_state == 'subscribed'
    broker.historicalDataUpdate(req_id, raw(str(int(now.timestamp())), close=107))
    assert target.snapshot()[-1].close == 107
    assert target.last_live_update is not None
    assert len(target) == 3


def test_yearly_restoration_keeps_paginated_months_and_replacement_volume():
    broker = make_provider()
    year = datetime.now(UTC).year
    target = BarSeries('AAPL', '1y', live=True)
    old = Bar(date(year - 1, 1, 1), 1, 2, 1, 2, 10)
    january = Bar(date(year, 1, 1), 100, 110, 90, 102, 50)
    broker._monthly_bars[target] = {old.timestamp: old, january.timestamp: january}
    target.update(old)
    target.update(january)

    def respond(req_id, *args):
        broker.historicalData(req_id, raw(f'{year}0101', close=105))
        broker.historicalDataEnd(req_id, '', '')

    broker.reqHistoricalData = Mock(side_effect=respond)
    broker.restore_series(target)
    req_id = broker.reqHistoricalData.call_args.args[0]
    assert len(target) == 2
    broker.historicalDataUpdate(req_id, raw(f'{year}0101', close=107))
    assert target.snapshot()[-1].volume == 50
    assert target.snapshot()[0] == old
    assert len(broker._monthly_bars[target]) == 2


def test_data_maintained_recovers_status_but_data_lost_requires_restore():
    broker = make_provider()
    target = BarSeries('AAPL', '1min', live=True)
    _, request = broker._new_request(target)
    request.initialized = True
    request.done.set()
    broker.error(-1, 0, 1100, 'lost')
    assert target.connection_state == 'disconnected'
    broker.error(-1, 0, 1102, 'maintained')
    assert target.connection_state == 'subscribed'
    assert not target.error
    assert request.error is None
    broker.error(-1, 0, 1101, 'data lost')
    assert target.connection_state == 'disconnected'
    assert request.error is not None


@pytest.mark.parametrize("include_sessions", [False, True])
def test_market_recovery_preserves_targets_and_cancellation(monkeypatch, include_sessions):
    original = make_provider()
    original.close = Mock()
    original.load_sessions = Mock()
    target = BarSeries('AAPL', '1min', live=True)
    original.bars = Mock(return_value=target)
    market = Market(original)
    market.bars('AAPL', live=True, include_sessions=include_sessions)
    replacement = make_provider()
    replacement.open = Mock()
    replacement.close = Mock()
    replacement.restore_series = Mock()
    replacement.load_sessions = Mock()
    constructor = Mock(return_value=replacement)
    monkeypatch.setattr('pyibquant.data.providers.ibkr.IBKRProvider', constructor)
    market._recover()
    original.close.assert_called_once()
    replacement.restore_series.assert_called_once_with(target)
    if include_sessions:
        replacement.load_sessions.assert_called_once_with(target)
    else:
        replacement.load_sessions.assert_not_called()
    market.cancel(target)
    market._recover()
    assert replacement.restore_series.call_count == 1
    assert target not in market._subscriptions
    market.close()
    assert market._stop.is_set()


def test_failed_recovery_keeps_history_and_retryable_targets(monkeypatch):
    original = make_provider()
    original.close = Mock()
    target = BarSeries('AAPL', '1d', live=True)
    target.update(Bar(date(2026, 1, 1), 1, 2, 1, 2, 10))
    market = Market(original)
    market._subscriptions[target] = None
    replacement = make_provider()
    replacement.open = Mock(side_effect=ConnectionError('TWS unavailable'))
    replacement.close = Mock()
    monkeypatch.setattr(
        'pyibquant.data.providers.ibkr.IBKRProvider', Mock(return_value=replacement)
    )
    with pytest.raises(ConnectionError):
        market._recover()
    assert len(target) == 1
    assert target.connection_state == 'reconnecting'
    assert 'TWS unavailable' in target.error
    assert target in market._subscriptions
    replacement.close.assert_called_once()


def test_maintenance_retries_with_bounded_backoff_and_stops():
    market = Market(make_provider())
    series = BarSeries('AAPL', '1min', live=True)
    series.connection_state = 'disconnected'
    market._subscriptions[series] = None
    market._recover = Mock(side_effect=ConnectionError('offline'))
    market._stop = Mock()
    market._stop.wait.side_effect = [False] * 8 + [True]
    market._maintain_connection()
    waits = [call.args[0] for call in market._stop.wait.call_args_list]
    assert waits == [1, 2, 4, 8, 16, 30, 30, 30, 30]
    assert market._recover.call_count == 8


def test_new_connection_copies_yearly_sources_without_aliasing():
    broker = make_provider()
    series = BarSeries('AAPL', '1y', live=True)
    month = Bar(date(2026, 1, 1), 100, 110, 90, 102, 50)
    broker._monthly_bars[series] = {month.timestamp: month}
    replacement = broker.new_connection()
    assert replacement._monthly_bars[series] == broker._monthly_bars[series]
    replacement._monthly_bars[series].clear()
    assert broker._monthly_bars[series]
    assert not replacement.isConnected()


@pytest.mark.parametrize("include_sessions", [False, True])
def test_schedule_refresh_respects_enrichment_choice(monkeypatch, include_sessions):
    broker = make_provider()
    broker.load_sessions = Mock()
    market = Market(broker)
    series = BarSeries('AAPL', '1min', live=True)
    series.connection_state = 'subscribed'
    series.include_sessions = include_sessions
    market._subscriptions[series] = None
    market._stop = Mock()
    market._stop.wait.side_effect = [False, True]
    clock = Mock(side_effect=[0, 301, 301])
    monkeypatch.setattr('pyibquant.market.monotonic', clock)
    market._maintain_connection()
    if include_sessions:
        broker.load_sessions.assert_called_once_with(series, recent_only=True)
    else:
        broker.load_sessions.assert_not_called()

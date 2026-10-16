"""Subscription ownership, independent cursors and explicit terminal stream states."""

from datetime import date
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import BarSeries, Market, Option
from pyibquant.data.providers.ibkr import IBKRProvider
from pyibquant.errors import DataError


@pytest.fixture
def provider():
    broker = IBKRProvider('127.0.0.1', 7497, 195, .02)
    broker.isConnected = Mock(return_value=True)
    broker.reqMarketDataType = Mock()
    broker.reqMktData = Mock()
    broker.cancelMktData = Mock()
    broker.cancelHistoricalData = Mock()
    broker.disconnect = Mock()

    def resolve(req_id, contract):
        contract.conId = 123
        if contract.secType == 'OPT':
            contract.multiplier = '100'
        broker.contractDetails(req_id, SimpleNamespace(contract=contract))
        broker.contractDetailsEnd(req_id)
    broker.reqContractDetails = Mock(side_effect=resolve)
    return broker


def test_subscription_returns_before_prices_and_consumers_keep_independent_cursors(provider):
    stream = Market(provider).stream_quote('AAPL')
    req_id = provider.reqMktData.call_args.args[0]
    assert provider.reqMktData.call_args.args[2:] == ('', False, False, [])
    initial = stream.latest()
    assert initial.bid is None and initial.sequence == 0 and initial.status == 'collecting'
    assert initial.streaming and not initial.to_dict()['snapshot_complete']
    assert initial.completed_at is None
    provider.tickPrice(req_id, 1, 100, None)
    first = stream.wait_for_update(initial.sequence, timeout=0)
    assert first.bid == 100 and first.sequence > initial.sequence
    provider.tickPrice(req_id, 2, 102, None)
    a = stream.wait_for_update(first.sequence, timeout=0)
    b = stream.wait_for_update(initial.sequence, timeout=0)
    assert a.sequence == b.sequence and a.midpoint == b.midpoint == 101
    assert first.ask is None
    assert stream.wait_for_update(a.sequence, timeout=.001).sequence == a.sequence
    stream.close()
    assert stream.closed and stream.latest().status == 'closed'
    provider.cancelMktData.assert_called_once_with(req_id)
    stream.close()
    assert provider.cancelMktData.call_count == 1 and not provider._requests


def test_two_streams_do_not_cancel_each_other_or_chart_bars(provider):
    market = Market(provider)
    first = market.stream_quote('AAPL')
    first_id = provider.reqMktData.call_args.args[0]
    second = market.stream_quote(Option('AAPL', date(2026, 11, 20), 340, 'C'))
    second_id = provider.reqMktData.call_args.args[0]
    provider.reqMarketDataType.assert_called_once_with(1)
    bars = BarSeries('AAPL', '1min', live=True)
    provider._new_request(bars)
    market.cancel(bars)
    assert not first.closed and not second.closed
    first.close()
    assert second_id in provider._requests
    provider.tickPrice(first_id, 1, 50, None)  # Late callbacks are ignored.
    provider.tickPrice(second_id, 1, 12.65, None)
    assert second.latest().bid == 12.65 and first.latest().bid is None
    second.close()
    assert not provider._requests


def test_different_feed_modes_require_separate_connections_until_streams_close(provider):
    stream = provider.stream_quote('AAPL', market_data_type='live')
    for method in (provider.stream_quote, provider.quote):
        with pytest.raises(DataError, match='another market_data_type'):
            method('AAPL', market_data_type='frozen')
    provider.reqMarketDataType.assert_called_once_with(1)
    assert provider.reqMktData.call_count == 1
    stream.close()
    other = provider.stream_quote('AAPL', market_data_type='frozen')
    assert provider.reqMarketDataType.call_args.args == (2,)
    other.close()


def test_same_mode_snapshot_does_not_end_or_overwrite_a_stream(provider):
    stream = provider.stream_quote('AAPL')
    stream_id = provider.reqMktData.call_args.args[0]

    def snapshot(req_id, contract, ticks, snapshot, *args):
        assert snapshot
        provider.tickPrice(stream_id, 1, 100, None)
        provider.tickPrice(req_id, 1, 110, None)
        provider.tickSnapshotEnd(req_id)
    provider.reqMktData = Mock(side_effect=snapshot)
    assert provider.quote('AAPL').bid == 110
    assert stream.latest().bid == 100 and not stream.closed
    provider.tickSnapshotEnd(stream_id)  # No snapshot-end event may close a stream.
    assert not stream.closed
    stream.close()


@pytest.mark.parametrize('terminal', ['permission', 'disconnect', 'close'])
def test_terminal_states_wake_waiters_and_preserve_first_failure(provider, terminal):
    stream = provider.stream_quote('AAPL')
    req_id = provider.reqMktData.call_args.args[0]
    ready = Event()
    observed = []

    def wait():
        ready.set()
        observed.append(stream.wait_for_update(0, timeout=1))
    worker = Thread(target=wait)
    worker.start()
    assert ready.wait(1)
    if terminal == 'permission':
        provider.error(req_id, 0, 354, 'Not subscribed')
    elif terminal == 'disconnect':
        provider.connectionClosed()
    else:
        provider.close()
    worker.join(1)
    assert not worker.is_alive()
    expected = {'permission': 'failed', 'disconnect': 'disconnected', 'close': 'closed'}[terminal]
    assert observed[0].status == expected and observed[0].error
    assert stream.closed
    stream.close()
    assert stream.latest().status == expected  # Later cleanup does not mask the first cause.


def test_permission_warning_is_observable_without_ending_the_stream(provider):
    stream = provider.stream_quote('AAPL')
    req_id = provider.reqMktData.call_args.args[0]
    for code in (10091, 2176):
        before = stream.latest().sequence
        provider.error(req_id, 0, code, 'Partial data warning')
        after = stream.wait_for_update(before, timeout=0)
        assert after.sequence > before and str(code) in after.warnings[-3]
    assert not stream.closed
    stream.close()


def test_initial_send_failure_cancels_and_releases_mode_ownership(provider):
    provider.reqMktData = Mock(side_effect=OSError('socket write failed'))
    with pytest.raises(OSError):
        provider.stream_quote('AAPL')
    assert not provider._requests
    provider.cancelMktData.assert_called_once()

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


def replacement_for(provider):
    replacement = provider.new_connection()
    replacement.isConnected = Mock(return_value=True)
    replacement.open = Mock()
    replacement.reqMarketDataType = Mock()
    replacement.reqMktData = Mock()
    replacement.cancelMktData = Mock()
    replacement.disconnect = Mock()
    return replacement


def managed_market(provider):
    market = Market(provider)
    market._recovery_thread = Mock()  # Drive recovery deterministically in these tests.
    return market


def test_managed_quote_recovery_keeps_owner_and_cursor_but_clears_all_fields(provider):
    market = managed_market(provider)
    stream = market.stream_quote(Option('AAPL', date(2026, 11, 20), 340, 'C'), reconnect=True)
    old_id = provider.reqMktData.call_args.args[0]
    provider.marketDataType(old_id, 1)
    provider.tickPrice(old_id, 1, 10, None)
    original = stream.latest()
    provider.connectionClosed()
    lost = stream.wait_for_update(original.sequence, timeout=0)
    assert not stream.closed and lost.status == 'disconnected'
    assert lost.bid is None and lost.market_data_type is None and not lost.field_received_at
    assert len(lost.gaps) == 1 and lost.gaps[0].ended_at is None
    provider.tickPrice(old_id, 1, 99, None)
    provider.marketDataType(old_id, 1)
    assert stream.latest().bid is None and stream.latest().market_data_type is None
    replacement = replacement_for(provider)
    provider.new_connection = Mock(return_value=replacement)
    market._recover()
    restored = stream.latest()
    assert not stream.closed and restored.status == 'collecting'
    assert restored.generation == 1 and restored.sequence > lost.sequence
    assert restored.bid is None and restored.market_data_type is None
    assert restored.gaps[0].ended_at is not None
    assert restored.gaps[0].next_generation == 1
    new_id, contract, *arguments = replacement.reqMktData.call_args.args
    assert contract.conId == original.instrument.instrument_id
    assert contract.secType == 'OPT' and arguments == ['', False, False, []]
    provider.tickPrice(old_id, 1, 98, None)
    provider.error(old_id, 0, 354, 'late old permission failure')
    assert stream.latest().bid is None and not stream.closed
    replacement.marketDataType(new_id, 1)
    replacement.tickPrice(new_id, 1, 11, None)
    assert stream.latest().bid == 11 and stream.latest().market_data_type == 'live'
    assert stream.latest().instrument == original.instrument
    stream.close()
    replacement.cancelMktData.assert_called_once_with(new_id)
    assert not replacement._requests
    market.close()


def test_failed_reconnect_retries_without_losing_gap_or_resurrecting_closed_owner(provider):
    from pyibquant.errors import ConnectionError

    market = managed_market(provider)
    stream = market.stream_quote('AAPL', reconnect=True)
    provider.connectionClosed()
    first_gap = stream.latest().gaps[0]
    failed = replacement_for(provider)
    failed.open.side_effect = ConnectionError('TWS offline')
    provider.new_connection = Mock(return_value=failed)
    with pytest.raises(ConnectionError):
        market._recover()
    assert not stream.closed and stream.latest().status == 'disconnected'
    assert stream.latest().gaps == (first_gap,)
    stream.close()
    failed.new_connection = Mock()
    market._recover()
    failed.new_connection.assert_not_called()
    market.close()


def test_recovery_send_failure_detaches_before_retry_and_retains_each_gap(provider):
    market = managed_market(provider)
    stream = market.stream_quote('AAPL', reconnect=True)
    provider.connectionClosed()
    failed = replacement_for(provider)
    failed.reqMktData.side_effect = OSError('write failed')
    provider.new_connection = Mock(return_value=failed)
    with pytest.raises(OSError):
        market._recover()
    assert not stream.closed and not failed._requests
    assert len(stream.latest().gaps) == 2
    assert stream.latest().generation == 1
    successful = replacement_for(provider)
    failed.new_connection = Mock(return_value=successful)
    market._recover()
    assert stream.latest().generation == 2 and len(stream.latest().gaps) == 2
    assert stream.latest().gaps[-1].ended_at is not None
    market.close()


@pytest.mark.parametrize('error_code', [354, 10197])
def test_permission_failure_is_terminal_and_is_not_automatically_retried(provider, error_code):
    market = managed_market(provider)
    stream = market.stream_quote('AAPL', reconnect=True)
    req_id = provider.reqMktData.call_args.args[0]
    provider.error(req_id, 0, error_code, 'market data unavailable')
    assert stream.closed and stream.latest().status == 'failed'
    provider.new_connection = Mock()
    market._recover()
    provider.new_connection.assert_not_called()
    market.close()


def test_cancellation_during_restore_cannot_leave_or_resurrect_a_request(provider):
    market = managed_market(provider)
    stream = market.stream_quote('AAPL', reconnect=True)
    provider.connectionClosed()
    replacement = replacement_for(provider)
    replacement.reqMktData.side_effect = lambda *args: stream.close()
    provider.new_connection = Mock(return_value=replacement)
    market._recover()
    assert stream.closed and not replacement._requests
    assert stream.latest().status == 'closed'
    market.close()


def test_quote_reconnect_requires_running_market_recovery_and_valid_boolean(provider):
    with pytest.raises(ValueError, match='requires Market.ibkr'):
        Market(provider).stream_quote('AAPL', reconnect=True)
    with pytest.raises(ValueError, match='boolean'):
        Market(provider).stream_quote('AAPL', reconnect=1)
    market = Market(provider)
    market.close()
    from pyibquant.errors import ConnectionError
    with pytest.raises(ConnectionError, match='closed'):
        market.stream_quote('AAPL')


def test_quote_only_maintenance_recovers_and_prunes_closed_handles(provider):
    market = managed_market(provider)
    stream = market.stream_quote('AAPL', reconnect=True)
    provider.connectionClosed()
    market._recover = Mock(side_effect=lambda: stream.close())
    market._stop = Mock()
    market._stop.wait.side_effect = [False, False, True]
    market._maintain_connection()
    market._recover.assert_called_once()
    assert not market._quote_subscriptions


def test_callback_already_waiting_on_old_state_cannot_contaminate_replacement(provider):
    from threading import current_thread

    market = managed_market(provider)
    stream = market.stream_quote('AAPL', reconnect=True)
    req_id = provider.reqMktData.call_args.args[0]
    state = stream._state
    original_lock = state.lock
    waiting = Event()
    main_thread = current_thread()

    class ObservedLock:
        def __enter__(self):
            if current_thread() is not main_thread:
                waiting.set()
            original_lock.acquire()

        def __exit__(self, *args):
            original_lock.release()

    state.lock = ObservedLock()
    replacement = replacement_for(provider)
    provider.new_connection = Mock(return_value=replacement)
    with state.lock:
        callback = Thread(target=provider.tickPrice, args=(req_id, 1, 999, None))
        callback.start()
        assert waiting.wait(1)  # Callback has captured the old request and is blocked.
        provider.connectionClosed()
        market._recover()
    callback.join(1)
    assert not callback.is_alive()
    assert stream.latest().generation == 1 and stream.latest().bid is None
    assert not stream.latest().field_received_at
    market.close()

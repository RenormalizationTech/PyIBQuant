"""Named requests reuse existing market acquisition and surface per-input errors."""

from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from pyibquant import (
    Bar,
    BarDataset,
    BarRequest,
    BarSeries,
    DatasetCollectionError,
    HistoricalRangeError,
    Market,
    Option,
)
from pyibquant.errors import ConnectionError, DataError


def series(symbol='A', interval='1d', complete=True, empty=False):
    result = BarSeries(symbol, interval)
    result.download_complete = complete
    if not empty:
        stamp = date(2025, 1, 1) if interval == '1d' else datetime(2025, 1, 1, tzinfo=UTC)
        result.update(Bar(stamp, 10, 12, 9, 11, 10))
    return result


def test_fetches_named_inputs_in_order_using_existing_range_dispatch():
    broker = Mock()
    originals = [series('A'), series('B')]
    broker.bars_range.side_effect = originals
    market = Market(broker)
    result = market.datasets({'alpha': ' a ', 'beta': BarRequest('B', primary_exchange='nasdaq')},
                             start='2025-01-01', end='2025-01-02', refresh=True)
    assert list(result) == ['alpha', 'beta']
    assert all(isinstance(value, BarDataset) for value in result.values())
    calls = broker.bars_range.call_args_list
    assert [call.args for call in calls] == [('A',), ('B',)]
    assert [call.kwargs['primary_exchange'] for call in calls] == ['', 'NASDAQ']
    assert all(call.kwargs['refresh'] is True for call in calls)
    assert all(call.kwargs['bounds'].start == date(2025, 1, 1) for call in calls)
    broker.bars.assert_not_called()
    assert not market._subscriptions
    originals[0].update(Bar(date(2025, 1, 2), 10, 12, 9, 11, 10))
    assert len(result['alpha']) == 1


def test_explicit_options_and_per_source_selectors_are_forwarded():
    option = Option('A', date(2099, 11, 20), 100, 'C', multiplier=50)
    broker = Mock()
    broker.bars_range.side_effect = [series('A', '5min') for _ in range(3)]
    result = Market(broker).datasets(
        {'underlying': 'A', 'midpoint': BarRequest(option, 'MIDPOINT'), 'trades': option},
        interval='5min', start='2025-01-01T00:00:00Z', end='2025-01-02T00:00:00Z',
    )
    assert list(result) == ['underlying', 'midpoint', 'trades']
    calls = broker.bars_range.call_args_list
    assert calls[0].args == ('A',)
    assert calls[1].args == calls[2].args == (option,)
    assert calls[1].kwargs['data_type'] == 'MIDPOINT'
    assert calls[2].kwargs['data_type'] == 'TRADES'
    assert 'primary_exchange' not in calls[1].kwargs


@pytest.mark.parametrize('failure', [
    'empty', 'partial', 'unknown', 'permission', 'disconnect', 'range',
])
def test_first_failed_input_is_named_and_completed_inputs_are_explicit(failure):
    broker = Mock()
    partial = series('B', complete=False)
    cause = {
        'empty': series('B', empty=True), 'partial': partial,
        'unknown': series('B', complete=None), 'permission': DataError('permission denied'),
        'disconnect': ConnectionError('lost connection'),
        'range': HistoricalRangeError('paging failed', partial,
                                      remaining_start=date(2025, 1, 1),
                                      remaining_end=date(2025, 1, 2)),
    }[failure]
    broker.bars_range.side_effect = [series(), cause]
    with pytest.raises(DatasetCollectionError) as caught:
        Market(broker).datasets({'a': 'A', 'b': 'B', 'c': 'C'},
                                start='2025-01-01', end='2025-01-02')
    error = caught.value
    assert error.failed_key == 'b'
    assert list(error.completed) == ['a']
    assert len(error.completed['a']) == 1
    assert broker.bars_range.call_count == 2
    assert error.__cause__ is not None
    if isinstance(cause, Exception):
        assert error.__cause__ is cause
    with pytest.raises(TypeError):
        error.completed['edited'] = error.completed['a']
    if failure == 'range':
        assert error.__cause__.partial is partial
        assert error.__cause__.remaining_end == date(2025, 1, 2)


def test_closed_market_fails_before_request():
    broker = Mock()
    market = Market(broker)
    market.close()
    with pytest.raises(DatasetCollectionError) as caught:
        market.datasets({'a': 'A'}, start='2025-01-01', end='2025-01-02')
    assert caught.value.failed_key == 'a'
    assert not caught.value.completed
    assert isinstance(caught.value.__cause__, ConnectionError)
    broker.bars_range.assert_not_called()


@pytest.mark.parametrize('instruments,kwargs', [
    ({}, {}), ({'timestamp': 'A'}, {}), ({' ': 'A'}, {}), ({1: 'A'}, {}),
    ({'a': 'A', 'bad': ''}, {}), ({'a': 'A', 'bad': object()}, {}),
    ({'a': 'A'}, {'interval': '2min'}), ({'a': 'A'}, {'regular_hours': 1}),
    ({'a': 'A'}, {'refresh': 'yes'}), ({'a': 'A'}, {'include_sessions': 1}),
    ({'a': 'A'}, {'start': '2025-01-03'}),
    ({'a': 'A', 'option': Option('A', date(2099, 11, 20), 100, 'C')}, {}),
    ({'a': 'A', 'option': Option('A', date(2099, 11, 20), 100, 'C')},
     {'interval': '5min', 'include_sessions': True}),
])
def test_invalid_requests_fail_before_any_provider_io(instruments, kwargs):
    broker = Mock()
    params = dict(start='2025-01-01', end='2025-01-02') | kwargs
    with pytest.raises(ValueError):
        Market(broker).datasets(instruments, **params)
    broker.bars_range.assert_not_called()
    broker.bars.assert_not_called()


@pytest.mark.parametrize('args,kwargs', [
    (('',), {}), ((1,), {}), (('A',), {'data_type': 'MIDPOINT'}),
    (('A',), {'data_type': 'BID_ASK'}), (('A',), {'primary_exchange': None}),
    ((Option('A', date(2099, 11, 20), 100, 'C'),), {'primary_exchange': 'NASDAQ'}),
])
def test_request_selector_validation(args, kwargs):
    with pytest.raises(ValueError):
        BarRequest(*args, **kwargs)


def test_keyboard_interrupt_is_not_converted_to_a_data_error():
    broker = Mock()
    broker.bars_range.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        Market(broker).datasets({'a': 'A'}, start='2025-01-01', end='2025-01-02')

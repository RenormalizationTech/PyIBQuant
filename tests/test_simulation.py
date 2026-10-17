"""Hand-calculated portfolio accounting and event-time isolation, without IBKR."""

import json
import runpy
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest

from pyibquant import Bar, BarDataset, BarSeries
from pyibquant.backtest import backtest_equity
from pyibquant.option_backtest import backtest_option
from pyibquant.research import above_sma
from pyibquant.simulation import Execution, Feed, NextOpen, TargetStrategy, simulate

START = datetime(2026, 10, 16, 13, 30, tzinfo=UTC)


def feed(prices=((10, 11), (12, 13), (14, 15)), *, symbol='STOCK', option=False,
         offsets=None, interval='5min', multiplier=None, **metadata):
    daily = interval == '1d'
    series = BarSeries(symbol, interval)
    series.asset_type, series.currency = ('option' if option else 'equity'), 'USD'
    series.multiplier = multiplier if multiplier is not None else (100 if option else 1)
    series.instrument_id = 123 if option else None
    series.data_type = 'MIDPOINT' if option else 'TRADES'
    series.adjustment = None if option else 'splits_only'
    if option:
        series.option_metadata = dict(expiry='20261120', strike=100, right='C')
    for key, value in metadata.items():
        setattr(series, key, value)
    stamps = [(date(2026, 10, 16) + timedelta(days=i) if daily else
               START + timedelta(minutes=i * 5 if offsets is None else offsets[i]))
              for i in range(len(prices))]
    series.requested_start = stamps[0]
    series.requested_end = stamps[-1] + timedelta(days=1)
    series.download_complete = metadata.get('download_complete', True)
    for stamp, (opening, close) in zip(stamps, prices, strict=True):
        series.update(Bar(stamp, opening, max(opening, close), min(opening, close), close,
                          None if option else 100))
    final = stamps[-1] if daily else stamps[-1] + timedelta(hours=4)
    return Feed(BarDataset.from_series(series), final)


class Script:
    def __init__(self, callback):
        self.callback = callback
        self.contexts = []

    def on_bar(self, context):
        self.contexts.append(context)
        self.callback(context)


def test_scaling_partial_exit_entry_fee_allocation_and_pnl_reconciliation():
    data = feed([(10, 10), (10, 10), (20, 20), (30, 30), (40, 40)], option=True,
                multiplier=150)
    # Buy two, buy one, sell one, sell two; average-price cost basis includes fees.
    instructions = [('buy', 2), ('buy', 1), ('sell', 1), ('sell', 2)]

    def trade(c):
        index = len(c.data['opt'].bars) - 1
        if index < len(instructions):
            c.submit('opt', *instructions[index])

    result = simulate({'opt': data}, Script(trade), initial_cash=10000,
                      execution=NextOpen(commission_per_unit=1))
    assert [f.cash_after for f in result.fills] == [6998, 3997, 8496, 20494]
    assert [f.realized_pnl for f in result.fills] == pytest.approx([0, 0, 2498, 7996])
    metrics = result.metrics()
    assert metrics['realized_net_pnl'] == pytest.approx(10494)
    assert metrics['unrealized_net_pnl'] == 0
    assert metrics['commissions'] == 6
    assert metrics['final_equity'] == 20494
    assert result.portfolio.positions['opt'].quantity == 0
    assert result.portfolio.positions['opt'].cost_basis == 0
    assert all(o.status == 'filled' for o in result.orders)


def test_partial_exit_and_open_position_reconcile_loss_and_costs():
    data = feed([(10, 10), (10, 8), (8, 7)], option=True)

    def trade(c):
        count = len(c.data['opt'].bars)
        if count == 1:
            c.submit('opt', 'buy', 3)
        elif count == 2:
            c.submit('opt', 'sell', 1)

    result = simulate({'opt': data}, Script(trade), execution=NextOpen(commission_per_unit=2))
    assert result.portfolio.cash == 7792
    assert result.portfolio.positions['opt'].quantity == 2
    assert result.portfolio.positions['opt'].average_price == 10
    assert result.portfolio.realized_pnl == -204
    assert result.portfolio.unrealized_pnl == -604
    assert result.portfolio.equity == 9192
    assert result.portfolio.equity - result.initial_cash == (
        result.portfolio.realized_pnl + result.portfolio.unrealized_pnl)


def test_shared_cash_priority_and_no_shorting_or_borrowing():
    a, b = feed(symbol='A'), feed(symbol='B')

    def trade(c):
        if len(c.data['a'].bars) == 1:
            c.submit('b', 'buy', 5)
            c.submit('a', 'buy', 5)
            c.submit('b', 'sell', 6)

    result = simulate({'a': a, 'b': b}, Script(trade), initial_cash=100)
    assert [(o.instrument, o.status, o.reason) for o in result.orders] == [
        ('b', 'filled', None), ('a', 'rejected', 'insufficient_cash'),
        ('b', 'rejected', 'insufficient_position')]
    assert result.portfolio.cash == 40
    assert result.portfolio.equity == 115


def test_cancel_market_order_before_its_next_open_and_terminal_cancel_behavior():
    slow = feed(offsets=[0, 15, 30], symbol='SLOW')
    fast = feed(prices=[(1, 1)]*7, symbol='FAST')

    def trade(c):
        elapsed = (c.timestamp - START).total_seconds() / 60
        if elapsed == 5:
            order_id = c.submit('slow', 'buy', 1, tag='test')
            assert order_id == 1
        if elapsed == 10:
            assert c.cancel(1)
            assert not c.cancel(1)

    result = simulate({'slow': slow, 'fast': fast}, Script(trade))
    assert not result.fills
    assert result.orders[0].status == 'canceled'
    assert result.orders[0].reason == 'strategy_cancel'
    assert result.orders[0].tag == 'test'


def test_underlying_signal_executes_option_at_boundary_without_future_bar_access():
    underlying = feed([(100, 101), (102, 103), (104, 105)], symbol='UNDERLYING')
    option = feed([(1, 2), (3, 4), (5, 6)], option=True)

    def trade(c):
        assert c.updated == ('option', 'underlying')
        n = len(c.data['underlying'].bars)
        assert len(c.data['option'].bars) == n
        assert c.data['underlying'].latest.close == 99 + n * 2
        assert c.data['option'].age == timedelta(0)
        if n == 1:
            c.submit('option', 'buy', 2)
        if n == 2:
            c.submit('option', 'sell', 1)

    result = simulate({'underlying': underlying, 'option': option}, Script(trade))
    assert [f.price for f in result.fills] == [3, 5]
    assert [f.timestamp for f in result.fills] == [START + timedelta(minutes=5),
                                                START + timedelta(minutes=10)]
    assert result.portfolio.positions['option'].quantity == 1
    assert result.portfolio.realized_pnl == 200
    assert result.portfolio.unrealized_pnl == 300


def test_future_price_changes_cannot_change_earlier_decisions():
    def run(last):
        strategy = Script(lambda c: c.submit('stock', 'buy', 1)
                          if len(c.data['stock'].bars) == 1 else None)
        result = simulate({'stock': feed([(10, 11), (12, 13), last])}, strategy)
        return result, strategy.contexts

    base, contexts = run((14, 15))
    changed, alternate = run((500, 900))
    assert base.orders == changed.orders
    assert base.fills == changed.fills
    assert contexts[0].data == alternate[0].data
    assert contexts[1].portfolio == alternate[1].portfolio
    assert len(contexts[0].data['stock'].bars) == 1  # Retained snapshots do not grow.


def test_asynchronous_closes_unavailable_history_and_stale_age():
    fast = feed([(1, 2)]*4, symbol='FAST')
    slow = feed([(10, 20), (20, 30)], offsets=[0, 15], interval='15min', symbol='SLOW')
    strategy = Script(lambda c: None)
    result = simulate({'fast': fast, 'slow': slow}, strategy)
    c5, c10, c15, c20, c30 = strategy.contexts
    assert c5.data['slow'].latest is None and c10.data['slow'].age is None
    assert c15.updated == ('fast', 'slow')
    assert c20.data['slow'].latest.close == 20
    assert c20.data['slow'].age == timedelta(minutes=5)
    assert c30.data['fast'].age == timedelta(minutes=10)
    assert result.portfolio.positions['fast'].marked_at == START + timedelta(minutes=20)


def test_final_orders_cancel_and_no_forced_exit():
    strategy = Script(lambda c: c.submit('s', 'buy', 1))
    result = simulate({'s': feed()}, strategy)
    assert len(result.fills) == 2
    assert result.portfolio.positions['s'].quantity == 2
    assert result.orders[-1].status == 'canceled'
    assert result.orders[-1].reason == 'end_of_data'
    assert result.orders[-1].submitted_at == START + timedelta(minutes=15)


def test_custom_execution_can_defer_and_access_only_open_and_current_portfolio():
    class Custom:
        def settings(self):
            return dict(model='defer_then_fee', fee=3)

        def execute(self, order, instrument, opening, portfolio):
            assert not hasattr(opening, 'close') and not hasattr(opening, 'volume')
            assert instrument.multiplier == 100
            assert portfolio.positions['o'].quantity == 0
            if opening.timestamp == START + timedelta(minutes=5):
                return None
            return Execution(opening.price + 1, 3)

    strategy = Script(lambda c: c.submit('o', 'buy', 1)
                      if len(c.data['o'].bars) == 1 else None)
    result = simulate({'o': feed(option=True)}, strategy, execution=Custom())
    assert len(result.fills) == 1
    assert result.fills[0].price == 15
    assert result.fills[0].commission == 3
    assert result.fills[0].slippage_cost == 100
    assert result.to_dict()['provenance']['execution']['model'] == 'defer_then_fee'


@pytest.mark.parametrize('quote', [Execution(0), Execution(float('inf')),
                                  Execution(1, -1), Execution(1, float('nan'))])
def test_custom_execution_invalid_results_fail_run(quote):
    class Invalid(NextOpen):
        def execute(self, *args):
            return quote

    with pytest.raises(ValueError):
        simulate({'s': feed()}, Script(lambda c: c.submit('s', 'buy', 1)), execution=Invalid())


@pytest.mark.parametrize('daily', [True, False])
def test_sma_target_adapter_matches_legacy_fills_pnl_and_final_equity(daily):
    data = feed([(10, 10), (10, 12), (12, 15), (15, 9), (9, 8), (8, 11), (11, 14)],
                interval='1d' if daily else '5min', option=not daily)
    signals = above_sma([b.close for b in data.dataset.snapshot()], window=2)
    strategy = TargetStrategy('s', lambda c: 2 if above_sma(
        [b.close for b in c.data['s'].bars], window=2)[-1] else 0)
    result = simulate({'s': data}, strategy, execution=NextOpen(commission=1, slippage_bps=5))
    if daily:
        legacy = backtest_equity(data.dataset, signals, finalized_through=data.finalized_through,
                                 shares=2, commission=1, slippage_bps=5)
    else:
        legacy = backtest_option(data.dataset, signals,
                                 finalized_through=data.finalized_through,
                                 fill_model='next_bar_open', contracts=2,
                                 commission_per_contract=.5, slippage_bps=5)
    assert [f.price for f in result.fills] == [f.price for f in legacy.fills]
    for key in ('final_cash', 'final_equity', 'realized_net_pnl', 'unrealized_net_pnl',
                'commissions', 'slippage_cost', 'total_return'):
        assert result.metrics()[key] == pytest.approx(legacy.metrics()[key])


def test_result_roundtrip_provenance_immutable_snapshots_and_atomic_save(tmp_path):
    data = feed()
    strategy = Script(lambda c: c.submit('s', 'buy', 1))
    result = simulate({'s': data}, strategy, strategy_settings=dict(name='demo'))
    path = result.save(tmp_path/'result.json')
    document = json.loads(path.read_text())
    assert document['provenance']['inputs']['s']['fingerprint'] == data.dataset.fingerprint()
    assert document['provenance']['inputs']['s']['metadata'] == data.dataset.metadata()
    assert document['provenance']['strategy'] == dict(name='demo')
    assert document['portfolio']['positions']['s']['quantity'] == 2
    document['provenance']['strategy']['name'] = 'changed'
    assert result.to_dict()['provenance']['strategy']['name'] == 'demo'
    with pytest.raises(TypeError):
        result.portfolio.positions['s'] = None
    with pytest.raises(FrozenInstanceError):
        result.portfolio.positions['s'].quantity = 999
    with pytest.raises(TypeError):
        strategy.contexts[0].data['s'] = None
    with pytest.raises(RuntimeError):
        strategy.contexts[0].submit('s', 'buy', 1)
    before = path.read_bytes()
    with patch('pyibquant.simulation.os.replace', side_effect=OSError('disk')):
        with pytest.raises(OSError):
            result.save(path)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ['result.json']


@pytest.mark.parametrize('kwargs', [dict(asset_type='future'), dict(currency='EUR'),
                                  dict(adjustment=None), dict(multiplier=2),
                                  dict(download_complete=False), dict(error='permission denied')])
def test_invalid_equity_provenance(kwargs):
    with pytest.raises(ValueError):
        simulate({'s': feed(**kwargs)}, Script(lambda c: None))


@pytest.mark.parametrize('kwargs', [dict(data_type='BID'), dict(instrument_id=None),
                                  dict(multiplier=0), dict(multiplier=True),
                                  dict(option_metadata=None),
                                  dict(option_metadata=dict(expiry='bad', strike=1, right='C')),
                                  dict(option_metadata=dict(expiry='20261120',
                                                            strike=1, right='X'))])
def test_invalid_option_provenance(kwargs):
    with pytest.raises(ValueError):
        simulate({'s': feed(option=True, **kwargs)}, Script(lambda c: None))


def test_calendar_finality_overlap_mixed_clocks_and_duplicate_identity():
    data = feed()
    with pytest.raises(ValueError, match='completion'):
        simulate({'s': Feed(data.dataset, START + timedelta(minutes=10))}, Script(lambda c: None))
    with pytest.raises(ValueError, match='timezone-aware'):
        simulate({'s': Feed(data.dataset, datetime(2026, 10, 17))}, Script(lambda c: None))
    starts = tuple(b.timestamp for b in data.dataset.snapshot())
    good = Feed(data.dataset, data.finalized_through, starts)
    result = simulate({'s': good}, Script(lambda c: None))
    assert result.to_dict()['provenance']['inputs']['s']['expected_starts'] == [
        s.isoformat() for s in starts]
    with pytest.raises(ValueError, match='Calendar mismatch'):
        simulate({'s': Feed(data.dataset, data.finalized_through, starts[:-1])},
                 Script(lambda c: None))
    with pytest.raises(ValueError, match='Overlapping'):
        simulate({'s': feed(offsets=[0, 1, 2])}, Script(lambda c: None))
    with pytest.raises(ValueError, match='mixing'):
        simulate({'s': data, 'daily': feed(interval='1d', symbol='DAILY')}, Script(lambda c: None))
    with pytest.raises(ValueError, match='once'):
        simulate({'s': data, 'alias': data}, Script(lambda c: None))


def test_option_expiry_rejected_even_when_only_other_feed_crosses_it():
    option = feed(option=True,
                  option_metadata=dict(expiry='20261017', strike=100, right='C'))
    with pytest.raises(ValueError, match='lifecycle'):
        simulate({'o': option, 's': feed(offsets=[0, 1440, 2880])}, Script(lambda c: None))
    with pytest.raises(ValueError, match='Expiry-day'):
        simulate({'o': feed(option=True,
                           option_metadata=dict(expiry='20261016', strike=100, right='C'))},
                 Script(lambda c: None))


@pytest.mark.parametrize('args, kwargs', [
    (('s', 'buy', 0), {}), (('s', 'buy', True), {}), (('s', 'buy', 1.5), {}),
    (('s', 'short', 1), {}), (('unknown', 'buy', 1), {}),
    (('s', 'buy', 1), dict(order_type='limit')),
])
def test_unsupported_orders_fail_explicitly(args, kwargs):
    with pytest.raises(ValueError):
        simulate({'s': feed()}, Script(lambda c: c.submit(*args, **kwargs)))


@pytest.mark.parametrize('kwargs', [dict(initial_cash=0), dict(initial_cash=True),
                                  dict(initial_cash=float('inf'))])
def test_invalid_cash(kwargs):
    with pytest.raises(ValueError):
        simulate({'s': feed()}, Script(lambda c: None), **kwargs)


@pytest.mark.parametrize('kwargs', [dict(commission=-1), dict(commission_per_unit=float('nan')),
                                  dict(slippage_bps=10000), dict(slippage_bps=True)])
def test_invalid_default_execution_costs(kwargs):
    with pytest.raises(ValueError):
        NextOpen(**kwargs)


def test_adverse_slippage_multiplier_costs_and_insufficient_exit_fee():
    data = feed([(1, 1), (1, 1), (.001, .001)], option=True)
    strategy = TargetStrategy('o', lambda c: 1 if len(c.data['o'].bars) == 1 else 0)
    result = simulate({'o': data}, strategy, initial_cash=101,
                      execution=NextOpen(commission_per_unit=1))
    assert result.orders[1].reason == 'insufficient_cash'
    assert result.portfolio.positions['o'].quantity == 1
    slipped = simulate({'o': feed(option=True)},
                       TargetStrategy('o', lambda c: 1 if len(c.data['o'].bars) == 1 else 0),
                       execution=NextOpen(slippage_bps=100))
    assert [f.price for f in slipped.fills] == pytest.approx([12.12, 13.86])
    assert slipped.metrics()['slippage_cost'] == pytest.approx(26)


def test_empty_inputs_invalid_target_overflow_and_custom_settings():
    with pytest.raises(ValueError, match='nonempty'):
        simulate({}, Script(lambda c: None))
    with pytest.raises(ValueError, match='Target'):
        simulate({'s': feed()}, TargetStrategy('s', lambda c: -1))
    with pytest.raises(ValueError, match='overflowed'):
        simulate({'s': feed()}, Script(lambda c: c.submit('s', 'buy', 10**308)))
    with pytest.raises(ValueError):
        simulate({'s': feed()}, Script(lambda c: None), strategy_settings=dict(x=float('nan')))


def test_close_and_next_open_both_contribute_to_drawdown_and_returns():
    result = simulate({'s': feed([(10, 10), (10, 20), (5, 5)])},
                      TargetStrategy('s', lambda c: 1), initial_cash=10)
    at_boundary = [p for p in result.equity_curve
                   if p.timestamp == START + timedelta(minutes=10)]
    assert [(p.phase, p.equity) for p in at_boundary] == [('close', 20), ('open', 5)]
    assert result.metrics()['max_drawdown'] == -.75
    cumulative = 1
    for point in result.equity_curve:
        cumulative *= 1 + point.period_return
    assert cumulative == pytest.approx(result.portfolio.equity / result.initial_cash)


def test_signal_feed_can_order_before_slow_option_bar_closes():
    signal = feed([(10, 10)]*5)
    option = feed([(1, 1), (2, 2)], option=True, interval='15min', offsets=[0, 15])
    result = simulate({'signal': signal, 'option': option},
                      TargetStrategy('option', lambda c: 2, decision_feed='signal'))
    assert len(result.fills) == 1
    assert result.fills[0].timestamp == START + timedelta(minutes=15)
    assert result.fills[0].quantity == 2
    assert result.orders[0].reason == 'strategy_cancel'
    assert result.orders[1].reason == 'strategy_cancel'
    assert result.orders[2].status == 'filled'


def test_retained_context_cannot_submit_during_a_later_active_callback():
    saved = []

    def trade(c):
        if saved:
            with pytest.raises(RuntimeError, match='no longer active'):
                saved[0].submit('s', 'buy', 1)
            with pytest.raises(RuntimeError):
                saved[0].cancel(1)
        saved.append(c)

    assert not simulate({'s': feed()}, Script(trade)).orders


def test_custom_price_improvement_has_negative_slippage_cost():
    class Improvement(NextOpen):
        def execute(self, order, instrument, opening, portfolio):
            return Execution(opening.price + (-1 if order.side == 'buy' else 1))

    result = simulate({'s': feed()},
                      TargetStrategy('s', lambda c: 1 if len(c.data['s'].bars) == 1 else 0),
                      execution=Improvement())
    assert [f.slippage_cost for f in result.fills] == [-1, -1]
    assert result.metrics()['slippage_cost'] == -2


def test_simultaneous_feeds_are_deterministic_and_filled_orders_cannot_cancel():
    feeds = {'a': feed(symbol='A'), 'b': feed(symbol='B')}

    def trade(c):
        assert c.updated == ('a', 'b')
        if len(c.data['a'].bars) == 1:
            c.submit('a', 'buy', 1)
            c.submit('b', 'buy', 2)
        else:
            assert not c.cancel(1)

    forward = simulate(feeds, Script(trade))
    reverse = simulate(dict(reversed(list(feeds.items()))), Script(trade))
    assert forward.to_dict() == reverse.to_dict()


@pytest.mark.parametrize('option', [False, True])
def test_runnable_saved_data_strategy_example(tmp_path, option):
    source = feed([(10, 10), (10, 12), (12, 9), (9, 8)],
                  interval='5min' if option else '1d')
    source_path = source.dataset.save(tmp_path/'source.json')
    output = tmp_path/'out'
    argv = ['examples/backtest_strategy.py', str(source_path), '--window', '2',
            '--finalized-through', source.finalized_through.isoformat(),
            '--output-dir', str(output), '--commission-per-unit', '.65', '--slippage-bps', '5']
    if option:
        selected = feed([(1, 1), (2, 2), (3, 3), (4, 4)], option=True)
        argv += ['--option-dataset', str(selected.dataset.save(tmp_path/'option.json'))]
    with patch.object(sys, 'argv', argv):
        runpy.run_path('examples/backtest_strategy.py', run_name='__main__')
    document = json.loads((output/'results.json').read_text())
    assert len(document['fills']) == 2
    assert document['provenance']['strategy']['window'] == 2
    assert document['provenance']['inputs']['signal']['fingerprint'] == source.dataset.fingerprint()
    if option:
        assert document['fills'][0]['instrument'] == 'option'
        assert BarDataset.load(output/'option.dataset.json').fingerprint() \
            == selected.dataset.fingerprint()
    assert BarDataset.load(output/'signal.dataset.json').fingerprint() \
        == source.dataset.fingerprint()

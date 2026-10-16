"""Hand-calculated accounting, timing and input-contract checks for equity research."""

import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from pyibquant import Bar, BarDataset, BarSeries
from pyibquant.backtest import backtest_equity
from pyibquant.research import above_sma, sma_crossover

FINAL = date(2026, 1, 31)


def dataset(prices=((100, 110), (120, 130), (140, 145)), **metadata):
    bars = BarSeries('DEMO', '1d')
    bars.asset_type, bars.currency = 'equity', 'USD'
    bars.multiplier, bars.data_type, bars.adjustment = 1, 'TRADES', 'splits_only'
    bars.requested_start, bars.requested_end = date(2026, 1, 1), date(2026, 2, 1)
    bars.download_complete = True
    for key, value in metadata.items():
        setattr(bars, key, value)
    for index, (opening, close) in enumerate(prices):
        bars.update(Bar(date(2026, 1, 1) + timedelta(days=index), opening,
                        max(opening, close), min(opening, close), close, 100))
    return BarDataset.from_series(bars)


def test_next_open_fill_prices_costs_and_completed_trade_accounting():
    result = backtest_equity(dataset(), [True, False, True], finalized_through=FINAL,
                             initial_cash=1000, shares=2, commission=1, slippage_bps=100)
    buy, sell = result.fills
    assert buy.signal_date == date(2026, 1, 1)
    assert buy.execution_date == date(2026, 1, 2)
    assert buy.price == pytest.approx(121.2)
    assert sell.price == pytest.approx(138.6)
    assert buy.cash_after == pytest.approx(756.6)
    assert sell.cash_after == pytest.approx(1032.8)
    assert [p.equity for p in result.equity_curve] == pytest.approx([1000, 1016.6, 1032.8])
    assert result.trades[0].net_pnl == pytest.approx(32.8)
    assert result.trades[0].return_fraction == pytest.approx(32.8 / 243.4)
    metrics = result.metrics()
    assert metrics['total_return'] == pytest.approx(.0328)
    assert metrics['commissions'] == 2
    assert metrics['slippage_cost'] == pytest.approx(5.2)
    assert metrics['realized_net_pnl'] == pytest.approx(32.8)
    assert metrics['unrealized_net_pnl'] == pytest.approx(0)
    assert metrics['ending_shares'] == 0 and metrics['win_rate'] == 1


def test_unrealized_position_drawdown_returns_and_last_signal_without_future_fill():
    data = dataset([(100, 100), (100, 90), (90, 80), (80, 110)])
    result = backtest_equity(data, [True, True, True, False], finalized_through=FINAL,
                             initial_cash=1000, shares=10)
    assert len(result.fills) == 1 and not result.trades
    assert [p.equity for p in result.equity_curve] == [1000, 900, 800, 1100]
    assert [p.period_return for p in result.equity_curve] == pytest.approx(
        [0, -.1, 800 / 900 - 1, 1100 / 800 - 1])
    assert result.metrics()['max_drawdown'] == pytest.approx(-.2)
    assert result.metrics()['unrealized_net_pnl'] == 100
    assert result.metrics()['ending_shares'] == 10
    assert result.metrics()['win_rate'] is None


def test_insufficient_cash_rejects_without_borrowing_and_next_target_retries():
    data = dataset([(100, 100), (100, 100), (40, 45), (50, 50)])
    result = backtest_equity(data, [True, True, False, False], finalized_through=FINAL,
                             initial_cash=100, shares=2, commission=1)
    assert len(result.rejections) == 1
    assert result.rejections[0].execution_date == date(2026, 1, 2)
    assert result.rejections[0].reason == 'insufficient_cash'
    assert [fill.side for fill in result.fills] == ['buy', 'sell']
    assert [fill.cash_after for fill in result.fills] == [19, 118]
    assert result.metrics()['realized_net_pnl'] == 18
    assert all(point.cash >= 0 for point in result.equity_curve)


def test_large_exit_fee_rejects_instead_of_borrowing_or_creating_a_phantom_sale():
    result = backtest_equity(dataset([(1, 1), (1, 1), (.01, .01)]), [True, False, False],
                             finalized_through=FINAL, initial_cash=2, commission=1)
    assert len(result.fills) == 1
    assert result.rejections[0].side == 'sell'
    assert result.metrics()['ending_shares'] == 1
    assert not result.trades


def test_no_signal_and_no_future_open_produce_no_trades():
    result = backtest_equity(dataset(), [False, False, True], finalized_through=FINAL)
    assert not result.fills and not result.trades
    assert result.metrics()['final_equity'] == 10000


def test_finality_and_calendar_are_explicit_not_inferred_from_download_completion():
    data = dataset()
    with pytest.raises(ValueError, match='confirmed final'):
        backtest_equity(data, [False] * 3, finalized_through=date(2026, 1, 2))
    with pytest.raises(ValueError, match='calendar date'):
        backtest_equity(data, [False] * 3, finalized_through=datetime(2026, 1, 31))
    with pytest.raises(ValueError, match='Calendar mismatch: 1 missing'):
        backtest_equity(data, [False] * 3, finalized_through=FINAL,
                         expected_dates=[date(2026, 1, day) for day in range(1, 5)])
    result = backtest_equity(data, [False] * 3, finalized_through=FINAL,
                             expected_dates=[bar.timestamp for bar in data.snapshot()])
    assert result.calendar_checked
    assert not any('Calendar coverage is unverified' in text for text in result.warnings)
    unchecked = backtest_equity(data, [False] * 3, finalized_through=FINAL)
    assert not unchecked.calendar_checked
    assert any('Calendar coverage is unverified' in text for text in unchecked.warnings)


@pytest.mark.parametrize('metadata', [
    {'download_complete': False}, {'error': 'provider failure'},
    {'requested_start': None, 'requested_end': None}, {'asset_type': 'option'},
    {'multiplier': 100}, {'adjustment': None}, {'regular_hours': False}, {'data_type': 'BID'},
])
def test_incompatible_or_incomplete_inputs_rejected(metadata):
    with pytest.raises(ValueError):
        backtest_equity(dataset(**metadata), [False] * 3, finalized_through=FINAL)


@pytest.mark.parametrize('config', [
    {'initial_cash': 0}, {'initial_cash': -1}, {'initial_cash': float('inf')},
    {'commission': -1}, {'commission': float('nan')}, {'slippage_bps': 10000},
    {'slippage_bps': -1}, {'shares': 0}, {'shares': 1.5}, {'shares': True},
])
def test_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        backtest_equity(dataset(), [False] * 3, finalized_through=FINAL, **config)


@pytest.mark.parametrize('signals', [[True], [True, False, 1], [True, None, False]])
def test_target_signals_must_be_explicit_booleans_matching_input_length(signals):
    with pytest.raises(ValueError, match='boolean target'):
        backtest_equity(dataset(), signals, finalized_through=FINAL)


def test_result_exports_are_independent_and_atomic(tmp_path):
    result = backtest_equity(dataset(), [True, False, False], finalized_through=FINAL)
    path = result.save(tmp_path / 'nested' / 'results.json')
    doc = json.loads(path.read_text())
    assert doc['fills'][0]['signal_date'] == '2026-01-01'
    assert doc['fills'][0]['execution_date'] == '2026-01-02'
    assert doc['execution']['fill_timing'] == 'next_supplied_open'
    assert doc['input_metadata']['coverage']['bar_finality'] == 'not_verified'
    doc['signals'][0] = False
    assert result.signals[0] is True
    with patch('pyibquant.backtest.os.replace', side_effect=OSError('denied')):
        with pytest.raises(OSError):
            result.save(path)
    assert json.loads(path.read_text())['signals'][0] is True
    assert list(path.parent.iterdir()) == [path]


def test_strategy_helpers_warmup_equality_and_prefix_causality():
    assert above_sma([1, 2, 3, 2, 1], 2) == (False, True, True, False, False)
    assert sma_crossover([1, 2, 3, 2, 1], 1, 3) == (False, False, True, False, False)
    assert above_sma([2, 2, 2], 2) == (False, False, False)
    assert sma_crossover([2, 2, 2], 1, 2) == (False, False, False)
    values = [100, 110, 120, 80, 90, 100]
    for count in range(1, len(values) + 1):
        assert above_sma(values[:count], 2) == above_sma(values, 2)[:count]
        assert sma_crossover(values[:count], 1, 3) == sma_crossover(values, 1, 3)[:count]
    with pytest.raises(ValueError, match='smaller'):
        sma_crossover(values, 3, 2)
    with pytest.raises(ValueError, match='positive integer'):
        above_sma(values, 0)


def test_future_prices_and_signals_cannot_change_earlier_results():
    original = dataset([(100, 100), (100, 110), (110, 90), (90, 120)])
    changed = dataset([(100, 100), (100, 110), (110, 90), (900, 999)])
    a = backtest_equity(original, [True, True, False, True], finalized_through=FINAL)
    b = backtest_equity(changed, [True, True, False, False], finalized_through=FINAL)
    assert a.equity_curve[:3] == b.equity_curve[:3]
    assert a.fills[:1] == b.fills[:1]


def test_export_fingerprint_identifies_exact_frozen_input(tmp_path):
    data = dataset()
    result = backtest_equity(data, [False] * 3, finalized_through=FINAL)
    saved = json.loads(data.save(tmp_path / 'input.json').read_text())
    assert result.input_fingerprint == saved['sha256'] == data.fingerprint()
    changed = dataset([(100, 100), (100, 110), (110, 115)])
    assert changed.fingerprint() != data.fingerprint()


@pytest.mark.parametrize('prices', [[], [(1, 1)], [(0, 1), (1, 1)], [(-1, 1), (1, 1)]])
def test_missing_or_nonpositive_prices_rejected(prices):
    data = dataset(prices)
    with pytest.raises(ValueError):
        backtest_equity(data, [False] * len(prices), finalized_through=FINAL)


def test_arithmetic_overflow_fails_instead_of_publishing_infinite_results():
    with pytest.raises(ValueError, match='overflowed'):
        backtest_equity(dataset([(1, 1), (1e308, 1e308)]), [True, False],
                         finalized_through=FINAL, shares=2)
    with pytest.raises(ValueError, match='too large'):
        backtest_equity(dataset(), [False] * 3, finalized_through=FINAL, shares=10**1000)


@pytest.mark.parametrize('strategy', ['above-sma', 'sma-cross'])
def test_offline_backtest_example_exports_both_strategies(tmp_path, monkeypatch, strategy):
    import runpy
    from pathlib import Path

    data = dataset([(100, 100), (101, 102), (103, 104), (100, 98), (97, 99)])
    source = data.save(tmp_path / 'source.json')
    target = tmp_path / 'output'
    monkeypatch.setattr('sys.argv', ['backtest_equity', str(source), '--finalized-through',
                                   FINAL.isoformat(), '--strategy', strategy, '--window', '2',
                                   '--fast', '1', '--slow', '2', '--output-dir', str(target)])
    with patch('pyibquant.Market.ibkr', side_effect=AssertionError('No broker needed')):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples' /
                           'backtest_equity.py'), run_name='__main__')
    saved = json.loads((target / 'results.json').read_text())
    loaded = BarDataset.load(target / 'inputs.dataset.json')
    assert saved['input_fingerprint'] == loaded.fingerprint()
    assert len(saved['equity_curve']) == 5
    assert saved['fills']
    assert json.loads((target / 'strategy.json').read_text())['name'] == strategy
    for filename in ['fills.csv', 'trades.csv', 'equity_curve.csv', 'rejections.csv']:
        assert (target / filename).is_file()

"""Hand-calculated premium accounting and timing; broker-independent inputs."""

import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from pyibquant import Bar, BarDataset, BarSeries
from pyibquant.option_backtest import backtest_option
from pyibquant.research import above_sma, sma_crossover

START = datetime(2026, 10, 16, 13, 30, tzinfo=UTC)
FINAL = START + timedelta(hours=1)


def dataset(prices=((10, 11), (12, 13), (14, 14.5)), **metadata):
    series = BarSeries('DEMO', '5min')
    series.asset_type, series.currency = 'option', 'USD'
    series.instrument_id, series.multiplier, series.data_type = 123, 150, 'MIDPOINT'
    series.option_metadata = dict(expiry='20261120', strike=100, right='C',
                                  trading_class='DEMO1', local_symbol='DEMO CALL')
    series.requested_start, series.requested_end = START, FINAL
    series.download_complete = True
    for name, value in metadata.items():
        setattr(series, name, value)
    for index, (opening, close) in enumerate(prices):
        series.update(Bar(START + timedelta(minutes=5*index), opening, max(opening, close),
                          min(opening, close), close, None))
    return BarDataset.from_series(series)


def simulate(data=None, signals=(True, False, True), **kwargs):
    return backtest_option(dataset() if data is None else data, signals,
                           **(dict(fill_model='next_bar_open', finalized_through=FINAL) | kwargs))


def test_multiplier_costs_cash_flows_and_prior_close_next_open_timing():
    result = simulate(initial_cash=10000, contracts=2, commission_per_contract=.65,
                      slippage_bps=100)
    buy, sell = result.fills
    assert buy.signal_bar_start == START
    assert buy.execution_time == START + timedelta(minutes=5)
    assert buy.price == pytest.approx(12.12)
    assert sell.price == pytest.approx(13.86)
    assert buy.commission == 1.3
    assert buy.cash_after == pytest.approx(6362.7)
    assert sell.cash_after == pytest.approx(10519.4)
    assert [p.equity for p in result.equity_curve] == pytest.approx([10000, 10262.7, 10519.4])
    trade = result.trades[0]
    assert trade.net_pnl == pytest.approx(519.4)
    assert trade.return_fraction == pytest.approx(519.4/3637.3)
    metrics = result.metrics()
    assert metrics['commissions'] == 2.6
    assert metrics['slippage_cost'] == pytest.approx(78)
    assert metrics['total_return'] == pytest.approx(.05194)
    assert metrics['realized_net_pnl'] == pytest.approx(519.4)
    assert metrics['unrealized_net_pnl'] == 0
    assert metrics['ending_contracts'] == 0 and metrics['win_rate'] == 1


def test_open_position_marks_multiplier_and_entry_fee_without_forced_last_exit():
    result = simulate(dataset([(10, 10), (10, 9), (9, 8), (8, 11)]),
                      [True, True, True, False], initial_cash=2000,
                      commission_per_contract=1)
    assert len(result.fills) == 1 and not result.trades
    assert [p.equity for p in result.equity_curve] == [2000, 1849, 1699, 2149]
    assert result.metrics()['max_drawdown'] == pytest.approx(1699/2000-1)
    assert result.metrics()['unrealized_net_pnl'] == 149
    assert result.metrics()['ending_contracts'] == 1
    assert result.metrics()['win_rate'] is None
    assert [p.period_return for p in result.equity_curve] == pytest.approx(
        [0, 1849/2000-1, 1699/1849-1, 2149/1699-1])


def test_insufficient_cash_retries_and_exit_commission_cannot_borrow():
    data = dataset([(10, 10), (10, 10), (4, 4), (5, 5)])
    result = simulate(data, [True, True, False, False], initial_cash=1000,
                      commission_per_contract=1)
    assert len(result.rejections) == 1
    assert result.rejections[0].execution_time == START + timedelta(minutes=5)
    assert [f.cash_after for f in result.fills] == [399, 1148]
    assert result.metrics()['realized_net_pnl'] == 148
    costly = simulate(dataset([(1, 1), (1, 1), (.001, .001)]),
                      initial_cash=151, commission_per_contract=1)
    assert costly.rejections[0].side == 'sell'
    assert costly.metrics()['ending_contracts'] == 1 and not costly.trades


def test_last_target_has_no_future_fill_and_flat_targets_do_nothing():
    result = simulate(signals=[False, False, True])
    assert not result.fills and not result.trades
    assert result.metrics()['final_equity'] == 10000


@pytest.mark.parametrize('metadata', [
    dict(asset_type='equity'), dict(currency='EUR'), dict(data_type='BID'), dict(data_type='ASK'),
    dict(multiplier=None), dict(multiplier=0), dict(multiplier=True), dict(multiplier=-1),
    dict(instrument_id=None), dict(instrument_id=0), dict(option_metadata=None),
    dict(option_metadata=dict(expiry='bad', strike=100, right='C')),
    dict(option_metadata=dict(expiry='20261120', strike=-1, right='C')),
    dict(option_metadata=dict(expiry='20261120', strike=100, right='X')),
    dict(download_complete=False), dict(error='permission denied'),
])
def test_invalid_inputs_are_rejected(metadata):
    with pytest.raises(ValueError):
        simulate(dataset(**metadata))


@pytest.mark.parametrize('kwargs', [
    dict(fill_model='midpoint_fill'), dict(finalized_through=START),
    dict(finalized_through=datetime(2026, 10, 16)), dict(contracts=0), dict(contracts=True),
    dict(contracts=1.5), dict(initial_cash=0), dict(initial_cash=float('inf')),
    dict(commission_per_contract=-1), dict(commission_per_contract=True),
    dict(slippage_bps=10000), dict(slippage_bps=float('nan')),
])
def test_invalid_assumptions(kwargs):
    with pytest.raises(ValueError):
        simulate(**kwargs)


@pytest.mark.parametrize('signals', [[True], [1, 0, 1], [True, False, None]])
def test_targets_must_be_one_bool_per_bar(signals):
    with pytest.raises(ValueError, match='boolean target'):
        simulate(signals=signals)


def test_expiry_day_rejected_in_new_york_even_if_no_position_is_open():
    for expiry in ['20261016', '20261015']:
        with pytest.raises(ValueError, match='lifecycle'):
            simulate(dataset(option_metadata=dict(expiry=expiry, strike=100, right='P')),
                      signals=[False]*3)
    # Saved history remains usable after the option expires; no wall-clock expiry check.
    assert simulate(dataset(option_metadata=dict(expiry='20261017', strike=100, right='P')))


def test_calendar_audit_and_finality_are_explicit():
    data = dataset()
    with pytest.raises(ValueError, match='Calendar mismatch: 1 missing'):
        simulate(data, expected_times=[START+timedelta(minutes=i*5) for i in range(4)])
    with pytest.raises(ValueError, match='timezone-aware'):
        simulate(data, expected_times=[datetime(2026, 10, 16)])
    result = simulate(data, expected_times=[bar.timestamp for bar in data.snapshot()])
    assert result.to_dict()['execution']['calendar_checked']
    assert not any('Calendar coverage is unverified' in w for w in result.warnings)
    assert any('Calendar coverage is unverified' in w for w in simulate().warnings)


def test_zero_bad_ohlc_single_bar_and_incomplete_ranges_rejected():
    for prices in [[(0, 0), (1, 1)], [(1, 1)]]:
        with pytest.raises(ValueError):
            simulate(dataset(prices), signals=[False]*len(prices))
    with pytest.raises(ValueError, match='fixed-range'):
        simulate(dataset(requested_start=None, requested_end=None))
    data = dataset()
    bad = BarDataset._create((Bar(START, 10, 9, 8, 10, None), *data.snapshot()[1:]),
                             data.metadata())
    with pytest.raises(ValueError, match='consistent OHLC'):
        simulate(bad)


def test_trade_and_midpoint_results_serialize_provenance_and_atomic_save(tmp_path):
    for source in ['TRADES', 'MIDPOINT']:
        data = dataset(data_type=source)
        result = simulate(data)
        target = result.save(tmp_path/f'{source}.json')
        document = json.loads(target.read_text())
        assert document['input_fingerprint'] == data.fingerprint()
        assert document['input_metadata'] == data.metadata()
        assert document['execution']['price_source'] == source
        assert document['execution']['bid_ask_spread'] is False
        assert document['fills'][0]['execution_time'] == (START+timedelta(minutes=5)).isoformat()
        document['input_metadata']['option']['strike'] = -1
        assert result.to_dict()['input_metadata']['option']['strike'] == 100
        before = target.read_bytes()
        with patch('pyibquant.option_backtest.os.replace', side_effect=OSError('disk')):
            with pytest.raises(OSError):
                result.save(target)
        assert target.read_bytes() == before
        assert not list(tmp_path.glob('*.tmp'))


def test_costless_round_trips_scale_linearly_with_multiplier_and_size():
    first = simulate(dataset(multiplier=25), contracts=3)
    second = simulate(dataset(multiplier=150), contracts=2)
    assert second.metrics()['realized_net_pnl'] == 4 * first.metrics()['realized_net_pnl']


def test_overlapping_bars_cannot_use_a_signal_before_its_close():
    data = dataset()
    original = data.snapshot()[1]
    overlap = Bar(START + timedelta(minutes=1), original.open, original.high,
                  original.low, original.close, None)
    bad = BarDataset._create((data.snapshot()[0], overlap, data.snapshot()[2]), data.metadata())
    with pytest.raises(ValueError, match='Overlapping'):
        simulate(bad)


def test_repeated_entries_losses_and_open_position_reconcile_total_pnl():
    data = dataset([(10, 10), (10, 11), (9, 9), (8, 9), (10, 10), (12, 11)])
    result = simulate(data, [True, False, True, False, True, False],
                      contracts=2, commission_per_contract=.5, slippage_bps=10)
    metrics = result.metrics()
    assert len(result.trades) == 2 and len(result.fills) == 5
    assert result.trades[0].net_pnl < 0 < result.trades[1].net_pnl
    assert metrics['win_rate'] == .5 and metrics['ending_contracts'] == 2
    assert metrics['final_equity'] - metrics['initial_cash'] == pytest.approx(
        metrics['realized_net_pnl'] + metrics['unrealized_net_pnl'])


def test_overflow_is_rejected_instead_of_writing_nonfinite_results():
    with pytest.raises(ValueError, match='overflowed'):
        simulate(dataset(multiplier=1e308), contracts=2)


def test_future_prices_and_targets_cannot_change_earlier_accounting():
    first = simulate(dataset([(10, 10), (10, 11), (11, 9), (9, 12)]),
                     [True, True, False, True])
    changed = simulate(dataset([(10, 10), (10, 11), (11, 9), (90, 120)]),
                       [True, True, False, False])
    assert first.equity_curve[:3] == changed.equity_curve[:3]
    assert first.fills[:1] == changed.fills[:1]


def test_example_refuses_unsupported_source_before_writing_outputs(tmp_path, monkeypatch):
    source = dataset(data_type='BID').save(tmp_path/'bid.json')
    output = tmp_path/'output'
    monkeypatch.setattr('sys.argv', [
        'backtest_option.py', str(source), '--finalized-through', FINAL.isoformat(),
        '--fill-model', 'next_bar_open', '--output-dir', str(output),
    ])
    with pytest.raises(SystemExit):
        runpy.run_path(str(Path(__file__).resolve().parents[1]/'examples/backtest_option.py'),
                       run_name='__main__')
    assert not output.exists()


@pytest.mark.parametrize('strategy', ['above-sma', 'sma-cross'])
def test_offline_example_outputs_reproducible_results_and_signals(tmp_path, monkeypatch, strategy):
    prices = [(10, 10), (10, 12), (12, 14), (14, 11), (11, 9), (9, 13)]
    data = dataset(prices)
    source = data.save(tmp_path/'input.json')
    output = tmp_path/'result'
    monkeypatch.setattr('sys.argv', [
        'backtest_option.py', str(source), '--finalized-through', FINAL.isoformat(),
        '--fill-model', 'next_bar_open', '--strategy', strategy, '--window', '2',
        '--fast', '1', '--slow', '2', '--output-dir', str(output),
    ])
    runpy.run_path(str(Path(__file__).resolve().parents[1]/'examples/backtest_option.py'),
                   run_name='__main__')
    document = json.loads((output/'results.json').read_text())
    closes = [p[1] for p in prices]
    expected = above_sma(closes, 2) if strategy == 'above-sma' else sma_crossover(closes, 1, 2)
    assert document['signals'] == list(expected)
    assert document['input_fingerprint'] == data.fingerprint()
    assert BarDataset.load(output/'inputs.dataset.json').fingerprint() == data.fingerprint()
    assert all((output/f'{name}.csv').is_file()
               for name in ['fills', 'trades', 'rejections', 'equity_curve'])

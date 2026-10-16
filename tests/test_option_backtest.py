"""Hand-calculated option accounting, causal quotes and explicit data-quality limits."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from pyibquant import QuoteRecording
from pyibquant.option_backtest import backtest_option, hold_window, spread_targets
from pyibquant.quotes import Quote, QuoteInstrument

BASE = datetime(2026, 10, 15, 14, tzinfo=UTC)


def make_recording(tmp_path, specs=None, *, instrument_updates=None, end_status='completed'):
    specs = specs if specs is not None else [dict(bid=9, ask=10), dict(bid=10, ask=11),
                                           dict(bid=12, ask=13)]
    instrument = dict(symbol='DEMO', instrument_id=123, asset_type='option', currency='USD',
                      exchange='SMART', primary_exchange='', local_symbol='DEMO OPTION',
                      trading_class='DEMO', multiplier=100, expiry='20261120',
                      strike=100, right='C')
    instrument.update(instrument_updates or {})
    identity = QuoteInstrument(**instrument)
    documents = [dict(type='header', format='pyibquant.quote_samples', version=1,
                      started_at=BASE.isoformat(), duration=max(1, len(specs)), interval=1,
                      instrument=instrument, requested_data_type='live')]
    for index, spec in enumerate(specs):
        stamp = BASE + timedelta(seconds=spec.get('time', index))
        receipt = BASE + timedelta(seconds=spec.get('receipt_time',
                                                    spec.get('time', index)-spec.get('age', 0)))
        receipts = dict(bid=receipt, ask=receipt-timedelta(seconds=spec.get('skew', 0)),
                        bid_size=receipt, ask_size=receipt)
        for name, seconds in spec.get('receipts', {}).items():
            receipts[name] = BASE + timedelta(seconds=seconds)
        quote = Quote(identity, 'live', spec.get('feed', 'live'), spec.get('delayed', False),
                      BASE, None, spec.get('bid'), spec.get('ask'), None,
                      spec.get('bid_size', 10), spec.get('ask_size', 10), None,
                      tuple(receipts.items()),
                      tuple(spec.get('ticks', dict(bid=1, ask=2, bid_size=0, ask_size=3)).items()),
                      (), (), streaming=True, sequence=index,
                      observed_at=stamp, status=spec.get('status', 'active'),
                      error=spec.get('error'), generation=spec.get('generation', 0),
                      gaps=spec.get('gaps', ()))
        documents.append(dict(type='sample', sampled_at=(stamp+timedelta(seconds=.01)).isoformat(),
                              quote=quote.to_dict()))
    lines = [json.dumps(record, sort_keys=True, separators=(',', ':'))+'\n' for record in documents]
    digest = hashlib.sha256(''.join(lines).encode()).hexdigest()
    end = dict(type='end', status=end_status, samples=len(specs), error=None,
               finished_at=(BASE+timedelta(days=1)).isoformat(), sha256=digest)
    path = tmp_path / 'quotes.jsonl'
    path.write_text(''.join(lines)+json.dumps(end)+'\n')
    return QuoteRecording.load(path, allow_incomplete=end_status != 'completed')


def test_ask_entry_bid_exit_multiplier_fees_and_slippage_are_charged_once(tmp_path):
    source = make_recording(tmp_path)
    result = backtest_option(source, [True, False, True], initial_cash=5000,
                              commission=1, slippage_bps=100)
    buy, sell = result.fills
    assert buy.signal_time < buy.price_received_at <= buy.execution_time
    assert buy.execution_time < sell.execution_time
    assert buy.price == pytest.approx(11.11) and sell.price == pytest.approx(11.88)
    assert buy.multiplier == sell.multiplier == 100
    assert buy.cash_after == pytest.approx(3888)
    assert sell.cash_after == pytest.approx(5075)
    assert [p.equity for p in result.equity_curve] == pytest.approx([5000, 4888, 5075])
    trade = result.trades[0]
    assert trade.net_pnl == pytest.approx(75)
    assert trade.return_fraction == pytest.approx(75/1112)
    metrics = result.metrics()
    assert metrics['commissions'] == 2 and metrics['slippage_cost'] == pytest.approx(23)
    assert metrics['total_return'] == pytest.approx(.015)
    assert metrics['max_drawdown'] == pytest.approx(-112/5000)
    assert metrics['realized_net_pnl'] == pytest.approx(75)
    assert metrics['unrealized_net_pnl'] == 0 and metrics['ending_contracts'] == 0
    assert result.input_fingerprint == source.fingerprint()


def test_adjusted_multiplier_and_per_contract_commission_are_not_assumed_100(tmp_path):
    source = make_recording(tmp_path, instrument_updates={'multiplier': 150})
    result = backtest_option(source, [True, False, False], contracts=2, commission=.5)
    assert result.fills[0].cash_after == 10000 - 2*150*11 - 1
    assert result.trades[0].net_pnl == 2*150*(12-11) - 2


def test_latency_keeps_first_pending_signal_through_unchanged_targets(tmp_path):
    source = make_recording(tmp_path, [dict(bid=9+i, ask=10+i) for i in range(5)])
    result = backtest_option(source, [True]*5, latency=3)
    assert len(result.fills) == 1
    assert result.fills[0].execution_time == BASE+timedelta(seconds=3.01)
    assert result.fills[0].signal_time == BASE+timedelta(seconds=.01)
    assert [item.reason for item in result.skipped_fills] == ['waiting_latency']*2


def test_repeated_old_price_is_not_reused_as_a_post_signal_execution_quote(tmp_path):
    source = make_recording(tmp_path, [dict(bid=9, ask=10), dict(bid=9, ask=10, receipt_time=0),
                                       dict(bid=10, ask=11)])
    result = backtest_option(source, [True, True, False])
    assert len(result.fills) == 1
    assert result.skipped_fills[0].reason == 'waiting_new_side_price'
    assert result.fills[0].execution_time == BASE+timedelta(seconds=2.01)
    assert result.metrics()['ending_contracts'] == 1  # No invented final exit.


def test_changed_target_cancels_unfilled_intent_after_current_observation(tmp_path):
    source = make_recording(tmp_path)
    result = backtest_option(source, [True, False, True], latency=10)
    assert not result.fills
    assert len(result.skipped_fills) == 1


@pytest.mark.parametrize('change,reason', [
    ({'bid': None}, 'missing_bid_ask'), ({'bid': 12}, 'crossed_quote'),
    ({'age': 3}, 'stale_quote'), ({'skew': 1.5}, 'asynchronous_sides'),
    ({'ask_size': 0}, 'insufficient_displayed_size'), ({'feed': None}, 'unconfirmed_live_feed'),
])
def test_unusable_quotes_skip_fills_instead_of_manufacturing_prices(tmp_path, change, reason):
    source = make_recording(tmp_path, [dict(bid=9, ask=10), dict(bid=10, ask=11) | change,
                                       dict(bid=12, ask=13)])
    result = backtest_option(source, [True, True, False],
                             max_quote_age=5 if 'skew' in change else 2)
    assert result.skipped_fills[0].reason == reason
    assert len(result.fills) == 1 and result.fills[0].execution_time == BASE+timedelta(seconds=2.01)


def test_insufficient_cash_or_top_size_never_borrows_or_partially_fills(tmp_path):
    source = make_recording(tmp_path)
    result = backtest_option(source, [True, True, True], initial_cash=100)
    assert not result.fills
    assert all(item.reason == 'insufficient_cash' for item in result.skipped_fills)
    assert result.metrics()['final_equity'] == 100
    result = backtest_option(source, [True]*3, contracts=11)
    assert not result.fills
    assert all(item.reason == 'insufficient_displayed_size' for item in result.skipped_fills)


def test_missing_position_valuation_stays_unknown_and_drawdown_is_not_certified(tmp_path):
    source = make_recording(tmp_path, [dict(bid=9, ask=10), dict(bid=10, ask=11),
                                       dict(bid=None, ask=None)])
    result = backtest_option(source, [True]*3)
    assert result.equity_curve[-1].equity is None
    assert result.equity_curve[-1].valuation_reason == 'missing_bid_ask'
    assert result.equity_curve[-1].period_return is None
    assert result.metrics()['final_equity'] is None and result.metrics()['total_return'] is None
    assert result.metrics()['max_drawdown'] is None
    assert not result.metrics()['valuation_complete']
    assert result.metrics()['unrealized_net_pnl'] is None
    json.dumps(result.to_dict(), allow_nan=False)


def test_recovered_valuation_does_not_bridge_unknown_period_returns_or_drawdown(tmp_path):
    source = make_recording(tmp_path, [dict(bid=9, ask=10), dict(bid=10, ask=11),
                                       dict(bid=None, ask=None), dict(bid=12, ask=13)])
    result = backtest_option(source, [True]*4)
    assert result.equity_curve[-1].equity == 10100
    assert result.equity_curve[-1].period_return is None
    assert result.equity_curve[-1].drawdown is None and result.metrics()['max_drawdown'] is None
    assert result.metrics()['total_return'] == pytest.approx(.01)


@pytest.mark.parametrize('feed,delayed', [('frozen', False), ('delayed', True),
                                         ('live', True), ('delayed_frozen', True)])
def test_frozen_and_delayed_are_not_live_backtest_inputs(tmp_path, feed, delayed):
    source = make_recording(tmp_path, [dict(bid=9, ask=10, feed=feed, delayed=delayed)]*3)
    with pytest.raises(ValueError, match='Frozen/delayed'):
        backtest_option(source, [True]*3)


@pytest.mark.parametrize('specs,updates,message', [
    ([dict(bid=9, ask=10, time=0), dict(bid=10, ask=11, time=10)], {}, 'gap'),
    ([dict(bid=9, ask=10, time=1), dict(bid=10, ask=11, time=0)], {}, 'nonincreasing'),
    ([dict(bid=9, ask=10), dict(bid=10, ask=11, time=86400)], {}, 'New York date'),
    (None, {'expiry': '20261015'}, 'before expiry'),
    (None, {'asset_type': 'equity'}, 'resolved option'),
    (None, {'multiplier': None}, 'recorded multiplier'),
    ([dict(bid=9, ask=10, receipt_time=1), dict(bid=10, ask=11)], {}, 'later than'),
])
def test_gap_expiry_identity_and_future_receipt_checks(tmp_path, specs, updates, message):
    source = make_recording(tmp_path, specs, instrument_updates=updates)
    with pytest.raises(ValueError, match=message):
        backtest_option(source, [True]*len(source))


def test_incomplete_recording_cannot_be_analyzed_even_if_loaded_for_inspection(tmp_path):
    source = make_recording(tmp_path, end_status='disconnected')
    with pytest.raises(ValueError, match='complete recording'):
        backtest_option(source, [True]*3)


@pytest.mark.parametrize('config', [dict(contracts=0), dict(contracts=True), dict(initial_cash=0),
                                    dict(commission=-1), dict(slippage_bps=10000),
                                    dict(max_quote_age=0), dict(max_side_skew=-1),
                                    dict(max_gap=float('inf')), dict(latency=-1),
                                    dict(quote_age_basis='unknown')])
def test_invalid_parameters_rejected(tmp_path, config):
    with pytest.raises(ValueError):
        backtest_option(make_recording(tmp_path), [False]*3, **config)


def test_signals_are_explicit_and_last_signal_has_no_fill(tmp_path):
    source = make_recording(tmp_path)
    for bad in ([True], [True, 1, False]):
        with pytest.raises(ValueError, match='boolean target'):
            backtest_option(source, bad)
    assert not backtest_option(source, [False, False, True]).fills


def test_helpers_and_engine_do_not_use_future_prices(tmp_path):
    a = make_recording(tmp_path, [dict(bid=9, ask=10), dict(bid=10, ask=11),
                                  dict(bid=12, ask=13), dict(bid=11, ask=12)])
    b = make_recording(tmp_path, [dict(bid=9, ask=10), dict(bid=10, ask=11),
                                  dict(bid=12, ask=13), dict(bid=1, ask=99)])
    assert spread_targets(a, .2)[:3] == spread_targets(b, .2)[:3]
    assert hold_window(a, 2) == hold_window(b, 2)
    first = backtest_option(a, [True]*4)
    second = backtest_option(b, [True]*4)
    assert first.equity_curve[:3] == second.equity_curve[:3]
    assert first.fills == second.fills
    assert first.input_fingerprint != second.input_fingerprint


def test_result_export_is_independent_and_finite(tmp_path):
    source = make_recording(tmp_path)
    result = backtest_option(source, [True, False, False])
    path = result.save(tmp_path / 'output' / 'result.json')
    document = json.loads(path.read_text())
    assert document['input_fingerprint'] == source.fingerprint()
    assert document['execution']['entry'] == 'ask_plus_slippage'
    document['signals'][0] = False
    assert result.signals[0] is True
    with pytest.raises(ValueError, match='overflowed'):
        backtest_option(make_recording(tmp_path, [dict(bid=1e308, ask=1e308)]*3), [True]*3)


@pytest.mark.parametrize('strategy', ['hold-window', 'spread-filter'])
@pytest.mark.parametrize('basis', ['price_receipt', 'side_update'])
def test_example_preserves_inputs_and_exports_reproducible_results(
    tmp_path, monkeypatch, strategy, basis,
):
    import csv
    import runpy
    from pathlib import Path

    source = make_recording(tmp_path)
    original_bytes = (tmp_path / 'quotes.jsonl').read_bytes()
    output = tmp_path / 'output'
    monkeypatch.setattr('sys.argv', ['backtest_option', str(tmp_path / 'quotes.jsonl'),
                                    '--strategy', strategy, '--hold-seconds', '1',
                                    '--max-spread-fraction', '.2', '--commission', '1',
                                    '--quote-age-basis', basis,
                                    '--output-dir', str(output)])
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples' / 'backtest_option.py'),
                   run_name='__main__')
    document = json.loads((output / 'results.json').read_text())
    assert document['input_fingerprint'] == source.fingerprint()
    assert (output / 'inputs.quotes.jsonl').read_bytes() == original_bytes
    assert json.loads((output / 'strategy.json').read_text())['name'] == strategy
    restored = QuoteRecording.load(output / 'inputs.quotes.jsonl')
    replay = backtest_option(restored, document['signals'], commission=1, quote_age_basis=basis)
    assert replay.to_dict() == document
    for name in ('fills', 'trades', 'skipped_fills', 'equity_curve'):
        with (output / f'{name}.csv').open(newline='') as stream:
            assert len(list(csv.DictReader(stream))) == len(document[name])


def test_example_rejects_frozen_before_creating_results(tmp_path, monkeypatch):
    import runpy
    from pathlib import Path

    make_recording(tmp_path, [dict(bid=9, ask=10, feed='frozen')]*3)
    output = tmp_path / 'output'
    monkeypatch.setattr('sys.argv', ['backtest_option', str(tmp_path / 'quotes.jsonl'),
                                    '--output-dir', str(output)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples' /
                           'backtest_option.py'), run_name='__main__')
    assert exc.value.code == 2
    assert not output.exists()


def test_side_size_updates_allow_unchanged_prices_with_original_receipts_and_accounting(tmp_path):
    source = make_recording(tmp_path, [
        dict(bid=9, ask=10),
        dict(bid=9, ask=10, time=3, receipts=dict(bid=0, ask=0)),
        dict(bid=9, ask=10, time=4, receipts=dict(bid=0, ask=0)),
    ])
    strict = backtest_option(source, [True, False, False], commission=1, slippage_bps=100)
    assert not strict.fills and strict.skipped_fills[0].reason == 'stale_quote'
    result = backtest_option(source, [True, False, False], commission=1,
                             slippage_bps=100, quote_age_basis='side_update')
    buy, sell = result.fills
    assert buy.price_received_at == sell.price_received_at == BASE
    assert buy.price_received_at < buy.signal_time < buy.side_received_at <= buy.execution_time
    assert sell.signal_time < sell.side_received_at <= sell.execution_time
    assert buy.side_received_at == buy.size_received_at
    assert result.trades[0].net_pnl == pytest.approx(-121)
    assert result.metrics()['final_cash'] == pytest.approx(9879)
    assert result.metrics()['commissions'] == 2
    assert result.metrics()['slippage_cost'] == pytest.approx(19)
    assert result.metrics()['valuation_complete']
    assert result.to_dict()['quote_age_basis'] == 'side_update'
    assert result.to_dict()['schema_version'] == 2


@pytest.mark.parametrize('receipts,ticks,reason', [
    # Old size, fresh last/Greek traffic, or opposite-side traffic cannot renew
    # the selected side. A repeated size from before the signal cannot fill it.
    (dict(bid=0, ask=0, bid_size=3, ask_size=0), None, 'stale_quote'),
    (dict(bid=0, ask=0, bid_size=0, ask_size=3), None, 'stale_quote'),
    (dict(bid=0, ask=0, bid_size=3, ask_size=1.5), None, 'asynchronous_sides'),
    (dict(bid=3, ask=3, bid_size=2, ask_size=2), None, 'waiting_side_size'),
    (dict(bid=0, ask=0, bid_size=0, ask_size=0), None, 'stale_quote'),
    (dict(bid=0, ask=0, bid_size=3, ask_size=3), {}, 'unverified_side_update'),
    (dict(bid=0, ask=0, bid_size=3, ask_size=3),
     dict(bid=1, ask=2, bid_size=0, ask_size=70), 'unverified_side_update'),
])
def test_side_update_mode_requires_both_matching_recent_confirmations(
    tmp_path, receipts, ticks, reason,
):
    change = dict(bid=9, ask=10, time=3, receipts=receipts)
    if ticks is not None:
        change['ticks'] = ticks
    source = make_recording(tmp_path, [dict(bid=9, ask=10), change])
    result = backtest_option(source, [True, True], quote_age_basis='side_update')
    assert not result.fills and result.skipped_fills[0].reason == reason


def test_side_update_mode_waits_for_post_signal_update_and_respects_latency(tmp_path):
    source = make_recording(tmp_path, [
        dict(bid=9, ask=10),
        dict(bid=9, ask=10, receipt_time=0),
        dict(bid=9, ask=10, receipts=dict(bid=0, ask=0)),
        dict(bid=9, ask=10, receipts=dict(bid=0, ask=0)),
    ])
    result = backtest_option(source, [True]*4, quote_age_basis='side_update')
    assert result.skipped_fills[0].reason == 'waiting_new_side_update'
    assert result.fills[0].execution_time == BASE+timedelta(seconds=2.01)
    delayed = backtest_option(source, [True]*4, quote_age_basis='side_update', latency=3)
    assert delayed.fills[0].execution_time == BASE+timedelta(seconds=3.01)


@pytest.mark.parametrize('change,reason', [
    (dict(bid=None), 'missing_bid_ask'), (dict(bid=11), 'crossed_quote'),
    (dict(ask_size=0), 'insufficient_displayed_size'),
    (dict(ask_size=None), 'missing_side_size'),
    (dict(bid_size=None), 'missing_side_size'),
    (dict(feed=None), 'unconfirmed_live_feed'),
])
def test_side_update_mode_preserves_price_feed_and_size_gates(tmp_path, change, reason):
    source = make_recording(tmp_path, [dict(bid=9, ask=10), dict(bid=9, ask=10) | change])
    result = backtest_option(source, [True, True], quote_age_basis='side_update')
    assert not result.fills and result.skipped_fills[0].reason == reason


@pytest.mark.parametrize('basis', ['price_receipt', 'side_update'])
def test_simulation_rejects_reconnect_even_if_recording_never_sampled_disconnected_state(
    tmp_path, basis,
):
    from pyibquant.quotes import QuoteGap

    gap = QuoteGap(BASE+timedelta(seconds=.2), BASE+timedelta(seconds=.5), 'socket lost', 0, 1)
    source = make_recording(tmp_path, [dict(bid=9, ask=10),
                                       dict(bid=10, ask=11, generation=1, gaps=(gap,))])
    with pytest.raises(ValueError, match='reconnect gap'):
        backtest_option(source, [True, True], quote_age_basis=basis)

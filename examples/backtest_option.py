"""Simulate one intraday option from our collected, confirmed-live quote samples.

No TWS, SDK or optional packages needed. Strategies demonstrate timing/accounting,
not expected profitability. Frozen/delayed recordings are rejected. Output includes
the exact input bytes, strategy settings, assumptions, results and CSV logs.
"""

import argparse
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pyibquant import QuoteRecording
from pyibquant.option_backtest import backtest_option, hold_window, spread_targets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--strategy', choices=['hold-window', 'spread-filter'],
                        default='hold-window')
    parser.add_argument('--hold-seconds', type=float, default=5)
    parser.add_argument('--max-spread-fraction', type=float, default=.05)
    parser.add_argument('--initial-cash', type=float, default=10000)
    parser.add_argument('--contracts', type=int, default=1)
    parser.add_argument('--commission', type=float, default=0, help='Per contract, per fill')
    parser.add_argument('--slippage-bps', type=float, default=0)
    parser.add_argument('--max-quote-age', type=float, default=2,
                        help='Local receipt age in seconds')
    parser.add_argument('--max-side-skew', type=float, default=1, help='Receipt skew in seconds')
    parser.add_argument('--max-gap', type=float, default=5, help='Maximum sample gap in seconds')
    parser.add_argument('--latency', type=float, default=0, help='Minimum signal-to-fill seconds')
    parser.add_argument('--output-dir', type=Path, default=Path('charts/option-backtest'))
    args = parser.parse_args()
    try:
        # Read once: validation, simulation and exported inputs use the same bytes,
        # even if another process replaces the original recording during the run.
        input_bytes = args.recording.read_bytes()
        with TemporaryDirectory(prefix='pyibquant-option-') as directory:
            snapshot = Path(directory) / 'quotes.jsonl'
            snapshot.write_bytes(input_bytes)
            recording = QuoteRecording.load(snapshot)
        signals = (hold_window(recording, args.hold_seconds) if args.strategy == 'hold-window'
                   else spread_targets(recording, args.max_spread_fraction))
        result = backtest_option(
            recording, signals, initial_cash=args.initial_cash, contracts=args.contracts,
            commission=args.commission, slippage_bps=args.slippage_bps,
            max_quote_age=args.max_quote_age, max_side_skew=args.max_side_skew,
            max_gap=args.max_gap, latency=args.latency,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    target = result.save(args.output_dir / 'results.json')
    target.with_name('inputs.quotes.jsonl').write_bytes(input_bytes)
    document = result.to_dict()
    for name, columns in [
        ('fills', ['signal_time', 'execution_time', 'side', 'contracts', 'multiplier', 'price',
                   'commission', 'slippage_cost', 'cash_after', 'quote_sequence',
                   'price_received_at', 'size_received_at']),
        ('trades', ['entry_time', 'exit_time', 'contracts', 'multiplier', 'entry_price',
                    'exit_price', 'commissions', 'net_pnl', 'return_fraction']),
        ('skipped_fills', ['signal_time', 'observation_time', 'side', 'reason']),
        ('equity_curve', ['timestamp', 'cash', 'contracts', 'equity', 'valuation_reason',
                         'period_return', 'drawdown']),
    ]:
        with target.with_name(f'{name}.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(document[name])
    target.with_name('strategy.json').write_text(json.dumps(dict(
        name=args.strategy,
        hold_seconds=args.hold_seconds if args.strategy == 'hold-window' else None,
        max_spread_fraction=(args.max_spread_fraction
                             if args.strategy == 'spread-filter' else None),
    ), indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result.metrics(), indent=2))
    print(f'Saved inputs, strategy, results and CSV logs to {target.parent}')
    for warning in result.warnings:
        print(f'Assumption: {warning}')


if __name__ == '__main__':
    main()

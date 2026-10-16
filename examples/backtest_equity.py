"""Run either of two simple daily equity strategies on a frozen dataset, offline.

Finality must be confirmed explicitly. Optional --calendar supplies expected
trading dates, one ISO date per line, for the exact input query. Outputs default
to ignored charts/backtest/. This simulates adjusted prices, not broker orders.
"""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from pyibquant import BarDataset
from pyibquant.backtest import backtest_equity
from pyibquant.research import above_sma, sma_crossover


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--finalized-through', required=True, type=date.fromisoformat)
    parser.add_argument('--calendar', type=Path)
    parser.add_argument('--strategy', choices=['above-sma', 'sma-cross'], default='above-sma')
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--fast', type=int, default=10)
    parser.add_argument('--slow', type=int, default=20)
    parser.add_argument('--initial-cash', type=float, default=10000)
    parser.add_argument('--shares', type=int, default=1)
    parser.add_argument('--commission', type=float, default=0)
    parser.add_argument('--slippage-bps', type=float, default=0)
    parser.add_argument('--output-dir', type=Path, default=Path('charts/backtest'))
    args = parser.parse_args()
    try:
        dataset = BarDataset.load(args.dataset)
        closes = [bar.close for bar in dataset.snapshot()]
        signals = above_sma(closes, args.window) if args.strategy == 'above-sma' \
            else sma_crossover(closes, args.fast, args.slow)
        expected = None if args.calendar is None else [
            date.fromisoformat(line.strip()) for line in args.calendar.read_text().splitlines()
            if line.strip()
        ]
        result = backtest_equity(
            dataset, signals, finalized_through=args.finalized_through,
            initial_cash=args.initial_cash, shares=args.shares, commission=args.commission,
            slippage_bps=args.slippage_bps, expected_dates=expected,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    target = result.save(args.output_dir / 'results.json')
    dataset.save(target.with_name('inputs.dataset.json'))
    document = result.to_dict()
    for name, columns in [
        ('fills', ['signal_date', 'execution_date', 'side', 'shares', 'price', 'commission',
                   'slippage_cost', 'cash_after']),
        ('trades', ['entry_date', 'exit_date', 'shares', 'entry_price', 'exit_price',
                    'commissions', 'net_pnl', 'return_fraction']),
        ('equity_curve', ['timestamp', 'cash', 'shares', 'close', 'equity',
                         'period_return', 'drawdown']),
        ('rejections', ['signal_date', 'execution_date', 'side', 'reason']),
    ]:
        with target.with_name(f'{name}.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(document[name])
    target.with_name('strategy.json').write_text(json.dumps(dict(
        name=args.strategy, window=args.window if args.strategy == 'above-sma' else None,
        fast=args.fast if args.strategy == 'sma-cross' else None,
        slow=args.slow if args.strategy == 'sma-cross' else None,
    ), indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result.metrics(), indent=2))
    print(f'Saved inputs, strategy, results and CSV logs to {target.parent}')
    for warning in result.warnings:
        print(f'Assumption: {warning}')


if __name__ == '__main__':
    main()

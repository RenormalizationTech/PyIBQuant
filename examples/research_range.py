"""Download a fixed IBKR dataset, save its metadata and compute a research signal.

Requires the documented manual IBKR setup. No browser/pandas is needed. Outputs
default to the Git-ignored charts/research/ directory. This computes a descriptive
close-versus-SMA signal; it does not simulate fills or calculate strategy profits.
"""

import argparse
import csv
import json
from pathlib import Path

from pyibquant import BarDataset, HistoricalRangeError, Market
from pyibquant.research import simple_returns, sma


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--interval', default='1d')
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=191)
    parser.add_argument('--cache-dir')
    parser.add_argument('--output-dir', type=Path, default=Path('charts/research'))
    args = parser.parse_args()
    if args.window <= 0:
        parser.error('--window must be positive')
    with Market.ibkr(args.host, args.port, args.client_id, cache_dir=args.cache_dir) as market:
        try:
            bars = market.bars(args.symbol, interval=args.interval, start=args.start, end=args.end)
        except HistoricalRangeError as exc:
            # A partial download is never analyzed as though it were the full dataset.
            raise SystemExit(
                f'{exc}\nCompleted {exc.partial.download_pages} pages. Remaining range: '
                f'[{exc.remaining_start}, {exc.remaining_end}). No research outputs written.'
            ) from exc

    target = bars.to_csv(args.output_dir / 'bars.csv')
    BarDataset.from_series(bars).save(target.with_name('bars.dataset.json'))
    metadata = bars.metadata()
    target.with_suffix('.metadata.json').write_text(
        json.dumps(metadata, indent=2), encoding='utf-8'
    )
    records = bars.to_records()
    closes = [row['close'] for row in records]
    returns, averages = simple_returns(closes), sma(closes, args.window)
    with target.with_name('signals.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['timestamp', 'close', 'simple_return', 'sma', 'above_sma'])
        for row, change, average in zip(records, returns, averages, strict=True):
            writer.writerow([row['timestamp'].isoformat(), row['close'], change, average,
                             None if average is None else int(row['close'] > average)])
    print(f'Saved {len(records)} bars, metadata and research signals to {target.parent}')
    for warning in metadata['warnings']:
        print(f'Provider warning: {warning}')


if __name__ == '__main__':
    main()

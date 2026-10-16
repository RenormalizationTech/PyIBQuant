"""Request one option's bounded intraday history, save it, and compute research signals.

Requires logged-in TWS/Gateway and the official SDK, but no open exchange session
or live recording. MIDPOINT/BID/ASK bars have no volume and are not executable fills.
Saved bars.dataset.json can be analyzed later with research_saved.py without IBKR.
"""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from pyibquant import BarDataset, HistoricalRangeError, Market, Option
from pyibquant.errors import PyIBQuantError
from pyibquant.research import simple_returns, sma


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol')
    parser.add_argument('--expiry', type=date.fromisoformat, required=True)
    parser.add_argument('--strike', type=float, required=True)
    parser.add_argument('--right', choices=['C', 'P'], required=True)
    parser.add_argument('--trading-class', default='')
    parser.add_argument('--multiplier', type=float)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--interval', default='5min')
    parser.add_argument('--data-type', choices=['TRADES', 'MIDPOINT', 'BID', 'ASK'],
                        default='MIDPOINT')
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=220)
    parser.add_argument('--cache-dir')
    parser.add_argument('--output-dir', type=Path, default=Path('charts/option-history'))
    args = parser.parse_args()
    if args.window <= 0:
        parser.error('--window must be positive')
    option = Option(args.symbol, args.expiry, args.strike, args.right,
                    args.trading_class, args.multiplier)
    try:
        with Market.ibkr(args.host, args.port, args.client_id,
                         cache_dir=args.cache_dir) as market:
            bars = market.bars(option, interval=args.interval, start=args.start, end=args.end,
                               data_type=args.data_type)
    except HistoricalRangeError as exc:
        raise SystemExit(
            f'{exc}\nCompleted {exc.partial.download_pages} pages. Remaining range: '
            f'[{exc.remaining_start}, {exc.remaining_end}). No research outputs written.'
        ) from exc
    except PyIBQuantError as exc:
        raise SystemExit(f'{exc}\nNo research outputs written.') from exc
    if not len(bars):
        raise SystemExit('IBKR returned no bars. No research outputs written.')

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
    print(f'Saved {len(records)} {args.data_type} bars, metadata and signals to {target.parent}')
    print('Signals describe historical prices; no fills or strategy profits are simulated.')
    for warning in metadata['warnings']:
        print(f'Provider warning: {warning}')


if __name__ == '__main__':
    main()

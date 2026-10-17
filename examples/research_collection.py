"""Request bounded equity/ETF inputs or inspect a saved collection offline.

Advanced analysis belongs in your own Python code. Fetch uses sequential requests
on one Market connection, reusing existing pacing/cache behavior. A failed, empty
or incomplete input prevents replacement of the destination collection.
"""

import argparse
import csv
import json
from pathlib import Path

from pyibquant import BarDatasetCollection, DatasetCollectionError, Market


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    fetch = commands.add_parser('fetch', help='Request explicit symbols from IBKR')
    fetch.add_argument('symbols', nargs='+')
    fetch.add_argument('--start', required=True)
    fetch.add_argument('--end', required=True)
    fetch.add_argument('--interval', default='1d')
    fetch.add_argument('--output', type=Path, required=True)
    fetch.add_argument('--extended-hours', action='store_true')
    fetch.add_argument('--host', default='127.0.0.1')
    fetch.add_argument('--port', type=int, default=7497)
    fetch.add_argument('--client-id', type=int, default=193)
    fetch.add_argument('--cache-dir')
    inspect = commands.add_parser('inspect', help='Align a saved collection without IBKR')
    inspect.add_argument('collection', type=Path)
    inspect.add_argument('--join', choices=['inner', 'outer'], required=True)
    inspect.add_argument('--field', choices=['open', 'high', 'low', 'close', 'volume'],
                         default='close')
    inspect.add_argument('--csv', type=Path, help='Optional aligned values export')
    inspect.add_argument('--quality-report', type=Path, help='Optional JSON quality report')
    args = parser.parse_args()
    if args.command == 'fetch':
        symbols = [symbol.strip().upper() for symbol in args.symbols]
        if any(not symbol for symbol in symbols) or len(set(symbols)) != len(symbols):
            parser.error('Supply distinct nonempty symbols')
        with Market.ibkr(args.host, args.port, args.client_id, cache_dir=args.cache_dir) as market:
            try:
                collection = market.datasets(
                    {symbol: symbol for symbol in symbols}, interval=args.interval,
                    start=args.start, end=args.end, regular_hours=not args.extended_hours,
                )
            except DatasetCollectionError as exc:
                raise SystemExit(f'{exc}. Collection not written; completed inputs: '
                                 f'{list(exc.completed)}') from exc
        target = collection.save(args.output)
        print(f'Saved {len(collection)} inputs to {target}; {collection.fingerprint()}')
    else:
        collection = BarDatasetCollection.load(args.collection)
        source = args.collection.expanduser().resolve()
        outputs = [path.expanduser().resolve() for path in (args.csv, args.quality_report)
                   if path is not None]
        if source in outputs or len(set(outputs)) != len(outputs):
            parser.error('Output paths must differ from the collection and each other')
        report = collection.quality_report(join=args.join, field=args.field)
        print(json.dumps(report, indent=2))
        if args.quality_report:
            target = args.quality_report.expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if args.csv:
            aligned = collection.align(field=args.field, join=args.join)
            target = args.csv.expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['timestamp', *aligned.columns])
                writer.writeheader()
                for row in aligned.to_records():
                    writer.writerow({**row, 'timestamp': row['timestamp'].isoformat()})
            print(f'Saved aligned values to {target}; missing values are blank')


if __name__ == '__main__':
    main()

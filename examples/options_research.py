"""Discover a chain, optionally select one contract and record sampled quotes.

No orders or regulatory snapshots. The chain lists candidate expiry/strike sets;
only the selected contract is resolved and subscribed. Frozen mode is explicit,
and recorded data is sampled observations, not a complete exchange tick archive.
"""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from pyibquant import (
    Market,
    QuoteRecording,
    QuoteRecordingSet,
    record_quotes,
    record_quotes_rotating,
)
from pyibquant.errors import PyIBQuantError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=195)
    parser.add_argument('--expiry', type=date.fromisoformat)
    parser.add_argument('--strike', type=float)
    parser.add_argument('--right', choices=['C', 'P'])
    parser.add_argument('--trading-class', default='')
    parser.add_argument('--multiplier', type=float)
    parser.add_argument('--market-data-type', default='live',
                        choices=['live', 'frozen', 'delayed', 'delayed_frozen'])
    parser.add_argument('--duration', type=float, default=10)
    parser.add_argument('--interval', type=float, default=1)
    parser.add_argument('--max-samples-per-file', type=int,
                        help='Rotate into a recording set after this many samples per file')
    parser.add_argument('--reconnect', action='store_true',
                        help='Restore quote subscription after disconnect; record gaps explicitly')
    parser.add_argument('--output-dir', type=Path, default=Path('charts/options-research'))
    args = parser.parse_args()
    if args.max_samples_per_file is not None and args.max_samples_per_file <= 0:
        parser.error('--max-samples-per-file must be positive')
    fields = (args.expiry, args.strike, args.right)
    selected = any(value is not None for value in fields)
    if selected and any(value is None for value in fields):
        parser.error('Supply --expiry, --strike and --right together')
    if not selected and (args.trading_class or args.multiplier is not None):
        parser.error('--trading-class/--multiplier require an explicit contract selector')
    target = args.output_dir / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    try:
        with Market.ibkr(args.host, args.port, args.client_id, timeout=30) as market:
            chain = market.option_chain(args.symbol)
            target.mkdir(parents=True, exist_ok=True)
            (target / 'chain.json').write_text(json.dumps(chain.to_dict(), indent=2),
                                              encoding='utf-8')
            for group in chain.groups:
                print(f'{group.exchange} / {group.trading_class} / '
                      f'multiplier {group.multiplier:g}: '
                      f'{len(group.expirations)} expiries, {len(group.strikes)} candidate strikes')
            if not selected:
                print(f'Saved discovery metadata to {target.resolve() / "chain.json"}')
                return
            option = chain.select(args.expiry, args.strike, args.right,
                                  trading_class=args.trading_class, multiplier=args.multiplier)
            with market.stream_quote(option, market_data_type=args.market_data_type,
                                     reconnect=args.reconnect) as stream:
                if args.max_samples_per_file is None:
                    path = record_quotes(stream, target / 'quotes.jsonl', duration=args.duration,
                                         interval=args.interval)
                else:
                    path = record_quotes_rotating(
                        stream, target / 'recording', duration=args.duration,
                        interval=args.interval,
                        max_samples=args.max_samples_per_file,
                    )
        # Reload after all broker connections are closed.
        opener = (QuoteRecording.open if args.max_samples_per_file is None
                  else QuoteRecordingSet.open)
        with opener(path, allow_incomplete=True) as recording:
            quality = recording.quality()
            print(f'Saved {len(recording)} sampled observations '
                  f'({quality["with_bid_ask"]} with bid/ask) to {path}')
            print(f'Recording complete: {recording.complete}; '
                  f'final status: {recording.metadata()["end"]["status"]}')
            complete = recording.complete
        print(f'Quote generation: {quality["generation"]}; '
              f'recorded gaps: {len(quality["gaps"])}')
        if not complete:
            raise SystemExit('Recording ended early; inspect its terminal '
                             'status/error before research.')
    except (PyIBQuantError, ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()

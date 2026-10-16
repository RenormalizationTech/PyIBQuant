"""Discover a chain, optionally select one contract and record sampled quotes.

No orders or regulatory snapshots. The chain lists candidate expiry/strike sets;
only the selected contract is resolved and subscribed. Frozen mode is explicit,
and recorded data is sampled observations, not a complete exchange tick archive.
"""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from pyibquant import Market, QuoteRecording, record_quotes
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
    parser.add_argument('--output-dir', type=Path, default=Path('charts/options-research'))
    args = parser.parse_args()
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
            with market.stream_quote(option, market_data_type=args.market_data_type) as stream:
                path = record_quotes(stream, target / 'quotes.jsonl', duration=args.duration,
                                     interval=args.interval)
        # Reload after all broker connections are closed.
        recording = QuoteRecording.load(path, allow_incomplete=True)
        rows = list(recording.samples())
        pairs = sum(row['quote']['bid'] is not None and row['quote']['ask'] is not None
                    for row in rows)
        print(f'Saved {len(recording)} sampled observations ({pairs} with bid/ask) to {path}')
        print(f'Recording complete: {recording.complete}; '
              f'final status: {recording.metadata()["end"]["status"]}')
        if not recording.complete:
            raise SystemExit('Recording ended early; inspect its terminal '
                             'status/error before research.')
    except (PyIBQuantError, ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()

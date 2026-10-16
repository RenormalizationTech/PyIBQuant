"""Inspect one stock or explicit option Level-one snapshot through local TWS.

Examples:
  python examples/quote_snapshot.py AAPL
  python examples/quote_snapshot.py AAPL --expiry 2026-11-20 --strike 340 --right C

These requests use standard snapshots, never regulatory snapshots, and do not
submit orders.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from pyibquant import Market, Option


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=194)
    parser.add_argument('--market-data-type', default='live',
                        choices=['live', 'frozen', 'delayed', 'delayed_frozen'])
    parser.add_argument('--expiry', type=date.fromisoformat)
    parser.add_argument('--strike', type=float)
    parser.add_argument('--right', choices=['C', 'P'])
    parser.add_argument('--trading-class', default='')
    parser.add_argument('--multiplier', type=float)
    parser.add_argument('--primary-exchange', default='')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    instrument = args.symbol
    option_fields = (args.expiry, args.strike, args.right)
    if any(value is not None for value in option_fields):
        if any(value is None for value in option_fields):
            parser.error('Supply --expiry, --strike and --right together')
        instrument = Option(args.symbol, args.expiry, args.strike, args.right,
                            args.trading_class, args.multiplier)
    elif args.trading_class or args.multiplier is not None:
        parser.error('--trading-class/--multiplier require an explicit option selector')
    with Market.ibkr(args.host, args.port, args.client_id, timeout=30) as market:
        quote = market.quote(instrument, primary_exchange=args.primary_exchange,
                             market_data_type=args.market_data_type)
    text = json.dumps(quote.to_dict(), indent=2) + '\n'
    print(text, end='')
    if args.output is not None:
        target = args.output.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()

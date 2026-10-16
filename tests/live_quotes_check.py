"""Explicit data-only standard quote snapshot check; no orders/regulatory snapshots."""

import argparse
import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from pyibquant import Market, Option


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=193)
    parser.add_argument('--symbol', default='AAPL')
    parser.add_argument('--market-data-type', default='live',
                        choices=['live', 'frozen', 'delayed', 'delayed_frozen'])
    parser.add_argument('--expiry', type=date.fromisoformat)
    parser.add_argument('--strike', type=float)
    parser.add_argument('--right', choices=['C', 'P'])
    parser.add_argument('--trading-class', default='')
    parser.add_argument('--multiplier', type=float)
    args = parser.parse_args()
    selector = args.symbol
    if any(value is not None for value in (args.expiry, args.strike, args.right)):
        if any(value is None for value in (args.expiry, args.strike, args.right)):
            parser.error('Option check requires --expiry, --strike and --right together')
        selector = Option(args.symbol, args.expiry, args.strike, args.right,
                          args.trading_class, args.multiplier)
    with Market.ibkr(args.host, args.port, args.client_id, timeout=30) as market:
        provider = market._provider
        provider.reqMktData = Mock(wraps=provider.reqMktData)
        quote = market.quote(selector, market_data_type=args.market_data_type)
        assert provider.reqMktData.call_args.args[2:] == ('', True, False, [])
        assert not provider._requests
    document = quote.to_dict()
    target = Path('charts/quote-check')
    target.mkdir(parents=True, exist_ok=True)
    name = f'{quote.instrument.instrument_id}-{quote.requested_data_type}.json'
    (target / name).write_text(json.dumps(document, indent=2))
    print(f'{quote.instrument.symbol} {quote.instrument.asset_type}: '
          f'bid={quote.bid}, ask={quote.ask}, '
          f'bid_size={quote.bid_size}, ask_size={quote.ask_size}; '
          f'requested={quote.requested_data_type}, reported={quote.market_data_type}, '
          f'delayed_ticks={quote.delayed_ticks}, Greeks={[g.source for g in quote.greeks]}')
    for warning in quote.warnings:
        print(f'Provider warning: {warning}')
    if quote.bid is None or quote.ask is None:
        raise SystemExit('Snapshot completed without a full bid/ask pair; '
                         'live BBO verification remains pending.')
    assert quote.instrument.instrument_id > 0 and quote.completed_at >= quote.requested_at
    assert quote.bid >= 0 and quote.ask >= 0
    print('PASS: standard Level-one snapshot, identity, explicit feed metadata '
          'and offline JSON export')


if __name__ == '__main__':
    main()

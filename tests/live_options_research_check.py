"""Explicit chain-to-stream-to-recording check with one selected contract, data only."""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

from pyibquant import Market, QuoteRecording, record_quotes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol', default='AAPL')
    parser.add_argument('--expiry', type=date.fromisoformat, default=date(2026, 11, 20))
    parser.add_argument('--strike', type=float, default=340)
    parser.add_argument('--right', choices=['C', 'P'], default='C')
    parser.add_argument('--trading-class', default='AAPL')
    parser.add_argument('--multiplier', type=float, default=100)
    parser.add_argument('--market-data-type',
                        choices=['live', 'frozen', 'delayed', 'delayed_frozen'],
                        default='frozen')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=196)
    args = parser.parse_args()
    directory = Path('charts/options-research-check') / datetime.now(UTC).strftime(
        '%Y%m%dT%H%M%S%fZ')
    with Market.ibkr(port=args.port, client_id=args.client_id, timeout=30) as market:
        provider = market._provider
        provider.reqMktData = Mock(wraps=provider.reqMktData)
        provider.reqHistoricalData = Mock(wraps=provider.reqHistoricalData)
        chain = market.option_chain(args.symbol)
        assert chain.underlying_instrument_id > 0 and chain.groups
        option = chain.select(args.expiry, args.strike, args.right,
                              trading_class=args.trading_class, multiplier=args.multiplier)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'chain.json').write_text(json.dumps(chain.to_dict(), indent=2))
        with market.stream_quote(option, market_data_type=args.market_data_type) as stream:
            path = record_quotes(stream, directory / 'quotes.jsonl', duration=6, interval=.5)
            last = stream.latest()
            assert last.error is None
        assert stream.closed and not provider._requests
        assert provider.reqMktData.call_count == 1
        assert provider.reqMktData.call_args.args[2:] == ('', False, False, [])
        provider.reqHistoricalData.assert_not_called()
    recording = QuoteRecording.load(path)
    assert recording.complete
    rows = list(recording.samples())
    pairs = [row for row in rows if row['quote']['bid'] is not None
             and row['quote']['ask'] is not None]
    models = [greek for row in rows for greek in row['quote']['greeks']
              if greek['source'] == 'model']
    print(f'{len(chain.groups)} chain groups; {len(rows)} samples; {len(pairs)} with bid/ask; '
          f'{len(models)} model observations; requested={args.market_data_type}, '
          f'reported={last.market_data_type}')
    if not pairs:
        raise SystemExit('Recording completed without BBO; '
                         'field availability verification pending.')
    assert last.instrument.multiplier == args.multiplier
    assert all(not row['quote']['snapshot_complete'] and row['quote']['streaming'] for row in rows)
    print('PASS: grouped discovery, selected-contract stream, sampled recording, '
          'selective cancellation and broker-free replay')


if __name__ == '__main__':
    main()

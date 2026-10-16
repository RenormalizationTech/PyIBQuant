"""Data-only TWS check: disconnect only this client's socket and record recovery.

Use live during the option session, or explicit frozen mode after hours.
Frozen checks verify connection lifecycle, not live freshness. No TWS restart, account request,
order submission, regulatory snapshot or other API client's connection is involved.
"""

import argparse
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Timer
from time import monotonic

from pyibquant import Market, Option, QuoteRecording, record_quotes
from pyibquant.option_backtest import backtest_option, hold_window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol', default='AAPL')
    parser.add_argument('--expiry', type=date.fromisoformat, default=date(2026, 11, 20))
    parser.add_argument('--strike', type=float, default=340)
    parser.add_argument('--right', choices=['C', 'P'], default='C')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=217)
    parser.add_argument('--market-data-type', choices=['live', 'frozen'], default='live')
    args = parser.parse_args()
    directory = Path('charts/quote-recovery-check') / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    with Market.ibkr(args.host, args.port, args.client_id, timeout=10) as market:
        option = Option(args.symbol, args.expiry, args.strike, args.right)
        with market.stream_quote(option, reconnect=True,
                                 market_data_type=args.market_data_type) as stream:
            deadline = monotonic() + 15
            quote = stream.latest()
            while monotonic() < deadline:
                if stream.closed:
                    raise SystemExit(f'Quote unavailable: {quote.error or quote.status}')
                if quote.market_data_type == args.market_data_type and quote.bid and quote.ask:
                    break
                quote = stream.wait_for_update(quote.sequence, timeout=.5)
            if not (quote.market_data_type == args.market_data_type and quote.bid and quote.ask):
                raise SystemExit(f'Confirmed {args.market_data_type} bid/ask '
                                 'did not arrive within 15 seconds')
            original = market._provider
            timer = Timer(3, original.disconnect)
            timer.start()
            try:
                path = record_quotes(stream, directory/'quotes.jsonl', duration=12, interval=.1)
            finally:
                timer.cancel()
                timer.join()
            assert market._provider is not original and not stream.closed
            assert stream.latest().generation >= 1
        assert stream.closed and not market._provider._requests
    recording = QuoteRecording.load(path)
    quality = recording.quality()
    assert quality['gaps'] and quality['generation'] >= 1
    rows = list(recording.samples())
    assert any(row['quote']['generation'] == 0 for row in rows)
    recovered = [row['quote'] for row in rows if row['quote']['generation'] >= 1
                 and row['quote']['market_data_type'] == args.market_data_type
                 and row['quote']['bid'] is not None and row['quote']['ask'] is not None]
    assert recovered, f'No confirmed {args.market_data_type} bid/ask after recovery'
    for quote in recovered:
        boundary = quote['gaps'][-1]['ended_at']
        assert all(datetime.fromisoformat(value) >= datetime.fromisoformat(boundary)
                   for value in quote['field_received_at'].values())
    try:
        backtest_option(recording, hold_window(recording))
    except ValueError as exc:
        expected = 'reconnect gap' if args.market_data_type == 'live' else 'Frozen/delayed'
        assert expected in str(exc), str(exc)
    else:
        raise AssertionError('Simulation accepted an ineligible recording')
    print(f'PASS: {len(rows)} samples; {quality["generation"]} replacement generation(s); '
          f'{len(quality["gaps"])} gap(s); new {args.market_data_type} fields after recovery; '
          'selective cancellation; offline replay; ineligible simulation rejected')
    print(path.resolve())


if __name__ == '__main__':
    main()

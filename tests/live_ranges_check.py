"""Explicit data-only TWS check for range paging, cache reuse and calendar bars.

Uses a separate client and writes generated market data under ignored charts/.
Requires the official SDK and optional cache dependency; no orders/account calls.
"""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

from pyibquant import Market


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=189)
    args = parser.parse_args()
    with Market.ibkr(args.host, args.port, args.client_id, timeout=15,
                     cache_dir='charts/range-cache') as market:
        provider = market._provider
        requests = Mock(wraps=provider.reqHistoricalData)
        provider.reqHistoricalData = requests
        intraday = market.bars('AAPL', interval='5min', start='2026-10-01',
                               end='2026-10-15', refresh=True)
        assert intraday.download_complete and intraday.download_pages == 2
        assert len(intraday) > 0 and not intraday.sessions
        assert all(intraday.requested_start <= b.timestamp < intraday.requested_end
                   for b in intraday.snapshot())
        assert [c.args[5] for c in requests.call_args_list] == ['TRADES', 'TRADES']
        requests.reset_mock()
        cached = market.bars('AAPL', interval='5min', start='2026-10-01', end='2026-10-15')
        assert cached.snapshot() == intraday.snapshot()
        assert cached.download_cached_pages == 2
        requests.assert_not_called()
        for interval, start, end in [
            ('1d', '2024-01-01', '2026-01-01'),
            ('1w', '2024-01-01', '2026-01-01'),
            ('1y', '2015-01-01', '2026-01-01'),
        ]:
            series = market.bars('AAPL', interval=interval, start=start, end=end, refresh=True)
            assert series.download_complete and len(series) > 0
            assert all(date.fromisoformat(start) <= b.timestamp < date.fromisoformat(end)
                       for b in series.snapshot())
            if interval == '1y':
                assert len(series) == 11 and series.download_pages == 2
                direct = provider.bars('AAPL', interval='1y', duration='11 Y',
                                       _end=date(2026, 1, 1), refresh=True)
                expected = tuple(b for b in direct.snapshot() if b.timestamp.year >= 2015)
                assert series.snapshot() == expected
            print(f'{interval}: {len(series)} bars / {series.download_pages} pages')
        small = market.bars('AAPL', interval='30s', start='2026-10-14T13:30:00Z',
                           end='2026-10-14T14:30:00Z', refresh=True)
        assert small.download_complete and len(small) > 0
        assert all(datetime(2026, 10, 14, 13, 30, tzinfo=UTC) <= b.timestamp <
                   datetime(2026, 10, 14, 14, 30, tzinfo=UTC) for b in small.snapshot())
    target = intraday.to_csv('charts/range-check/AAPL-5min.csv')
    metadata = intraday.metadata()
    assert metadata['instrument_id'] > 0 and metadata['currency'] == 'USD'
    assert metadata['adjustment'] == 'splits_only'
    Path(target).with_suffix('.metadata.json').write_text(json.dumps(metadata, indent=2))
    print('PASS: intraday/calendar/30s ranges, exclusive bounds, cache reuse, yearly '
          'OHLCV consistency and exported query/identity metadata')


if __name__ == '__main__':
    main()

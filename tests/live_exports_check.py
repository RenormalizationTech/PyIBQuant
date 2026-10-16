"""Explicit data-only TWS check: optional enrichment and research exports.

Requires the manual IBKR setup and optional pandas extra. Uses its own API client
and writes market-data exports only under the Git-ignored charts/ directory.
"""

import argparse
import csv
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from pyibquant import Market


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=188)
    args = parser.parse_args()
    with Market.ibkr(args.host, args.port, args.client_id, timeout=10) as market:
        broker = market._provider
        requests = Mock(wraps=broker.reqHistoricalData)
        broker.reqHistoricalData = requests
        bars = market.bars('AAPL', interval='5min', duration='1 D')
        assert not bars.include_sessions and not bars.sessions
        assert [call.args[5] for call in requests.call_args_list] == ['TRADES']
        requests.reset_mock()
        enriched = market.bars('AAPL', interval='5min', duration='1 D', include_sessions=True)
        assert enriched.include_sessions and enriched.sessions and not enriched.schedule_error
        assert [call.args[5] for call in requests.call_args_list] == [
            'TRADES', 'SCHEDULE', 'SCHEDULE']
        requests.reset_mock()
        daily = market.bars('AAPL', interval='1d', duration='1 M')
        assert [call.args[5] for call in requests.call_args_list] == ['TRADES']

    # All three formats work after disconnecting, without additional provider requests.
    for series in (bars, daily):
        records = series.to_records()
        frame = series.to_dataframe()
        target = series.to_csv(Path('charts') / 'research-check' / f'AAPL-{series.interval}.csv')
        with target.open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        assert len(records) == len(frame) == len(rows) == len(series)
        assert rows[0]['timestamp'] == records[0]['timestamp'].isoformat()
        assert float(rows[-1]['close']) == frame['close'].iloc[-1]
        if series.interval == '1d':
            assert type(frame.index[0]) is date
        else:
            assert str(frame.index.tz) == 'UTC'
    print('PASS: no implicit SCHEDULE requests, explicit enrichment, records/CSV/pandas '
          'exports after disconnect, UTC intraday and date-only daily values')


if __name__ == '__main__':
    main()

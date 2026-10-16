"""Explicit TWS integration check using its own data-only API client.

Run manually with TWS logged in. Disconnects this script's socket only; does not
restart TWS, alter other API clients, request account data or place orders.
"""

import argparse
from time import monotonic, sleep

from pyibquant import Market


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=187)
    args = parser.parse_args()
    with Market.ibkr(args.host, args.port, args.client_id, timeout=10) as market:
        bars = market.bars(
            'AAPL', interval='1min', duration='1 D', live=True, include_sessions=True
        )
        assert bars.sessions and not bars.schedule_error, bars.schedule_error
        yearly = market.bars('AAPL', interval='1y', duration='2 Y', live=True)
        market.load_older(yearly)
        closed_years = yearly.snapshot()[:-1]
        oldest = bars.snapshot()[0].timestamp
        original = market._provider
        original.disconnect()
        deadline = monotonic() + 90
        while monotonic() < deadline:
            if market._provider is not original and all(
                series.connection_state == 'subscribed' for series in (bars, yearly)
            ):
                break
            sleep(0.1)
        assert market._provider is not original
        assert all(series.connection_state == 'subscribed' for series in (bars, yearly))
        assert not bars.error and not yearly.error, (bars.error, yearly.error)
        assert bars.snapshot()[0].timestamp <= oldest
        restored = {bar.timestamp: bar for bar in yearly.snapshot()}
        assert all(restored[bar.timestamp] == bar for bar in closed_years)
        assert bars.sessions and not bars.schedule_error
        market.cancel(bars)
        market.cancel(yearly)
        assert not market._subscriptions
        print('PASS: actual session schedules, automatic socket reconnect, intraday backfill, '
              'preserved yearly source months/history and cancellation')


if __name__ == '__main__':
    main()

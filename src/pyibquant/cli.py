"""Command-line historical and live chart entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import PyIBQuantError
from .market import Market


def main() -> int:
    parser = argparse.ArgumentParser(description="IBKR market data and interactive HTML charts")
    sub = parser.add_subparsers(dest="command", required=True)
    chart = sub.add_parser("chart", help="Chart a US stock or ETF")
    chart.add_argument("symbol")
    chart.add_argument(
        "--interval", default="1min", choices=["30s", "1min", "5min", "15min", "30min", "1h", "1d"]
    )
    chart.add_argument("--duration", default="1 D")
    chart.add_argument("--host", default="127.0.0.1")
    chart.add_argument("--port", type=int, default=7497, help="TWS/IB Gateway socket port")
    chart.add_argument("--client-id", type=int, default=71)
    chart.add_argument("--timeout", type=float, default=30)
    chart.add_argument("--primary-exchange", default="")
    chart.add_argument("--extended-hours", action="store_true")
    chart.add_argument("--live", action="store_true", help="Keep bar updates running on localhost")
    chart.add_argument(
        "--web-port", type=int, default=0, help="Live chart HTTP port; 0 selects a free port"
    )
    chart.add_argument("--output", type=Path, default=Path("charts/chart.html"))
    chart.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        with Market.ibkr(
            host=args.host, port=args.port, client_id=args.client_id, timeout=args.timeout
        ) as market:
            bars = market.bars(
                args.symbol,
                interval=args.interval,
                duration=args.duration,
                live=args.live,
                regular_hours=not args.extended_hours,
                primary_exchange=args.primary_exchange,
            )
            print(f"Received {len(bars)} bars for {bars.symbol}", flush=True)
            if args.live:
                market.serve(bars, port=args.web_port, open_browser=not args.no_browser)
            else:
                print(bars.plot(args.output, open_browser=not args.no_browser))
        return 0
    except (PyIBQuantError, ImportError, ValueError, OSError) as exc:
        print(f"pyibquant: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

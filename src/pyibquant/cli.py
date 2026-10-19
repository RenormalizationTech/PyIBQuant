"""Command-line historical and live chart entry point."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .data.cache import HistoricalCache, default_cache_dir
from .errors import ConnectionError, PyIBQuantError
from .market import Market


def main() -> int:
    parser = argparse.ArgumentParser(description="IBKR market data and interactive HTML charts")
    sub = parser.add_subparsers(dest="command", required=True)
    chart = sub.add_parser("chart", help="Chart a US stock or ETF")
    chart.add_argument("symbol")
    chart.add_argument(
        "--provider", choices=["ibkr", "yahoo"], default="ibkr",
        help="Data source; yahoo is an optional daily historical preview only",
    )
    chart.add_argument(
        "--interval",
        default="1min",
        choices=["30s", "1min", "5min", "15min", "30min", "1h", "2h", "4h", "1d", "1w", "1y"],
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
        "--no-reconnect", action="store_true", help="Disable automatic live subscription recovery"
    )
    chart.add_argument(
        "--web-port", type=int, default=0, help="Live chart HTTP port; 0 selects a free port"
    )
    chart.add_argument("--output", type=Path, default=Path("charts/chart.html"))
    chart.add_argument("--no-browser", action="store_true")
    cache_flags = chart.add_mutually_exclusive_group()
    cache_flags.add_argument("--cache", action="store_true", help="Enable local historical caching")
    cache_flags.add_argument("--no-cache", action="store_true", help="Disable historical caching")
    chart.add_argument("--cache-dir", type=Path, help="Enable caching in this directory")
    chart.add_argument(
        "--cache-max-age", type=float, default=86400, help="Cache lifetime in seconds"
    )
    chart.add_argument(
        "--refresh-cache", action="store_true", help="Bypass reads and refresh cache entries"
    )
    cache = sub.add_parser("cache", help="Inspect or clear the local historical cache without IBKR")
    cache.add_argument("action", choices=["inspect", "clear"])
    cache.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    args = parser.parse_args()
    try:
        if args.command == "cache":
            store = HistoricalCache(args.cache_dir)
            if args.action == "inspect":
                print(json.dumps(store.inspect(), indent=2))
            else:
                print(f"Removed {store.clear()} historical cache entries from {store.directory}")
            return 0
        if args.provider == "yahoo":
            if args.interval != "1d" or args.live or args.extended_hours or args.primary_exchange:
                raise ValueError(
                    "Yahoo preview supports daily US stock/ETF snapshots only: use --interval 1d "
                    "without --live, --extended-hours or --primary-exchange"
                )
            if args.cache or args.cache_dir or args.refresh_cache:
                raise ValueError("Yahoo preview does not support IBKR cache flags")
            from .data.providers.yahoo import preview_bars

            bars = preview_bars(args.symbol, duration=args.duration, timeout=args.timeout)
            print(bars.warnings[0], file=sys.stderr)
            print(f"Received {len(bars)} preview bars for {bars.symbol}", flush=True)
            print(bars.plot(args.output, open_browser=not args.no_browser))
            return 0
        cache_dir = (
            None
            if args.no_cache
            else (args.cache_dir or (default_cache_dir() if args.cache else None))
        )
        if args.refresh_cache and cache_dir is None:
            raise ValueError("--refresh-cache requires --cache or --cache-dir")
        with Market.ibkr(
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            timeout=args.timeout,
            cache_dir=cache_dir,
            cache_max_age=args.cache_max_age,
            refresh_cache=args.refresh_cache,
            reconnect=not args.no_reconnect,
        ) as market:
            bars = market.bars(
                args.symbol,
                interval=args.interval,
                duration=args.duration,
                live=args.live,
                regular_hours=not args.extended_hours,
                primary_exchange=args.primary_exchange,
                include_sessions=True,
            )
            print(f"Received {len(bars)} bars for {bars.symbol}", flush=True)
            if args.live:
                market.serve(bars, port=args.web_port, open_browser=not args.no_browser)
            else:
                print(bars.plot(args.output, open_browser=not args.no_browser))
        return 0
    except (PyIBQuantError, ImportError, ValueError, OSError) as exc:
        print(f"pyibquant: {exc}", file=sys.stderr)
        if (args.command == "chart" and args.provider == "ibkr"
                and isinstance(exc, (ConnectionError, ImportError))):
            command = shlex.join([
                "pyibquant", "chart", args.symbol, "--provider", "yahoo", "--interval", "1d",
                "--duration", "1 Y",
            ])
            print(
                "For an optional daily Yahoo historical preview without TWS:\n"
                "  python -m pip install -e '.[yahoo]'\n"
                f"  {command}", file=sys.stderr,
            )
        return 1
    except KeyboardInterrupt:
        return 130

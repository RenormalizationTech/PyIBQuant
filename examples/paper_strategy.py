"""Bounded one-minute above-SMA paper strategy; observation-only unless --execute is set.

The --execute path is for the owner to run in a confirmed paper session.
Stops never flatten positions. Pending-order cancellation follows the profile or
the explicit --cancel-on-stop/--no-cancel-on-stop option.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

from pyibquant import BrokerError, Market, PaperBroker
from pyibquant.broker import money
from pyibquant.trading.performance import serve
from pyibquant.trading.profile import PaperProfile
from pyibquant.trading.runner import EquityRunner


def close_starting_share(broker, series, quote, *, execute=False, at=None):
    """Explicit one-share preflight/close; never adopt it as a strategy fill."""
    at = at or datetime.now(UTC)
    recovery = broker.reconcile()
    if not recovery.clear:
        raise BrokerError("Resolve working/uncertain orders before the starting-share check")
    positions = [
        p
        for p in recovery.snapshot.positions
        if p.get("symbol") == series.symbol and money(p.get("quantity")) != 0
    ]
    if not positions:
        return dict(symbol=series.symbol, action="already flat")
    if (
        len(positions) != 1
        or money(positions[0].get("quantity")) != 1
        or positions[0].get("con_id") != series.instrument_id
        or positions[0].get("asset_type") != "STK"
        or positions[0].get("currency") != "USD"
    ):
        raise BrokerError(
            "Starting close requires exactly one long share of the selected USD equity"
        )
    receipts = dict(quote.field_received_at)
    if (
        quote.instrument.instrument_id != series.instrument_id
        or quote.instrument.symbol != series.symbol
        or quote.status != "active"
        or quote.market_data_type != "live"
        or quote.is_delayed
        or quote.crossed
        or quote.bid is None
        or quote.ask is None
        or quote.bid <= 0
        or quote.ask <= 0
        or not all(
            k in receipts and 0 <= (at - receipts[k]).total_seconds() <= 15 for k in ("bid", "ask")
        )
    ):
        raise BrokerError("Starting close requires a fresh live bid/ask")
    if not any(s["regular"] and s["start"] <= at.timestamp() < s["end"] for s in series.sessions):
        raise BrokerError("Starting close requires a provider-confirmed regular session")
    price = (Decimal(str(quote.bid)) * Decimal(".9995")).quantize(
        Decimal(".01"), rounding=ROUND_DOWN
    )
    if price <= 0 or price > broker.max_order_value:
        raise BrokerError("Starting-share close exceeds the configured price/notional cap")
    plan = dict(
        symbol=series.symbol,
        action="SELL",
        quantity=1,
        limit_price=str(price),
        mode="execute" if execute else "read-only preflight",
    )
    print(json.dumps(plan), flush=True)
    if not execute:
        return plan
    oid = broker.submit_limit(
        series.symbol,
        "SELL",
        1,
        float(price),
        tag="owner-authorized-starting-close",
        key="starting-close-" + broker.session[:24],
    )
    outcome = broker.wait_order(oid)
    if outcome["status"] != "Filled" or money(outcome.get("filled")) != 1:
        raise BrokerError("Starting share did not fully fill; strategy will not start")
    snapshot = broker.refresh()
    if any(
        p.get("symbol") == series.symbol and money(p.get("quantity")) != 0
        for p in snapshot.positions
    ):
        raise BrokerError("Selected symbol is not flat after the close; strategy will not start")
    return dict(plan, order_id=oid, status="Filled")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", nargs="?")
    parser.add_argument(
        "--profile", type=Path, help="Saved JSON paper configuration; never enables orders"
    )
    parser.add_argument("--window", type=int)
    parser.add_argument(
        "--resume-run", help="Restore a checkpointed run ID; stays paused without --execute"
    )
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--execute", action="store_true", help="Enable paper order submission")
    parser.add_argument("--cancel-on-stop", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--close-existing-share",
        action="store_true",
        help="Preflight closing exactly one manual share; sends only with --execute",
    )
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args()
    try:
        profile = (
            PaperProfile.load(args.profile)
            if args.profile
            else PaperProfile(seconds=180, cancel_on_stop=False)
        )
        profile = replace(
            profile,
            symbol=args.symbol.upper() if args.symbol else profile.symbol,
            window=args.window if args.window is not None else profile.window,
            seconds=args.seconds if args.seconds is not None else profile.seconds,
            journal=args.journal if args.journal is not None else profile.journal,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.cancel_on_stop is True and not args.execute:
        parser.error("--cancel-on-stop requires --execute")
    cancel_on_stop = args.execute and (
        profile.cancel_on_stop if args.cancel_on_stop is None else args.cancel_on_stop
    )
    args.symbol = profile.symbol
    if args.resume_run and args.close_existing_share:
        parser.error("--resume-run cannot close or adopt a starting share")
    with PaperBroker.ibkr(**profile.broker_options(execute=args.execute)) as broker:
        restored = EquityRunner.restore(broker, args.resume_run) if args.resume_run else None
        if restored is not None:
            if restored.config.symbol != args.symbol.upper():
                parser.error("Symbol differs from the persisted run configuration")
            if args.window is not None and args.window != restored.config.window:
                parser.error("--window cannot override the persisted run configuration")
            print(
                json.dumps(
                    dict(
                        run_id=restored.run_id,
                        status=restored.status,
                        reason=restored.reason,
                        orders=restored._orders,
                        pnl_baseline=str(restored._pnl_baseline),
                    )
                ),
                flush=True,
            )
            if not args.execute:
                broker.export_strategy(restored.run_id, "charts/paper/strategy-audit.json")
                broker.report("charts/paper/strategy.html")
                return
        if args.execute and restored is None:
            recovery = broker.reconcile()
            if not recovery.clear:
                raise BrokerError("Resolve working or uncertain orders before launching a new run")
        with Market.ibkr(
            host=profile.host,
            port=profile.port,
            client_id=profile.market_client_id,
            reconnect=False,
        ) as market:
            series = market.bars(
                args.symbol.upper(),
                interval="1min",
                duration="1 D",
                live=True,
                include_sessions=True,
            )
            with market.stream_quote(args.symbol.upper()) as stream:
                runner = restored or EquityRunner(
                    broker,
                    profile.runner_config(execute=args.execute),
                )
                server = serve(broker)
                worker = Thread(target=server.serve_forever, daemon=True)
                worker.start()
                print(f"Account performance: http://127.0.0.1:{server.server_port}", flush=True)
                # Wait for independent live feed/quote initialization before arming.
                if args.execute:
                    deadline = monotonic() + 10
                    while not broker.snapshot().pnl and monotonic() < deadline:
                        sleep(0.25)
                deadline = monotonic() + 15
                while monotonic() < deadline:
                    q = stream.latest()
                    if (
                        series.last_live_update
                        and q.market_data_type == "live"
                        and q.bid is not None
                        and q.ask is not None
                    ):
                        break
                    stream.wait_for_update(q.sequence, timeout=0.25)
                try:
                    if args.close_existing_share:
                        close_starting_share(broker, series, stream.latest(), execute=args.execute)
                    if restored is not None:
                        runner.resume(series)
                    else:
                        runner.start(series)
                    print(
                        "Runner started: "
                        + (
                            "paper orders enabled"
                            if not runner.config.dry_run
                            else "observation only; orders disabled"
                        ),
                        flush=True,
                    )
                    finish = monotonic() + profile.seconds
                    sequence = broker.snapshot().sequence
                    while monotonic() < finish and runner.status == "running":
                        runner.step(series, stream.latest())
                        snapshot = broker.wait_for_update(sequence, timeout=0.25)
                        sequence = snapshot.sequence
                    print(
                        f"Runner {runner.status}: {runner.reason or 'bounded run complete'}",
                        flush=True,
                    )
                except KeyboardInterrupt:
                    pass
                finally:
                    runner.stop()
                    try:
                        if cancel_on_stop:
                            try:
                                runner.cancel_owned_orders()
                            finally:
                                if args.close_existing_share:
                                    broker.cancel_owned_orders(
                                        tag="owner-authorized-starting-close"
                                    )
                    finally:
                        try:
                            broker.export_strategy(
                                runner.run_id, "charts/paper/strategy-audit.json"
                            )
                            broker.report("charts/paper/strategy.html")
                            directory = Path("charts/paper/runs") / runner.run_id
                            broker.export_strategy(runner.run_id, directory / "audit.json")
                            broker.report(directory / "account.html")
                        finally:
                            server.shutdown()
                            server.server_close()
                            worker.join(3)


if __name__ == "__main__":
    main()

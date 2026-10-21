"""Bounded underlying-SMA selected-option runner; observation unless --execute.

Explicit contract, one long option, no rolling or expiry-day execution. Stopping
can retain inventory; cancellation and owned flatten are separate runner APIs.
"""

from __future__ import annotations

import argparse
import json
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from time import monotonic

from pyibquant import BrokerError, Market, Option, PaperBroker
from pyibquant.trading.option_runner import OptionRunner
from pyibquant.trading.profile import PaperProfile
from pyibquant.trading.runner import EquityRunner


def refresh_quiet_quote(market, selector, stack, stream, runner, series):
    """Request new live data for a quiet BBO; never re-date cached fields.

    Refresh only on a new decision candle, for an otherwise valid live stream.
    Missing/delayed/crossed/disconnected inputs still reach the runner's refusal.
    """
    bars = series.snapshot()
    q = stream.latest()
    at = datetime.now(UTC)
    receipts = dict(q.field_received_at)
    if not (
        runner.status == "running" and runner._seen is not None and bars
        and bars[-1].timestamp > runner._seen
        and q.status == "active" and q.market_data_type == "live" and not q.is_delayed
        and not q.crossed and q.bid is not None and q.ask is not None
        and q.bid > 0 and q.ask > 0 and all(k in receipts for k in ("bid", "ask"))
        and any((at - receipts[k]).total_seconds() > runner.config.max_data_age
                for k in ("bid", "ask"))
    ):
        return stream
    old_ages = {k: (at - receipts[k]).total_seconds() for k in ("bid", "ask")}
    stream.close()
    fresh = stack.enter_context(market.stream_quote(selector))
    end = monotonic() + 5
    while monotonic() < end:
        q = fresh.latest()
        at = datetime.now(UTC)
        receipts = dict(q.field_received_at)
        if (q.status == "active" and q.market_data_type == "live"
            and q.bid is not None and q.ask is not None
            and all(k in receipts and 0 <= (at - receipts[k]).total_seconds()
                    <= runner.config.max_data_age for k in ("bid", "ask"))):
            break
        if q.status in {"failed", "closed", "disconnected"}:
            break
        fresh.wait_for_update(q.sequence, timeout=.25)
    runner._log("runner_quote_refresh", reason="quiet_live_quote", prior_field_ages=old_ages,
                quote_status=q.status, market_data_type=q.market_data_type)
    return fresh


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path("examples/paper_aapl.json"))
    parser.add_argument("--expiry", type=date.fromisoformat)
    parser.add_argument("--strike", type=float)
    parser.add_argument("--right", choices=["C", "P"])
    parser.add_argument("--trading-class", default="")
    parser.add_argument("--multiplier", type=float)
    parser.add_argument("--entry-when", choices=["above_sma", "below_sma"])
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--resume-run")
    parser.add_argument("--new-session", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.new_session and not (args.resume_run and args.execute):
        parser.error("--new-session requires --resume-run and --execute")
    if args.resume_run and any(v is not None for v in (
        args.expiry, args.strike, args.right, args.multiplier, args.entry_when,
    )):
        parser.error("Restore uses its saved option/signal; do not override selection")
    if args.resume_run and args.trading_class:
        parser.error("Restore uses its saved trading class")
    if not args.resume_run and any(v is None for v in (args.expiry, args.strike, args.right)):
        parser.error("New runs require --expiry, --strike and --right")
    try:
        profile = PaperProfile.load(args.profile)
        if args.seconds is not None:
            profile = replace(profile, seconds=args.seconds)
        if profile.quantity != 1:
            raise ValueError("Selected-option runner supports one long contract")
        selector = (Option(profile.symbol, args.expiry, args.strike, args.right,
                           args.trading_class, args.multiplier) if not args.resume_run else None)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    with PaperBroker.ibkr(**profile.broker_options(execute=args.execute)) as broker:
        if args.resume_run:
            runner = EquityRunner.restore(broker, args.resume_run)
            if not isinstance(runner, OptionRunner):
                raise BrokerError("Selected run is not an option strategy")
            if runner.config.symbol != profile.symbol:
                raise BrokerError("Profile underlying differs from the saved run")
            selector = runner.selector
            if not args.execute:
                broker.export_strategy(runner.run_id, "charts/paper/option-strategy-audit.json")
                print(json.dumps(dict(run_id=runner.run_id, status=runner.status,
                                      execution=runner._execution_checkpoint())))
                return
        else:
            assert selector is not None
            runner = OptionRunner(broker, profile.runner_config(execute=args.execute), selector,
                                  entry_when=args.entry_when or "above_sma")
        assert selector is not None
        if args.execute and not broker.reconcile().clear:
            raise BrokerError("Resolve working or uncertain orders before option strategy launch")
        with Market.ibkr(host=profile.host, port=profile.port,
                         client_id=profile.market_client_id, reconnect=False) as market:
            series = market.bars(profile.symbol, interval="1min", duration="1 D", live=True,
                                 include_sessions=True)
            with ExitStack() as streams:
                stream = streams.enter_context(market.stream_quote(selector))
                deadline = monotonic() + 15
                while monotonic() < deadline:
                    q = stream.latest()
                    if series.last_live_update and q.bid is not None and q.ask is not None:
                        break
                    stream.wait_for_update(q.sequence, timeout=.25)
                try:
                    if args.resume_run:
                        runner.resume(series, new_session=args.new_session)
                    else:
                        runner.start(series)
                    print(json.dumps(dict(run_id=runner.run_id, status=runner.status,
                                          execute=not runner.config.dry_run,
                                          execution=runner._execution_checkpoint())), flush=True)
                    deadline = monotonic() + profile.seconds
                    sequence = broker.snapshot().sequence
                    while runner.status == "running" and monotonic() < deadline:
                        stream = refresh_quiet_quote(
                            market, selector, streams, stream, runner, series,
                        )
                        runner.step(series, stream.latest())
                        sequence = broker.wait_for_update(sequence, timeout=.25).sequence
                except KeyboardInterrupt:
                    pass
                finally:
                    halt_reason = runner.reason or "Bounded duration complete"
                    last_status = runner.status
                    try:
                        runner.stop()
                        if args.execute and profile.cancel_on_stop:
                            runner.cancel_owned_orders(timeout=15)
                    finally:
                        broker.export_strategy(runner.run_id,
                                               "charts/paper/option-strategy-audit.json")
                        broker.report("charts/paper/option-strategy.html")
                print(json.dumps(dict(run_id=runner.run_id, status=runner.status,
                                      previous_status=last_status, reason=halt_reason,
                                      ledger=broker.strategy_ledger(runner.run_id).to_dict())))


if __name__ == "__main__":
    main()

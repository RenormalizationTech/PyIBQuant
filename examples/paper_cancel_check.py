"""Read-only preflight or one-share AAPL resting-order cancellation check.

Only --execute can transmit. --resume-check inspects/cancels the original order
without replacing it. Any fill is retained and reported, never blindly reversed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import monotonic

from pyibquant import BrokerError, Market, PaperBroker
from pyibquant.broker import mask_account_data
from pyibquant.trading.cancel_check import (
    check_tag,
    execute_check,
    finish_check,
    flat_preflight,
    make_plan,
)
from pyibquant.trading.checkpoint import RunLease
from pyibquant.trading.profile import PaperProfile


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("paper_aapl.json"))
    parser.add_argument("--execute", action="store_true", help="Enable one bounded paper check")
    parser.add_argument("--resume-check", help="Exact prior check ID; never submits another order")
    args = parser.parse_args()
    try:
        profile = PaperProfile.load(args.profile)
        if args.resume_check:
            check_tag(args.resume_check)
        if profile.symbol != "AAPL":
            raise ValueError("This integration check is restricted to AAPL")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    options = profile.broker_options(execute=args.execute)
    options.update(client_id=297, max_quantity=1, max_order_value=min(500, profile.max_order_value))
    check_id = args.resume_check
    directory = None
    result = None
    with PaperBroker.ibkr(**options) as broker:
        lease = RunLease(broker.journal.path, "cancel-check")
        lease.acquire()
        try:
            if args.resume_check:
                directory = Path("charts/paper/cancel-checks") / args.resume_check
                result = finish_check(broker, args.resume_check)
            else:
                flat_preflight(broker)
                with Market.ibkr(
                    host=profile.host, port=profile.port, client_id=298, reconnect=False
                ) as market:
                    series = market.bars(
                        "AAPL", interval="1min", duration="1 D", include_sessions=True
                    )
                    with market.stream_quote("AAPL") as stream:
                        deadline = monotonic() + 15
                        while True:
                            q = stream.latest()
                            try:
                                plan = make_plan(broker, series, q)
                                break
                            except BrokerError:
                                if monotonic() >= deadline or q.status in {
                                    "closed",
                                    "failed",
                                    "disconnected",
                                }:
                                    raise
                                stream.wait_for_update(q.sequence, timeout=0.25)
                        check_id = plan.check_id
                        directory = Path("charts/paper/cancel-checks") / check_id
                        save(directory / "before.json", broker.snapshot().to_dict())
                        save(directory / "plan.json", plan.to_dict())
                        print(
                            json.dumps(
                                dict(
                                    mode="execute" if args.execute else "read-only",
                                    **plan.to_dict(),
                                )
                            ),
                            flush=True,
                        )
                        print(f"Check ID: {check_id}", flush=True)
                        result = (
                            execute_check(broker, plan)
                            if args.execute
                            else dict(
                                check_id=check_id,
                                outcome="preflight_only",
                            preflight_ready=True,
                                passed=False,
                                order_transmission=False,
                            )
                        )
        except (BrokerError, KeyboardInterrupt) as exc:
            detail = mask_account_data(str(exc) or "Interrupted", broker.account)
            has_intent = bool(check_id) and any(
                o.get("tag") == check_tag(check_id) for o in broker.snapshot().orders
            )
            result = dict(
                check_id=check_id,
                passed=False,
                outcome="unconfirmed",
                error=detail,
                order_transmission=args.execute,
                recovery=(
                    "Use --resume-check with this check ID; never blindly repeat --execute"
                    if has_intent
                    else "No order intent was created; correct the preflight failure"
                ),
            )
        finally:
            try:
                if directory is not None:
                    if result is not None:
                        save(directory / "result.json", result)
                    save(directory / "after.json", broker.snapshot().to_dict())
                    if check_id:
                        broker.export_strategy(check_tag(check_id), directory / "audit.json")
                    broker.report(directory / "account.html")
            finally:
                lease.release()
        print(json.dumps(result), flush=True)
        if directory is not None:
            print(f"Artifacts: {directory}", flush=True)
        if result is None or result.get("outcome") == "unconfirmed":
            raise SystemExit(1)
        if args.execute and not result.get("passed"):
            raise SystemExit(2)


if __name__ == "__main__":
    main()

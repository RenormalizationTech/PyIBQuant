"""Inspect or explicitly flatten one exact run's reconciled AAPL holdings.

Default is read-only. --execute submits at most one bounded limit SELL, waits for
terminal evidence and applies the saved pending-order cleanup policy. No BUY,
adoption of manual holdings, strategy resume or automatic replacement occurs.
"""

import argparse
import json
from pathlib import Path
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

from pyibquant import BrokerError, Market, PaperBroker
from pyibquant.broker import money
from pyibquant.trading.profile import PaperProfile
from pyibquant.trading.runner import EquityRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("paper_aapl.json"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    profile = PaperProfile.load(args.profile)
    if profile.symbol != "AAPL":
        parser.error("This bounded exit workflow supports AAPL only")
    directory = Path("charts/paper/runs") / args.run_id
    # Restore validates the ID before using it to write any artifact.
    with PaperBroker.ibkr(**profile.broker_options(
        execute=args.execute, preflight=not args.execute
    )) as broker:
        if not args.execute:
            for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
                setattr(broker._adapter, name,
                        Mock(side_effect=AssertionError("Read-only exit plan")))
        runner = EquityRunner.restore(broker, args.run_id)
        if runner.config.symbol != profile.symbol:
            raise BrokerError("Profile and persisted strategy symbol differ")
        result = None
        try:
            with Market.ibkr(
                host=profile.host, port=profile.port, client_id=profile.market_client_id,
                reconnect=False,
            ) as market:
                series = market.bars(
                    profile.symbol, interval="1min", duration="1 D", include_sessions=True
                )
                with market.stream_quote(profile.symbol) as stream:
                    deadline = monotonic() + 15
                    while True:
                        q = stream.latest()
                        if q.market_data_type == "live" and q.bid is not None and q.ask is not None:
                            break
                        if monotonic() >= deadline or q.status in {"failed", "closed"}:
                            raise BrokerError("Fresh live quote unavailable for the exit plan")
                        stream.wait_for_update(q.sequence, timeout=.25)
                    plan = runner.flatten_plan(series, q)
                    result = dict(mode="execute" if args.execute else "read-only", plan=plan)
                    print(json.dumps(result), flush=True)
                    if args.execute:
                        oid = runner.flatten(series, stream.latest())
                        if oid is not None:
                            order = broker.wait_order(oid, timeout=20)
                            result["order_id"], result["status"] = oid, order.get("status")
                        recovery = broker.reconcile()
                        ledger = broker.strategy_ledger(runner.run_id)
                        result.update(
                            reconciled=recovery.clear, ledger=ledger.to_dict(),
                            flat=all(q == 0 for _, q in ledger.positions),
                            account_flat=all(
                                money(p.get("quantity")) == 0 for p in recovery.snapshot.positions
                                if p.get("con_id") == plan["con_id"]
                            ),
                            pending_owned_order=broker.funding()["pending_owned_order"],
                        )
                        result["passed"] = bool(
                            recovery.clear and ledger.complete and result["flat"]
                            and result["account_flat"] and not result["pending_owned_order"]
                        )
                        print(json.dumps(result), flush=True)
        finally:
            try:
                if args.execute and runner._lease._file is not None:
                    runner.stop()
                    if profile.cancel_on_stop:
                        runner.cancel_owned_orders(timeout=15)
            finally:
                directory.mkdir(parents=True, exist_ok=True)
                if result is not None:
                    target = directory / ("flatten-" + uuid4().hex + ".json")
                    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
                    target.chmod(0o600)
                broker.export_strategy(runner.run_id, directory / "audit.json")
                broker.report(directory / "account.html")
        if args.execute and (not result or not result.get("passed")):
            raise SystemExit(2)


if __name__ == "__main__":
    main()

"""Read-only selected-option plan or one human-launched paper BUY/SELL round trip.

One contract, two order attempts maximum, existing premium cap, no expiry-day
orders. Resume can only resolve/cancel existing orders and close owned inventory;
it never buys or replaces an attempted sell. Uncertain outcomes remain explicit.
"""

import argparse
import json
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

from pyibquant import BrokerError, Market, Option, PaperBroker
from pyibquant.broker import mask_account_data, money
from pyibquant.trading.checkpoint import RunLease
from pyibquant.trading.option_order import round_limit
from pyibquant.trading.profile import PaperProfile


def fresh_quote(stream):
    deadline = monotonic() + 15
    while True:
        q = stream.latest()
        now = datetime.now(UTC)
        stamps = dict(q.field_received_at)
        if (
            q.status == "active" and q.market_data_type == "live" and not q.is_delayed
            and not q.crossed and q.bid is not None and q.ask is not None and q.bid > 0
            and all(k in stamps and 0 <= (now - stamps[k]).total_seconds() <= 10
                    for k in ("bid", "ask"))
        ):
            return q
        if monotonic() >= deadline or q.status in {"closed", "failed", "disconnected"}:
            raise BrokerError("Fresh live option bid/ask unavailable")
        stream.wait_for_update(q.sequence, timeout=.25)


def execution_limit(value, side, rules):
    # Paper option simulation does not support penny fills. A coarser grid still
    # has to satisfy the actual SMART market rule; no minimum tick is fabricated.
    nickel = Decimal(".05")
    price = (Decimal(str(value)) / nickel).to_integral_value(
        rounding=ROUND_UP if side == "BUY" else ROUND_DOWN
    ) * nickel
    return round_limit(price, side, rules)


def create_plan(broker, selector, series, q, max_loss):
    from zoneinfo import ZoneInfo

    contract, rules = broker._adapter.resolve_option(selector)
    recovery = broker.reconcile()
    at = datetime.now(UTC)
    if not recovery.clear or any(money(p.get("quantity")) != 0
                                 for p in recovery.snapshot.positions):
        raise BrokerError("Option entry check requires flat holdings and clear orders")
    if selector.expiry <= at.astimezone(ZoneInfo("America/New_York")).date():
        raise BrokerError("Expiry-day and expired option checks are unsupported")
    if not any(s["regular"] and s["start"] <= at.timestamp() < s["end"]
               for s in series.sessions):
        raise BrokerError("Provider-confirmed underlying regular session is required")
    multiplier = money(contract.multiplier)
    if multiplier is None or multiplier <= 0:
        raise BrokerError("Missing option multiplier")
    if q.instrument.instrument_id != contract.conId or money(q.instrument.multiplier) != multiplier:
        raise BrokerError("Option plan identity/multiplier mismatch")
    stamps = dict(q.field_received_at)
    if any(k not in stamps or not 0 <= (at - stamps[k]).total_seconds() <= 15
           for k in ("bid", "ask")):
        raise BrokerError("Option plan quote became stale during reconciliation")
    buy = execution_limit(q.ask, "BUY", rules)
    sell = execution_limit(q.bid, "SELL", rules)
    premium = buy * multiplier
    estimated_cost = (buy - sell) * multiplier + 4
    if premium > broker.max_order_value or premium + 2 > (money(broker.funding()["usable"]) or 0):
        raise BrokerError("Option premium plus fee reserve exceeds the funding/order cap")
    if estimated_cost > Decimal(str(max_loss)):
        raise BrokerError("Quoted spread plus fee estimate exceeds the session-loss budget")
    return dict(
        symbol=selector.symbol, expiry=selector.expiry.isoformat(), strike=selector.strike,
        right=selector.right, trading_class=selector.trading_class,
        multiplier=str(multiplier), con_id=contract.conId, local_symbol=contract.localSymbol,
        quantity=1, buy_limit=str(buy), exit_reference=str(sell),
        max_entry_premium=str(premium), estimated_spread_and_fees=str(estimated_cost),
        max_order_value=str(broker.max_order_value), checked_at=at.isoformat(),
    )


def finish_check(broker, selector, get_quote, check_id):
    """Exit-only recovery; an attempted sell is never automatically repeated."""
    tag = "option-check-" + check_id
    report = broker.reconcile()
    if report.missing_orders or report.foreign_orders:
        raise BrokerError("Unresolved missing/foreign orders block option recovery")
    orders = [o for o in report.snapshot.orders if o.get("tag") == tag]
    if not orders or any(not broker._owned(o) for o in orders):
        raise BrokerError("No exact owned option-check order to recover")
    broker.cancel_owned_orders(tag=tag, timeout=15)
    report = broker.reconcile()
    ledger = broker.strategy_ledger(tag)
    if not ledger.complete:
        raise BrokerError("Option executions do not reconcile; no exit/replacement sent")
    contract, rules = broker._adapter.resolve_option(selector)
    owned = dict(ledger.positions).get(contract.conId, Decimal(0))
    if owned == 1:
        if any(o.get("side") == "SELL" for o in orders):
            raise BrokerError("A sell was already attempted; inspect before another exit")
        q = get_quote()
        price = execution_limit(q.bid, "SELL", rules)
        oid = broker.submit_option_limit(selector, "SELL", 1, float(price),
                                        quote=q, tag=tag, key=check_id + ":sell")
        broker.wait_order(oid, timeout=20)
    elif owned != 0:
        raise BrokerError("Unexpected option inventory; no automatic adjustment")
    report = broker.reconcile()
    ledger = broker.strategy_ledger(tag)
    deadline = monotonic() + 5
    while ledger.commissions is None and monotonic() < deadline:
        snap = broker.snapshot()
        broker.wait_for_update(snap.sequence, timeout=.25)
        ledger = broker.strategy_ledger(tag)
    account_flat = all(money(p.get("quantity")) == 0 for p in report.snapshot.positions)
    flat = all(q == 0 for _, q in ledger.positions)
    return dict(
        check_id=check_id, passed=(report.clear and account_flat and flat and ledger.complete
                                 and ledger.execution_count == 2),
        flat=flat, account_flat=account_flat, reconciled=report.clear,
        ledger=ledger.to_dict(), pending_owned_order=broker.funding()["pending_owned_order"],
        round_trip_filled=ledger.execution_count == 2,
    )


def finish_cancellation(broker, check_id, *, wait_ack=True):
    """One exact option BUY: acknowledge, rest briefly, cancel and verify reservation."""
    tag = "option-check-" + check_id
    if not wait_ack:
        recovery = broker.reconcile()
        if recovery.missing_orders or recovery.foreign_orders:
            raise BrokerError("Missing/foreign orders block exact option cancellation recovery")

    def original_order():
        rows = [o for o in broker.snapshot().orders if o.get("tag") == tag]
        if len(rows) != 1 or not broker._owned(rows[0]) or rows[0].get("side") != "BUY":
            raise BrokerError("Expected exactly one owned option cancellation BUY")
        return rows[0]

    deadline, acknowledged_at = monotonic() + 10, None
    acknowledged = any(e["kind"] == "option_cancel_ack"
                       and e["payload"].get("check_id") == check_id
                       for e in broker.journal.events(broker.account))
    while True:
        order = original_order()
        if order.get("status") in {"Submitted", "PreSubmitted"}:
            if acknowledged_at is None:
                acknowledged, acknowledged_at = True, monotonic()
                broker._record("option_cancel_ack", dict(check_id=check_id,
                                                          order_id=order["order_id"]))
            if not wait_ack or monotonic() - acknowledged_at >= 2:
                break
        if order.get("status") in {"Filled", "Cancelled", "ApiCancelled", "Inactive"}:
            if order.get("recovery_source") == "completed_orders":
                acknowledged = True
            break
        if monotonic() >= deadline:
            break
        snapshot = broker.snapshot()
        broker.wait_for_update(snapshot.sequence, timeout=.25)
    reserved = broker.funding()["pending_buy_estimate"]
    broker._record("option_cancel_reservation", dict(check_id=check_id, estimated=reserved))
    broker.cancel_owned_orders(tag=tag, timeout=15)
    recovery = broker.reconcile()
    order = original_order()
    ledger = broker.strategy_ledger(tag)
    flat = all(money(p.get("quantity")) == 0 for p in recovery.snapshot.positions)
    pending = broker.funding()["pending_owned_order"]
    passed = (acknowledged and order.get("status") in {"Cancelled", "ApiCancelled"}
              and money(order.get("filled")) == 0 and ledger.complete
              and recovery.clear and flat and not pending)
    return dict(
        check_id=check_id, passed=passed, acknowledged=acknowledged,
        outcome="canceled_unfilled" if passed else "fill_observed"
        if (money(order.get("filled")) or 0) > 0 else "not_confirmed",
        status=order.get("status"), order_id=order["order_id"],
        flat=flat, account_flat=flat, reconciled=recovery.clear,
        ledger=ledger.to_dict(), pending_owned_order=pending,
        reservation_before_cancel=reserved,
        reservation_after_cancel=broker.funding()["pending_buy_estimate"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("paper_aapl.json"))
    parser.add_argument("--expiry", type=date.fromisoformat)
    parser.add_argument("--strike", type=float)
    parser.add_argument("--right", choices=["C", "P"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume-check")
    parser.add_argument("--cancel-only", action="store_true",
                        help="New check: one resting option BUY, acknowledge and cancel")
    parser.add_argument("--exit-owned", action="store_true",
                        help="With --resume-check --execute: explicitly close retained inventory")
    args = parser.parse_args()
    profile = PaperProfile.load(args.profile)
    if profile.symbol != "AAPL":
        parser.error("Initial option check is restricted to AAPL")
    check_id = args.resume_check or uuid4().hex
    if len(check_id) != 32 or any(c not in "0123456789abcdef" for c in check_id):
        parser.error("Use the exact printed Check ID")
    if args.resume_check and (args.expiry or args.strike or args.right):
        parser.error("Resume uses the persisted contract; do not override expiry/strike")
    if args.cancel_only and args.resume_check:
        parser.error("Resume uses the persisted check kind; omit --cancel-only")
    if args.exit_owned and (not args.resume_check or not args.execute):
        parser.error("--exit-owned requires --resume-check and --execute")
    options = profile.broker_options(execute=args.execute)
    options.update(client_id=311, max_quantity=1, max_order_value=min(500, profile.max_order_value))
    directory = Path("charts/paper/option-checks") / check_id
    with PaperBroker.ibkr(**options) as broker:
        lease = RunLease(broker.journal.path, "option-check")
        lease.acquire()
        result = None
        try:
            if not args.execute:
                for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
                    setattr(broker._adapter, name,
                            Mock(side_effect=AssertionError("Read-only plan")))
            if args.resume_check:
                plans = [e["payload"] for e in broker.journal.events(broker.account)
                         if e["kind"] == "option_check_plan"
                         and e["payload"].get("check_id") == check_id]
                if not plans:
                    raise BrokerError("No persisted option check plan")
                p = plans[-1]
                selector = Option("AAPL", date.fromisoformat(p["expiry"]), p["strike"],
                                  p["right"], p["trading_class"], float(p["multiplier"]))
            else:
                if args.expiry is None or args.strike is None:
                    parser.error("A new option check requires explicit --expiry and --strike")
                selector = Option("AAPL", args.expiry, args.strike, args.right or "C", "AAPL", 100)
            print(f"Check ID: {check_id}", flush=True)
            with Market.ibkr(host=profile.host, port=profile.port, client_id=312,
                             reconnect=False) as market, market.stream_quote(selector) as stream:
                def get_quote():
                    return fresh_quote(stream)

                if args.resume_check:
                    if args.execute:
                        if p.get("check_kind") == "cancel" and not args.exit_owned:
                            result = finish_cancellation(broker, check_id, wait_ack=False)
                        else:
                            result = finish_check(broker, selector, get_quote, check_id)
                    else:
                        result = {"check_id": check_id, "ledger": broker.strategy_ledger(
                            "option-check-" + check_id).to_dict(), "order_transmission": False}
                else:
                    series = market.bars("AAPL", interval="1min", duration="1 D",
                                         include_sessions=True)
                    if args.execute:
                        risk = broker.refresh_pnl(renew=False)
                        if not risk.pnl.get("validated") or money(risk.pnl.get("daily")) is None:
                            raise BrokerError("Validated account P&L required before option entry")
                    q = get_quote()
                    plan = create_plan(broker, selector, series, q, profile.max_session_loss)
                    plan["check_kind"] = "cancel" if args.cancel_only else "round_trip"
                    if args.cancel_only:
                        _, rules = broker._adapter.resolve_option(selector)
                        resting = execution_limit(Decimal(str(q.bid)) * Decimal(".90"),
                                                  "SELL", rules)
                        plan["buy_limit"] = str(resting)
                        plan["max_entry_premium"] = str(resting * Decimal(plan["multiplier"]))
                    result = dict(check_id=check_id, plan=plan, preflight_ready=True,
                                  order_transmission=args.execute)
                    print(json.dumps(result), flush=True)
                    if args.execute:
                        broker._record("option_check_plan", dict(
                            **plan, check_id=check_id, pnl_baseline=risk.pnl["daily"]
                        ))
                        oid = broker.submit_option_limit(
                            selector, "BUY", 1, float(plan["buy_limit"]), quote=q,
                            tag="option-check-" + check_id, key=check_id + ":buy",
                        )
                        if args.cancel_only:
                            result = finish_cancellation(broker, check_id)
                        else:
                            broker.wait_order(oid, timeout=20)
                            result = finish_check(broker, selector, get_quote, check_id)
        except (BrokerError, KeyboardInterrupt) as exc:
            has_intent = any(o.get("tag") == "option-check-" + check_id
                             for o in broker.snapshot().orders)
            result = dict(check_id=check_id, passed=False, outcome="unconfirmed",
                          error=mask_account_data(str(exc), broker.account),
                          recovery=("Use --resume-check with this exact ID; never repeat entry"
                                    if has_intent else "No intent; correct preflight inputs"))
        finally:
            try:
                if args.execute:
                    try:
                        broker.cancel_owned_orders(tag="option-check-" + check_id, timeout=15)
                    except BrokerError as exc:
                        result = dict(result or {}, passed=False,
                                      cleanup_error=mask_account_data(str(exc), broker.account))
            finally:
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / "result.json"
                path.write_text(json.dumps(result, indent=2), encoding="utf-8")
                path.chmod(0o600)
                broker.export_strategy("option-check-" + check_id, directory / "audit.json")
                broker.report(directory / "account.html")
                lease.release()
        print(json.dumps(result), flush=True)
        print(f"Artifacts: {directory}", flush=True)
        if args.execute and not (result or {}).get("passed"):
            raise SystemExit(2)
        if (result or {}).get("outcome") == "unconfirmed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()

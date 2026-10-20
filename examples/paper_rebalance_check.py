"""Explicit paper check: sell current long USD equities, then buy one AAPL share.

Default is read-only preflight. --execute requires the owner's exact authorization.
Uses live-quoted DAY limits, or a holding-only market close for missing subscriptions.
Never touches a live account.
An uncertain outcome stops the sequence rather than retrying an order blindly.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from time import monotonic

from pyibquant import BrokerError, Market, PaperBroker

TERMINAL = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
DIRECTORY = Path("charts/paper/rebalance-check")


def fresh_quote(stream, timeout=15):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        q = stream.latest()
        receipts = dict(q.field_received_at)
        if q.status in {"failed", "closed", "disconnected"}:
            break
        if (
            q.market_data_type == "live"
            and q.status == "active"
            and not q.is_delayed
            and not q.crossed
            and q.bid is not None
            and q.ask is not None
            and q.bid > 0
            and all(
                k in receipts and 0 <= (datetime.now(UTC) - receipts[k]).total_seconds() < 10
                for k in ("bid", "ask")
            )
        ):
            return q
        stream.wait_for_update(q.sequence, timeout=0.25)
    raise BrokerError(
        f"{q.instrument.symbol}: no fresh confirmed bid/ask; status={q.status}, "
        f"feed={q.market_data_type}, bid={q.bid}, ask={q.ask}, "
        f"warnings={q.warnings}, error={q.error}. No new order submitted"
    )


def holdings(broker):
    result = []
    for p in broker.snapshot().positions:
        quantity = Decimal(str(p["quantity"]))
        if not quantity:
            continue
        if (
            p["asset_type"] != "STK"
            or p["currency"] != "USD"
            or quantity < 0
            or quantity != quantity.to_integral_value()
        ):
            raise BrokerError("Check supports long whole-share USD equities only; no orders sent")
        result.append(dict(symbol=p["symbol"], con_id=p["con_id"], quantity=int(quantity)))
    return sorted(result, key=lambda p: p["symbol"])


def transmit(broker, stream, symbol, side, quantity, key):
    q = fresh_quote(stream)
    basis = Decimal(str(q.bid if side == "SELL" else q.ask))
    price = (basis * (Decimal(".999") if side == "SELL" else Decimal("1.001"))).quantize(
        Decimal(".01"), rounding=ROUND_DOWN if side == "SELL" else ROUND_UP
    )
    if side == "BUY" and (symbol != "AAPL" or quantity != 1 or price > 500):
        raise BrokerError("AAPL check is capped at one share and $500 order notional")
    oid = broker.submit_limit(
        symbol, side, quantity, float(price), tag="owner-authorized-rebalance", key=key
    )
    print(
        json.dumps(
            dict(
                order_id=oid,
                symbol=symbol,
                side=side,
                quantity=quantity,
                limit_price=str(price),
                status="submitted",
            )
        ),
        flush=True,
    )
    outcome = broker.wait_order(oid)
    print(
        json.dumps(
            dict(
                order_id=oid,
                symbol=symbol,
                status=outcome["status"],
                filled=outcome.get("filled"),
                average_fill_price=outcome.get("average_fill_price"),
            )
        ),
        flush=True,
    )
    if outcome["status"] != "Filled" or Decimal(outcome.get("filled", "0")) != quantity:
        raise BrokerError("Order did not fully fill; no next step will be sent")
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--buy-only",
        action="store_true",
        help="Resume the one-share AAPL check only if the account is already flat",
    )
    args = parser.parse_args()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    expected = None
    discovery = Path("charts/paper/discovery.json")
    if discovery.exists():
        accounts = json.loads(discovery.read_text())["accounts"]
        if len(accounts) == 1:
            expected = accounts[0]
    with PaperBroker.ibkr(
        account=expected,
        client_id=280,
        readonly=not args.execute,
        paper_confirmed=args.execute,
        journal=DIRECTORY / "account.sqlite3",
        max_quantity=1,
        max_order_value=500,
    ) as broker:
        streams = {}
        try:
            initial = holdings(broker)
            if args.buy_only and initial:
                raise BrokerError(
                    "Buy-only resume requires a flat account; no positions will be sold"
                )
            working = [o for o in broker.snapshot().orders if o.get("status") not in TERMINAL]
            if working:
                raise BrokerError("Existing open orders must be resolved before liquidation")
            if broker.base_currency() != "USD":
                raise BrokerError("This check requires the confirmed USD paper account")
            (DIRECTORY / "before.json").write_text(
                json.dumps(broker.snapshot().to_dict(), indent=2)
            )
            with Market.ibkr(client_id=282, reconnect=False) as market:
                for symbol in sorted({p["symbol"] for p in initial} | {"AAPL"}):
                    streams[symbol] = market.stream_quote(symbol)
                plans = []
                market_closes = set()
                for p in initial:
                    try:
                        q = fresh_quote(streams[p["symbol"]])
                    except BrokerError:
                        q = streams[p["symbol"]].latest()
                        if q.status != "failed" or "10168" not in (q.error or ""):
                            raise
                        market_closes.add(p["symbol"])
                    if q.instrument.instrument_id != p["con_id"]:
                        raise BrokerError(
                            "Quote and holding identity differ; no order will be sent"
                        )
                    plans.append(
                        dict(
                            **p,
                            order_type="MKT" if p["symbol"] in market_closes else "LMT",
                            approximate_notional=str(Decimal(str(q.bid)) * p["quantity"])
                            if q.bid is not None
                            else None,
                        )
                    )
                aapl = fresh_quote(streams["AAPL"])
                if Decimal(str(aapl.ask)) * Decimal("1.001") > 500:
                    raise BrokerError("AAPL exceeds the $500 check cap")
                print(
                    json.dumps(
                        dict(
                            account=broker.snapshot().to_dict()["account"],
                            mode="execute" if args.execute else "read-only preflight",
                            sell=plans,
                            buy=dict(symbol="AAPL", quantity=1, max_notional=500),
                        )
                    ),
                    flush=True,
                )
                if not args.execute:
                    (DIRECTORY / "preflight.json").write_text(
                        json.dumps(dict(positions=plans), indent=2)
                    )
                    return
                run = broker.session[:12]
                initial.sort(key=lambda p: (p["symbol"] not in market_closes, p["symbol"]))
                # Scope expansion is only for liquidation of the observed holdings.
                for p in initial:
                    broker.refresh()
                    current = holdings(broker)
                    current_qty = next(
                        (r["quantity"] for r in current if r["con_id"] == p["con_id"]), 0
                    )
                    if current_qty != p["quantity"]:
                        raise BrokerError("Holdings changed since preflight; stopping")
                    broker.max_quantity = p["quantity"]
                    if p["symbol"] in market_closes:
                        oid = broker.close_position_market(
                            p["symbol"],
                            p["quantity"],
                            tag="owner-authorized-rebalance",
                            key=run + "-sell-" + p["symbol"],
                        )
                        print(
                            json.dumps(
                                dict(
                                    order_id=oid,
                                    symbol=p["symbol"],
                                    side="SELL",
                                    quantity=p["quantity"],
                                    order_type="MKT",
                                )
                            ),
                            flush=True,
                        )
                        outcome = broker.wait_order(oid)
                        print(
                            json.dumps(
                                dict(
                                    order_id=oid,
                                    status=outcome["status"],
                                    filled=outcome.get("filled"),
                                )
                            ),
                            flush=True,
                        )
                        if (
                            outcome["status"] != "Filled"
                            or Decimal(outcome.get("filled", "0")) != p["quantity"]
                        ):
                            raise BrokerError("Market close did not fully fill; stopping")
                    else:
                        q = fresh_quote(streams[p["symbol"]])
                        broker.max_order_value = (
                            Decimal(str(q.bid)) * p["quantity"] * Decimal("1.01")
                        )
                        transmit(
                            broker,
                            streams[p["symbol"]],
                            p["symbol"],
                            "SELL",
                            p["quantity"],
                            run + "-sell-" + p["symbol"],
                        )
                    broker.refresh()
                    if any(r["con_id"] == p["con_id"] for r in holdings(broker)):
                        raise BrokerError(
                            "Liquidated holding remains in broker positions; stopping"
                        )
                broker.refresh()
                if holdings(broker):
                    raise BrokerError("Account is not flat; AAPL buy will not be sent")
                broker.max_quantity, broker.max_order_value = 1, Decimal(500)
                transmit(broker, streams["AAPL"], "AAPL", "BUY", 1, run + "-buy-AAPL")
                broker.refresh()
                final = holdings(broker)
                if len(final) != 1 or final[0]["symbol"] != "AAPL" or final[0]["quantity"] != 1:
                    raise BrokerError("Final holdings differ from the one-share AAPL target")
                print(
                    "PASS: all starting positions sold; final holding is one AAPL share", flush=True
                )
        finally:
            if args.execute:
                for order in broker.snapshot().orders:
                    if broker._owned(order) and order.get("status") not in TERMINAL:
                        broker.cancel(order["order_id"])
                        try:
                            broker.wait_order(order["order_id"], timeout=10)
                        except BrokerError as exc:
                            print(f"Cleanup needs reconciliation: {exc}", flush=True)
            for stream in streams.values():
                stream.close()
            (DIRECTORY / "after.json").write_text(json.dumps(broker.snapshot().to_dict(), indent=2))
            broker.report(DIRECTORY / "account.html")


if __name__ == "__main__":
    main()

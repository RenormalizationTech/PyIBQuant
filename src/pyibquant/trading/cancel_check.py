"""One bounded paper cancellation check, with no automatic replacement or unwind."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from time import monotonic
from typing import Any
from uuid import uuid4

from ..bars import BarSeries
from ..broker import TERMINAL_ORDER_STATES, BrokerError, PaperBroker, money
from ..quotes import Quote


def check_tag(check_id: str) -> str:
    if (
        not isinstance(check_id, str)
        or len(check_id) != 32
        or any(c not in "0123456789abcdef" for c in check_id)
    ):
        raise ValueError("Use the exact 32-character cancellation check ID")
    return "cancel-check-" + check_id


@dataclass(frozen=True)
class CancellationPlan:
    check_id: str
    symbol: str
    con_id: int
    limit_price: Decimal
    bid: Decimal
    ask: Decimal
    checked_at: datetime

    def __post_init__(self) -> None:
        check_tag(self.check_id)
        if (
            self.symbol != "AAPL"
            or type(self.con_id) is not int
            or self.con_id <= 0
            or not isinstance(self.checked_at, datetime)
            or self.checked_at.utcoffset() is None
            or any(money(v) is None for v in (self.bid, self.ask, self.limit_price))
            or not 0 < self.limit_price < self.bid <= self.ask
            or self.limit_price > 500
        ):
            raise ValueError("Use a bounded one-share AAPL plan with a limit below a valid bid")

    @property
    def tag(self) -> str:
        return check_tag(self.check_id)

    def to_dict(self) -> dict[str, Any]:
        return dict(
            check_id=self.check_id,
            symbol=self.symbol,
            con_id=self.con_id,
            side="BUY",
            quantity=1,
            limit_price=str(self.limit_price),
            bid=str(self.bid),
            ask=str(self.ask),
            checked_at=self.checked_at.isoformat(),
            max_notional=500,
            resting_seconds=2,
            fill_policy="Report any fill and retain the holding; no automatic sell or replacement",
        )


def flat_preflight(broker: PaperBroker) -> None:
    report = broker.reconcile()
    if not report.clear:
        raise BrokerError("Resolve working, missing or foreign orders before this check")
    if broker.base_currency() != "USD":
        raise BrokerError("Cancellation check requires a confirmed USD base currency")
    if any(money(p.get("quantity")) != 0 for p in report.snapshot.positions):
        raise BrokerError("Cancellation check requires a fully flat starting account")


def make_plan(
    broker: PaperBroker, series: BarSeries, quote: Quote, *, at: datetime | None = None
) -> CancellationPlan:
    at = at or datetime.now(UTC)
    if at.utcoffset() is None:
        raise ValueError("Use a timezone-aware check clock")
    if (
        series.symbol != "AAPL"
        or quote.instrument.symbol != series.symbol
        or series.instrument_id is None
        or quote.instrument.instrument_id != series.instrument_id
        or series.asset_type != "equity"
        or series.currency != "USD"
        or series.error
    ):
        raise BrokerError("Cancellation check supports matching AAPL USD equity data only")
    if not any(s["regular"] and s["start"] <= at.timestamp() < s["end"] for s in series.sessions):
        raise BrokerError("Cancellation check requires a provider-confirmed regular session")
    receipts = dict(quote.field_received_at)
    bid, ask = money(quote.bid), money(quote.ask)
    if (
        quote.market_data_type != "live"
        or quote.is_delayed
        or quote.crossed
        or quote.status != "active"
        or bid is None
        or ask is None
        or not 0 < bid <= ask
        or any(
            k not in receipts or not 0 <= (at - receipts[k]).total_seconds() <= 10
            for k in ("bid", "ask")
        )
    ):
        raise BrokerError("Cancellation check requires a fresh live bid/ask")
    price = (bid * Decimal(".98")).quantize(Decimal(".01"), rounding=ROUND_DOWN)
    if not 0 < price < bid or price > 500 or price > broker.max_order_value:
        raise BrokerError("Resting BUY must be below bid and within the $500 order cap")
    budget = money(broker.funding()["usable"])
    if budget is None or budget < price + 2:
        raise BrokerError("Insufficient or unknown settled-cash funding including fee reserve")
    return CancellationPlan(uuid4().hex, series.symbol, series.instrument_id, price, bid, ask, at)


def owned_check_order(broker: PaperBroker, check_id: str) -> dict[str, Any]:
    tag = check_tag(check_id)
    orders = [dict(o) for o in broker.snapshot().orders if o.get("tag") == tag]
    if len(orders) != 1 or not broker._owned(orders[0]):
        raise BrokerError("Expected one durable cancellation-check order owned by this API client")
    return orders[0]


def _result(broker: PaperBroker, check_id: str, *, acknowledged: bool) -> dict[str, Any]:
    recovery = broker.reconcile()
    order = owned_check_order(broker, check_id)
    filled = money(order.get("filled"))
    ledger = broker.strategy_ledger(check_tag(check_id))
    flat = all(money(p.get("quantity")) == 0 for p in recovery.snapshot.positions)
    canceled = order.get("status") in {"Cancelled", "ApiCancelled"}
    passed = (
        acknowledged and canceled and filled == 0 and flat and recovery.clear and ledger.complete
    )
    return dict(
        check_id=check_id,
        passed=passed,
        outcome=(
            "canceled_unfilled"
            if passed
            else "fill_observed"
            if filled is not None and filled > 0
            else "not_confirmed"
        ),
        acknowledged=acknowledged,
        order_id=order["order_id"],
        status=order.get("status"),
        filled=str(filled) if filled is not None else None,
        flat=flat,
        reconciled=recovery.clear,
        ledger=ledger.to_dict(),
        pending_owned_order=broker.funding()["pending_owned_order"],
        order_transmission=not broker.readonly,
    )


def finish_check(broker: PaperBroker, check_id: str) -> dict[str, Any]:
    """Resume cancellation only. Never submits a new order or unwinds a fill."""
    order = owned_check_order(broker, check_id)
    acknowledged = any(
        e["kind"] == "cancel_check_ack" and e["payload"].get("check_id") == check_id
        for e in broker.journal.events(broker.account)
    )
    if not broker.readonly:
        broker.cancel_owned_orders(tag=check_tag(check_id), timeout=15)
        # A fill can win before cancel selection; fetch the actual terminal state.
        broker.wait_order(order["order_id"], timeout=15)
        if broker.cancel_owned_orders(tag=check_tag(check_id), timeout=0):
            raise BrokerError("Terminal check order unexpectedly remained cancelable")
    result = _result(broker, check_id, acknowledged=acknowledged)
    broker._record("cancel_check_result", result)
    return result


def execute_check(broker: PaperBroker, plan: CancellationPlan) -> dict[str, Any]:
    if broker.readonly:
        raise BrokerError("Cancellation check execution requires an enabled paper broker")
    check_tag(plan.check_id)
    if any(o.get("tag") == plan.tag for o in broker.snapshot().orders):
        raise BrokerError("Check already has an order; use --resume-check, never submit it again")
    flat_preflight(broker)
    age = (datetime.now(UTC) - plan.checked_at).total_seconds()
    if not 0 <= age <= 10 or plan.symbol != "AAPL" or not 0 < plan.limit_price <= 500:
        raise BrokerError("Cancellation plan is stale or outside the approved AAPL bounds")
    contract = broker._adapter.resolve(plan.symbol)
    if contract.conId != plan.con_id:
        raise BrokerError("Cancellation plan contract differs from broker resolution")
    broker._record("cancel_check_plan", plan.to_dict())
    try:
        oid = broker.submit_limit(
            plan.symbol,
            "BUY",
            1,
            float(plan.limit_price),
            tag=plan.tag,
            key=plan.check_id,
        )
        deadline = monotonic() + 10
        acknowledged_at = None
        while True:
            snapshot = broker.snapshot()
            order = owned_check_order(broker, plan.check_id)
            if order.get("status") in TERMINAL_ORDER_STATES:
                break
            if order.get("status") in {"Submitted", "PreSubmitted"}:
                if acknowledged_at is None:
                    acknowledged_at = monotonic()
                    broker._record(
                        "cancel_check_ack",
                        dict(
                            check_id=plan.check_id,
                            order_id=oid,
                            status=order["status"],
                        ),
                    )
                if monotonic() - acknowledged_at >= 2:
                    break
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            broker.wait_for_update(snapshot.sequence, timeout=min(0.25, remaining))
    finally:
        # Exact-tag cleanup also covers interrupted waits or unknown send outcomes.
        # Any unconfirmed cancellation raises with durable order evidence intact.
        broker.cancel_owned_orders(tag=plan.tag, timeout=15)
    return finish_check(broker, plan.check_id)

"""Selected long-option orders using the shared paper broker lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..broker import BrokerError, money
from ..quotes import Option, Quote

if TYPE_CHECKING:
    from ..broker import PaperBroker


def tick_at(price: Decimal, rules: tuple[tuple[Decimal, Decimal], ...]) -> tuple[Decimal, Decimal]:
    if not rules or rules[0][0] != 0 or any(
        not edge.is_finite() or not tick.is_finite() or edge < 0 or tick <= 0
        for edge, tick in rules
    ) or any(rules[i][0] >= rules[i + 1][0] for i in range(len(rules) - 1)):
        raise BrokerError("Invalid option price-increment ladder")
    return next((row for row in reversed(rules) if row[0] <= price), rules[0])


def round_limit(price: Decimal, side: str, rules: tuple[tuple[Decimal, Decimal], ...]) -> Decimal:
    if side not in {"BUY", "SELL"} or not price.is_finite() or price <= 0:
        raise ValueError("Use a positive premium and BUY/SELL")
    result = price
    for _ in range(len(rules) + 1):
        edge, tick = tick_at(result, rules)
        result = edge + ((result - edge) / tick).to_integral_value(
            rounding=ROUND_UP if side == "BUY" else ROUND_DOWN
        ) * tick
        new_edge, new_tick = tick_at(result, rules)
        if result > 0 and (result - new_edge) % new_tick == 0:
            return result
    raise BrokerError("Cannot produce a positive tick-valid option limit")


def submit_option_limit(
    broker: PaperBroker, selector: Option, side: str, quantity: int, limit_price: float,
    *, quote: Quote, tag: str, key: str | None = None,
) -> int:
    if not isinstance(selector, Option) or not isinstance(quote, Quote):
        raise ValueError("Use an explicit Option and immutable quote")
    price = money(limit_price)
    if (
        side not in {"BUY", "SELL"} or type(quantity) is not int
        or quantity != 1 or quantity > broker.max_quantity
        or price is None or price <= 0 or isinstance(limit_price, bool)
    ):
        raise ValueError("Initial option scope is one long contract with a positive limit")
    if not tag:
        raise ValueError("An explicit option ownership tag is required")
    with broker._commands:
        if broker.readonly or broker._closed:
            raise BrokerError("Broker is read-only or closed")
        contract, rules = broker._adapter.resolve_option(selector)
        report = broker.reconcile()
        at = datetime.now(UTC)
        if selector.expiry <= at.astimezone(ZoneInfo("America/New_York")).date():
            raise BrokerError("Expiry-day and expired option orders are unsupported")
        multiplier = money(contract.multiplier)
        if multiplier is None or multiplier <= 0:
            raise BrokerError("Option multiplier is missing")
        premium = price * quantity * multiplier
        if premium > broker.max_order_value:
            raise BrokerError("Option premium including multiplier exceeds the order cap")
        edge, tick = tick_at(price, rules)
        if (price - edge) % tick != 0:
            raise BrokerError("Option limit is not valid for the broker price-increment rule")
        q = quote.instrument
        receipts = dict(quote.field_received_at)
        if (
            q.asset_type != "option" or q.instrument_id != contract.conId
            or q.symbol != selector.symbol or q.currency != "USD"
            or money(q.multiplier) != multiplier
            or q.expiry != selector.expiry.strftime("%Y%m%d")
            or money(q.strike) != money(selector.strike) or q.right != selector.right
            or quote.market_data_type != "live" or quote.is_delayed or quote.crossed
            or quote.status != "active" or quote.bid is None or quote.ask is None
            or quote.bid <= 0 or quote.ask <= 0
            or any(k not in receipts or not 0 <= (at - receipts[k]).total_seconds() <= 15
                   for k in ("bid", "ask"))
        ):
            raise BrokerError("Option order requires a fresh live exact-contract bid/ask")
        if not report.clear or not report.snapshot.complete or not broker._adapter.isConnected():
            raise BrokerError("Resolve working or uncertain orders before option submission")
        positions = [p for p in report.snapshot.positions if p.get("con_id") == contract.conId]
        amounts = [money(p.get("quantity")) for p in positions]
        if any(q is None or q < 0 or q != q.to_integral_value() for q in amounts):
            raise BrokerError("Option position is unknown, short or fractional")
        held = sum((q for q in amounts if q is not None), Decimal(0))
        if side == "BUY":
            if held != 0:
                raise BrokerError("Initial option entry requires a flat selected contract")
            budget = money(broker.funding()["usable"])
            if budget is None or budget < premium + Decimal(2) * quantity:
                raise BrokerError("Insufficient settled-cash option funding including fee reserve")
        else:
            ledger = broker.strategy_ledger(tag)
            owned = dict(ledger.positions).get(contract.conId, Decimal(0))
            if not ledger.complete or held != owned or held != quantity:
                raise BrokerError("Option sell must close this tag's reconciled long holding")
        return broker._send_intent(
            contract, selector.symbol, side, quantity, price, tag, key,
            dict(asset_type="OPT", currency="USD", multiplier=str(multiplier),
                 expiry=selector.expiry.strftime("%Y%m%d"), local_symbol=contract.localSymbol),
        )

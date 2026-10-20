"""Strategy attribution from durable intents and broker executions, never signals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def contract_multiplier(row: Mapping[str, Any]) -> Decimal | None:
    """Equities are per share; options require a positive explicit multiplier."""
    from ..broker import money

    asset = row.get("asset_type", "STK")
    if asset == "STK":
        return Decimal(1)
    if asset == "OPT":
        value = money(row.get("multiplier"))
        return value if value is not None and value > 0 else None
    return None


@dataclass(frozen=True)
class StrategyLedger:
    tag: str
    positions: tuple[tuple[int, Decimal], ...]
    execution_count: int
    cash_flow: Decimal
    commissions: Decimal | None
    issues: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Order fill quantities reconcile; commission completeness is separate."""
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        flat = self.complete and all(q == 0 for _, q in self.positions)
        return dict(
            tag=self.tag,
            complete=self.complete,
            positions=[dict(con_id=c, quantity=str(q)) for c, q in self.positions],
            execution_count=self.execution_count,
            cash_flow=str(self.cash_flow),
            commissions=str(self.commissions) if self.commissions is not None else None,
            realized_pnl=(
                str(self.cash_flow - self.commissions)
                if flat and self.commissions is not None
                else None
            ),
            issues=list(self.issues),
            scope="Recorded USD strategy executions; open positions are not marked to market",
        )


def strategy_ledger(
    tag: str,
    orders: tuple[Mapping[str, Any], ...],
    executions: tuple[Mapping[str, Any], ...],
) -> StrategyLedger:
    from ..broker import money

    if not isinstance(tag, str) or not tag or len(tag) > 100:
        raise ValueError("An exact nonempty strategy tag is required")
    selected = {
        (o.get("client_id"), o["order_id"]): o
        for o in orders
        if o.get("tag") == tag and str(o.get("order_ref", "")).startswith("pyibquant:")
    }
    positions: dict[int, Decimal] = {}
    cash_flow, fees = Decimal(0), Decimal(0)
    fees_known, count = True, 0
    issues = []
    for key, order in selected.items():
        multiplier = contract_multiplier(order)
        fills = [e for e in executions if (e.get("client_id"), e.get("order_id")) == key]
        filled = Decimal(0)
        for fill in fills:
            quantity, price = money(fill.get("quantity")), money(fill.get("price"))
            sign = {"BUY": 1, "BOT": 1, "SELL": -1, "SLD": -1}.get(str(fill.get("side")))
            expected_sign = {"BUY": 1, "SELL": -1}.get(str(order.get("side")))
            if (
                quantity is None
                or quantity <= 0
                or price is None
                or price <= 0
                or sign is None
                or sign != expected_sign
                or fill.get("con_id") != order.get("con_id")
                or fill.get("currency") != "USD"
                or multiplier is None or contract_multiplier(fill) != multiplier
                or (fill.get("order_ref") and fill["order_ref"] != order.get("order_ref"))
            ):
                issues.append(
                    f"Order {key}: invalid or conflicting execution {fill.get('exec_id')}"
                )
                continue
            filled += quantity
            con_id = int(fill["con_id"])
            positions[con_id] = positions.get(con_id, Decimal(0)) + sign * quantity
            cash_flow -= sign * quantity * price * multiplier
            count += 1
            fee = money(fill.get("commission"))
            if fee is None or fill.get("fee_currency") != "USD":
                fees_known = False
            else:
                fees += fee
        if money(order.get("filled")) != filled:
            issues.append(f"Order {key}: journal executions do not match broker filled quantity")
    return StrategyLedger(
        tag,
        tuple(sorted(positions.items())),
        count,
        cash_flow,
        fees if fees_known else None,
        tuple(issues),
    )

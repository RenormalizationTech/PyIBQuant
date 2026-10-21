"""Durable USD cash ceiling, independent of broker balance/hold timing.

The local T+1 policy deliberately holds US option sales longer than IBKR's
reported T+0 availability. Calendar closures are conservative, not an exchange
session calendar. Fresh broker restrictions always remain an additional cap.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .ledger import contract_multiplier

NY = ZoneInfo("America/New_York")
TERMINAL = frozenset({"Filled", "Cancelled", "ApiCancelled", "Inactive"})
# Union of US market and banking closures, intentionally stricter than either.
# 2026 OCC memo 57897 and Federal Reserve 2026–2030 holiday schedule.
_CLOSURES = """
2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19
2026-07-03 2026-09-07 2026-10-12 2026-11-11 2026-11-26 2026-12-25
2027-01-01 2027-01-18 2027-02-15 2027-03-26 2027-05-31 2027-06-18
2027-07-05 2027-09-06 2027-10-11 2027-11-11 2027-11-25 2027-12-24
2027-12-31
"""


@dataclass(frozen=True)
class SettlementPolicy:
    """Versioned conservative US/USD STK/OPT policy; explicit bounded calendar."""

    version: str = "us-usd-conservative-t1-2026-2027-v1"
    start: date = date(2026, 1, 1)
    end: date = date(2027, 12, 31)
    holidays: tuple[date, ...] = tuple(date.fromisoformat(s) for s in _CLOSURES.split())
    equity_days: int = 1
    option_days: int = 1
    fee_allowance: Decimal = Decimal(2)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version, str) or not self.version
            or type(self.start) is not date or type(self.end) is not date
            or self.start > self.end
            or any(type(d) is not date or not self.start <= d <= self.end
                   for d in self.holidays)
            or any(type(n) is not int or n < 1 for n in (self.equity_days, self.option_days))
            or not isinstance(self.fee_allowance, Decimal)
            or not self.fee_allowance.is_finite() or self.fee_allowance <= 0
            or len(set(self.holidays)) != len(self.holidays)
        ):
            raise ValueError("Use a versioned bounded calendar and positive fee allowance")

    def settlement_date(self, trade_date: date, asset_type: str, currency: str) -> date:
        if currency != "USD" or asset_type not in {"STK", "OPT"}:
            raise ValueError("No settlement policy for this product/currency")
        if not self.start <= trade_date <= self.end:
            raise ValueError("Trade date outside settlement calendar coverage")
        days = self.equity_days if asset_type == "STK" else self.option_days
        result = trade_date
        while days:
            result += timedelta(days=1)
            if result > self.end:
                raise ValueError("Settlement date outside calendar coverage")
            if result.weekday() < 5 and result not in self.holidays:
                days -= 1
        return result

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "start": self.start.isoformat(), "end": self.end.isoformat(),
                "holidays": [d.isoformat() for d in self.holidays],
                "fee_allowance": str(self.fee_allowance)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SettlementPolicy:
        return cls(**{**value, "start": date.fromisoformat(value["start"]),
                      "end": date.fromisoformat(value["end"]),
                      "holidays": tuple(date.fromisoformat(d) for d in value["holidays"]),
                      "fee_allowance": Decimal(value["fee_allowance"])})


def execution_day(fill: Mapping[str, Any]) -> date:
    """Use broker execution time; only missing live timestamps use first receipt."""
    raw = fill.get("broker_time")
    if raw:
        parts = str(raw).split()
        if len(parts) in {2, 3} and len(parts[0]) == 8 and parts[0].isdigit():
            stamp = datetime.strptime(" ".join(parts[:2]), "%Y%m%d %H:%M:%S")
            if len(parts) != 3:
                raise ValueError("Broker execution timezone is missing")
            zone = ZoneInfo(parts[2])
            stamp = stamp.replace(tzinfo=zone)
        else:
            stamp = datetime.fromisoformat(str(raw))
            if stamp.utcoffset() is None:
                raise ValueError("Execution timestamp is not timezone aware")
    else:
        stamp = datetime.fromisoformat(fill["first_received_at"])
        if stamp.utcoffset() is None:
            raise ValueError("Execution receipt is not timezone aware")
    return stamp.astimezone(NY).date()


def fingerprint(fill: Mapping[str, Any]) -> dict[str, Any]:
    return {k: fill.get(k) for k in (
        "client_id", "order_id", "con_id", "side", "quantity", "price", "currency",
        "asset_type", "multiplier", "broker_time", "commission", "fee_currency",
    )}


def cash_ledger(
    baseline: Mapping[str, Any], orders: tuple[Mapping[str, Any], ...],
    executions: tuple[Mapping[str, Any], ...], *, at: datetime,
) -> dict[str, Any]:
    """Recompute from durable facts; never subtract a local hold from broker funds."""
    from ..broker import money

    issues: list[str] = []
    if baseline.get("version") != 1:
        raise ValueError("Unsupported funding baseline version")
    policy = SettlementPolicy.from_dict(baseline["settlement_policy"])
    day = at.astimezone(NY).date()
    initial = money(baseline["cash"])
    if initial is None or initial < 0:
        raise ValueError("Invalid funding baseline")
    if not policy.start <= day <= policy.end:
        issues.append("Current date outside settlement calendar coverage")
    if at < datetime.fromisoformat(baseline["at"]):
        issues.append("Funding clock precedes its durable baseline")
    cash, reserved, fee_hold, unsettled = initial, Decimal(0), Decimal(0), Decimal(0)
    obligations: list[dict[str, Any]] = []
    excluded = baseline["executions"]
    if not isinstance(excluded, Mapping):
        raise ValueError("Invalid funding baseline execution coverage")
    selected = {(o.get("client_id"), o["order_id"]): o for o in orders
                if str(o.get("order_ref", "")).startswith("pyibquant:")}
    fills = {f["exec_id"]: f for f in executions}
    for eid, original in excluded.items():
        if eid not in fills or fingerprint(fills[eid]) != original:
            issues.append(f"Baseline execution changed: {eid}")
    for key, order in selected.items():
        quantity, reported = money(order.get("quantity")), money(order.get("filled"))
        multiplier, price = contract_multiplier(order), money(order.get("limit_price"))
        side = order.get("side")
        parts = [f for f in executions if (f.get("client_id"), f.get("order_id")) == key]
        filled, fees, missing_fees = Decimal(0), Decimal(0), False
        for fill in parts:
            q, p = money(fill.get("quantity")), money(fill.get("price"))
            if (
                q is None or q <= 0 or p is None or p <= 0 or multiplier is None
                or fill.get("con_id") != order.get("con_id")
                or fill.get("currency") != "USD" or contract_multiplier(fill) != multiplier
                or fill.get("side") not in ({"BOT", "BUY"} if side == "BUY" else {"SLD", "SELL"})
            ):
                issues.append(f"Invalid funding execution: {fill['exec_id']}")
                continue
            filled += q
            if fill["exec_id"] in excluded:
                continue
            commission = money(fill.get("commission"))
            if commission is None:
                missing_fees = True
            elif fill.get("fee_currency") != "USD":
                issues.append(f"Non-USD execution fee: {fill['exec_id']}")
            else:
                # Do not spend rebates before a broker cash reconciliation.
                fees += max(Decimal(0), commission)
            gross = q * p * multiplier
            if side == "BUY":
                cash -= gross
            else:
                try:
                    trade_day = execution_day(fill)
                    settle = policy.settlement_date(trade_day, order.get("asset_type", "STK"),
                                                    order.get("currency", "USD"))
                    if trade_day > day:
                        raise ValueError("Future execution date")
                    released = settle <= day
                    if released:
                        cash += gross
                    else:
                        unsettled += gross
                    obligations.append(dict(exec_id=fill["exec_id"], currency="USD",
                                            gross=str(gross), trade_date=trade_day.isoformat(),
                                            settlement_date=settle.isoformat(), released=released))
                except (ValueError, KeyError) as exc:
                    issues.append(f"Unknown sale settlement {fill['exec_id']}: {exc}")
        if quantity is None or reported is None or filled != reported or filled > quantity:
            issues.append(f"Order {key}: funding executions do not match filled quantity")
        cash -= fees
        if missing_fees:
            issues.append(f"Order {key}: execution fees are not confirmed")
        active = order.get("status") not in TERMINAL
        if side not in {"BUY", "SELL"}:
            issues.append(f"Order {key}: unknown side")
        allowance = money(order.get("fee_allowance", str(policy.fee_allowance)))
        if allowance is None or allowance <= 0:
            issues.append(f"Order {key}: invalid fee allowance")
            allowance = policy.fee_allowance
        hold = max(Decimal(0), allowance - fees) if active or missing_fees else Decimal(0)
        fee_hold += hold
        if active and side == "BUY":
            if quantity is None or price is None or price <= 0 or multiplier is None:
                issues.append(f"Order {key}: unknown buy reservation")
            else:
                reserved += max(Decimal(0), quantity - filled) * price * multiplier + hold
    cash -= fee_hold
    return dict(cash_ceiling=str(max(Decimal(0), cash)), pending_buy_estimate=str(reserved),
                fee_reserve=str(fee_hold), local_unsettled=str(unsettled),
                settlement_obligations=obligations, settlement_policy=policy.to_dict(),
                funding_issues=issues, baseline_at=baseline["at"],
                coverage="Recorded fills after baseline; external flows remain broker-capped")


def baseline_payload(cash: Decimal, executions: tuple[Mapping[str, Any], ...],
                     policy: SettlementPolicy, *, at: datetime | None = None) -> dict[str, Any]:
    return dict(version=1, cash=str(cash), at=(at or datetime.now(UTC)).isoformat(),
                executions={f["exec_id"]: fingerprint(f) for f in executions},
                settlement_policy=policy.to_dict())

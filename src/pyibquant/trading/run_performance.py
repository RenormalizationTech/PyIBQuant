"""USD long-equity/option accounting from executions and observed portfolio marks."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .ledger import contract_multiplier, strategy_ledger


def valuation(
    tag: str,
    orders: tuple[Mapping[str, Any], ...],
    executions: tuple[Mapping[str, Any], ...],
    marks: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    from ..broker import money

    ledger = strategy_ledger(tag, orders, executions)
    keys = {(o.get("client_id"), o["order_id"]) for o in orders if o.get("tag") == tag}
    fills = [e for e in executions if (e.get("client_id"), e.get("order_id")) in keys]
    lots: dict[int, deque[list[Any]]] = {}
    multipliers: dict[int, Decimal] = {}
    realized, realized_fees = Decimal(0), Decimal(0)
    realized_known = True
    issues = list(ledger.issues)
    for e in fills:
        q, price = money(e.get("quantity")), money(e.get("price"))
        if q is None or q <= 0 or price is None or price <= 0 or "con_id" not in e:
            continue  # Ledger validation supplies the issue; no fabricated zero costs.
        con_id = int(e["con_id"])
        multiplier = contract_multiplier(e)
        if multiplier is None:
            continue  # Ledger supplies the invalid-multiplier issue.
        multipliers[con_id] = multiplier
        price *= multiplier  # FIFO prices are dollars per contract, not quoted premium units.
        fee = money(e.get("commission")) if e.get("fee_currency") == "USD" else None
        queue = lots.setdefault(con_id, deque())
        if e.get("side") in {"BOT", "BUY"}:
            queue.append([q, price, fee / q if fee is not None else None])
        elif e.get("side") in {"SLD", "SELL"}:
            remaining = q
            while remaining and queue:
                lot = queue[0]
                used = min(remaining, lot[0])
                realized += used * (price - lot[1])
                if lot[2] is None or fee is None:
                    realized_known = False
                else:
                    realized_fees += used * (lot[2] + fee / q)
                lot[0] -= used
                remaining -= used
                if lot[0] == 0:
                    queue.popleft()
            if remaining:
                issues.append("Sell precedes sufficient owned buys; FIFO attribution unavailable")
    exposure, unrealized, entry_fees = Decimal(0), Decimal(0), Decimal(0)
    marks_known, entry_fees_known = True, True
    holdings = []
    for con_id, queue in lots.items():
        quantity = sum((lot[0] for lot in queue), Decimal(0))
        if quantity == 0:
            continue
        mark = marks.get(con_id, {})
        price = money(mark.get("price"))
        stamp = mark.get("time")
        if price is None or price <= 0 or not stamp:
            marks_known = False
        else:
            exposure += quantity * price * multipliers[con_id]
            unrealized += sum(
                (q * (price * multipliers[con_id] - cost) for q, cost, _ in queue), Decimal(0)
            )
        for q, _, fee in queue:
            if fee is None:
                entry_fees_known = False
            else:
                entry_fees += q * fee
        holdings.append(
            dict(
                con_id=con_id,
                quantity=str(quantity),
                mark=str(price) if price is not None else None,
                mark_time=stamp,
            )
        )
    complete = not issues
    net = (
        ledger.cash_flow + exposure - ledger.commissions
        if complete and marks_known and ledger.commissions is not None
        else None
    )
    return dict(
        complete=complete,
        issues=issues,
        positions=holdings,
        order_count=len(keys),
        execution_count=ledger.execution_count,
        cash_flow=str(ledger.cash_flow),
        commissions=number(ledger.commissions),
        gross_realized=number(realized if complete else None),
        realized_pnl=number(realized - realized_fees if complete and realized_known else None),
        unrealized_pnl=number(
            unrealized - entry_fees if complete and marks_known and entry_fees_known else None
        ),
        net_pnl=number(net),
        gross_exposure=number(exposure if complete and marks_known else None),
        mark_status="last observed portfolio marks"
        if holdings and marks_known
        else ("missing marks" if holdings else "flat; no marks required"),
    )


def number(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def run_reports(events: list[dict[str, Any]], snapshot: Any) -> list[dict[str, Any]]:
    """Reconstruct each run without assigning account-wide P&L or manual trades to it."""
    from ..broker import money

    runs: dict[str, dict[str, Any]] = {}
    first_fills: dict[str, int] = {}
    for e in events:
        p, kind = e["payload"], e["kind"]
        if kind == "execution":
            first_fills.setdefault(p["exec_id"], e["sequence"])
        run_id = p.get("run_id")
        if not run_id:
            continue
        if kind in {"runner_start", "runner_checkpoint"} and run_id not in runs:
            runs[run_id] = dict(
                run_id=run_id,
                symbol=p.get("symbol"),
                started_at=e["received_at"],
                status="unknown",
                config={},
                points=[],
            )
        if run_id not in runs:
            continue
        row = runs[run_id]
        if kind == "runner_start":
            row.update(status="running", config=p.copy())
        elif kind == "runner_checkpoint":
            row.update(
                config=p.get("config", {}),
                checkpoint_version=p.get("version"),
                status=p.get("status", "unknown"),
                reason=p.get("reason", ""),
            )
        elif kind in {"runner_pause", "runner_stop", "runner_resume"}:
            row.update(
                status={
                    "runner_pause": "paused",
                    "runner_stop": "stopped",
                    "runner_resume": "running",
                }[kind],
                reason=p.get("reason", ""),
            )
            if kind == "runner_pause":
                row["last_pause_reason"] = p.get("reason", "")
        row["updated_at"] = e["received_at"]
    ordered_fills = tuple(
        sorted(snapshot.executions, key=lambda e: first_fills.get(e["exec_id"], 0))
    )
    for tag, run in runs.items():
        orders = tuple(o for o in snapshot.orders if o.get("tag") == tag)
        keys = {(o.get("client_id"), o["order_id"]) for o in orders}
        fills = tuple(e for e in ordered_fills if (e.get("client_id"), e.get("order_id")) in keys)
        fill_ids = {e["exec_id"] for e in fills}
        replay: dict[str, dict[str, Any]] = {}
        fees: dict[str, dict[str, Any]] = {}
        marks: dict[int, dict[str, Any]] = {}
        points = []
        gap = True
        peak, drawdown = Decimal(0), Decimal(0)
        for e in events:
            p, kind = e["payload"], e["kind"]
            if kind in {"closed", "disconnected"} or (kind == "error" and p.get("fatal")):
                gap = True
            changed = False
            if kind == "portfolio" and p.get("currency") == "USD":
                mark = dict(price=p.get("market_price"), time=e["received_at"])
                changed = marks.get(p["con_id"]) != mark and bool(replay)
                marks[p["con_id"]] = mark
            elif kind == "fee" and p.get("exec_id") in fill_ids:
                changed = fees.get(p["exec_id"]) != p and p["exec_id"] in replay
                fees[p["exec_id"]] = p
            elif kind == "execution" and p.get("exec_id") in fill_ids:
                changed = replay.get(p["exec_id"]) != p
                replay[p["exec_id"]] = p
            if not changed:
                continue
            history = tuple({**f, **fees.get(key, {})} for key, f in replay.items())
            # Compare each historical point with its observed cumulative fill, not
            # the final order total (which would leak later fills into earlier data).
            past_orders = []
            for order in orders:
                key = (order.get("client_id"), order["order_id"])
                observed = [f for f in history if (f.get("client_id"), f.get("order_id")) == key]
                total = sum((money(f.get("quantity")) or Decimal(0) for f in observed), Decimal(0))
                past_orders.append({**order, "filled": str(total)})
            value = valuation(tag, tuple(past_orders), history, marks)
            net = money(value["net_pnl"])
            if net is not None:
                peak = max(peak, net)
                drawdown = max(drawdown, peak - net)
            points.append(
                dict(
                    time=e["received_at"],
                    session=e["session"],
                    gap=gap,
                    net=value["net_pnl"],
                    realized=value["realized_pnl"],
                    exposure=value["gross_exposure"],
                    drawdown=str(drawdown),
                )
            )
            gap = False
        for position in snapshot.positions:
            if position.get("currency") == "USD" and "market_price" in position:
                marks[position["con_id"]] = dict(
                    price=position["market_price"],
                    time=position.get("mark_received_at", position.get("received_at")),
                )
        run.update(valuation(tag, orders, fills, marks))
        run["mode"] = "observation" if run["config"].get("dry_run", True) else "paper execution"
        run.update(
            points=points,
            observed_drawdown=str(drawdown),
            orders=[{k: v for k, v in o.items() if k != "account"} for o in orders],
            executions=[{k: v for k, v in f.items() if k != "account"} for f in fills],
        )
        # A recovered journal is not evidence that the process is still running.
        if (
            snapshot.status in {"offline", "closed", "disconnected", "failed"}
            and run["status"] == "running"
        ):
            run["status"] = "interrupted/unverified"
        run["report_time"] = datetime.now(UTC).isoformat()
    return list(runs.values())

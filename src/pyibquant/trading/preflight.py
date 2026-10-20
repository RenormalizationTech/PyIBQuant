"""Read-only operational checks; a passed preflight never authorizes transmission."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from importlib import import_module
from typing import Any

from ..broker import PaperBroker, mask_account_data, money
from .profile import PaperProfile


def check_profile(profile: PaperProfile, *, connect: bool = False) -> dict[str, Any]:
    checks = []
    checks.append(dict(name="Configuration", status="pass", detail="Valid bounded paper profile"))
    try:
        sdk = import_module("ibapi")
        version = sdk.get_version_string()
        supported = tuple(int(v) for v in version.split(".")[:2]) >= (10, 33)
        checks.append(
            dict(name="Official IBKR SDK", status="pass" if supported else "fail", detail=version)
        )
    except (ImportError, AttributeError, ValueError) as exc:
        checks.append(dict(name="Official IBKR SDK", status="fail", detail=str(exc)))
    parent = profile.journal.parent
    while not parent.exists():
        parent = parent.parent
    writable = (
        parent.is_dir()
        and os.access(parent, os.W_OK)
        and (
            not profile.journal.exists()
            or (profile.journal.is_file() and os.access(profile.journal, os.W_OK))
        )
    )
    checks.append(
        dict(
            name="Journal location",
            status="pass" if writable else "fail",
            detail=str(profile.journal),
        )
    )
    report: dict[str, Any] = dict(
        checked_at=datetime.now(UTC).isoformat(),
        profile=profile.to_dict(),
        checks=checks,
        connected=False,
        order_transmission=False,
        deferred=[
            "Regular session and fresh live bars/bid/ask at launch",
            "Broker order permission and normal bounded-session completion",
            "Resting-order cancellation and process restart with the paper API",
        ],
        stop_policy=(
            "Cancel pending run orders; keep filled holdings until explicit exit/flatten"
            if profile.cancel_on_stop
            else "No automatic cancellation or flatten on stop"
        ),
    )
    if connect and all(c["status"] == "pass" for c in checks):
        try:
            with PaperBroker.ibkr(**profile.broker_options(preflight=True)) as broker:
                report["connected"] = True
                recovery = broker.reconcile()
                report["account"] = broker.snapshot().to_dict()["account"]
                checks.append(
                    dict(
                        name="Account download",
                        status="pass" if recovery.snapshot.complete else "fail",
                        detail="Selected paper account; read-only connection",
                    )
                )
                checks.append(
                    dict(
                        name="Order reconciliation",
                        status="pass" if recovery.clear else "fail",
                        detail=f"{len(recovery.working_orders)} tracked working, "
                        f"{len(recovery.missing_orders)} missing, "
                        f"{len(recovery.foreign_orders)} foreign working",
                    )
                )
                funding = broker.funding()
                report["funding"] = funding
                checks.append(
                    dict(
                        name="USD settled-cash funding",
                        status="pass" if (money(funding["usable"]) or 0) > 0 else "fail",
                        detail="; ".join(funding["blocked_reasons"])
                        or "Positive broker-reported cash budget; rechecked at each order",
                    )
                )
                positions = [
                    dict(p)
                    for p in recovery.snapshot.positions
                    if p.get("symbol") == profile.symbol and money(p.get("quantity")) != 0
                ]
                report["selected_positions"] = [
                    {k: v for k, v in p.items() if k != "account"} for p in positions
                ]
                checks.append(
                    dict(
                        name="New-run starting holdings",
                        status="pass" if not positions else "fail",
                        detail="Selected symbol is flat"
                        if not positions
                        else "Existing holdings require explicit restore or close",
                    )
                )
                contract = broker._adapter.resolve(profile.symbol)
                report["contract_id"] = contract.conId
                checks.append(
                    dict(
                        name="Contract",
                        status="pass",
                        detail=f"{profile.symbol} resolved as a USD equity",
                    )
                )
                snapshot = broker.refresh_pnl(renew=False)
                checks.append(
                    dict(
                        name="Validated account P&L",
                        status="pass" if snapshot.pnl.get("validated") else "fail",
                        detail=(
                            "Same-day validated P&L confirmed by fresh unchanged flat-account data"
                            if snapshot.pnl.get("risk_source") == "flat_account_reconciliation"
                            else "New subscription sample validated without changing risk limits"
                        ),
                    )
                )
        except Exception as exc:
            checks.append(
                dict(
                    name="Read-only API preflight",
                    status="fail",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    elif not connect:
        report["deferred"].insert(
            0, "Account connectivity, funds, holdings and contract resolution (--connect)"
        )
    report["local_ready"] = all(c["status"] == "pass" for c in checks)
    report["ready_to_trade"] = False
    selected = report.get("account")
    # The broker output is already masked; use the configured account for remaining
    # configuration/error text, and never persist credentials or enable trading.
    if profile.account:
        report = mask_account_data(report, profile.account)
    if selected:
        report["account"] = selected
    return report

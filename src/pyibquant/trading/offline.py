"""Offline report replay reads the source journal without a broker connection."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from ..broker import AccountSnapshot, BrokerError, PaperBroker
from .journal import Journal


def recover_flat_reference(events: list[dict[str, Any]], account: str) -> dict[str, Any] | None:
    """Recover evidence from a legacy validated sample, never current broker state."""
    validations = [e for e in events if e["kind"] == "pnl_validated"]
    if not validations:
        return None
    last = validations[-1]
    stamp = datetime.fromisoformat(last["received_at"])
    current = datetime.now(UTC)
    if (
        stamp > current
        or stamp.astimezone(ZoneInfo("America/New_York")).date()
        != current.astimezone(ZoneInfo("America/New_York")).date()
    ):
        return None
    session = last["session"]
    adapter = SimpleNamespace(client_id=1, close=lambda: None)
    with TemporaryDirectory(prefix="pyibquant-risk-replay-") as temporary:
        with PaperBroker(adapter, Path(temporary) / "replay.sqlite3", account=account) as replay:
            for event in events:
                if event["sequence"] > last["sequence"]:
                    break
                if event["session"] == session or event["kind"] in {
                    "intent", "order", "order_status", "execution", "fee", "send_unknown"
                }:
                    replay._apply(event["kind"], event["payload"], event["received_at"])
            reference = replay._pnl_reference
            if reference is None:
                return None
            pnl = dict(replay._validated_pnl)
            age = (stamp - datetime.fromisoformat(pnl["received_at"])).total_seconds()
            if not 0 <= age <= 15:
                return None
            return dict(
                version=1,
                reference=replay._risk_fingerprint(reference),
                pnl=pnl,
                reference_session=session,
                recovered_validation_sequence=last["sequence"],
            )


def load_account(
    path: str | Path, *, account: str | None = None
) -> tuple[list[dict[str, Any]], AccountSnapshot]:
    source = Journal(path, readonly=True)
    try:
        events = source.events(account)
    finally:
        source.close()
    accounts = {e["account"] for e in events}
    if len(accounts) != 1:
        raise BrokerError("Select one account with journal history for an offline report")
    selected = next(iter(accounts))
    clients = [e["payload"].get("client_id", 1) for e in events if e["kind"] == "session"]
    adapter = SimpleNamespace(client_id=clients[-1] if clients else 1, close=lambda: None)
    # Use the same state reducer as the broker. The disposable journal/worker never
    # touches the source, opens a socket or has any order transport methods.
    with TemporaryDirectory(prefix="pyibquant-report-") as temporary:
        with PaperBroker(adapter, Path(temporary) / "replay.sqlite3", account=selected) as broker:
            with broker._lock:
                for event in events:
                    broker._apply(event["kind"], event["payload"], event["received_at"])
                broker.session = events[-1]["session"]
                broker._sequence = events[-1]["sequence"]
                broker._status = "offline"
                broker._barriers.clear()
                snapshot = broker.snapshot()
    return events, snapshot

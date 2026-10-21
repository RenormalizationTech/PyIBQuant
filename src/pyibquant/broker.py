"""Paper broker API. Broker state and fills are separate from offline simulation."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path
from queue import Queue
from threading import Condition, RLock, Thread
from time import monotonic
from types import MappingProxyType, TracebackType
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .errors import PyIBQuantError
from .quotes import Option, Quote
from .trading.funding import SettlementPolicy, baseline_payload, cash_ledger
from .trading.journal import Journal
from .trading.ledger import StrategyLedger, contract_multiplier, strategy_ledger


class BrokerError(PyIBQuantError):
    """Broker command, reconciliation or funding check failed."""


TERMINAL_ORDER_STATES = frozenset({"Filled", "Cancelled", "ApiCancelled", "Inactive"})
PNL_SETTLE_SECONDS = 2.0
FUNDING_EVENTS = frozenset({
    "intent", "order", "order_status", "execution", "fee", "send_unknown", "funding_baseline",
})


class OrderWaitError(BrokerError):
    """A wait ended without confirmation; last_order is evidence, not permission to retry."""

    def __init__(self, message: str, last_order: Mapping[str, Any] | None) -> None:
        super().__init__(message)
        self.last_order = MappingProxyType(dict(last_order)) if last_order is not None else None


@dataclass(frozen=True)
class Reconciliation:
    """Fresh download plus durable unresolved identities; not complete historical coverage."""

    snapshot: AccountSnapshot
    working_orders: tuple[Mapping[str, Any], ...]
    missing_orders: tuple[Mapping[str, Any], ...]
    foreign_orders: tuple[Mapping[str, Any], ...]
    completed_orders_checked: bool = False

    @property
    def clear(self) -> bool:
        return self.snapshot.complete and not self.working_orders and not self.foreign_orders


def money(value: Any) -> Decimal | None:
    """Missing/unset/invalid broker numbers never become spendable zeroes."""
    try:
        result = Decimal(str(value))
        if (
            not result.is_finite()
            or abs(result) >= Decimal("1e100")
            or result == Decimal(2**127 - 1)
        ):
            return None
        return result
    except (InvalidOperation, ValueError, TypeError):
        return None


def settled_schedule(value: str, *, on_date: date | None = None) -> Decimal | None:
    """Read IBKR date:balance entries, selecting today's balance, never future funds."""
    balances: dict[date, Decimal] = {}
    for entry in value.split(";"):
        parts = entry.split(":")
        if len(parts) != 2 or len(parts[0]) != 8 or not parts[0].isdigit():
            return None
        try:
            day = datetime.strptime(parts[0], "%Y%m%d").date()
        except ValueError:
            return None
        amount = money(parts[1])
        if amount is None or day in balances:
            return None
        balances[day] = amount
    expected = on_date or datetime.now(ZoneInfo("America/New_York")).date()
    return balances.get(expected)


def now() -> str:
    return datetime.now(UTC).isoformat()


def mask_account_data(value: Any, account: str) -> Any:
    """Redact identifiers in metadata and provider text as well as account fields."""
    if isinstance(value, str):
        return value.replace(account, account[:2] + "***" + account[-3:])
    if isinstance(value, dict):
        return {k: mask_account_data(v, account) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_account_data(v, account) for v in value]
    return value


@dataclass(frozen=True)
class AccountValue:
    tag: str
    currency: str
    value: str
    received_at: str
    source: str

    @property
    def number(self) -> Decimal | None:
        return money(self.value)


@dataclass(frozen=True)
class AccountSnapshot:
    account: str
    session: str
    sequence: int
    status: str
    complete: bool
    values: tuple[AccountValue, ...]
    positions: tuple[Mapping[str, Any], ...]
    orders: tuple[Mapping[str, Any], ...]
    executions: tuple[Mapping[str, Any], ...]
    pnl: Mapping[str, Any]
    errors: tuple[str, ...]

    def value(self, tag: str, currency: str = "") -> AccountValue | None:
        return next((v for v in self.values if v.tag == tag and v.currency == currency), None)

    def to_dict(self, *, mask_account: bool = True) -> dict[str, Any]:
        def copy_rows(rows: tuple[Mapping[str, Any], ...]) -> list[dict[str, Any]]:
            return [
                {k: v for k, v in r.items() if not mask_account or k != "account"} for r in rows
            ]

        result = dict(
            account=self.account[:2] + "***" + self.account[-3:] if mask_account else self.account,
            session=self.session,
            sequence=self.sequence,
            status=self.status,
            complete=self.complete,
            values=[asdict(v) for v in self.values],
            positions=copy_rows(self.positions),
            orders=copy_rows(self.orders),
            executions=copy_rows(self.executions),
            pnl=dict(self.pnl),
            errors=list(self.errors),
        )
        return mask_account_data(result, self.account) if mask_account else result


class PaperBroker:
    """One API account and durable journal; read-only unless explicitly enabled.

    paper_confirmed is the caller's assertion of the selected paper session, not
    inferred proof from a port. Live accounts are rejected. Default funding policy
    is no borrowing even when the paper account itself reports a margin type.
    """

    def __init__(
        self,
        adapter: Any,
        journal: str | Path,
        *,
        account: str,
        readonly: bool = True,
        paper_confirmed: bool = False,
        max_order_value: float = 500,
        max_quantity: int = 1,
        settlement_policy: SettlementPolicy | None = None,
    ) -> None:
        if not isinstance(readonly, bool) or not isinstance(paper_confirmed, bool):
            raise ValueError("readonly and paper_confirmed must be booleans")
        if not account.startswith("DU") or not account[2:].isalnum():
            raise BrokerError("PaperBroker requires a selected DU paper account")
        if not readonly and not paper_confirmed:
            raise BrokerError("Order mode requires explicit paper-session confirmation")
        cap = money(max_order_value)
        if cap is None or cap <= 0 or isinstance(max_order_value, bool):
            raise ValueError("max_order_value must be positive and finite")
        if isinstance(max_quantity, bool) or not isinstance(max_quantity, int) or max_quantity < 1:
            raise ValueError("max_quantity must be a positive whole number")
        self.settlement_policy = settlement_policy or SettlementPolicy()
        self._funding_baseline: dict[str, Any] | None = None
        self._funding_conflicts: set[str] = set()
        self._adapter = adapter
        self.account, self.readonly = account, readonly
        self.max_order_value, self.max_quantity = cap, max_quantity
        self.session = uuid4().hex
        self.journal = Journal(journal)
        self._lock = RLock()
        self._changed = Condition(self._lock)
        self._commands = RLock()
        self._queue: Queue[tuple[str, dict[str, Any], str] | None] = Queue()
        self._values: dict[tuple[str, str], AccountValue] = {}
        self._positions: dict[int, dict[str, Any]] = {}
        self._orders: dict[str, dict[str, Any]] = {}
        self._observed_orders: set[str] = set()
        self._executions: dict[str, dict[str, Any]] = {}
        self._fees: dict[str, dict[str, Any]] = {}
        self._pnl: dict[str, Any] = {}
        self._validated_pnl: dict[str, Any] = {}
        self._pnl_reference: tuple[Any, ...] | None = None
        self._pnl_candidate_reference: tuple[Any, ...] | None = None
        self._prior_flat_risk: dict[str, Any] | None = None
        self._barriers: set[str] = set()
        self._errors: list[str] = []
        self._status, self._sequence = "synchronizing", 0
        self._fatal: str | None = None
        self._closed = False
        self._halted = False
        self._last_callback = monotonic()
        # Replay only identities/logs, never reuse old account values as current funds.
        history = self.journal.events(account)
        self._applied_sequences = {e["sequence"] for e in history}
        self._session_clients = {
            e["session"]: e["payload"]["client_id"] for e in history
            if e["kind"] == "session" and type(e["payload"].get("client_id")) is int
        }
        for event in history:
            if event["kind"] == "pnl_flat_reference":
                self._prior_flat_risk = event["payload"]
            if event["kind"] in {
                "intent",
                "order",
                "order_status",
                "execution",
                "fee",
                "send_unknown",
                "funding_baseline",
            }:
                self._apply(
                    event["kind"], event["payload"], event["received_at"],
                    source_session=event["session"],
                )
        if self._funding_baseline is not None:
            try:
                frozen_policy = SettlementPolicy.from_dict(
                    self._funding_baseline["settlement_policy"]
                )
                if settlement_policy is not None and frozen_policy != settlement_policy:
                    raise BrokerError("Settlement policy differs from durable funding baseline")
            except (KeyError, ValueError, TypeError, InvalidOperation, BrokerError) as exc:
                self.journal.close()
                raise BrokerError(f"Cannot restore funding policy: {exc}") from exc
            self.settlement_policy = frozen_policy
        if self._prior_flat_risk is None and any(e["kind"] == "pnl_validated" for e in history):
            from .trading.offline import recover_flat_reference

            self._prior_flat_risk = recover_flat_reference(history, account)
        prior_ids = [
            int(o["order_id"])
            for o in self._orders.values()
            if o.get("client_id") == adapter.client_id and int(o["order_id"]) >= 0
        ]
        if prior_ids and hasattr(adapter, "seed_order_id"):
            adapter.seed_order_id(max(prior_ids) + 1)
        self._observed_orders.clear()  # Replay is not a fresh broker observation.
        self._worker = Thread(target=self._process, daemon=True, name="pyibquant-broker-events")
        self._worker.start()
        adapter.sink = self.enqueue
        adapter.prepare = self._begin_refresh
        self._record(
            "session",
            dict(readonly=readonly, funding_policy="no_borrowing", client_id=adapter.client_id),
        )

    @classmethod
    def ibkr(
        cls,
        *,
        journal: str | Path = "charts/paper/account.sqlite3",
        account: str | None = None,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 272,
        timeout: float = 20,
        readonly: bool = True,
        paper_confirmed: bool = False,
        max_order_value: float = 500,
        max_quantity: int = 1,
        settlement_policy: SettlementPolicy | None = None,
    ) -> PaperBroker:
        from .trading.ibkr import BrokerAdapter

        adapter = BrokerAdapter(host, port, client_id, timeout)
        broker = None
        try:
            accounts = adapter.open()
            if account is None:
                if len(accounts) != 1:
                    raise BrokerError("Select one account explicitly; discovery is ambiguous")
                account = accounts[0]
            if account not in accounts:
                raise BrokerError("Selected account is not in managedAccounts")
            broker = cls(
                adapter,
                journal,
                account=account,
                readonly=readonly,
                paper_confirmed=paper_confirmed,
                max_order_value=max_order_value,
                max_quantity=max_quantity,
                settlement_policy=settlement_policy,
            )
            adapter.subscribe(account)
            broker.wait_ready(timeout)
            return broker
        except BaseException:
            if broker is not None:
                broker.close()
            else:
                adapter.close()
            raise

    def enqueue(self, kind: str, payload: dict[str, Any]) -> None:
        if payload.get("account", self.account) != self.account:
            return
        if not self._closed:
            self._queue.put((kind, payload, now()))

    def _record(self, kind: str, payload: dict[str, Any], stamp: str | None = None) -> None:
        with self._changed:
            stamp = stamp or now()
            sequence = self.journal.append(self.session, self.account, stamp, kind, payload)
            self._apply(kind, payload, stamp)
            self._sequence = sequence
            self._applied_sequences.add(sequence)
            self._changed.notify_all()

    def _process(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                kind, payload, stamp = item
                self._record(kind, payload, stamp)
            except Exception as exc:
                with self._changed:
                    self._fatal = f"Account journal failed: {type(exc).__name__}"
                    self._status = "failed"
                    self._changed.notify_all()
            finally:
                self._queue.task_done()

    def _apply(
        self, kind: str, p: dict[str, Any], stamp: str, *, source_session: str | None = None
    ) -> None:
        if p.get("account", self.account) != self.account:
            return
        self._last_callback = monotonic()
        if kind == "session":
            if type(p.get("client_id")) is int:
                self._session_clients[source_session or self.session] = p["client_id"]
        elif kind == "funding_baseline":
            self._funding_baseline = dict(p)
        elif kind == "value":
            if (
                p["tag"] == "NetLiquidation"
                and p.get("source") == "account_summary"
                and p["currency"] not in {"", "BASE"}
            ):
                # Currency is subscription metadata, not a fresh cash observation.
                self._values["BaseCurrency", ""] = AccountValue(
                    "BaseCurrency", "", p["currency"], stamp, "account_summary_metadata"
                )
            self._values[p["tag"], p["currency"]] = AccountValue(
                p["tag"],
                p["currency"],
                str(p["value"]),
                stamp,
                "account_summary_metadata"
                if p["tag"] == "AccountType"
                else p.get("source", "account_updates"),
            )
        elif kind in {"position", "portfolio"}:
            self._positions[p["con_id"]] = {
                **self._positions.get(p["con_id"], {}),
                **p,
                "received_at": stamp,
            }
            if kind == "portfolio":
                self._positions[p["con_id"]]["mark_received_at"] = stamp
        elif kind == "pnl":
            unrealized = money(p.get("unrealized"))
            self._pnl_candidate_reference = (
                self._flat_risk_reference(unrealized=unrealized)
                if unrealized is not None
                else None
            )
            same_generation = p.get("request_id") == self._pnl.get("request_id")
            samples = self._pnl.get("valid_samples", 0) if same_generation else 0
            validated = self._pnl.get("validated", False) if same_generation else False
            self._pnl = {
                **p,
                "received_at": stamp,
                "valid_samples": samples + int(money(p.get("daily")) is not None),
                "validated": validated,
            }
            if validated and money(p.get("daily")) is not None:
                if any(
                    money(p.get(k)) != money(self._validated_pnl.get(k))
                    for k in ("daily", "unrealized", "realized")
                ):
                    self._pnl_reference = None
                self._validated_pnl = dict(self._pnl)
        elif kind == "pnl_validated":
            if p.get("request_id") == self._pnl.get("request_id"):
                self._pnl["validated"] = True
                self._validated_pnl = dict(self._pnl)
                current_reference = self._flat_risk_reference()
                self._pnl_reference = (
                    current_reference
                    if current_reference == self._pnl_candidate_reference
                    else None
                )
        elif kind in {"intent", "order", "order_status", "send_unknown"}:
            if kind == "send_unknown" and "client_id" not in p:
                origin = self._session_clients.get(source_session or self.session)
                if origin is None:
                    raise BrokerError("Unattributed send outcome: source-session client ID missing")
                p = {**p, "client_id": origin}
            key = f"{p.get('client_id', self._adapter.client_id)}:{p['order_id']}"
            # Status callbacks lack an account. Only attach them after an account-bound
            # openOrder or this client's persisted intent establishes the identity.
            if kind == "order_status" and key not in self._orders:
                return
            old = self._orders.get(key, {})
            updated = {**old, **p, "received_at": stamp}
            # Late Submitted must not erase confirmed terminal state or reduce fills.
            if old.get("status") in {"Filled", "Cancelled", "ApiCancelled"} and p.get(
                "status"
            ) not in {"Filled", "Cancelled", "ApiCancelled"}:
                updated["status"] = old["status"]
            if money(old.get("filled")) is not None and money(p.get("filled")) is not None:
                updated["filled"] = str(max(Decimal(old["filled"]), Decimal(p["filled"])))
            if (
                money(updated.get("quantity")) is not None
                and money(updated.get("filled")) is not None
            ):
                if Decimal(updated["filled"]) >= Decimal(updated["quantity"]):
                    updated["status"] = "Filled"
                    updated["remaining"] = "0"
            updated_price = money(updated.get("average_fill_price"))
            if updated_price is None or updated_price <= 0:
                old_price = money(old.get("average_fill_price"))
                updated["average_fill_price"] = (
                    str(old_price) if old_price is not None and old_price > 0 else None
                )
            self._orders[key] = updated
            if kind == "order":
                self._observed_orders.add(key)
        elif kind == "execution":
            old_fill = self._executions.get(p["exec_id"])
            if old_fill is not None and any(old_fill.get(k) != p.get(k) for k in (
                "client_id", "order_id", "con_id", "quantity", "price", "side",
                "currency", "asset_type", "multiplier", "broker_time",
            )):
                self._funding_conflicts.add(f"Conflicting execution revision: {p['exec_id']}")
            self._executions[p["exec_id"]] = {
                **p,
                **self._fees.get(p["exec_id"], {}),
                "first_received_at": old_fill["first_received_at"] if old_fill else stamp,
                "received_at": stamp,
            }
            order_key = f"{p['client_id']}:{p['order_id']}"
            self._observed_orders.add(order_key)
            order = self._orders.get(order_key)
            cumulative = money(p.get("cumulative_quantity"))
            if order is not None and cumulative is not None:
                order["filled"] = str(max(money(order.get("filled")) or Decimal(0), cumulative))
                total = money(order.get("quantity"))
                if total is not None:
                    order["remaining"] = str(max(Decimal(0), total - Decimal(order["filled"])))
                    if Decimal(order["filled"]) >= total:
                        order["status"] = "Filled"
                average = money(p.get("average_fill_price"))
                if average is not None and average > 0 and cumulative == Decimal(order["filled"]):
                    order["average_fill_price"] = str(average)
                else:
                    # Older journals lack broker cumulative-average prices. Derive
                    # only when unique execution quantities reconcile exactly.
                    fills = [
                        e
                        for e in self._executions.values()
                        if e.get("client_id") == p["client_id"]
                        and e.get("order_id") == p["order_id"]
                    ]
                    valid = [(money(e.get("quantity")), money(e.get("price"))) for e in fills]
                    if all(q is not None and q > 0 and v is not None and v > 0 for q, v in valid):
                        units = sum((q for q, _ in valid if q is not None), Decimal(0))
                        cost = sum(
                            (q * v for q, v in valid if q is not None and v is not None), Decimal(0)
                        )
                        if units > 0 and units == Decimal(order["filled"]):
                            order["average_fill_price"] = str(cost / units)
                order["received_at"] = stamp
        elif kind == "fee":
            self._fees[p["exec_id"]] = p
            if p["exec_id"] in self._executions:
                self._executions[p["exec_id"]].update(p)
        elif kind == "sync":
            self._observed_orders.clear()
            summary_ready = "summary" in self._barriers
            self._barriers.clear()
            if summary_ready:
                self._barriers.add("summary")
            self._values = {
                key: value
                for key, value in self._values.items()
                if value.source == "account_summary_metadata"
            }
            self._positions.clear()
            self._status = "synchronizing"
        elif kind == "barrier":
            self._barriers.add(p["name"])
            if (
                not self._halted
                and not self._fatal
                and {"account", "summary", "positions", "orders", "executions"} <= self._barriers
            ):
                self._status = "ready"
        elif kind in {"disconnected", "error", "closed"}:
            if kind != "error" or p.get("fatal"):
                self._status = kind if kind != "error" else "failed"
                self._barriers.clear()
                self._halted = True
            if kind == "error" and p.get("code") in {201, 202}:
                order = self._orders.get(f"{self._adapter.client_id}:{p.get('request_id')}")
                if order and order.get("status") != "Filled":
                    order["status"] = "Inactive" if p["code"] == 201 else "Cancelled"
                    order["reason"] = p.get("message", "")
            if p.get("message"):
                self._errors.append(p["message"])
                self._errors = self._errors[-50:]

    def snapshot(self) -> AccountSnapshot:
        with self._lock:

            def freeze(rows: Iterable[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
                return tuple(MappingProxyType(dict(r)) for r in rows)

            return AccountSnapshot(
                self.account,
                self.session,
                self._sequence,
                self._status,
                self._status == "ready",
                tuple(self._values.values()),
                freeze(self._positions.values()),
                freeze(self._orders.values()),
                freeze(self._executions.values()),
                MappingProxyType(dict(self._pnl)),
                tuple(self._errors) + ((self._fatal,) if self._fatal else ()),
            )

    def wait_ready(self, timeout: float = 20) -> AccountSnapshot:
        with self._changed:
            if not self._changed.wait_for(
                lambda: self._status in {"ready", "failed", "disconnected"}, timeout
            ):
                missing = ", ".join(
                    sorted(
                        {"account", "summary", "positions", "orders", "executions"} - self._barriers
                    )
                )
                details = "; ".join(self._errors[-3:])
                raise BrokerError(
                    f"Account refresh incomplete (missing: {missing}); "
                    f"no trading enabled" + (f". {details}" if details else "")
                )
            if self._status != "ready":
                raise BrokerError("Broker synchronization failed: " + "; ".join(self._errors))
            return self.snapshot()

    def wait_for_update(self, after: int, timeout: float = 5) -> AccountSnapshot:
        with self._changed:
            self._changed.wait_for(lambda: self._sequence > after or self._closed, timeout)
            return self.snapshot()

    def refresh_pnl(self, *, timeout: float = 5, renew: bool = True) -> AccountSnapshot:
        """Request a new P&L subscription sample without sending any orders.

        A quiet flat account may not emit repeated unchanged P&L. Only a valid
        callback for the new request generation satisfies this wait. An old
        sample is retained for audit, never relabeled as current on timeout.
        Collect the initial callback burst for two seconds. An all-zero first
        callback replacing prior nonzero P&L requires a subsequent valid callback;
        an unconfirmed reset times out rather than triggering a false loss stop.
        Startup uses renew=False to validate the initial active subscription
        without canceling it; unchanged zero P&L may not be resent on renewal.
        If no valid callback arrives, a journaled same-day flat-account reference
        may be confirmed against fresh matching account downloads. This returns
        explicit risk-confirmation metadata, never a synthesized broker callback.
        """
        if isinstance(timeout, bool) or not isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if not isinstance(renew, bool):
            raise ValueError("renew must be a boolean")
        with self._commands:
            with self._lock:
                if self._closed or self._status != "ready" or not self._adapter.isConnected():
                    raise BrokerError("Cannot refresh P&L while broker state is uncertain")
                previous_nonzero = any(
                    (money((self._validated_pnl or self._pnl).get(k)) or Decimal(0)) != 0
                    for k in ("daily", "unrealized", "realized")
                )
            try:
                active = getattr(self._adapter, "_pnl_id", -1)
                request_id = (
                    active
                    if not renew and type(active) is int and active >= 0
                    else self._adapter.request_pnl(self.account)
                )
            except Exception as exc:
                raise BrokerError("P&L subscription renewal failed; no fresh risk data") from exc
            deadline = monotonic() + timeout
            settle_at: float | None = None
            with self._changed:
                while True:
                    if self._closed or self._status != "ready" or not self._adapter.isConnected():
                        raise BrokerError("Broker state became uncertain during P&L refresh")
                    valid = (
                        self._pnl.get("request_id") == request_id
                        and money(self._pnl.get("daily")) is not None
                    )
                    clock = monotonic()
                    if valid and settle_at is None:
                        settle_at = clock + PNL_SETTLE_SECONDS
                    all_zero = all(
                        money(self._pnl.get(k)) == 0 for k in ("daily", "unrealized", "realized")
                    )
                    unconfirmed_reset = (
                        previous_nonzero and all_zero and self._pnl.get("valid_samples", 0) < 2
                    )
                    if (
                        valid
                        and not unconfirmed_reset
                        and settle_at is not None
                        and clock >= settle_at
                    ):
                        self._record(
                            "pnl_validated",
                            dict(
                                request_id=request_id,
                                daily=self._pnl["daily"],
                                received_at=self._pnl["received_at"],
                                valid_samples=self._pnl["valid_samples"],
                            ),
                        )
                        if self._pnl_reference is not None:
                            age = (
                                datetime.now(UTC)
                                - datetime.fromisoformat(self._pnl["received_at"])
                            ).total_seconds()
                            if 0 <= age <= 15:
                                reference = dict(
                                    version=1,
                                    reference=self._risk_fingerprint(self._pnl_reference),
                                    pnl=dict(self._validated_pnl),
                                    reference_session=self.session,
                                )
                                self._record("pnl_flat_reference", reference)
                                self._prior_flat_risk = reference
                        return self.snapshot()
                    remaining = deadline - clock
                    if remaining <= 0:
                        break
                    if valid and not unconfirmed_reset and settle_at is not None:
                        remaining = min(remaining, max(0, settle_at - clock))
                    self._changed.wait(remaining)
            if not renew and not valid and self._prior_flat_risk is not None:
                confirmed = self._confirm_prior_flat_risk()
                if confirmed is not None:
                    return confirmed
            raise BrokerError(
                "Fresh broker P&L unavailable; refresh timed out"
                + (" (unconfirmed all-zero reset)" if unconfirmed_reset else "")
                + (
                    "; no valid callback for the active subscription. Check TWS "
                    "'Prepare portfolio PnL data when downloading positions'; "
                    "if enabled, restart the paper TWS/Gateway session and run "
                    "the read-only preflight"
                    if not valid
                    else ""
                )
            )

    @staticmethod
    def _risk_fingerprint(reference: tuple[Any, ...]) -> str:
        return json.dumps(
            reference,
            default=lambda value: str(value.normalize()),
            separators=(",", ":"),
        )

    def _confirm_prior_flat_risk(self) -> AccountSnapshot | None:
        """A prior session is evidence only; fresh broker downloads must match it."""
        saved = self._prior_flat_risk
        if not saved or saved.get("version") != 1:
            return None
        trusted = saved.get("pnl", {})
        try:
            stamp = datetime.fromisoformat(trusted["received_at"])
            current = datetime.now(UTC)
            if (
                stamp.utcoffset() is None
                or stamp > current
                or stamp.astimezone(ZoneInfo("America/New_York")).date()
                != current.astimezone(ZoneInfo("America/New_York")).date()
                or trusted.get("validated") is not True
                or any(money(trusted.get(k)) is None for k in ("daily", "unrealized", "realized"))
                or money(trusted.get("unrealized")) != 0
            ):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        # Never substitute the old sample into the broker's current P&L state.
        # The flat proof needs its zero-unrealized premise separately.
        self.refresh()
        with self._lock:
            reference = self._flat_risk_reference(unrealized=money(trusted["unrealized"]))
            if (
                reference is None
                or self._risk_fingerprint(reference) != saved.get("reference")
                or (self._pnl and any(
                    money(self._pnl.get(k)) != money(trusted.get(k))
                    for k in ("daily", "unrealized", "realized")
                ))
            ):
                return None
            confirmed = now()
            self._record(
                "pnl_risk_confirmation",
                dict(
                    source="flat_account_reconciliation",
                    reference_session=saved.get("reference_session"),
                    sample_received_at=trusted["received_at"],
                    confirmed_at=confirmed,
                    daily=trusted["daily"],
                    account_refresh_sequence=self._sequence,
                ),
            )
            return replace(self.snapshot(), pnl=MappingProxyType({
                **trusted,
                "risk_confirmed_at": confirmed,
                "risk_source": "flat_account_reconciliation",
            }))

    def _flat_risk_reference(self, *, unrealized: Decimal | None = None) -> tuple[Any, ...] | None:
        """Proof inputs only: no exposure, USD funds, and unchanged economic events."""
        if self._status != "ready" or self.base_currency() != "USD":
            return None
        risk_unrealized = (
            money(self._validated_pnl.get("unrealized")) if unrealized is None else unrealized
        )
        if risk_unrealized != 0:
            return None
        if any(money(p.get("quantity")) != 0 for p in self._positions.values()):
            return None
        if any(o.get("status") not in TERMINAL_ORDER_STATES for o in self._orders.values()):
            return None
        for value in self._values.values():
            if (
                value.tag in {"CashBalance", "TotalCashValue"}
                and value.currency not in {"", "BASE", "USD"}
                and value.number != 0
            ):
                return None
        nlv = self._values.get(("NetLiquidation", "USD"))
        cash = self._values.get(("CashBalance", "USD"))
        funding = self.funding()
        funds = (
            nlv.number if nlv else None,
            cash.number if cash else None,
            *(
                money(funding[k])
                for k in ("TotalCashValue", "SettledCash", "AvailableFunds", "BuyingPower")
            ),
        )
        if any(v is None for v in funds):
            return None
        executions = tuple(
            sorted(
                (
                    key,
                    e.get("client_id"),
                    e.get("order_id"),
                    e.get("con_id"),
                    e.get("side"),
                    e.get("currency"),
                    money(e.get("quantity")),
                    money(e.get("price")),
                    money(e.get("cumulative_quantity")),
                    money(e.get("commission")),
                    e.get("fee_currency"),
                )
                for key, e in self._executions.items()
            )
        )
        fees = tuple(
            sorted(
                (key, money(e.get("commission")), e.get("fee_currency"))
                for key, e in self._fees.items()
            )
        )
        return funds, executions, fees

    def refresh_risk(self, *, timeout: float = 5) -> AccountSnapshot:
        """Confirm quiet flat-account risk with a fresh download, else renew P&L.

        This never refreshes the old P&L receipt time. A separate confirmation
        timestamp identifies an unchanged, fully flat USD account. Any changed
        funds, position, working order, execution or fee requires a new P&L sample.
        """
        if isinstance(timeout, bool) or not isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        with self._commands:
            with self._lock:
                reference = self._pnl_reference
                trusted = dict(self._validated_pnl)
            if reference is None and self._prior_flat_risk is not None:
                confirmed = self._confirm_prior_flat_risk()
                if confirmed is not None:
                    return confirmed
            if reference is not None and trusted.get("validated"):
                snapshot = self.refresh()
                with self._lock:
                    if self._pnl.get("validated"):
                        try:
                            age = (
                                datetime.now(UTC) - datetime.fromisoformat(self._pnl["received_at"])
                            ).total_seconds()
                        except (KeyError, TypeError, ValueError):
                            age = None
                        if age is not None and 0 <= age <= 15:
                            return self.snapshot()
                    confirmation = now()
                    same_day = (
                        datetime.fromisoformat(trusted["received_at"])
                        .astimezone(ZoneInfo("America/New_York"))
                        .date()
                        == datetime.fromisoformat(confirmation)
                        .astimezone(ZoneInfo("America/New_York"))
                        .date()
                    )
                    if (
                        same_day
                        and self._pnl_reference == reference
                        and self._flat_risk_reference() == reference
                        and self._validated_pnl == trusted
                        and all(
                            money(self._pnl.get(k)) == money(trusted.get(k))
                            for k in ("daily", "unrealized", "realized")
                        )
                    ):
                        self._record(
                            "pnl_risk_confirmation",
                            dict(
                                source="flat_account_reconciliation",
                                request_id=trusted.get("request_id"),
                                sample_received_at=trusted["received_at"],
                                confirmed_at=confirmation,
                                daily=trusted["daily"],
                                account_refresh_sequence=snapshot.sequence,
                            ),
                        )
                        return replace(
                            self.snapshot(),
                            pnl=MappingProxyType(
                                {
                                    **trusted,
                                    "risk_confirmed_at": confirmation,
                                    "risk_source": "flat_account_reconciliation",
                                }
                            ),
                        )
            return self.refresh_pnl(timeout=timeout)

    def wait_order(self, order_id: int, *, timeout: float = 35) -> Mapping[str, Any]:
        """Wait for this client's known order to finish; never cancel or retry it.

        Filled, Cancelled, ApiCancelled and Inactive are returned unchanged. A
        terminal state does not imply a full fill. Timeouts/disconnects raise
        OrderWaitError carrying the last immutable order, including partial fills.
        """
        if isinstance(timeout, bool) or not isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id < 0:
            raise ValueError("order_id must be a nonnegative integer")
        key = f"{self._adapter.client_id}:{order_id}"
        deadline = monotonic() + timeout
        with self._changed:
            while True:
                order = self._orders.get(key)
                if order is None:
                    raise OrderWaitError(f"Unknown order {order_id} for this client", None)
                if order.get("status") in TERMINAL_ORDER_STATES:
                    return MappingProxyType(dict(order))
                if self._closed or self._status != "ready" or not self._adapter.isConnected():
                    raise OrderWaitError(f"Order {order_id}: broker state uncertain", order)
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise OrderWaitError(
                        f"Order {order_id} still unresolved; reconcile before retry", order
                    )
                self._changed.wait(remaining)

    def funding(self, *, at: datetime | None = None) -> dict[str, Any]:
        """Fresh broker cap plus durable settled-cash ceiling, never margin capacity."""
        at = at or datetime.now(UTC)
        if at.utcoffset() is None:
            raise ValueError("Funding clock must be timezone aware")
        with self._lock:
            base = self.base_currency()

            def amount(tag: str) -> Decimal | None:
                # Aggregate funds are only usable for this USD-only engine if base is USD.
                v = (
                    self._values.get((tag, "USD"))
                    or (self._values.get((tag, "BASE")) if base == "USD" else None)
                    or (self._values.get((tag, "")) if base == "USD" else None)
                )
                return v.number if v else None

            amounts = {
                tag: amount(tag)
                for tag in ("SettledCash", "TotalCashValue", "AvailableFunds", "BuyingPower")
            }
            settled_source = "SettledCash"
            if amounts["SettledCash"] is None:
                schedule = self._values.get(("SettledCashByDate", "USD"))
                if schedule:
                    amounts["SettledCash"] = settled_schedule(
                        schedule.value, on_date=at.astimezone(ZoneInfo("America/New_York")).date()
                    )
                    settled_source = "SettledCashByDate:USD:today"
            cash = self._values.get(("CashBalance", "USD"))
            if cash is not None and cash.number is not None:
                amounts["TotalCashValue"] = (
                    min(cash.number, amounts["TotalCashValue"])
                    if amounts["TotalCashValue"] is not None
                    else cash.number
                )
            # Broker values can lag executions. No new exposure while any owned
            # order is unresolved, or until a fresh account download after a fill.
            pending = any(
                str(o.get("order_ref", "")).startswith("pyibquant:")
                and o.get("status") not in {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
                for o in self._orders.values()
            )
            usable = (
                max(Decimal(0), min(v for v in amounts.values() if v is not None))
                if all(v is not None for v in amounts.values())
                and not pending
                and self._status == "ready"
                and base == "USD"
                else None
            )
            total, settled = amounts["TotalCashValue"], amounts["SettledCash"]
            unsettled = (
                max(Decimal(0), total - settled)
                if total is not None and settled is not None
                else None
            )
            local: dict[str, Any] = {}
            blocked = [f"Missing or invalid {tag}" for tag, v in amounts.items() if v is None]
            for value in self._values.values():
                if value.tag in {*amounts, "CashBalance", "SettledCashByDate"}:
                    age = (at - datetime.fromisoformat(value.received_at)).total_seconds()
                    if not 0 <= age <= 60:
                        blocked.append(f"Stale funding field: {value.tag}")
            if self._funding_baseline is not None:
                try:
                    local = cash_ledger(self._funding_baseline, tuple(self._orders.values()),
                                        tuple(self._executions.values()), at=at)
                except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                    blocked.append(f"Invalid durable funding baseline: {exc}")
                blocked.extend(local.get("funding_issues", []))
                if usable is not None and "cash_ceiling" in local:
                    usable = min(usable, Decimal(local["cash_ceiling"]))
            if self._funding_baseline is None and self._orders and usable is not None:
                try:
                    legacy = cash_ledger(baseline_payload(
                        usable, (), self.settlement_policy, at=at,
                    ), tuple(self._orders.values()), tuple(self._executions.values()), at=at)
                    if legacy["funding_issues"] or Decimal(legacy["local_unsettled"]) != 0:
                        blocked.append("Legacy fills/settlements require reconciliation first")
                except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
                    blocked.append(f"Invalid legacy funding coverage: {exc}")
            blocked.extend(sorted(self._funding_conflicts))
            reserved = sum(
                ((money(o.get("limit_price")) or Decimal(0))
                 * (money(o.get("remaining")) or Decimal(0))
                 * (contract_multiplier(o) or Decimal(0))
                 + self.settlement_policy.fee_allowance
                 for o in self._orders.values()
                 if str(o.get("order_ref", "")).startswith("pyibquant:")
                 and o.get("side") == "BUY" and o.get("status") not in TERMINAL_ORDER_STATES),
                Decimal(0),
            )
            invalid_reserved = any(
                str(o.get("order_ref", "")).startswith("pyibquant:") and o.get("side") == "BUY"
                and o.get("status") not in TERMINAL_ORDER_STATES
                and contract_multiplier(o) is None for o in self._orders.values()
            )
            if invalid_reserved:
                blocked.append("Pending contract multiplier is unknown")
            if pending:
                blocked.append("Owned order remains unresolved")
            if self._status != "ready":
                blocked.append("Account is not synchronized")
            if base != "USD":
                blocked.append("USD base currency is not confirmed")
            if any(o.get("status") not in TERMINAL_ORDER_STATES
                   and not str(o.get("order_ref", "")).startswith("pyibquant:")
                   for o in self._orders.values()):
                blocked.append("Foreign working order has an untracked commitment")
            if blocked:
                usable = None
            pending_estimate = local.pop("pending_buy_estimate", str(reserved))
            return dict(
                **local,
                policy="no_borrowing",
                blocked_reasons=blocked,
                unsettled_estimate=str(unsettled) if unsettled is not None else None,
                pending_buy_estimate=(None if invalid_reserved else
                                      pending_estimate),
                settled_source=settled_source,
                base_currency=base,
                **{k: str(v) if v is not None else None for k, v in amounts.items()},
                usable=str(usable) if usable is not None else None,
                pending_owned_order=pending,
            )

    def base_currency(self) -> str | None:
        with self._lock:
            metadata = self._values.get(("BaseCurrency", ""))
            if metadata:
                return metadata.value
            currencies = {
                v.currency
                for v in self._values.values()
                if v.tag == "NetLiquidation"
                and v.source == "account_summary"
                and v.currency not in {"", "BASE"}
            }
            return next(iter(currencies)) if len(currencies) == 1 else None

    def _owned(self, order: Mapping[str, Any]) -> bool:
        return order.get("client_id") == self._adapter.client_id and str(
            order.get("order_ref", "")
        ).startswith("pyibquant:")

    def submit_limit(
        self,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: float,
        *,
        tag: str = "manual",
        key: str | None = None,
    ) -> int:
        """Submit a bounded USD equity DAY limit order, returning an ID, not a fill."""
        if limit_price is None:
            raise ValueError("A limit order requires a price")
        return self._submit_equity(symbol, side, quantity, limit_price, tag=tag, key=key)

    def close_position_market(
        self,
        symbol: str,
        quantity: int,
        *,
        tag: str = "manual-close",
        key: str | None = None,
    ) -> int:
        """Explicit market sell limited to existing long whole-share USD equity holdings.

        For owner-directed liquidation only; no market buys, shorting or assumed
        execution price. Quantity cap applies; a market notional cannot be capped.
        """
        return self._submit_equity(symbol, "SELL", quantity, None, tag=tag, key=key)

    def _submit_equity(
        self,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: float | None,
        *,
        tag: str = "manual",
        key: str | None = None,
    ) -> int:
        price = money(limit_price)
        if not isinstance(tag, str) or len(tag) > 100:
            raise ValueError("tag must be a string of at most 100 characters")
        if key is not None and (not key or len(key) > 40 or not key.isascii()):
            raise ValueError("key must contain 1–40 ASCII characters")
        if side not in {"BUY", "SELL"} or not symbol.strip().isalnum():
            raise ValueError("Use an equity symbol and BUY or SELL")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError("quantity must be a positive whole number")
        if limit_price is None:
            if side != "SELL":
                raise BrokerError("Market orders are restricted to closing existing long holdings")
        elif price is None or price <= 0 or isinstance(limit_price, bool):
            raise ValueError("limit_price must be positive and finite")
        if quantity > self.max_quantity or (
            price is not None and price * quantity > self.max_order_value
        ):
            raise BrokerError("Configured order size/notional limit exceeded")
        with self._commands:
            if self.readonly or self._closed:
                raise BrokerError("Broker is read-only or closed")
            self._adapter.refresh(self.account)
            self.wait_ready(self._adapter.timeout)
            contract = self._adapter.resolve(symbol.upper())
            with self._lock:
                if self._fatal or self._status != "ready" or not self._adapter.isConnected():
                    raise BrokerError("Broker is not synchronized")
                if any(
                    str(o.get("order_ref", "")).startswith("pyibquant:")
                    and o.get("status") not in {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
                    for o in self._orders.values()
                ):
                    raise BrokerError(
                        "Resolve the outstanding owned order before submitting another"
                    )
                if side == "BUY":
                    funding = self.funding()
                    budget = money(funding["usable"])
                    # Conservative configurable cap plus $2 fee reserve for the initial tiny orders.
                    if (price is None or budget is None
                        or budget < price * quantity + self.settlement_policy.fee_allowance):
                        details = "; ".join(funding["blocked_reasons"])
                        raise BrokerError(
                            "Insufficient or unknown broker-reported USD funds"
                            + (f": {details}" if details else "")
                        )
                else:
                    held = money(self._positions.get(contract.conId, {}).get("quantity", 0))
                    if held is None or held < quantity:
                        raise BrokerError("Sell exceeds reconciled holdings; shorting is disabled")
            return self._send_intent(contract, symbol.upper(), side, quantity, price, tag, key)

    def _send_intent(
        self, contract: Any, symbol: str, side: str, quantity: int, price: Decimal | None,
        tag: str, key: str | None, metadata: dict[str, Any] | None = None,
    ) -> int:
        """Serialize account cash commitments across local broker processes."""
        from .trading.checkpoint import RunLease

        lease = RunLease(self.journal.path, "funding")
        with self._commands:
            lease.acquire()
            try:
                history = self.journal.events(self.account)
                if any(e["kind"] in FUNDING_EVENTS and e["sequence"] not in self._applied_sequences
                       for e in history):
                    raise BrokerError(
                        "Funding journal changed; reopen and reconcile before sending"
                    )
                durable = {(e["payload"].get("client_id"), e["payload"]["order_id"])
                           for e in history if e["kind"] == "intent"}
                replayed = {(o.get("client_id"), o["order_id"]) for o in self._orders.values()}
                baselines = [e["payload"] for e in history if e["kind"] == "funding_baseline"]
                if (not durable <= replayed
                    or (baselines and baselines[-1] != self._funding_baseline)):
                    raise BrokerError(
                        "Funding journal changed; reopen and reconcile before sending"
                    )
                return self._send_funded_intent(contract, symbol, side, quantity, price, tag, key,
                                                metadata)
            finally:
                lease.release()

    def _send_funded_intent(
        self, contract: Any, symbol: str, side: str, quantity: int, price: Decimal | None,
        tag: str, key: str | None, metadata: dict[str, Any] | None,
    ) -> int:
        """Shared durable identity/send boundary for validated equity and option orders."""
        if not isinstance(tag, str) or len(tag) > 100:
            raise ValueError("tag must be a string of at most 100 characters")
        if key is not None and (not key or len(key) > 40 or not key.isascii()):
            raise ValueError("key must contain 1–40 ASCII characters")
        with self._lock:
            order_ref = "pyibquant:" + (key or uuid4().hex)
            if any(o.get("order_ref") == order_ref for o in self._orders.values()):
                raise BrokerError("Order idempotency key already exists")
            if side == "BUY":
                try:
                    self.settlement_policy.settlement_date(
                        datetime.now(ZoneInfo("America/New_York")).date(),
                        (metadata or {}).get("asset_type", "STK"), "USD",
                    )
                except ValueError as exc:
                    raise BrokerError(f"No supported settlement coverage: {exc}") from exc
                funds = money(self.funding()["usable"])
                cost = (price or Decimal(0)) * quantity * (
                    contract_multiplier(metadata or {}) or Decimal(1)
                ) + self.settlement_policy.fee_allowance
                if funds is None or funds < cost:
                    raise BrokerError("Funding changed before durable reservation; no order sent")
            if self._funding_baseline is None:
                funds = money(self.funding()["usable"])
                if funds is not None:
                    # Existing journals migrate only after fully explained terminal fills.
                    legacy = cash_ledger(baseline_payload(
                        funds, (), self.settlement_policy,
                    ), tuple(self._orders.values()), tuple(self._executions.values()),
                        at=datetime.now(UTC))
                    if not legacy["funding_issues"] and Decimal(legacy["local_unsettled"]) == 0:
                        self._record("funding_baseline", baseline_payload(
                            funds, tuple(self._executions.values()), self.settlement_policy,
                        ))
                # An explicit owned/holding-only exit is still allowed when cash is
                # unknown. Such legacy fills must settle/reconcile before a later BUY.
                if self._funding_baseline is None and side == "BUY":
                    raise BrokerError("Legacy fills/settlements require reconciliation first")
            oid = self._adapter.allocate_id()
            self._record("intent", dict(
                order_id=oid, client_id=self._adapter.client_id, account=self.account,
                order_ref=order_ref, tag=tag, con_id=contract.conId, symbol=symbol,
                side=side, quantity=str(quantity),
                limit_price=str(price) if price is not None else None,
                order_type="LMT" if price is not None else "MKT",
                filled="0", remaining=str(quantity), status="PendingSubmit",
                fee_allowance=str(self.settlement_policy.fee_allowance),
                **({"asset_type": "STK", "currency": "USD"} | (metadata or {})),
            ))
        try:
            self._adapter.send_order(oid, contract, side, quantity, price, self.account, order_ref)
        except Exception as exc:
            self._record("send_unknown", dict(
                order_id=oid, client_id=self._adapter.client_id, status="UnknownSend"
            ))
            raise BrokerError("Send outcome unknown; reconcile, never blindly retry") from exc
        return oid

    def submit_option_limit(
        self, selector: Option, side: str, quantity: int, limit_price: float, *, quote: Quote,
        tag: str, key: str | None = None,
    ) -> int:
        """Bounded USD long-option DAY limit; fresh exact quote and tick rule required."""
        from .trading.option_order import submit_option_limit

        return submit_option_limit(self, selector, side, quantity, limit_price,
                                   quote=quote, tag=tag, key=key)

    def cancel(self, order_id: int) -> None:
        with self._commands, self._lock:
            order = self._orders.get(f"{self._adapter.client_id}:{order_id}")
            if self.readonly or self._closed or not order or not self._owned(order):
                raise BrokerError("Only this broker client's owned paper orders can be canceled")
            if order.get("status") in TERMINAL_ORDER_STATES:
                return
            self._record("cancel_requested", dict(order_id=order_id))
            self._adapter.cancel_order(order_id)

    def refresh(self) -> AccountSnapshot:
        with self._commands:
            if self._closed:
                raise BrokerError("Broker is closed")
            self._adapter.refresh(self.account)
            return self.wait_ready(self._adapter.timeout)

    def reconcile(self) -> Reconciliation:
        """Refresh account/open orders/executions and identify unresolved journal orders.

        Absence from a download never proves cancellation. IBKR execution lookback
        is limited; this method does not claim a complete account order history.
        No orders are sent, adopted, canceled or resubmitted.
        """
        with self._commands:
            self.refresh()
            completed_checked = False
            if hasattr(self._adapter, "completed_orders"):
                rows = self._adapter.completed_orders(self.account)
                with self._lock:
                    # Validate the entire batch before changing any terminal states.
                    updates = self._completed_updates(rows)
                    self._record("completed_order_download", dict(
                        rows=rows, matched=len(updates), coverage="TWS-returned records only"
                    ))
                    for update in updates:
                        self._record("order", update)
                completed_checked = True
            with self._lock:
                snap = self.snapshot()
                working = tuple(
                    o
                    for o in snap.orders
                    if str(o.get("order_ref", "")).startswith("pyibquant:")
                    and o.get("status") not in TERMINAL_ORDER_STATES
                )
                missing = tuple(
                    o
                    for o in working
                    if f"{o.get('client_id')}:{o['order_id']}" not in self._observed_orders
                )
                foreign = tuple(
                    o
                    for o in snap.orders
                    if o.get("status") not in TERMINAL_ORDER_STATES and not self._owned(o)
                )
                result = Reconciliation(snap, working, missing, foreign, completed_checked)
                self._record(
                    "reconciliation",
                    dict(
                        working=len(working),
                        missing=len(missing),
                        foreign=len(foreign),
                        clear=result.clear,
                        completed_orders_checked=completed_checked,
                    ),
                )
                return result

    def _completed_updates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Only exact durable identities may acquire broker-confirmed terminal state."""
        updates: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("account") != self.account:
                continue
            perm = row.get("perm_id")
            if not isinstance(perm, int) or isinstance(perm, bool) or perm <= 0:
                continue
            candidates = [o for o in self._orders.values() if o.get("perm_id") == perm]
            if not candidates:
                continue  # No adoption of an external or historically unbound order.
            if len(candidates) != 1:
                raise BrokerError("Ambiguous completed-order permanent identity")
            old = candidates[0]
            if any(row.get(k) != old.get(k) for k in (
                "client_id", "order_id", "con_id", "order_ref", "side"
            )):
                raise BrokerError("Completed-order identity conflicts with the journal")
            status = row.get("status")
            if status not in {"Filled", "Cancelled", "ApiCancelled"}:
                continue  # Inactive/unknown status alone is not safe cancellation evidence.
            quantity, filled = money(old.get("quantity")), money(row.get("filled"))
            previous = money(old.get("filled"))
            if (
                quantity is None or quantity <= 0 or filled is None or filled < 0
                or filled > quantity or (previous is not None and filled < previous)
                or (status == "Filled" and filled != quantity)
                or (old.get("status") == "Filled" and status != "Filled")
            ):
                raise BrokerError("Completed-order fill quantity conflicts; reconcile manually")
            # TWS can report zero totalQuantity for filled records. Keep durable
            # submitted quantity; execution callbacks alone establish price/fees.
            update = dict(
                account=self.account, client_id=old["client_id"], order_id=old["order_id"],
                perm_id=perm, status=status, filled=str(filled), remaining="0",
                completed_time=row.get("completed_time"),
                completed_status=row.get("completed_status"),
                recovery_source="completed_orders",
            )
            key = f"{old['client_id']}:{old['order_id']}"
            if key in updates and updates[key] != update:
                raise BrokerError("Conflicting duplicate completed-order records")
            updates[key] = update
        return list(updates.values())

    def strategy_ledger(self, tag: str) -> StrategyLedger:
        """Audit recorded strategy fills; cash flow is not marked-to-market P&L."""
        snap = self.snapshot()
        return strategy_ledger(tag, snap.orders, snap.executions)

    def export_strategy(self, tag: str, path: str | Path) -> Path:
        """Save a masked strategy audit, including actual fills and missing-data issues."""
        snap = self.snapshot()
        ledger = strategy_ledger(tag, snap.orders, snap.executions)
        from .trading.run_performance import run_reports

        summary = next(
            (r for r in run_reports(self.journal.events(self.account), snap) if r["run_id"] == tag),
            None,
        )
        orders = [dict(o) for o in snap.orders if o.get("tag") == tag]
        keys = {(o.get("client_id"), o["order_id"]) for o in orders}
        executions = [
            dict(e) for e in snap.executions if (e.get("client_id"), e.get("order_id")) in keys
        ]
        for row in orders + executions:
            row.pop("account", None)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                mask_account_data(
                    dict(
                        account=snap.to_dict()["account"],
                        session=snap.session,
                        sequence=snap.sequence,
                        ledger=ledger.to_dict(),
                        performance=summary,
                        orders=orders,
                        executions=executions,
                    ),
                    self.account,
                ),
                allow_nan=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        target.chmod(0o600)
        return target

    def cancel_owned_orders(
        self, *, tag: str, timeout: float = 35
    ) -> tuple[Mapping[str, Any], ...]:
        """Cancel this client's working orders with an exact durable tag, then wait.

        A fill can win a cancellation race. On uncertainty the wait raises, retaining
        all identities in the journal. No unrelated orders or holdings are touched.
        """
        if not isinstance(tag, str) or not tag or len(tag) > 100:
            raise ValueError("An exact nonempty strategy tag is required")
        if isinstance(timeout, bool) or not isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        with self._commands:
            if self.readonly or self._closed:
                raise BrokerError("Broker is read-only or closed")
            orders = [
                o
                for o in self.snapshot().orders
                if self._owned(o)
                and o.get("tag") == tag
                and o.get("status") not in TERMINAL_ORDER_STATES
            ]
            deadline = monotonic() + timeout
            for order in orders:
                self.cancel(order["order_id"])
            return tuple(
                self.wait_order(o["order_id"], timeout=max(0, deadline - monotonic()))
                for o in orders
            )

    def _begin_refresh(self) -> None:
        self._queue.join()
        self._record("sync", {})

    def close(self) -> None:
        with self._commands:
            if self._closed:
                return
            self._adapter.close()
            self._queue.join()
            self._record(
                "closed", dict(message="Observer stopped; working orders are not canceled")
            )
            self._closed = True
            self._queue.put(None)
            self._worker.join(5)
            self.journal.close()

    def __enter__(self) -> PaperBroker:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def report(self, path: str | Path) -> Path:
        from .trading.performance import write_report

        return write_report(
            self.journal.events(self.account), self.snapshot(), path, funding=self.funding()
        )

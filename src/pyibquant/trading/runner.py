"""Small completed-bar equity runner with explicit lifecycle and broker-owned fills."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from threading import RLock
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..bars import BarSeries
from ..broker import AccountSnapshot, BrokerError, PaperBroker, money
from ..quotes import Quote
from ..research import above_sma
from .checkpoint import RunLease


@dataclass(frozen=True)
class RunnerConfig:
    symbol: str
    window: int = 20
    quantity: int = 1
    dry_run: bool = True
    max_orders: int = 4
    max_session_loss: float = 25
    max_data_age: float = 15

    def __post_init__(self) -> None:
        if not isinstance(self.dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        if (
            not isinstance(self.symbol, str)
            or not self.symbol
            or not self.symbol.isalnum()
            or self.symbol != self.symbol.upper()
        ):
            raise ValueError("Use an uppercase equity symbol")
        for value in (self.window, self.quantity, self.max_orders):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("window, quantity and max_orders must be positive whole numbers")
        for limit in (self.max_session_loss, self.max_data_age):
            parsed = money(limit)
            if parsed is None or parsed <= 0 or isinstance(limit, bool):
                raise ValueError("Loss limit and data age must be positive and finite")


class EquityRunner:
    """Above-SMA one-minute runner; default observation mode never submits orders.

    Completion is witnessed by a subsequent live candle, not a browser timer.
    Historical warmup never triggers orders. Late revisions cannot repeat a decision.
    No synthetic fills or strategy P&L are inferred from observed signals.
    """

    def __init__(self, broker: PaperBroker, config: RunnerConfig) -> None:
        if config.quantity > broker.max_quantity:
            raise BrokerError("Target quantity exceeds configured broker limit")
        self.broker, self.config = broker, config
        self.run_id = uuid4().hex
        self.status = "stopped"
        self.reason = ""
        self._lock = RLock()
        self._seen: datetime | None = None
        self._day = ""
        self._pnl_baseline: Decimal | None = None
        self._orders = 0
        self._instrument_id: int | None = None
        self._order_cap = broker.max_order_value
        self._quantity_cap = broker.max_quantity
        self._lease = RunLease(broker.journal.path, self.run_id)
        self._restored_checkpoint: int | None = None

    def _require_execution(self) -> None:
        if not self.config.dry_run and self.broker.readonly:
            raise BrokerError("Execution runner requires an explicitly enabled paper broker")

    def _intent_count(self) -> int:
        identities = {
            (e["payload"].get("client_id"), e["payload"].get("order_id"))
            for e in self.broker.journal.events(self.broker.account)
            if e["kind"] == "intent" and e["payload"].get("tag") == self.run_id
        }
        return len(identities)

    def _check_restored_state(self) -> None:
        if self._restored_checkpoint is None:
            return
        events = self.broker.journal.events(self.broker.account)
        latest = [
            e
            for e in events
            if e["kind"] == "runner_checkpoint" and e["payload"].get("run_id") == self.run_id
        ][-1]
        if latest["sequence"] != self._restored_checkpoint:
            raise BrokerError("Run changed after restore; restore its latest checkpoint again")
        durable = {
            (e["payload"].get("client_id"), e["payload"].get("order_id"))
            for e in events
            if e["kind"] == "intent" and e["payload"].get("tag") == self.run_id
        }
        replayed = {
            (o.get("client_id"), o["order_id"])
            for o in self.broker.snapshot().orders
            if o.get("tag") == self.run_id
        }
        if not durable <= replayed:
            raise BrokerError(
                "Journal intents changed; reopen the broker and restore before resuming"
            )

    def _checkpoint(self) -> None:
        self._log(
            "runner_checkpoint",
            version=1,
            config=asdict(self.config),
            instrument_id=self._instrument_id,
            day=self._day,
            pnl_baseline=str(self._pnl_baseline) if self._pnl_baseline is not None else None,
            last_seen=self._seen.isoformat() if self._seen else None,
            status=self.status,
            reason=self.reason,
            orders=max(self._orders, self._intent_count()),
            order_cap=str(self._order_cap),
            quantity_cap=self._quantity_cap,
        )

    @classmethod
    def restore(cls, broker: PaperBroker, run_id: str) -> EquityRunner:
        """Restore identity/configuration/risk limits, paused, without any API requests.

        Holdings come from durable executions, never a checkpoint position guess.
        Explicit resume requires the same trading date, fresh account/feed/P&L,
        reconciled holdings and no unresolved orders. Old incomplete journals fail.
        """
        if (
            not isinstance(run_id, str)
            or len(run_id) != 32
            or any(c not in "0123456789abcdef" for c in run_id)
        ):
            raise ValueError("Use the exact 32-character run ID from the journal")
        events = broker.journal.events(broker.account)
        checkpoints = [
            e
            for e in events
            if e["kind"] == "runner_checkpoint" and e["payload"].get("run_id") == run_id
        ]
        if not checkpoints:
            raise BrokerError("No recoverable checkpoint; legacy runs support reporting only")
        p = checkpoints[-1]["payload"]
        try:
            if type(p["version"]) is not int or p["version"] != 1:
                raise ValueError("unsupported checkpoint version")
            config = RunnerConfig(**p["config"])
            seen = datetime.fromisoformat(p["last_seen"])
            day = datetime.fromisoformat(p["day"]).date().isoformat()
            baseline, cap = money(p["pnl_baseline"]), money(p["order_cap"])
            instrument_id, quantity_cap, orders = p["instrument_id"], p["quantity_cap"], p["orders"]
            if (
                seen.utcoffset() is None
                or day != seen.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                or not isinstance(instrument_id, int)
                or isinstance(instrument_id, bool)
                or instrument_id <= 0
                or not isinstance(quantity_cap, int)
                or isinstance(quantity_cap, bool)
                or quantity_cap < config.quantity
                or not isinstance(orders, int)
                or isinstance(orders, bool)
                or orders < 0
                or cap is None
                or cap <= 0
                or (not config.dry_run and baseline is None)
            ):
                raise ValueError("invalid checkpoint state")
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerError(f"Invalid runner checkpoint: {exc}") from exc
        runner = cls(broker, config)
        runner.run_id, runner._seen, runner._day = run_id, seen, day
        runner._instrument_id, runner._pnl_baseline = instrument_id, baseline
        runner._order_cap, runner._quantity_cap = cap, quantity_cap
        runner._orders = max(orders, runner._intent_count())
        runner._lease = RunLease(broker.journal.path, run_id)
        runner._restored_checkpoint = checkpoints[-1]["sequence"]
        runner.status, runner.reason = (
            "paused",
            "Restored checkpoint; explicit reconciliation/resume required",
        )
        return runner

    def _log(self, kind: str, **details: Any) -> None:
        self.broker._record(kind, dict(run_id=self.run_id, symbol=self.config.symbol, **details))

    @staticmethod
    def _fresh_pnl(snapshot: AccountSnapshot, at: datetime) -> Decimal | None:
        if snapshot.pnl.get("validated") is False:
            return None
        value = money(snapshot.pnl.get("daily"))
        try:
            stamp = datetime.fromisoformat(
                snapshot.pnl["risk_confirmed_at"]
                if snapshot.pnl.get("risk_source") == "flat_account_reconciliation"
                else snapshot.pnl["received_at"]
            )
            age = (at - stamp).total_seconds()
        except (KeyError, TypeError, ValueError):
            return None
        return value if 0 <= age <= 15 else None

    def _risk_snapshot(
        self, snapshot: AccountSnapshot, at: datetime, *, real_clock: bool, force: bool = False
    ) -> tuple[AccountSnapshot, datetime]:
        if force or self._fresh_pnl(snapshot, at) is None:
            snapshot = self.broker.refresh_pnl(renew=False) if force else self.broker.refresh_risk()
            if real_clock:
                at = datetime.now(UTC)
            if force and self._fresh_pnl(snapshot, at) is None:
                snapshot = self.broker.refresh_risk()
                if real_clock:
                    at = datetime.now(UTC)
            self._log(
                "runner_pnl_refresh",
                request_id=snapshot.pnl.get("request_id"),
                risk_source=snapshot.pnl.get("risk_source", "reqPnL"),
            )
        return snapshot, at

    def _loss_reason(self, pnl: Decimal) -> str | None:
        assert self._pnl_baseline is not None
        change = pnl - self._pnl_baseline
        limit = Decimal(str(self.config.max_session_loss))
        self._log(
            "runner_loss_check",
            baseline=str(self._pnl_baseline),
            current=str(pnl),
            change=str(change),
            limit=str(limit),
        )
        if change <= -limit:
            return (
                f"Account session-loss limit reached (change={change:.2f}, "
                f"limit={limit:.2f}, baseline={self._pnl_baseline:.2f}, current={pnl:.2f})"
            )
        return None

    def start(self, series: BarSeries, *, at: datetime | None = None) -> None:
        real_clock = at is None
        at = at or datetime.now(UTC)
        with self._lock:
            self._require_execution()
            if self.status != "stopped" or self._seen is not None:
                raise BrokerError("Runner already started; resume a paused run or create a new run")
            if at.utcoffset() is None:
                raise ValueError("Runner clock must be timezone aware")
            if series.symbol != self.config.symbol or series.interval != "1min" or not series.live:
                raise BrokerError("Runner requires its own live one-minute equity feed")
            if series.instrument_id is None or series.instrument_id <= 0:
                raise BrokerError("Runner requires a resolved contract identity")
            snapshot = self.broker.snapshot()
            if not snapshot.complete:
                raise BrokerError("Synchronize the account before starting")
            if not self.config.dry_run and any(
                p.get("symbol") == self.config.symbol and money(p.get("quantity")) != 0
                for p in snapshot.positions
            ):
                raise BrokerError("Execution example requires a flat selected symbol at start")
            bars = series.snapshot()
            if not bars or not isinstance(bars[-1].timestamp, datetime):
                raise BrokerError("Runner needs intraday warmup bars")
            if not self.config.dry_run:
                snapshot, at = self._risk_snapshot(snapshot, at, real_clock=real_clock, force=True)
            self._pnl_baseline = self._fresh_pnl(snapshot, at)
            if not self.config.dry_run and self._pnl_baseline is None:
                raise BrokerError("Fresh broker daily P&L is required for the session-loss limit")
            if not self.config.dry_run and self.broker.funding()["pending_owned_order"]:
                raise BrokerError("Resolve outstanding owned orders before starting")
            self._seen = bars[-1].timestamp
            self._instrument_id = series.instrument_id
            self._day = at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            self.status, self.reason = "running", ""
            if not self.config.dry_run:
                self._lease.acquire()
            self._log(
                "runner_start",
                window=self.config.window,
                quantity=self.config.quantity,
                dry_run=self.config.dry_run,
                max_orders=self.config.max_orders,
                max_session_loss=self.config.max_session_loss,
                pnl_baseline=str(self._pnl_baseline) if self._pnl_baseline is not None else None,
            )
            self._checkpoint()

    def pause(self, reason: str = "Paused by user") -> None:
        with self._lock:
            self.status, self.reason = "paused", reason
            self._log("runner_pause", reason=reason)
            if self._seen is not None:
                self._checkpoint()

    def stop(self) -> None:
        with self._lock:
            self.status, self.reason = "stopped", "Stopped by user"
            try:
                self._log("runner_stop")
                if self._seen is not None:
                    self._checkpoint()
            finally:
                self._lease.release()

    def cancel_owned_orders(self, *, timeout: float = 35) -> tuple[Mapping[str, Any], ...]:
        """Separate from stop; never cancel another strategy run's orders."""
        return self.broker.cancel_owned_orders(tag=self.run_id, timeout=timeout)

    def resume(self, series: BarSeries, *, at: datetime | None = None) -> None:
        """Resume a paused in-memory run after a read-only reconciliation.

        Keeps its loss baseline, order count and strategy identity. Skips bars
        observed during the pause. A disconnected broker requires a new session;
        this method does not reconnect or restore a process from a checkpoint.
        """
        real_clock = at is None
        at = at or datetime.now(UTC)
        with self._lock:
            self._require_execution()
            if self.status != "paused" or self._seen is None:
                raise BrokerError("Only a previously started, paused run can resume")
            if at.utcoffset() is None:
                raise ValueError("Runner clock must be timezone aware")
            day = at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if day != self._day:
                raise BrokerError("New trading date requires a new session baseline")
            if (
                series.symbol != self.config.symbol
                or series.instrument_id != self._instrument_id
                or series.instrument_id is None
                or series.interval != "1min"
                or not series.live
                or series.error
                or series.connection_state != "subscribed"
            ):
                raise BrokerError("Resume requires the selected live one-minute feed")
            with series._lock:
                live_stamp = series.last_live_update
                bars = series.snapshot()
            if real_clock:
                at = datetime.now(UTC)
            age = (at - live_stamp).total_seconds() if live_stamp else None
            if (
                age is None
                or not 0 <= age <= self.config.max_data_age
                or not bars
                or not isinstance(bars[-1].timestamp, datetime)
            ):
                raise BrokerError("Resume requires fresh intraday bars")
            if bars[-1].timestamp < self._seen:
                raise BrokerError("Resume feed is behind the persisted candle cursor")
            report = self.broker.reconcile()
            if not report.clear:
                raise BrokerError("Resolve working or uncertain orders before resuming")
            if not self.config.dry_run:
                if not any(
                    s["regular"] and s["start"] <= at.timestamp() < s["end"]
                    for s in series.sessions
                ):
                    raise BrokerError("Resume requires a provider-confirmed regular session")
                ledger = self.broker.strategy_ledger(self.run_id)
                held = next(
                    (
                        money(p.get("quantity"))
                        for p in report.snapshot.positions
                        if p.get("con_id") == series.instrument_id
                    ),
                    Decimal(0),
                )
                owned = dict(ledger.positions).get(series.instrument_id, Decimal(0))
                if not ledger.complete or held is None or held != owned:
                    raise BrokerError(
                        "Strategy fills and account holdings differ; reconcile manually"
                    )
                risk, at = self._risk_snapshot(report.snapshot, at, real_clock=real_clock)
                pnl = self._fresh_pnl(risk, at)
                if pnl is None or self._pnl_baseline is None:
                    raise BrokerError("Fresh broker P&L is required to resume")
                reason = self._loss_reason(pnl)
                if reason:
                    raise BrokerError(reason)
                self._orders = max(self._orders, self._intent_count())
                if self._orders >= self.config.max_orders:
                    raise BrokerError("Per-run order limit reached")
                self._lease.acquire()
                try:
                    self._check_restored_state()
                except Exception:
                    self._lease.release()
                    raise
            self._restored_checkpoint = None
            self._seen = bars[-1].timestamp
            self.status, self.reason = "running", ""
            self._log("runner_resume", skipped_through=self._seen.isoformat())
            self._checkpoint()

    def flatten_plan(
        self, series: BarSeries, quote: Quote, *, at: datetime | None = None
    ) -> dict[str, Any]:
        """Read-only bounded exit plan from fresh reconciliation and owned fills."""
        real_clock = at is None
        at = at or datetime.now(UTC)
        with self._lock:
            if self.config.dry_run or self._seen is None:
                raise BrokerError("Flatten requires a previously started execution run")
            if at.utcoffset() is None:
                raise ValueError("Runner clock must be timezone aware")
            report = self.broker.reconcile()
            if real_clock:
                at = datetime.now(UTC)
            if not report.clear:
                raise BrokerError("Resolve working or uncertain orders before flattening")
            if (
                series.symbol != self.config.symbol
                or series.instrument_id is None
                or series.instrument_id != self._instrument_id
                or quote.instrument.symbol != self.config.symbol
                or quote.instrument.instrument_id != series.instrument_id
            ):
                raise BrokerError("Flatten feed/quote instrument mismatch")
            ledger = self.broker.strategy_ledger(self.run_id)
            owned = dict(ledger.positions).get(series.instrument_id, Decimal(0))
            held = next(
                (
                    money(p.get("quantity"))
                    for p in report.snapshot.positions
                    if p.get("con_id") == series.instrument_id
                ),
                Decimal(0),
            )
            if (
                not ledger.complete
                or held is None
                or held != owned
                or owned != owned.to_integral_value()
                or not 0 <= owned <= self.config.quantity
            ):
                raise BrokerError(
                    "Strategy fills and account holdings differ; no flatten order sent"
                )
            if owned == 0:
                return dict(run_id=self.run_id, symbol=self.config.symbol, quantity=0,
                            con_id=series.instrument_id, side="SELL", limit_price=None,
                            checked_at=at.isoformat())
            receipts = dict(quote.field_received_at)
            if (
                quote.market_data_type != "live"
                or quote.is_delayed
                or quote.crossed
                or quote.status != "active"
                or quote.bid is None
                or quote.ask is None
                or quote.bid <= 0
                or quote.ask <= 0
                or not all(
                    k in receipts
                    and 0 <= (at - receipts[k]).total_seconds() <= self.config.max_data_age
                    for k in ("bid", "ask")
                )
            ):
                raise BrokerError("Flatten requires a fresh live bid/ask")
            if not any(
                s["regular"] and s["start"] <= at.timestamp() < s["end"] for s in series.sessions
            ):
                raise BrokerError("Flatten requires a provider-confirmed regular session")
            price = (Decimal(str(quote.bid)) * Decimal(".9995")).quantize(
                Decimal(".01"), rounding=ROUND_DOWN
            )
            if owned > self._quantity_cap or price * owned > self._order_cap:
                raise BrokerError("Restored run's order quantity/notional cap exceeded")
            return dict(
                run_id=self.run_id, symbol=self.config.symbol, con_id=series.instrument_id,
                quantity=int(owned), side="SELL", limit_price=str(price),
                checked_at=at.isoformat(), bid=quote.bid, ask=quote.ask,
                max_order_value=str(self._order_cap),
            )

    def flatten(self, series: BarSeries, quote: Quote, *, at: datetime | None = None) -> int | None:
        """Pause and submit one bounded limit sell for reconciled strategy holdings.

        Returns an order ID, not confirmed liquidation. No baseline reset or
        automatic replacement. External/mixed positions remain refused.
        """
        with self._lock:
            self._require_execution()
            if self.config.dry_run or self._seen is None:
                raise BrokerError("Flatten requires a previously started execution run")
            self._lease.acquire()
            try:
                self._check_restored_state()
            except Exception:
                self._lease.release()
                raise
            self._restored_checkpoint = None
            self.pause("Explicit strategy flatten requested")
            plan = self.flatten_plan(series, quote, at=at)
            if plan["quantity"] == 0:
                return None
            oid = self.broker.submit_limit(
                self.config.symbol,
                "SELL",
                plan["quantity"],
                float(plan["limit_price"]),
                tag=self.run_id,
                key="flatten:" + uuid4().hex,
            )
            self._orders += 1
            self._log("runner_flatten", order_id=oid,
                      quantity=str(plan["quantity"]), limit_price=plan["limit_price"])
            self._checkpoint()
            return oid

    def step(self, series: BarSeries, quote: Quote, *, at: datetime | None = None) -> int | None:
        real_clock = at is None
        at = at or datetime.now(UTC)
        with self._lock:
            if self.status != "running":
                return None
            if not self.config.dry_run and self.broker.readonly:
                self.pause("Broker is read-only")
                return None
            if at.utcoffset() is None:
                raise ValueError("Runner clock must be timezone aware")
            if (
                series.symbol != self.config.symbol
                or series.instrument_id != self._instrument_id
                or series.interval != "1min"
                or not series.live
                or quote.instrument.symbol != self.config.symbol
                or quote.instrument.instrument_id != series.instrument_id
            ):
                self.pause("Feed/quote instrument mismatch")
                return None
            snap = self.broker.snapshot()
            if not snap.complete or series.error or series.connection_state != "subscribed":
                self.pause("Account or market feed disconnected/incomplete")
                return None
            with series._lock:
                live_stamp = series.last_live_update
                bars = series.snapshot()
            # Sample the clock after the feed receipt. An API callback can arrive
            # during the account snapshot; comparing it with the earlier entry
            # clock falsely classifies a healthy feed as future/stale.
            if real_clock:
                at = datetime.now(UTC)
            day = at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if day != self._day:
                self.pause("New trading date: reconcile and start a new session baseline")
                return None
            age = (at - live_stamp).total_seconds() if live_stamp else None
            if age is None or not 0 <= age <= self.config.max_data_age:
                self._log(
                    "runner_feed_check_failed",
                    checked_at=at.isoformat(),
                    last_live_update=live_stamp.isoformat() if live_stamp else None,
                    age=age,
                    max_data_age=self.config.max_data_age,
                )
                self.pause(
                    "No fresh live bar callback "
                    f"(age={age:.3f}s, limit={self.config.max_data_age:g}s)"
                    if age is not None
                    else "No fresh live bar callback (no callback received)"
                )
                return None
            if not bars:
                self.pause("Live bar history is empty")
                return None
            current = bars[-1].timestamp
            assert isinstance(current, datetime)
            if self._seen is None or current <= self._seen:
                return None
            previous = self._seen
            self._seen = current  # Commit observation before evaluating strategy or submitting.
            self._checkpoint()  # Durable candle cursor precedes every possible order intent.
            if current - previous != timedelta(minutes=1) or (at - current).total_seconds() > 30:
                self.pause("Missed/stale candle boundary; no catch-up orders")
                return None
            # Require provider regular-session evidence for both closed candle and decision time.
            if not any(
                s["regular"] and s["start"] <= previous.timestamp() and at.timestamp() < s["end"]
                for s in series.sessions
            ):
                self.pause("No provider-confirmed regular session for this decision")
                return None
            receipts = dict(quote.field_received_at)
            if (
                quote.market_data_type != "live"
                or quote.is_delayed
                or quote.crossed
                or quote.status != "active"
                or quote.bid is None
                or quote.ask is None
                or quote.bid <= 0
                or quote.ask <= 0
                or not all(
                    k in receipts
                    and 0 <= (at - receipts[k]).total_seconds() <= self.config.max_data_age
                    for k in ("bid", "ask")
                )
            ):
                self.pause("Quote is stale, missing, delayed, frozen or crossed")
                return None
            completed = tuple(b for b in bars if b.timestamp < current)
            if len(completed) < self.config.window or completed[-1].timestamp != previous:
                self.pause("Completed-bar history is incomplete")
                return None
            # Require a contiguous trailing window; do not bridge overnight gaps.
            trailing = completed[-self.config.window :]
            times = [b.timestamp for b in trailing if isinstance(b.timestamp, datetime)]
            if len(times) != len(trailing) or any(
                times[i + 1] - times[i] != timedelta(minutes=1) for i in range(len(times) - 1)
            ):
                self.pause("Gap in SMA warmup; wait for a complete contiguous window")
                return None
            target = (
                self.config.quantity
                if above_sma([b.close for b in trailing], self.config.window)[-1]
                else 0
            )
            self._log(
                "signal",
                bar_time=previous.isoformat(),
                target=target,
                dry_run=self.config.dry_run,
                close=completed[-1].close,
                bid=quote.bid,
                ask=quote.ask,
            )
            if self.config.dry_run:
                return None
            try:
                snap, at = self._risk_snapshot(snap, at, real_clock=real_clock)
            except BrokerError as exc:
                self.pause(f"Broker P&L refresh failed: {exc}")
                return None
            live_stamp = series.last_live_update
            if real_clock:
                at = datetime.now(UTC)
            pnl = self._fresh_pnl(snap, at)
            if pnl is None or self._pnl_baseline is None:
                self.pause("Broker P&L baseline/data unavailable or stale")
                return None
            # A blocking refresh must not make previously fresh quote/bar inputs
            # eligible after their freshness window or decision boundary expires.
            if (
                not all(
                    0 <= (at - receipts[k]).total_seconds() <= self.config.max_data_age
                    for k in ("bid", "ask")
                )
                or live_stamp is None
                or not 0
                <= (at - live_stamp).total_seconds()
                <= self.config.max_data_age
                or not 0 <= (at - current).total_seconds() <= 30
            ):
                self.pause("Market inputs became stale while refreshing broker P&L")
                return None
            reason = self._loss_reason(pnl)
            if reason:
                self.pause(reason + "; stop does not liquidate positions")
                return None
            if self.broker.funding()["pending_owned_order"]:
                self._log("signal_skipped", reason="Owned order still unresolved")
                return None
            selected = [p for p in snap.positions if p.get("con_id") == series.instrument_id]
            if any(money(p.get("quantity")) is None for p in selected):
                self.pause("Selected-symbol position quantity is unknown")
                return None
            held = sum(
                (
                    money(p.get("quantity")) or Decimal(0)
                    for p in snap.positions
                    if p.get("con_id") == series.instrument_id
                ),
                Decimal(0),
            )
            if held != held.to_integral_value() or not 0 <= held <= self.config.quantity:
                self.pause("Unexpected selected-symbol position; reconcile manually")
                return None
            ledger = self.broker.strategy_ledger(self.run_id)
            if not ledger.complete or held != dict(ledger.positions).get(
                series.instrument_id, Decimal(0)
            ):
                self.pause("Account holdings differ from strategy-owned executions")
                return None
            delta = Decimal(target) - held
            if delta == 0:
                return None
            self._orders = max(self._orders, self._intent_count())
            if self._orders >= self.config.max_orders:
                self.pause("Per-run order limit reached")
                return None
            side = "BUY" if delta > 0 else "SELL"
            price = Decimal(str(quote.ask if delta > 0 else quote.bid))
            price *= Decimal("1.0005") if delta > 0 else Decimal(".9995")
            price = price.quantize(Decimal(".01"), rounding=ROUND_UP if delta > 0 else ROUND_DOWN)
            if abs(delta) > self._quantity_cap or price * abs(delta) > self._order_cap:
                self.pause("Run's persisted order quantity/notional cap exceeded")
                return None
            try:
                oid = self.broker.submit_limit(
                    self.config.symbol,
                    side,
                    int(abs(delta)),
                    float(price),
                    tag=self.run_id,
                    key=self.run_id[:12] + ":" + str(int(previous.timestamp())),
                )
            except BrokerError as exc:
                self.pause(str(exc))
                return None
            self._orders += 1
            self._checkpoint()
            return oid

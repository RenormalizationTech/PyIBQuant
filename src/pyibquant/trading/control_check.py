"""Bounded integration-check orchestration; all decisions remain in EquityRunner."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..bars import BarSeries
from ..broker import BrokerError
from .runner import EquityRunner


class RunnerControlCheck:
    """Pause after a live signal, skip a candle, resume with unchanged risk limits.

    Does not submit, cancel or flatten. The operator explicitly launches an execution
    runner; ordinary strategy decisions and stop cleanup retain their normal caps.
    """

    def __init__(self, runner: EquityRunner) -> None:
        if runner.config.dry_run or runner.status != "running":
            raise BrokerError("Control check requires a started execution runner")
        self.runner = runner
        self.phase = "waiting_signal"
        self._paused_at = 0.0
        self._cursor: datetime | None = None
        self._state: tuple[Any, ...] = ()
        self._signal = self._last_signal()

    @property
    def passed(self) -> bool:
        return self.phase == "passed"

    def _last_signal(self) -> int:
        return max((
            e["sequence"] for e in self.runner.broker.journal.events(self.runner.broker.account)
            if e["kind"] == "signal" and e["payload"].get("run_id") == self.runner.run_id
        ), default=0)

    def _protected_state(self) -> tuple[Any, ...]:
        r = self.runner
        return r.run_id, r.config, r._pnl_baseline, r._orders, r._intent_count()

    def tick(
        self, series: BarSeries, *, elapsed: float, at: datetime | None = None
    ) -> str | None:
        if self.passed:
            return None
        r = self.runner
        if self.phase != "paused" and r.status != "running":
            raise BrokerError(f"Control check interrupted by runner {r.status}: {r.reason}")
        signal = self._last_signal()
        if self.phase == "waiting_signal" and signal > self._signal:
            if r.broker.funding()["pending_owned_order"]:
                return None  # Do not pause/resume over an unresolved submission.
            self._signal = signal
            self._state = self._protected_state()
            self._cursor = r._seen
            self._paused_at = elapsed
            r.pause("Bounded execution control check: skip one live candle")
            self.phase = "paused"
            r._log("runner_control_check", phase=self.phase, pause_seconds=65)
            return "paused"
        if self.phase == "paused":
            if (
                r.status != "paused" or r._seen != self._cursor
                or self._protected_state() != self._state or signal != self._signal
            ):
                raise BrokerError("Runner state or signals changed while deliberately paused")
            bars = series.snapshot()
            current = bars[-1].timestamp if bars else None
            if (
                elapsed - self._paused_at < 65 or not isinstance(current, datetime)
                or self._cursor is None or current <= self._cursor
            ):
                return None
            r.resume(series, at=at)
            if self._protected_state() != self._state:
                r.pause("Control check found changed baseline/configuration/order budget")
                raise BrokerError("Resume changed protected runner state")
            self.phase = "resumed"
            r._log("runner_control_check", phase=self.phase, skipped_through=str(r._seen))
            return "resumed"
        if self.phase == "resumed" and signal > self._signal:
            self.phase = "passed"
            r._log("runner_control_check", phase=self.phase)
            return "passed"
        return None

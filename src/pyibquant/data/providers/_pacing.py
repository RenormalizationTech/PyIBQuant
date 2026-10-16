"""Connection-local IBKR history pacing; state is retained across reconnects."""

from __future__ import annotations

from threading import Event, Lock
from time import monotonic
from typing import Any

from ...errors import ConnectionError


class HistoryPacer:
    def __init__(self) -> None:
        self._lock = Lock()
        self._last: float | None = None
        self._last_small: float | None = None
        self._identical: dict[tuple[Any, ...], float] = {}

    def acquire(self, key: tuple[Any, ...], *, small: bool, stop: Event) -> None:
        with self._lock:
            now = monotonic()
            wait = max(0.0, (self._last + 0.25 - now) if self._last is not None else 0.0)
            if small:
                # 11 seconds keeps our small-bar rate below 60 requests / 10 minutes
                # and below 6 requests / 2 seconds, including long downloads.
                if self._last_small is not None:
                    wait = max(wait, self._last_small + 11.0 - now)
                if key in self._identical:
                    wait = max(wait, self._identical[key] + 15.1 - now)
            if stop.wait(wait):
                raise ConnectionError("Historical request interrupted: Market connection closed")
            now = monotonic()
            self._last = now
            self._identical = {k: v for k, v in self._identical.items() if now - v < 15.1}
            if small:
                self._last_small = now
                self._identical[key] = now

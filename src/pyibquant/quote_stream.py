"""Independent quote subscription ownership and cursor-based observation."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from types import TracebackType

from .quotes import Quote, _QuoteState


class QuoteStream:
    """One requested quote subscription, not a tick archive or execution signal.

    latest() copies the accumulated fields. Independent consumers use their own
    sequence cursor with wait_for_update(); intermediate callbacks can coalesce.
    No user code or file IO executes on the IBKR callback thread. Close explicitly
    or use a context manager. Disconnects end the handle; resubscribe explicitly.
    """

    def __init__(self, state: _QuoteState, cancel: Callable[[], None]) -> None:
        self._state = state
        self._cancel = cancel

    def latest(self) -> Quote:
        return self._state.snapshot()

    def wait_for_update(self, after: int = 0, *, timeout: float | None = None) -> Quote:
        """Wait for a newer sequence or stream end; timeout returns current state.

        A returned sequence equal to after means no newer callback was observed.
        Closing, permission failures and disconnects wake all waiting consumers.
        """
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ValueError('after must be a nonnegative integer sequence')
        if timeout is not None and (not isfinite(timeout) or timeout < 0):
            raise ValueError('timeout must be nonnegative and finite, or None')
        with self._state.changed:
            self._state.changed.wait_for(
                lambda: self._state.sequence > after or self._state.completed_at is not None,
                timeout=timeout,
            )
            return self._state.snapshot()

    @property
    def closed(self) -> bool:
        with self._state.lock:
            return self._state.completed_at is not None

    def close(self) -> None:
        self._cancel()

    def __enter__(self) -> QuoteStream:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

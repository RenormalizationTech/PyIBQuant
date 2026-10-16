"""Small public entry point; provider imports are lazy."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from types import TracebackType
from typing import TYPE_CHECKING

from .bars import BarSeries
from .data.cache import HistoricalCache
from .data.history import HistoryBoundary, normalize_range
from .errors import PyIBQuantError
from .quotes import Option, Quote

if TYPE_CHECKING:
    from .data.providers.ibkr import IBKRProvider


class Market:
    def __init__(self, provider: IBKRProvider) -> None:
        self._provider = provider
        self._operation_lock = RLock()
        self._subscriptions: dict[BarSeries, None] = {}
        self._stop = Event()
        self._recovery_thread: Thread | None = None

    @classmethod
    def ibkr(
        cls,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 71,
        timeout: float = 30,
        *,
        cache_dir: str | Path | None = None,
        cache_max_age: float = 86400,
        refresh_cache: bool = False,
        reconnect: bool = True,
    ) -> Market:
        """Connect to TWS/IB Gateway. This adapter only requests market data."""
        from .data.providers.ibkr import IBKRProvider

        if not 1 <= port <= 65535 or client_id < 0 or timeout <= 0:
            raise ValueError("Use a valid port, nonnegative client_id, and positive timeout")
        cache = HistoricalCache(cache_dir, max_age=cache_max_age) if cache_dir is not None else None
        provider = IBKRProvider(
            host, port, client_id, timeout, cache=cache, refresh_cache=refresh_cache
        )
        provider.open()
        market = cls(provider)
        if reconnect:
            market._recovery_thread = Thread(
                target=market._maintain_connection, daemon=True, name="pyibquant-reconnect"
            )
            market._recovery_thread.start()
        return market

    def quote(
        self, symbol: str | Option, *, primary_exchange: str = "",
        market_data_type: str = "live",
    ) -> Quote:
        """Return one immutable Level-one snapshot, separate from historical bars.

        Uses standard reqMktData, never a regulatory snapshot. Missing fields stay
        None; actual delayed/frozen feed type and local receipt times are explicit.
        Snapshot completion normally takes about 11 seconds; use a longer timeout.
        A disconnect raises instead of silently reissuing the snapshot request.
        """
        with self._operation_lock:
            provider = self._provider
        return provider.quote(symbol, primary_exchange=primary_exchange,
                              market_data_type=market_data_type)

    def bars(
        self,
        symbol: str,
        *,
        interval: str = "1min",
        duration: str | None = None,
        start: HistoryBoundary | None = None,
        end: HistoryBoundary | None = None,
        live: bool = False,
        regular_hours: bool = True,
        primary_exchange: str = "",
        refresh: bool = False,
        include_sessions: bool = False,
    ) -> BarSeries:
        """Request bars; opt into separate regular/extended session-schedule queries."""
        if not isinstance(include_sessions, bool):
            raise ValueError("include_sessions must be a boolean")
        bounds = None
        if start is not None or end is not None:
            if start is None or end is None:
                raise ValueError("Provide both start and end for a historical range")
            if duration is not None or live:
                raise ValueError("Historical ranges cannot be combined with duration or live=True")
            bounds = normalize_range(start, end, interval)
        if bounds is not None:
            # Keep a single provider generation for this dataset, but do not hold
            # the connection/control lock through a potentially lengthy download.
            with self._operation_lock:
                provider = self._provider
            series = provider.bars_range(
                symbol, interval=interval, bounds=bounds, regular_hours=regular_hours,
                primary_exchange=primary_exchange, refresh=refresh,
            )
            series.include_sessions = include_sessions
            if include_sessions:
                if isinstance(bounds.end, datetime):
                    provider.load_sessions(series, before=bounds.end)
                else:
                    provider.load_sessions(series)
            return series
        with self._operation_lock:
            series = self._provider.bars(
                symbol,
                interval=interval,
                duration="1 D" if duration is None else duration,
                live=live,
                regular_hours=regular_hours,
                primary_exchange=primary_exchange,
                refresh=refresh,
            )
            series.include_sessions = include_sessions
            if include_sessions:
                self._provider.load_sessions(series)
            if live:
                self._subscriptions[series] = None
            return series

    def _recover(self) -> None:
        """Reopen the socket and restore series in place, preserving chart identity."""
        with self._operation_lock:
            if self._stop.is_set() or not self._subscriptions:
                return
            old = self._provider
            for series in self._subscriptions:
                series.connection_state = "reconnecting"
                series.status = "Reconnecting to IBKR; existing bars retained"
            old.close()
            replacement = old.new_connection()
            self._provider = replacement
            try:
                replacement.open()
                for series in self._subscriptions:
                    if self._stop.is_set():
                        replacement.close()
                        return
                    replacement.restore_series(series)
                    if series.include_sessions:
                        replacement.load_sessions(series)
            except (PyIBQuantError, OSError) as exc:
                replacement.close()
                for series in self._subscriptions:
                    series.connection_state = "reconnecting"
                    series.status = "IBKR reconnect failed; retrying automatically"
                    series.error = str(exc)
                raise

    def _maintain_connection(self) -> None:
        delay = 1.0
        next_schedule_check = monotonic() + 300
        while not self._stop.wait(delay):
            try:
                with self._operation_lock:
                    active = list(self._subscriptions)
                    broken = active and (
                        not self._provider.isConnected() or any(
                            s.connection_state in {"disconnected", "reconnecting"} for s in active
                        )
                    )
                    if broken:
                        self._recover()
                    if monotonic() >= next_schedule_check:
                        for series in active:
                            if series.include_sessions:
                                self._provider.load_sessions(series, recent_only=True)
                        next_schedule_check = monotonic() + 300
                delay = 1.0
            except (PyIBQuantError, OSError):
                delay = min(30.0, delay * 2)

    def cancel(self, series: BarSeries) -> None:
        """Cancel a subscription, including automatic restoration after disconnects."""
        with self._operation_lock:
            self._subscriptions.pop(series, None)
            self._provider.cancel_bars(series)

    def serve(
        self, bars: BarSeries, *, port: int = 0, open_browser: bool = True,
        include_sessions: bool = True,
    ) -> None:
        """Serve a chart until Ctrl+C, enabling session enrichment by default."""
        from .visualization.chart import serve_chart

        if not isinstance(include_sessions, bool):
            raise ValueError("include_sessions must be a boolean")
        with self._operation_lock:
            enabled = bars.include_sessions
            bars.include_sessions = include_sessions
            if include_sessions and not enabled:
                if isinstance(bars.requested_end, datetime):
                    self._provider.load_sessions(bars, before=bars.requested_end)
                else:
                    self._provider.load_sessions(bars)

        def load(symbol: str, interval: str, duration: str, regular_hours: bool) -> BarSeries:
            return self.bars(
                symbol,
                interval=interval,
                duration=duration,
                live=bars.live,
                regular_hours=regular_hours,
                primary_exchange=bars.primary_exchange if symbol.upper() == bars.symbol else "",
                include_sessions=include_sessions,
            )

        serve_chart(
            bars,
            port=port,
            open_browser=open_browser,
            loader=load,
            cancel=self.cancel,
            history_loader=self.load_older,
        )

    def load_older(self, bars: BarSeries, *, refresh: bool = False) -> int:
        """Fetch one older page, retaining existing candles and any live subscription."""
        if bars.requested_start is not None:
            raise ValueError("Fixed-range datasets cannot load older bars; request a new range")
        with self._operation_lock:
            previous = bars.snapshot()
            added = self._provider.load_older(bars, refresh=refresh)
            before = previous[0].timestamp if previous else None
            if bars.include_sessions and added and isinstance(before, datetime):
                self._provider.load_sessions(bars, before=before)
            return added

    @property
    def cache(self) -> HistoricalCache | None:
        """Configured cache, or None when historical caching is disabled."""
        return self._provider.cache

    def close(self) -> None:
        self._stop.set()
        self._provider.close()
        if self._recovery_thread is not None:
            self._recovery_thread.join(timeout=self._provider.timeout + 3)
        with self._operation_lock:
            self._subscriptions.clear()

    def __enter__(self) -> Market:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

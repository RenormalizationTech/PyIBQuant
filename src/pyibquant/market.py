"""Small public entry point; provider imports are lazy."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

from .bars import BarSeries
from .data.cache import HistoricalCache

if TYPE_CHECKING:
    from .data.providers.ibkr import IBKRProvider


class Market:
    def __init__(self, provider: IBKRProvider) -> None:
        self._provider = provider

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
        return cls(provider)

    def bars(
        self,
        symbol: str,
        *,
        interval: str = "1min",
        duration: str = "1 D",
        live: bool = False,
        regular_hours: bool = True,
        primary_exchange: str = "",
        refresh: bool = False,
    ) -> BarSeries:
        return self._provider.bars(
            symbol,
            interval=interval,
            duration=duration,
            live=live,
            regular_hours=regular_hours,
            primary_exchange=primary_exchange,
            refresh=refresh,
        )

    def serve(self, bars: BarSeries, *, port: int = 0, open_browser: bool = True) -> None:
        """Serve an in-memory chart on localhost until Ctrl+C. Keeps live requests open."""
        from .visualization.chart import serve_chart

        def load(symbol: str, interval: str, duration: str, regular_hours: bool) -> BarSeries:
            return self.bars(
                symbol,
                interval=interval,
                duration=duration,
                live=bars.live,
                regular_hours=regular_hours,
                primary_exchange=bars.primary_exchange if symbol.upper() == bars.symbol else "",
            )

        serve_chart(
            bars,
            port=port,
            open_browser=open_browser,
            loader=load,
            cancel=self._provider.cancel_bars,
            history_loader=self.load_older,
        )

    def load_older(self, bars: BarSeries, *, refresh: bool = False) -> int:
        """Fetch one older page, retaining existing candles and any live subscription."""
        return self._provider.load_older(bars, refresh=refresh)

    @property
    def cache(self) -> HistoricalCache | None:
        """Configured cache, or None when historical caching is disabled."""
        return self._provider.cache

    def close(self) -> None:
        self._provider.close()

    def __enter__(self) -> Market:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

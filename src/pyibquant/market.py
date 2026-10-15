"""Small public entry point; provider imports are lazy."""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING

from .bars import BarSeries

if TYPE_CHECKING:
    from .data.providers.ibkr import IBKRProvider


class Market:
    def __init__(self, provider: IBKRProvider) -> None:
        self._provider = provider

    @classmethod
    def ibkr(
        cls, host: str = "127.0.0.1", port: int = 7497, client_id: int = 71, timeout: float = 30
    ) -> Market:
        """Connect to TWS/IB Gateway. This adapter only requests market data."""
        from .data.providers.ibkr import IBKRProvider

        if not 1 <= port <= 65535 or client_id < 0 or timeout <= 0:
            raise ValueError("Use a valid port, nonnegative client_id, and positive timeout")
        provider = IBKRProvider(host, port, client_id, timeout)
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
    ) -> BarSeries:
        return self._provider.bars(
            symbol,
            interval=interval,
            duration=duration,
            live=live,
            regular_hours=regular_hours,
            primary_exchange=primary_exchange,
        )

    def serve(self, bars: BarSeries, *, port: int = 0, open_browser: bool = True) -> None:
        """Serve an in-memory chart on localhost until Ctrl+C. Keeps live requests open."""
        from .visualization.chart import serve_chart

        def load(symbol: str, interval: str, duration: str) -> BarSeries:
            return self.bars(
                symbol,
                interval=interval,
                duration=duration,
                live=bars.live,
                regular_hours=bars.regular_hours,
                primary_exchange=bars.primary_exchange if symbol.upper() == bars.symbol else "",
            )

        serve_chart(
            bars,
            port=port,
            open_browser=open_browser,
            loader=load,
            cancel=self._provider.cancel_bars,
        )

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

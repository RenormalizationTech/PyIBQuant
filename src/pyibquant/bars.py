"""Provider-independent bars; intraday timestamps are always UTC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class Bar:
    timestamp: datetime | date
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if isinstance(self.timestamp, datetime) and self.timestamp.utcoffset() is None:
            raise ValueError("Intraday timestamps must be timezone-aware")
        if not all(
            isfinite(value) for value in (self.open, self.high, self.low, self.close, self.volume)
        ):
            raise ValueError("OHLCV values must be finite")

    def chart_data(self) -> dict[str, Any]:
        time = (
            int(self.timestamp.timestamp())
            if isinstance(self.timestamp, datetime)
            else self.timestamp.isoformat()
        )
        return dict(
            time=time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


class BarSeries:
    """Thread-safe snapshot of historical bars and optional incoming updates."""

    def __init__(self, symbol: str, interval: str, *, live: bool = False) -> None:
        self.symbol = symbol
        self.interval = interval
        self.live = live
        self.provider = "IBKR"
        self.duration = "1 D"
        self.regular_hours = True
        self.primary_exchange = ""
        self.status = "Loading historical data"
        self.error: str | None = None
        self.warnings: list[str] = []
        self._bars: dict[datetime | date, Bar] = {}
        self._lock = RLock()

    def update(self, bar: Bar) -> None:
        with self._lock:
            self._bars[bar.timestamp] = bar

    def __len__(self) -> int:
        with self._lock:
            return len(self._bars)

    def snapshot(self) -> tuple[Bar, ...]:
        with self._lock:
            return tuple(self._bars[key] for key in sorted(self._bars))

    def payload(self) -> dict[str, Any]:
        with self._lock:
            return dict(
                duration=self.duration,
                symbol=self.symbol,
                interval=self.interval,
                provider=self.provider,
                live=self.live,
                status=self.status,
                error=self.error,
                warnings=list(self.warnings),
                bars=[bar.chart_data() for bar in self.snapshot()],
            )

    def plot(self, path: str | Path = "charts/chart.html", *, open_browser: bool = True) -> Path:
        """Export an HTML snapshot. Use Market.serve() for live updates."""
        from .visualization.chart import write_chart

        return write_chart(self, path, open_browser=open_browser)

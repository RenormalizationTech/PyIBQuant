"""Provider-independent bars; intraday timestamps are always UTC."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pandas import DataFrame

_EXPORT_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def _iso_timestamp(stamp: date | datetime) -> str:
    return (stamp.astimezone(UTC) if isinstance(stamp, datetime) else stamp).isoformat()


@dataclass(frozen=True)
class Bar:
    timestamp: datetime | date
    open: float
    high: float
    low: float
    close: float
    volume: float | None

    def __post_init__(self) -> None:
        if isinstance(self.timestamp, datetime) and self.timestamp.utcoffset() is None:
            raise ValueError("Intraday timestamps must be timezone-aware")
        if not all(
            isfinite(value) for value in (self.open, self.high, self.low, self.close)
        ) or self.volume is not None and not isfinite(self.volume):
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
        self.instrument_id: int | None = None
        self.asset_type: str | None = None
        self.currency: str | None = None
        self.exchange: str | None = None
        self.multiplier: float | None = None
        self.option_metadata: dict[str, Any] | None = None
        self.data_type: str | None = None
        self.adjustment: str | None = None
        self.session_timezone: str | None = None
        self.duration = "1 D"
        self.regular_hours = True
        self.primary_exchange = ""
        self.status = "Loading historical data"
        self.error: str | None = None
        self.history_exhausted = False
        self.cache_hit = False
        self.cache_created_at: str | None = None
        self.history_cache_hit = False
        self.warnings: list[str] = []
        self.sessions: list[dict[str, Any]] = []
        self.include_sessions = False
        self.schedule_error: str | None = None
        self.last_update: datetime | None = None
        self.last_live_update: datetime | None = None
        self.connection_state = "connecting" if live else "snapshot"
        self.requested_start: date | datetime | None = None
        self.requested_end: date | datetime | None = None
        self.download_complete: bool | None = None
        self.download_pages = 0
        self.download_cached_pages = 0
        self.empty_windows: list[tuple[date | datetime, date | datetime]] = []
        self._bars: dict[datetime | date, Bar] = {}
        self._lock = RLock()

    def update(self, bar: Bar, *, live: bool = False) -> None:
        with self._lock:
            self._bars[bar.timestamp] = bar
            self.last_update = datetime.now(UTC)
            if live:
                self.last_live_update = self.last_update

    def merge_sessions(self, sessions: Iterable[dict[str, Any]]) -> None:
        with self._lock:
            merged = {(s["start"], s["end"], s["regular"]): s for s in self.sessions}
            merged.update({(s["start"], s["end"], s["regular"]): s for s in sessions})
            self.sessions = sorted(merged.values(), key=lambda s: s["start"])

    def __len__(self) -> int:
        with self._lock:
            return len(self._bars)

    def prepend(self, bars: Iterable[Bar]) -> int:
        """Merge older timestamps atomically; never replace existing/live candles."""
        with self._lock:
            earliest = min(self._bars) if self._bars else None
            count = len(self._bars)
            for bar in bars:
                if earliest is None or bar.timestamp < earliest:
                    self._bars.setdefault(bar.timestamp, bar)
            return len(self._bars) - count

    def snapshot(self) -> tuple[Bar, ...]:
        with self._lock:
            return tuple(self._bars[key] for key in sorted(self._bars))

    def to_records(self) -> list[dict[str, Any]]:
        """Copy one ordered snapshot to OHLCV records with native UTC/date timestamps."""
        return [dict(
            timestamp=(
                bar.timestamp.astimezone(UTC)
                if isinstance(bar.timestamp, datetime) else bar.timestamp
            ),
            open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
        ) for bar in self.snapshot()]

    def to_csv(self, path: str | Path) -> Path:
        """Atomically save one OHLCV snapshot; ISO timestamps keep UTC offsets/dates."""
        records = self.to_records()
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=target.parent,
                prefix=f".{target.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                writer = csv.DictWriter(stream, fieldnames=_EXPORT_COLUMNS)
                writer.writeheader()
                for record in records:
                    writer.writerow({**record, "timestamp": record["timestamp"].isoformat()})
            os.replace(temporary, target)
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def to_dataframe(self) -> DataFrame:
        """Return an independent pandas OHLCV frame indexed by UTC datetimes/dates.

        Install pyibquant[pandas] to use this optional export. Date-only bars keep
        Python dates instead of manufacturing midnight timestamps.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "DataFrame export requires pandas. Install it with: "
                "python -m pip install 'pyibquant[pandas]'"
            ) from exc
        frame = pd.DataFrame.from_records(self.to_records(), columns=_EXPORT_COLUMNS)
        frame = frame.astype(dict.fromkeys(_EXPORT_COLUMNS[1:], "float64"))
        return frame.set_index("timestamp")

    def metadata(self) -> dict[str, Any]:
        """Copy JSON-compatible identity/query metadata; coverage is not a gap audit."""
        with self._lock:
            bars = self.snapshot()
            date_only = self.interval in {"1d", "1w", "1y"}
            fixed = self.requested_start is not None
            result = dict(
                schema_version=1, provider=self.provider, symbol=self.symbol,
                instrument_id=self.instrument_id, asset_type=self.asset_type,
                currency=self.currency, exchange=self.exchange,
                primary_exchange=self.primary_exchange, multiplier=self.multiplier,
                interval=self.interval, data_type=self.data_type, adjustment=self.adjustment,
                regular_hours=self.regular_hours, session_timezone=self.session_timezone,
                timestamp_kind="date" if date_only else "datetime",
                timestamp_timezone=None if date_only else "UTC",
                query=dict(
                    mode="range" if fixed else "lookback",
                    duration=None if fixed else self.duration,
                    start=self.requested_start.isoformat() if self.requested_start else None,
                    end=self.requested_end.isoformat() if self.requested_end else None,
                    boundaries="start_inclusive_end_exclusive" if fixed else None,
                ),
                coverage=dict(
                    rows=len(bars), first=_iso_timestamp(bars[0].timestamp) if bars else None,
                    last=_iso_timestamp(bars[-1].timestamp) if bars else None,
                    gaps="not_verified", bar_finality="not_verified",
                ),
                download=dict(
                    complete=self.download_complete, pages=self.download_pages,
                    cached_pages=self.download_cached_pages,
                    empty_windows=[(start.isoformat(), end.isoformat())
                                   for start, end in self.empty_windows],
                ),
                last_received_at=self.last_update.isoformat() if self.last_update else None,
                cache_hit=self.cache_hit, cache_created_at=self.cache_created_at,
                include_sessions=self.include_sessions, error=self.error,
                sessions=[dict(session) for session in self.sessions],
                schedule_error=self.schedule_error,
                warnings=list(self.warnings),
            )
            if self.option_metadata is not None:
                result['option'] = deepcopy(self.option_metadata)
                result['volume_available'] = self.data_type == 'TRADES'
            return result

    def payload(self) -> dict[str, Any]:
        with self._lock:
            return dict(
                duration=self.duration,
                symbol=self.symbol,
                interval=self.interval,
                provider=self.provider,
                live=self.live,
                regular_hours=self.regular_hours,
                status=self.status,
                error=self.error,
                history_exhausted=self.history_exhausted,
                cache_hit=self.cache_hit,
                cache_created_at=self.cache_created_at,
                history_cache_hit=self.history_cache_hit,
                warnings=list(self.warnings),
                sessions=[dict(session) for session in self.sessions],
                include_sessions=self.include_sessions,
                schedule_error=self.schedule_error,
                last_update=self.last_update.isoformat() if self.last_update else None,
                last_live_update=(
                    self.last_live_update.isoformat() if self.last_live_update else None
                ),
                connection_state=self.connection_state,
                requested_start=self.requested_start.isoformat() if self.requested_start else None,
                requested_end=self.requested_end.isoformat() if self.requested_end else None,
                download_complete=self.download_complete,
                download_pages=self.download_pages,
                download_cached_pages=self.download_cached_pages,
                empty_windows=[(start.isoformat(), end.isoformat())
                               for start, end in self.empty_windows],
                bars=[bar.chart_data() for bar in self.snapshot()],
            )

    def plot(self, path: str | Path = "charts/chart.html", *, open_browser: bool = True) -> Path:
        """Export an HTML snapshot. Use Market.serve() for live updates."""
        from .visualization.chart import write_chart

        return write_chart(self, path, open_browser=open_browser)

"""Provider-independent historical query boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

HistoryBoundary = str | date | datetime


@dataclass(frozen=True)
class HistoryRange:
    start: date | datetime
    end: date | datetime

    def contains(self, stamp: date | datetime) -> bool:
        return self.start <= stamp < self.end


def normalize_range(start: HistoryBoundary, end: HistoryBoundary, interval: str) -> HistoryRange:
    """Dates mean NY midnight intraday; calendar bars require date-only bounds."""
    def boundary(value: HistoryBoundary) -> date | datetime:
        if isinstance(value, str):
            text = value
            try:
                value = date.fromisoformat(text)
            except ValueError:
                try:
                    value = datetime.fromisoformat(text)
                except ValueError as exc:
                    raise ValueError("Use an ISO date or a timezone-aware ISO datetime") from exc
        if not isinstance(value, date):
            raise ValueError("Historical boundaries must be dates or timezone-aware datetimes")
        if interval in {"1d", "1w", "1y"}:
            if isinstance(value, datetime):
                raise ValueError("Daily/weekly/yearly boundaries must be calendar dates")
            return value
        if not isinstance(value, datetime):
            value = datetime.combine(value, time.min, ZoneInfo("America/New_York"))
        if value.utcoffset() is None:
            raise ValueError("Intraday datetime boundaries must include a timezone")
        if value.microsecond:
            raise ValueError("Historical datetime boundaries must use whole seconds")
        return value.astimezone(UTC)

    bounds = HistoryRange(boundary(start), boundary(end))
    if bounds.start >= bounds.end:
        raise ValueError("start must be earlier than the exclusive end")
    return bounds

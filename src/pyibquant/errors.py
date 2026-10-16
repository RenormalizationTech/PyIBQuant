"""Errors callers can handle without importing a provider's SDK."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bars import BarSeries


class PyIBQuantError(Exception):
    """Base error."""


class ConnectionError(PyIBQuantError):
    """TWS connection failed or was lost."""


class DataError(PyIBQuantError):
    """A market-data request failed."""


class RequestTimeout(DataError):
    """The provider did not finish a request in time."""


class HistoricalRangeError(DataError):
    """A range download failed; partial holds completed pages, never a silent success."""

    def __init__(
        self, message: str, partial: BarSeries, *,
        remaining_start: date | datetime, remaining_end: date | datetime,
    ) -> None:
        super().__init__(message)
        self.partial = partial
        self.remaining_start = remaining_start
        self.remaining_end = remaining_end


class CacheError(PyIBQuantError):
    """A local historical cache entry could not be read or written."""

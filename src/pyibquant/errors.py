"""Errors callers can handle without importing a provider's SDK."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bars import BarSeries
    from .dataset import BarDataset


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


class DatasetCollectionError(DataError):
    """A named input failed; completed frozen inputs are explicit, never success.

    The original exception is __cause__; HistoricalRangeError there retains its
    own completed pages and remaining bounds. No automatic retry or save occurs.
    """

    def __init__(self, failed_key: str, completed: Mapping[str, BarDataset], reason: str) -> None:
        super().__init__(f'Dataset {failed_key!r} failed: {reason}')
        self.failed_key = failed_key
        self.completed: Mapping[str, BarDataset] = MappingProxyType(dict(completed))

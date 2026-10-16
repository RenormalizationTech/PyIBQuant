"""Optional, provider-independent historical query cache backed by Parquet."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from ..bars import Bar
from ..errors import CacheError

Query = Mapping[str, str | int | bool]
_METADATA = b"pyibquant.cache"
_PREFIX = "pyibquant-v1-"


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "pyibquant"


@dataclass(frozen=True)
class CacheEntry:
    bars: tuple[Bar, ...]
    created_at: datetime


class HistoricalCache:
    """Exact-query cache. Directory creation is deferred until the first write.

    Fixed-end history expires after max_age seconds (default 24 hours). Queries
    ending 'now' expire after at most five minutes. Live subscriptions bypass it.
    """

    def __init__(self, directory: str | Path | None = None, *, max_age: float = 86400) -> None:
        if not isfinite(max_age) or max_age <= 0:
            raise ValueError("cache max_age must be a positive finite number of seconds")
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ImportError(
                "Historical caching requires: pip install 'pyibquant[cache]'"
            ) from exc
        self._pa, self._pq = pa, pq
        self.directory = Path(directory) if directory is not None else default_cache_dir()
        self.directory = self.directory.expanduser().resolve()
        self.max_age = max_age
        self._schema = pa.schema(
            [
                ("time", pa.string()),
                ("open", pa.float64()),
                ("high", pa.float64()),
                ("low", pa.float64()),
                ("close", pa.float64()),
                ("volume", pa.float64()),
            ]
        )

    @staticmethod
    def _digest(query: Query) -> str:
        value = json.dumps(dict(query), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return sha256(value.encode()).hexdigest()

    def _path(self, query: Query) -> Path:
        return self.directory / f"{_PREFIX}{self._digest(query)}.parquet"

    def _ttl(self, query: Query) -> float:
        return min(self.max_age, 300) if not query.get("end") else self.max_age

    def _metadata(self, value: Mapping[bytes, bytes] | None) -> dict[str, Any]:
        try:
            result = json.loads((value or {})[_METADATA])
            if (
                not isinstance(result, dict)
                or result.get("version") != 1
                or not isinstance(result.get("query"), dict)
                or result.get("timestamp_kind") not in {"date", "datetime"}
                or type(result.get("rows")) is not int
                or result["rows"] <= 0
                or not all(isinstance(result.get(key), str) for key in ("first", "last"))
            ):
                raise ValueError("invalid cache metadata")
            for key in ("created_at", "ttl_seconds"):
                if type(result.get(key)) not in {float, int} or not isfinite(result[key]):
                    raise ValueError("invalid cache age metadata")
            if result["ttl_seconds"] <= 0:
                raise ValueError("invalid cache lifetime")
            return result
        except (KeyError, ValueError, TypeError) as exc:
            raise CacheError("Invalid historical cache metadata") from exc

    def _expired(self, metadata: dict[str, Any]) -> bool:
        age = time.time() - metadata["created_at"]
        return age < 0 or age >= min(metadata["ttl_seconds"], self._ttl(metadata["query"]))

    def get(self, query: Query) -> CacheEntry | None:
        path = self._path(query)
        try:
            # Read the footer first so expired entries do not load their market data.
            parquet = self._pq.ParquetFile(path)
            metadata = self._metadata(parquet.schema_arrow.metadata)
            if metadata["query"] != dict(query):
                raise CacheError("Historical cache query does not match its file")
            if self._expired(metadata):
                return None
            table = parquet.read()
            if table.schema.remove_metadata() != self._schema or table.num_rows != metadata["rows"]:
                raise CacheError("Historical cache schema/row count is invalid")
            date_only = metadata["timestamp_kind"] == "date"
            bars = tuple(
                Bar(
                    date.fromisoformat(row["time"])
                    if date_only
                    else datetime.fromisoformat(row["time"]),
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                )
                for row in table.to_pylist()
            )
            stamps = [bar.timestamp for bar in bars]
            if stamps != sorted(set(stamps)):
                raise CacheError("Historical cache timestamps are not ordered and unique")
            return CacheEntry(bars, datetime.fromtimestamp(metadata["created_at"], UTC))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            raise CacheError(f"Cannot read historical cache entry: {path.name}") from exc

    def put(self, query: Query, bars: Sequence[Bar]) -> None:
        if not bars:  # Do not persist empty results, failures, or 'no history' conclusions.
            return
        path = self._path(query)
        temporary: Path | None = None
        try:
            date_only = not isinstance(bars[0].timestamp, datetime)
            if any((not isinstance(bar.timestamp, datetime)) != date_only for bar in bars):
                raise ValueError("Cache timestamps must have one type")
            if [bar.timestamp for bar in bars] != sorted({bar.timestamp for bar in bars}):
                raise ValueError("Cache bars must be ordered and unique")
            rows = []
            for bar in bars:
                stamp = bar.timestamp
                if isinstance(stamp, datetime):
                    stamp = stamp.astimezone(UTC)
                rows.append({**bar.chart_data(), "time": stamp.isoformat()})
            metadata = dict(
                version=1,
                query=dict(query),
                created_at=time.time(),
                ttl_seconds=self._ttl(query),
                timestamp_kind="date" if date_only else "datetime",
                rows=len(rows),
                first=rows[0]["time"],
                last=rows[-1]["time"],
            )
            table = self._pa.Table.from_pylist(rows, schema=self._schema)
            table = table.replace_schema_metadata({_METADATA: json.dumps(metadata).encode()})
            self.directory.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                dir=self.directory, prefix=".pyibquant-", delete=False
            ) as stream:
                temporary = Path(stream.name)
            self._pq.write_table(table, temporary, compression="snappy")
            os.replace(temporary, path)
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            raise CacheError(f"Cannot write historical cache entry: {path.name}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def inspect(self) -> list[dict[str, Any]]:
        """Read entry metadata without loading bars or connecting to a provider."""
        entries = []
        try:
            for path in sorted(self.directory.glob(f"{_PREFIX}*.parquet")):
                try:
                    metadata = self._metadata(self._pq.read_metadata(path).metadata)
                    entries.append(
                        {
                            "file": path.name,
                            **metadata,
                            "bytes": path.stat().st_size,
                            "expired": self._expired(metadata),
                        }
                    )
                except (CacheError, OSError, ValueError, TypeError) as exc:
                    entries.append({"file": path.name, "error": str(exc)})
            return entries
        except OSError as exc:
            raise CacheError("Cannot inspect the historical cache directory") from exc

    def clear(self) -> int:
        """Remove only this cache's namespaced Parquet files, including corrupt ones."""
        count = 0
        try:
            for path in self.directory.glob(f"{_PREFIX}*.parquet"):
                path.unlink(missing_ok=True)
                count += 1
            return count
        except OSError as exc:
            raise CacheError("Cannot clear the historical cache directory") from exc

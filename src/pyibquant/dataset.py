"""Frozen, broker-independent research inputs and explicit calendar comparisons."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .bars import Bar, BarSeries, _iso_timestamp


def _stamp(value: str, kind: str) -> date | datetime:
    if kind == "date":
        return date.fromisoformat(value)
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Dataset datetimes must include a timezone")
    return result.astimezone(UTC)


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value: Any) -> float:
    # Preserve JSON integer/float representation so reload keeps the input digest.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Dataset OHLCV values must be JSON numbers (or null volume)')
    return value


@dataclass(frozen=True)
class CoverageAudit:
    """Comparison to caller-supplied expected bar starts, not an exchange calendar."""

    expected_count: int
    observed_count: int
    missing: tuple[date | datetime, ...]
    unexpected: tuple[date | datetime, ...]
    unconfirmed: tuple[date | datetime, ...]
    finality_checked: bool

    @property
    def matches_calendar(self) -> bool:
        return not self.missing and not self.unexpected


@dataclass(frozen=True, init=False)
class BarDataset:
    """Immutable snapshot with copied provenance; loading never connects to IBKR.

    A single JSON document commits bars and metadata together. Its SHA-256 detects
    accidental edits, not authenticity. File format version is separate from the
    embedded provider metadata schema. Live updates cannot modify a saved dataset.
    """

    _bars: tuple[Bar, ...]
    _metadata_json: str

    @classmethod
    def from_series(cls, series: BarSeries) -> BarDataset:
        # Capture bar rows and their coverage metadata under the same snapshot lock.
        with series._lock:
            return cls._create(series.snapshot(), series.metadata())

    @classmethod
    def _create(cls, bars: tuple[Bar, ...], metadata: dict[str, Any]) -> BarDataset:
        kind = metadata.get("timestamp_kind")
        interval = metadata.get("interval")
        if kind not in {"date", "datetime"} or not isinstance(interval, str) or not interval:
            raise ValueError("Dataset requires an interval and timestamp kind")
        if not isinstance(metadata.get("symbol"), str) or not metadata["symbol"]:
            raise ValueError("Dataset requires a symbol")
        if (interval in {"1d", "1w", "1y"}) != (kind == "date"):
            raise ValueError("Dataset interval and timestamp kind disagree")
        previous = None
        for bar in bars:
            if (isinstance(bar.timestamp, datetime)) != (kind == "datetime"):
                raise ValueError("Dataset contains inconsistent timestamp kinds")
            if previous is not None and bar.timestamp <= previous:
                raise ValueError("Dataset timestamps must be unique and increasing")
            previous = bar.timestamp
        coverage = metadata.get("coverage", {})
        if (coverage.get("rows") != len(bars)
                or coverage.get("first") != (_iso_timestamp(bars[0].timestamp) if bars else None)
                or coverage.get("last") != (_iso_timestamp(bars[-1].timestamp) if bars else None)):
            raise ValueError("Dataset coverage metadata does not match its bars")
        query = metadata.get("query", {})
        if query.get("mode") == "range":
            start, end = _stamp(query["start"], kind), _stamp(query["end"], kind)
            if start >= end or any(not start <= bar.timestamp < end for bar in bars):
                raise ValueError("Dataset bars fall outside the requested range")
        result = object.__new__(cls)
        object.__setattr__(result, "_bars", bars)
        object.__setattr__(result, "_metadata_json", _encoded(metadata))
        return result

    def snapshot(self) -> tuple[Bar, ...]:
        return self._bars

    def __len__(self) -> int:
        return len(self._bars)

    def metadata(self) -> dict[str, Any]:
        """Return an independent provenance copy, including original receipt time."""
        return json.loads(self._metadata_json)

    def describe(self) -> dict[str, Any]:
        """Summarize recorded identity and acquisition semantics, without guessing."""
        metadata = self.metadata()
        return dict(
            fingerprint=self.fingerprint(), rows=len(self), provider=metadata.get('provider'),
            instrument={key: metadata.get(key) for key in (
                'symbol', 'instrument_id', 'asset_type', 'currency', 'exchange',
                'primary_exchange', 'multiplier', 'option',
            )},
            sampling={key: metadata.get(key) for key in (
                'interval', 'data_type', 'adjustment', 'regular_hours',
                'session_timezone', 'timestamp_kind', 'timestamp_timezone',
            )},
            query=metadata.get('query'), coverage=metadata.get('coverage'),
            download=metadata.get('download'),
        )

    def quality_report(
        self, expected: Iterable[date | datetime] | None = None, *,
        finalized_through: date | datetime | None = None,
    ) -> dict[str, Any]:
        """Report observations and optional caller assertions; never certify quality.

        expected contains bar starts from the caller's calendar for this exact
        query/sampling. With no calendar, missing/unexpected counts remain unknown.
        Finality uses audit()'s inclusive BAR-START assertion, not bar-end inference.
        Price/volume counts are descriptive flags, not corrections or validity rules.
        The original provenance and fingerprint are never changed by a report.
        """
        metadata = self.metadata()
        audit = self.audit(expected if expected is not None else (
            bar.timestamp for bar in self._bars), finalized_through=finalized_through)
        calendar = None if expected is None else dict(
            basis='caller_supplied_bar_starts', expected_count=audit.expected_count,
            observed_count=audit.observed_count, matches_calendar=audit.matches_calendar,
            missing=[_iso_timestamp(stamp) for stamp in audit.missing],
            unexpected=[_iso_timestamp(stamp) for stamp in audit.unexpected],
            missing_count=len(audit.missing), unexpected_count=len(audit.unexpected),
        )
        flags = dict(
            null_volume=sum(bar.volume is None for bar in self._bars),
            zero_volume=sum(bar.volume == 0 for bar in self._bars),
            negative_volume=sum(bar.volume is not None and bar.volume < 0 for bar in self._bars),
            nonpositive_price=sum(min(bar.open, bar.high, bar.low, bar.close) <= 0
                                  for bar in self._bars),
            inconsistent_ohlc=sum(not (bar.low <= min(bar.open, bar.close)
                                      <= max(bar.open, bar.close) <= bar.high)
                                  for bar in self._bars),
        )
        warnings = list(metadata.get('warnings', []))
        if not self._bars:
            warnings.append('Dataset has no observed bars.')
        complete = metadata.get('download', {}).get('complete')
        if complete is not True:
            warnings.append('Download is incomplete.' if complete is False
                            else 'Download completeness is unknown.')
        if expected is None:
            warnings.append('No expected calendar supplied; missing market bars are unknown.')
        elif not audit.matches_calendar:
            warnings.append('Observed bar starts do not match the supplied calendar.')
        if audit.unconfirmed:
            warnings.append('Some observed bars lack caller confirmation of finality.')
        for key in ('error', 'schedule_error'):
            if metadata.get(key):
                warnings.append(f'{key}: {metadata[key]}')
        return dict(
            schema_version=1, description=self.describe(), observations=flags,
            calendar=calendar,
            finality=dict(
                basis=('caller_asserted_inclusive_bar_start'
                       if audit.finality_checked else 'unknown'),
                finalized_through=(_iso_timestamp(finalized_through)
                                   if finalized_through is not None else None),
                confirmed_count=len(self) - len(audit.unconfirmed),
                unconfirmed_count=len(audit.unconfirmed),
                unconfirmed=[_iso_timestamp(stamp) for stamp in audit.unconfirmed],
            ),
            warnings=warnings,
        )

    def to_records(self) -> list[dict[str, Any]]:
        return [dict(timestamp=(bar.timestamp.astimezone(UTC)
                                if isinstance(bar.timestamp, datetime) else bar.timestamp),
                     open=bar.open, high=bar.high, low=bar.low, close=bar.close,
                     volume=bar.volume) for bar in self._bars]

    def _payload(self) -> dict[str, Any]:
        return dict(metadata=self.metadata(), bars=[
            {**row, "timestamp": row["timestamp"].isoformat()} for row in self.to_records()
        ])

    def fingerprint(self) -> str:
        """Content digest of frozen bars and provenance, matching the saved file."""
        return hashlib.sha256(_encoded(self._payload()).encode()).hexdigest()

    def save(self, path: str | Path) -> Path:
        """Atomically replace one file with all rows, provenance and integrity digest."""
        payload = self._payload()
        digest = hashlib.sha256(_encoded(payload).encode()).hexdigest()
        document = dict(format="pyibquant.bars", version=1, sha256=digest, payload=payload)
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent,
                prefix=f".{target.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(_encoded(document) + "\n")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    @classmethod
    def load(cls, path: str | Path) -> BarDataset:
        """Read a supported dataset; reject corrupt, inconsistent or edited content."""
        return cls._from_document(json.loads(Path(path).expanduser().read_text(encoding="utf-8")))

    def _document(self) -> dict[str, Any]:
        return dict(format="pyibquant.bars", version=1, sha256=self.fingerprint(),
                    payload=self._payload())

    @classmethod
    def _from_document(cls, document: Any) -> BarDataset:
        try:
            if document["format"] != "pyibquant.bars" or document["version"] != 1:
                raise ValueError("Unsupported dataset format/version")
            payload = document["payload"]
            digest = hashlib.sha256(_encoded(payload).encode()).hexdigest()
            if digest != document["sha256"]:
                raise ValueError("Dataset integrity check failed")
            metadata = payload["metadata"]
            bars = tuple(
                Bar(_stamp(row["timestamp"], metadata["timestamp_kind"]),
                    _number(row['open']), _number(row['high']),
                    _number(row['low']), _number(row['close']),
                    None if row['volume'] is None else _number(row['volume']))
                for row in payload["bars"]
            )
            return cls._create(bars, metadata)
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("Malformed dataset document") from exc

    def audit(
        self, expected: Iterable[date | datetime], *,
        finalized_through: date | datetime | None = None,
    ) -> CoverageAudit:
        """Compare all rows to explicit expected bar starts (same query/hours).

        Supply trading dates for daily bars or bar starts from a trusted calendar
        for intraday/week/year bars. No weekday/holiday/session assumptions are
        made here. finalized_through is a caller assertion: bars with starts at or
        before it are final. Without it, every observed bar remains unconfirmed.
        This comparison does not change stored provider provenance or certify data.
        """
        kind = self.metadata()["timestamp_kind"]

        def normalize(value: date | datetime) -> date | datetime:
            if not isinstance(value, date) or isinstance(value, datetime) != (kind == "datetime"):
                raise ValueError("Audit timestamps must match the dataset timestamp kind")
            return _stamp(value.isoformat(), kind)

        values = [normalize(value) for value in expected]
        if len(set(values)) != len(values):
            raise ValueError("Expected calendar contains duplicate bar starts")
        expected_set = set(values)
        observed = {normalize(bar.timestamp) for bar in self._bars}
        final = normalize(finalized_through) if finalized_through is not None else None
        return CoverageAudit(
            len(expected_set), len(observed), tuple(sorted(expected_set - observed)),
            tuple(sorted(observed - expected_set)),
            tuple(sorted(value for value in observed if final is None or value > final)),
            final is not None,
        )

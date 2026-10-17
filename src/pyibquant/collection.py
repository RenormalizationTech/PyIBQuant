"""Small multi-instrument data containers for user-owned scientific analysis."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Any, Literal

from .dataset import BarDataset, _encoded


@dataclass(frozen=True)
class AlignedData:
    """A derived view of exact bar-start matches, with explicit missing values."""

    timestamps: tuple[date | datetime, ...]
    columns: Mapping[str, tuple[float | None, ...]]
    _metadata_json: str

    def metadata(self) -> dict[str, Any]:
        return json.loads(self._metadata_json)

    def to_records(self) -> list[dict[str, Any]]:
        return [dict(timestamp=stamp, **{key: values[i] for key, values in self.columns.items()})
                for i, stamp in enumerate(self.timestamps)]

    def to_dataframe(self) -> Any:
        """Optional pandas table; missing values become NaN, with no filling."""
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("Install pyibquant[pandas] for DataFrame exports") from exc
        kind = self.metadata()['timestamp_kind']
        index = (pd.DatetimeIndex(self.timestamps, tz='UTC', name='timestamp')
                 if kind == 'datetime' else pd.Index(self.timestamps, name='timestamp'))
        return pd.DataFrame(dict(self.columns), index=index, dtype='float64')


@dataclass(frozen=True, init=False)
class BarDatasetCollection(Mapping[str, BarDataset]):
    """Named frozen inputs saved as one integrity-checked, broker-free document.

    Keys are user labels, not inferred contract identities. Each source retains
    all original bars and provenance. Heterogeneous inputs may be stored together;
    alignment requires matching intervals, timestamp kinds and session settings.
    """

    _datasets: Mapping[str, BarDataset]

    def __init__(self, datasets: Mapping[str, BarDataset]) -> None:
        if not datasets:
            raise ValueError('A collection requires at least one dataset')
        copied = dict(datasets)
        for key, dataset in copied.items():
            if not isinstance(key, str) or not key.strip() or key == 'timestamp':
                raise ValueError('Dataset labels must be nonempty strings other than timestamp')
            if not isinstance(dataset, BarDataset):
                raise ValueError('Collection values must be frozen BarDataset instances')
        object.__setattr__(self, '_datasets', MappingProxyType(copied))

    def __getitem__(self, key: str) -> BarDataset:
        return self._datasets[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._datasets)

    def __len__(self) -> int:
        return len(self._datasets)

    def describe(self) -> dict[str, Any]:
        """Describe each source independently; no merged identity or quality score."""
        return dict(fingerprint=self.fingerprint(), dataset_count=len(self),
                    datasets={key: dataset.describe() for key, dataset in self.items()})

    def quality_report(
        self, expected: Mapping[str, Iterable[date | datetime]] | None = None, *,
        finalized_through: Mapping[str, date | datetime] | None = None,
        join: Literal['inner', 'outer'] | None = None, field: str = 'close',
    ) -> dict[str, Any]:
        """Inspect sources even if they cannot align; calendars are per input.

        With an explicit join, include alignment losses or the blocking reason.
        Without it, alignment is not attempted. Differences in recorded sampling,
        source, currency and adjustment are evidence for the user's own judgement.
        """
        calendars = dict(expected) if expected is not None else {}
        finality = dict(finalized_through) if finalized_through is not None else {}
        unknown = (calendars.keys() | finality.keys()) - self.keys()
        if unknown:
            raise ValueError(f'Unknown dataset labels in assertions: {sorted(unknown, key=str)}')
        if join not in {None, 'inner', 'outer'}:
            raise ValueError('join must be inner or outer')
        if field not in {'open', 'high', 'low', 'close', 'volume'}:
            raise ValueError('field must be an OHLCV column')
        metadata = {key: dataset.metadata() for key, dataset in self.items()}
        differences = {}
        for setting in ('interval', 'timestamp_kind', 'regular_hours', 'session_timezone',
                        'data_type', 'currency', 'adjustment', 'multiplier'):
            values = {key: source.get(setting) for key, source in metadata.items()}
            if any(value != next(iter(values.values())) for value in values.values()):
                differences[setting] = values
        alignment = None
        if join is not None:
            try:
                alignment = dict(status='available',
                                 **self.align(field=field, join=join).metadata())
            except ValueError as exc:
                alignment = dict(status='unavailable', join=join, field=field, reason=str(exc))
        return dict(
            schema_version=1, fingerprint=self.fingerprint(), dataset_count=len(self),
            datasets={key: dataset.quality_report(calendars.get(key),
                                                 finalized_through=finality.get(key))
                      for key, dataset in self.items()},
            differences=differences, alignment=alignment,
        )

    def _payload(self) -> dict[str, Any]:
        # A list preserves user column order while canonical JSON sorts object keys.
        return dict(datasets=[dict(key=key, dataset=value._document())
                              for key, value in self.items()])

    def fingerprint(self) -> str:
        return hashlib.sha256(_encoded(self._payload()).encode()).hexdigest()

    def save(self, path: str | Path) -> Path:
        """Atomically save every original dataset; alignment never discards stored rows."""
        document = dict(format='pyibquant.collection', version=1,
                        sha256=self.fingerprint(), payload=self._payload())
        content = _encoded(document) + '\n'
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                    prefix=f'.{target.name}.', suffix='.tmp',
                                    delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    @classmethod
    def load(cls, path: str | Path) -> BarDatasetCollection:
        """Verify the collection and each constituent dataset without any broker access."""
        document = json.loads(Path(path).expanduser().read_text(encoding='utf-8'))
        try:
            if document['format'] != 'pyibquant.collection' or document['version'] != 1:
                raise ValueError('Unsupported collection format/version')
            payload = document['payload']
            if hashlib.sha256(_encoded(payload).encode()).hexdigest() != document['sha256']:
                raise ValueError('Collection integrity check failed')
            datasets = {}
            for entry in payload['datasets']:
                key = entry['key']
                if key in datasets:
                    raise ValueError('Duplicate dataset label')
                datasets[key] = BarDataset._from_document(entry['dataset'])
            return cls(datasets)
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError('Malformed collection document') from exc

    def align(self, *, field: str = 'close', join: Literal['inner', 'outer']) -> AlignedData:
        """Select OHLCV values by exact bar-start timestamp; never fill or resample.

        inner keeps observed starts shared by all inputs; outer keeps their union.
        Neither proves bars are missing from an exchange calendar. Known partial
        downloads are rejected; unknown completeness/finality remains unverified.
        Price sources, currencies, adjustments and contract multipliers remain
        per-input metadata, without conversion or an assertion of comparability.
        """
        if field not in {'open', 'high', 'low', 'close', 'volume'}:
            raise ValueError('field must be an OHLCV column')
        if join not in {'inner', 'outer'}:
            raise ValueError('join must be inner or outer')
        metadata = {key: dataset.metadata() for key, dataset in self.items()}
        first = next(iter(metadata.values()))
        for key, source in metadata.items():
            for setting in ('interval', 'timestamp_kind', 'regular_hours', 'session_timezone'):
                if source.get(setting) != first.get(setting):
                    raise ValueError(f'{key}: incompatible {setting}; align compatible inputs')
            if source.get('download', {}).get('complete') is False:
                raise ValueError(f'{key}: incomplete download; refusing alignment')
        values = {key: {(bar.timestamp.astimezone(UTC)
                         if isinstance(bar.timestamp, datetime) else bar.timestamp):
                        getattr(bar, field) for bar in dataset.snapshot()}
                  for key, dataset in self.items()}
        sets = [set(rows) for rows in values.values()]
        stamps = tuple(sorted(set.intersection(*sets) if join == 'inner' else set.union(*sets)))
        selected = set(stamps)
        columns = {key: tuple(rows.get(stamp) for stamp in stamps) for key, rows in values.items()}
        report = dict(
            field=field, join=join, interval=first['interval'],
            timestamp_kind=first['timestamp_kind'], rows=len(stamps),
            matching='exact_bar_start', fill='none', resampling='none',
            gaps='not_verified', bar_finality='not_verified',
            sources={key: dict(fingerprint=self[key].fingerprint(), metadata=metadata[key],
                               input_rows=len(rows), dropped_rows=len(set(rows) - selected),
                               absent_rows=len(selected - set(rows)),
                               null_values=sum(value is None for value in columns[key]))
                     for key, rows in values.items()},
        )
        return AlignedData(stamps, MappingProxyType(columns), _encoded(report))

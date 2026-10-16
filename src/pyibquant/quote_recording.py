"""Sampled Level-one quote recordings with provenance, integrity and offline replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, TextIO

from .quote_stream import QuoteStream
from .quotes import DATA_TYPES


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('Recording timestamps must include a timezone')
    return result.astimezone(UTC)


def _validate_continuity(quote: dict[str, Any], previous: dict[str, Any] | None) -> None:
    """Reject erased/revised gaps, generation rollback and pre-gap carried fields."""
    generation, gaps = quote['generation'], quote['gaps']
    if type(generation) is not int or generation < 0 or not isinstance(gaps, list):
        raise ValueError('Invalid quote generation/gaps')
    observed = _aware(quote['observed_at'])
    expected_generation = 0
    last_end: datetime | None = None
    for index, gap in enumerate(gaps):
        started = _aware(gap['started_at'])
        ended = _aware(gap['ended_at']) if gap['ended_at'] is not None else None
        if (type(gap['previous_generation']) is not int
                or gap['previous_generation'] != expected_generation
                or not isinstance(gap['reason'], str) or not gap['reason']
                or started > observed or last_end is not None and started < last_end):
            raise ValueError('Invalid quote gap history')
        if ended is None:
            if (index != len(gaps)-1 or gap['next_generation'] is not None
                    or quote['status'] not in {'disconnected', 'closed', 'failed'}):
                raise ValueError('Invalid open quote gap')
        else:
            if (ended < started or ended > observed
                    or type(gap['next_generation']) is not int
                    or gap['next_generation'] != expected_generation+1):
                raise ValueError('Invalid quote gap boundary')
            expected_generation += 1
            last_end = ended
    if generation != expected_generation:
        raise ValueError('Quote generation does not match gap history')
    if gaps:
        if gaps[-1]['ended_at'] is None:
            if (any(quote[name] is not None for name in
                    ('bid', 'ask', 'last', 'bid_size', 'ask_size', 'last_size'))
                    or quote['field_received_at'] or quote['field_tick_types'] or quote['greeks']
                    or quote['market_data_type'] is not None or quote['delayed_ticks']):
                raise ValueError('Disconnected quote retained pre-gap fields')
        elif last_end is not None and (
            any(_aware(stamp) < last_end for stamp in quote['field_received_at'].values())
            or any(_aware(greek['received_at']) < last_end for greek in quote['greeks'])
        ):
            raise ValueError('Quote retained fields from an earlier generation')
    if previous is not None:
        old_gaps = previous.get('gaps', [])
        if generation < previous.get('generation', 0) or len(gaps) < len(old_gaps):
            raise ValueError('Quote continuity history moved backward')
        for old, new in zip(old_gaps, gaps):
            if old['ended_at'] is not None:
                if old != new:
                    raise ValueError('Previously recorded quote gap was revised')
            elif any(old[key] != new[key] for key in
                     ('started_at', 'reason', 'previous_generation')):
                raise ValueError('Previously recorded quote gap was revised')


def record_quotes(
    stream: QuoteStream, path: str | Path, *, duration: float,
    interval: float = 1, overwrite: bool = False,
) -> Path:
    """Sample latest accumulated fields at a bounded cadence on the calling thread.

    Every sample keeps field receipt times, so unchanged/stale values remain
    identifiable. This is not an exchange tick archive or an executable BBO feed.
    The stream remains owned by the caller. Use its context manager for cleanup.
    Files are exclusive by default. Interrupted IO leaves a detectable partial
    JSONL file; a footer marks recording completion, not quote/data completeness.
    """
    _validate_sampling(duration, interval)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    initial = stream.latest().to_dict()
    digest = hashlib.sha256()
    count = 0
    with target.open('w' if overwrite else 'x', encoding='utf-8', newline='\n') as file:
        def write(record: dict[str, Any], *, hashed: bool = True) -> None:
            line = _encoded(record) + '\n'
            file.write(line)
            file.flush()
            if hashed:
                digest.update(line.encode('utf-8'))

        write(dict(type='header', format='pyibquant.quote_samples', version=2,
                   started_at=datetime.now(UTC).isoformat(), duration=duration, interval=interval,
                   instrument=initial['instrument'],
                   requested_data_type=initial['requested_data_type'],
                   sampling='latest_fields_at_local_intervals', exchange_tick_archive=False,
                   timestamp_semantics='local_sampling_and_callback_receipt_not_exchange_time'))
        for record in _sample_records(stream, duration, interval):
            write(record)
            count += 1
        final = stream.latest()
        status = final.status if stream.closed or final.status == 'disconnected' else 'completed'
        write(dict(type='end', status=status, samples=count,
                   finished_at=datetime.now(UTC).isoformat(), error=final.error,
                   sha256=digest.hexdigest()), hashed=False)
    return target


@dataclass(frozen=True)
class QuoteRecording:
    """Loaded immutable sampled inputs. Iteration returns independent JSON records.

    complete means the requested recording duration finished, not that every field
    was available or every exchange update was captured. Missing footer, stopped
    streams and disconnects require allow_incomplete=True. A final truncated line
    may be recovered only in that mode; checksum failures are always rejected.
    """

    _header_json: str
    _samples_json: tuple[str, ...]
    _end_json: str | None

    def __len__(self) -> int:
        return len(self._samples_json)

    @property
    def complete(self) -> bool:
        return self._end_json is not None and json.loads(self._end_json)['status'] == 'completed'

    def metadata(self) -> dict[str, Any]:
        return dict(header=json.loads(self._header_json),
                    end=json.loads(self._end_json) if self._end_json else None,
                    complete=self.complete, samples=len(self))

    def samples(self) -> Iterator[dict[str, Any]]:
        for record in self._samples_json:
            yield json.loads(record)

    def fingerprint(self) -> str:
        """Digest of canonical header, samples and footer, including completion state.

        This identifies replay inputs; the on-disk footer digest separately checks
        original header/sample bytes. Neither digest establishes authenticity.
        """
        digest = hashlib.sha256()
        digest.update((self._header_json + '\n').encode('utf-8'))
        for record in self._samples_json:
            digest.update((record + '\n').encode('utf-8'))
        digest.update((self._end_json or 'null').encode('utf-8'))
        return digest.hexdigest()

    def quality(self) -> dict[str, Any]:
        """Describe sampled availability/feed labels, never execution suitability."""
        return _quality(self.samples())

    @classmethod
    def load(cls, path: str | Path, *, allow_incomplete: bool = False) -> QuoteRecording:
        header = end = None
        samples = []
        with Path(path).expanduser().open(encoding='utf-8', newline='') as file:
            for record in _read_records(file, allow_incomplete=allow_incomplete):
                if record['type'] == 'header':
                    header = _encoded(record)
                elif record['type'] == 'sample':
                    samples.append(_encoded(record))
                else:
                    end = _encoded(record)
        assert header is not None
        return cls(header, tuple(samples), end)

    @staticmethod
    def open(path: str | Path, *, allow_incomplete: bool = False) -> QuoteRecordingReader:
        """Validate once, then replay from disk with bounded sample memory."""
        return QuoteRecordingReader(path, allow_incomplete=allow_incomplete)


def _read_records(
    file: TextIO, *, allow_incomplete: bool = False, raw_digest: Any = None,
) -> Iterator[dict[str, Any]]:
    """Internal single-pass validator; callers exhaust it before trusting inputs."""
    header: dict[str, Any] | None = None
    end: dict[str, Any] | None = None
    count = 0
    digest = hashlib.sha256()
    previous_sequence = -1
    previous_quote: dict[str, Any] | None = None
    try:
        for line in file:
            if raw_digest is not None:
                raw_digest.update(line.encode('utf-8'))
            if end is not None:
                raise ValueError('Recording contains data after its footer')
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if allow_incomplete and header is not None and not file.read(1):
                    break
                raise
            _encoded(record)  # Reject NaN/infinity, including overflowing JSON numbers.
            if header is None:
                if (record['type'] != 'header'
                        or record['format'] != 'pyibquant.quote_samples'
                        or type(record['version']) is not int
                        or record['version'] not in {1, 2}):
                    raise ValueError('Unsupported quote recording format/version')
                _aware(record['started_at'])
                for name in ('duration', 'interval'):
                    if (isinstance(record[name], bool) or not isfinite(record[name])
                            or record[name] <= 0):
                        raise ValueError('Invalid recording duration/interval')
                if (not isinstance(record['instrument'], dict)
                        or record['requested_data_type'] not in DATA_TYPES):
                    raise ValueError('Invalid recording identity/feed mode')
                header = record
            elif record['type'] == 'sample':
                _aware(record['sampled_at'])
                quote = record['quote']
                _aware(quote['observed_at'])
                sequence = quote['sequence']
                if (quote['instrument'] != header['instrument']
                        or quote['requested_data_type'] != header['requested_data_type']
                        or quote['streaming'] is not True
                        or quote['snapshot_complete'] is not False
                        or type(sequence) is not int or sequence < 0
                        or sequence < previous_sequence):
                    raise ValueError('Recording sample identity/mode/sequence '
                                     'is inconsistent')
                previous_sequence = sequence
                if header['version'] == 2 or 'generation' in quote or 'gaps' in quote:
                    _validate_continuity(quote, previous_quote)
                previous_quote = quote
                if (quote['status'] not in {'collecting', 'active', 'closed',
                                           'disconnected', 'failed'}
                        or quote['market_data_type'] is not None
                        and quote['market_data_type'] not in DATA_TYPES):
                    raise ValueError('Invalid quote stream status/feed type')
                for name in ('bid', 'ask', 'last', 'bid_size', 'ask_size', 'last_size'):
                    value = quote[name]
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, (int, float))
                        or not isfinite(value) or value < 0
                    ):
                        raise ValueError('Invalid quote price/size')
                count += 1
            elif record['type'] == 'end':
                if (record['sha256'] != digest.hexdigest()
                        or record['samples'] != count):
                    raise ValueError('Recording integrity/count check failed')
                if record['status'] not in {
                    'completed', 'closed', 'disconnected', 'failed',
                }:
                    raise ValueError('Invalid recording completion status')
                if record['status'] == 'completed' and (
                    record['error'] is not None or not count
                    or previous_quote is None or previous_quote['status']
                    in {'closed', 'disconnected', 'failed'}
                ):
                    raise ValueError('Completed recording has an invalid terminal sample')
                _aware(record['finished_at'])
                end = record
                yield record
                continue
            else:
                raise ValueError('Unexpected quote recording entry')
            digest.update(line.encode('utf-8'))
            yield record
        if header is None:
            raise ValueError('Recording has no header')
        if (end is None or end['status'] != 'completed') and not allow_incomplete:
            raise ValueError('Incomplete recording; explicitly use '
                             'allow_incomplete=True to inspect')
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError('Malformed quote recording') from exc


@dataclass(frozen=True)
class _RecordingInfo:
    header: str
    end: str | None
    samples: int
    fingerprint: str

    def metadata(self) -> dict[str, Any]:
        end = json.loads(self.end) if self.end is not None else None
        return dict(header=json.loads(self.header), end=end, samples=self.samples,
                    complete=end is not None and end['status'] == 'completed')


class _Scan:
    def __init__(self) -> None:
        self.header: str | None = None
        self.end: str | None = None
        self.count = 0
        self.digest = hashlib.sha256()

    def add(self, record: dict[str, Any]) -> None:
        encoded = _encoded(record)
        if record['type'] == 'end':
            self.end = encoded
        else:
            self.digest.update((encoded+'\n').encode('utf-8'))
            if record['type'] == 'header':
                self.header = encoded
            else:
                self.count += 1

    def info(self) -> _RecordingInfo:
        assert self.header is not None
        digest = self.digest.copy()
        digest.update((self.end or 'null').encode('utf-8'))
        return _RecordingInfo(self.header, self.end, self.count, digest.hexdigest())


class QuoteRecordingReader:
    """Prevalidated disk-backed replay; use as a context manager.

    Opening validates the entire input before returning any samples. Replay makes
    another checked pass through the same open file. Path replacement cannot swap
    that file. Do not edit inputs in place; exhaust each iterator to detect edits
    made during replay. Memory holds one sample and its gap history, not all rows.
    One iterator may be active per reader; use separate readers for concurrency.
    """

    def __init__(self, path: str | Path, *, allow_incomplete: bool = False) -> None:
        self._file = Path(path).expanduser().open(encoding='utf-8', newline='')
        self._allow_incomplete = allow_incomplete
        self._reading = Lock()
        self._active_records: Iterator[dict[str, Any]] | None = None
        try:
            scan = _Scan()
            for record in self._records():
                scan.add(record)
            self._info = scan.info()
        except BaseException:
            self.close()
            raise

    def _records(self) -> Iterator[dict[str, Any]]:
        self._file.seek(0)
        return _read_records(self._file, allow_incomplete=self._allow_incomplete)

    def __len__(self) -> int:
        return self._info.samples

    @property
    def complete(self) -> bool:
        return bool(self.metadata()['complete'])

    def metadata(self) -> dict[str, Any]:
        return self._info.metadata()

    def fingerprint(self) -> str:
        return self._info.fingerprint

    def samples(self) -> Iterator[dict[str, Any]]:
        if self._file.closed:
            raise ValueError('Quote recording reader is closed')
        if not self._reading.acquire(blocking=False):
            raise RuntimeError('Another sample iterator is active on this reader')
        try:
            scan = _Scan()
            records = self._records()
            self._active_records = records
            for record in records:
                scan.add(record)
                if record['type'] == 'sample':
                    # Keep consumers independent of the parser's continuity state.
                    yield json.loads(_encoded(record))
            if self._file.closed:
                raise ValueError('Quote recording reader is closed')
            if scan.info() != self._info:
                raise ValueError('Quote recording changed during replay')
        finally:
            active_records = self._active_records
            self._active_records = None
            close = getattr(active_records, 'close', None)
            if close is not None:
                close()
            self._reading.release()

    def quality(self) -> dict[str, Any]:
        return _quality(self.samples())

    def close(self) -> None:
        records = self._active_records
        self._active_records = None
        try:
            close = getattr(records, 'close', None)
            if close is not None:
                close()
        finally:
            self._file.close()

    def __enter__(self) -> QuoteRecordingReader:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def _quality(samples: Iterator[dict[str, Any]]) -> dict[str, Any]:
    pairs = crossed = delayed = frozen = model = 0
    types: dict[str, int] = {}
    versions = 0
    previous_sequence = None
    latest: dict[str, Any] = {}
    count = 0
    for row in samples:
        count += 1
        quote = row['quote']
        kind = quote['market_data_type'] or 'unknown'
        types[kind] = types.get(kind, 0) + 1
        if quote['sequence'] != previous_sequence:
            versions += 1
        previous_sequence = quote['sequence']
        latest = quote
        bid, ask = quote['bid'], quote['ask']
        pairs += bid is not None and ask is not None
        crossed += bid is not None and ask is not None and bid > ask
        delayed += quote['delayed_ticks'] or kind in {'delayed', 'delayed_frozen'}
        frozen += kind in {'frozen', 'delayed_frozen'}
        model += any(greek['source'] == 'model' and greek['implied_volatility'] is not None
                     and greek['delta'] is not None for greek in quote['greeks'])
    return dict(samples=count, with_bid_ask=pairs, crossed_pairs=crossed,
                delayed_samples=delayed, frozen_samples=frozen, feed_types=types,
                with_model_iv_delta=model, distinct_observed_versions=versions,
                generation=latest.get('generation', 0), gaps=latest.get('gaps', []),
                exchange_quote_age='unknown', executable_prices='not_verified')


def _validate_sampling(duration: float, interval: float) -> None:
    for name, value in [('duration', duration), ('interval', interval)]:
        if isinstance(value, bool) or not isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be positive and finite')


def _sample_records(
    stream: QuoteStream, duration: float, interval: float,
) -> Iterator[dict[str, Any]]:
    started = monotonic()
    deadline = started + duration
    next_sample = started
    while True:
        quote = stream.latest()
        yield dict(type='sample', sampled_at=datetime.now(UTC).isoformat(), quote=quote.to_dict())
        if stream.closed:
            break
        next_sample += interval
        now = monotonic()
        if next_sample < now:
            next_sample = now + interval
        with stream._state.changed:
            stream._state.changed.wait_for(lambda: stream.closed,
                                           timeout=max(0, min(deadline, next_sample)-monotonic()))
        if stream.closed:
            continue
        if monotonic() >= deadline:
            break
    final = stream.latest()
    if final.gaps != quote.gaps or final.generation != quote.generation:
        yield dict(type='sample', sampled_at=datetime.now(UTC).isoformat(), quote=final.to_dict())

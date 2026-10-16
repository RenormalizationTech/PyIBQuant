"""Exclusive rotating quote capture and validated replay of ordered recording segments."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any
from uuid import uuid4

from .quote_recording import (
    QuoteRecordingReader,
    _aware,
    _encoded,
    _read_records,
    _sample_records,
    _Scan,
    _validate_continuity,
    _validate_sampling,
)
from .quote_stream import QuoteStream


class _SegmentWriter:
    def __init__(self, path: Path, header: dict[str, Any]) -> None:
        self.path = path
        self.file = path.open('x', encoding='utf-8', newline='\n')
        self.digest = hashlib.sha256()
        self.content_digest = hashlib.sha256()
        self.count = 0
        try:
            self.write(header)
        except BaseException:
            self.file.close()
            raise

    def write(self, record: dict[str, Any], *, footer: bool = False) -> None:
        line = (_encoded(record)+'\n').encode('utf-8')
        self.file.write(line.decode('utf-8'))
        self.file.flush()
        self.content_digest.update(line)
        if not footer:
            self.digest.update(line)
        if record['type'] == 'sample':
            self.count += 1

    def finish(self, status: str, error: str | None = None) -> dict[str, Any]:
        self.write(dict(type='end', status=status, samples=self.count, error=error,
                        finished_at=datetime.now(UTC).isoformat(), sha256=self.digest.hexdigest()),
                   footer=True)
        self.file.close()
        return dict(file=self.path.name, samples=self.count,
                    sha256=self.content_digest.hexdigest())


def record_quotes_rotating(
    stream: QuoteStream, directory: str | Path, *, duration: float,
    interval: float = 1, max_samples: int = 10_000,
) -> Path:
    """Rotate at sample boundaries into a new, exclusive recording directory.

    Returns the atomically published recording.json manifest after graceful stop.
    Every segment has its own footer/checksum and an ordered predecessor digest.
    Crashes/IO errors leave diagnostic segments but no successful manifest. No
    overwrite, pruning or closed-file resume is performed. Caller owns the stream.
    """
    _validate_sampling(duration, interval)
    if type(max_samples) is not int or max_samples <= 0:
        raise ValueError('max_samples must be a positive integer')
    target = Path(directory).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=False)
    initial = stream.latest()
    header = dict(type='header', format='pyibquant.quote_samples', version=2,
                  started_at=datetime.now(UTC).isoformat(), duration=duration, interval=interval,
                  instrument=initial.to_dict()['instrument'],
                  requested_data_type=initial.requested_data_type,
                  sampling='latest_fields_at_local_intervals', exchange_tick_archive=False,
                  timestamp_semantics='local_sampling_and_callback_receipt_not_exchange_time')
    recording_id = str(uuid4())
    segments: list[dict[str, Any]] = []
    logical_digest = hashlib.sha256((_encoded(header)+'\n').encode('utf-8'))
    writer: _SegmentWriter | None = None
    try:
        for record in _sample_records(stream, duration, interval):
            if writer is not None and writer.count >= max_samples:
                segments.append(writer.finish('completed'))
                writer = None
            if writer is None:
                rotation = dict(recording_id=recording_id, index=len(segments),
                                previous_sha256=segments[-1]['sha256'] if segments else None)
                writer = _SegmentWriter(target/f'{len(segments):06d}.quotes.jsonl',
                                        header | dict(rotation=rotation))
            writer.write(record)
            logical_digest.update((_encoded(record)+'\n').encode('utf-8'))
        final = stream.latest()
        status = final.status if stream.closed or final.status == 'disconnected' else 'completed'
        assert writer is not None
        segments.append(writer.finish(status, final.error))
        end = dict(type='end', status=status, samples=sum(item['samples'] for item in segments),
                   error=final.error, finished_at=datetime.now(UTC).isoformat(),
                   sha256=logical_digest.hexdigest())
        manifest = dict(format='pyibquant.quote_recording_set', version=1,
                        recording_id=recording_id, header=header, segments=segments, end=end)
        manifest['sha256'] = hashlib.sha256(_encoded(manifest).encode('utf-8')).hexdigest()
        temporary = None
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target,
                                    prefix='.recording.', suffix='.tmp', delete=False) as file:
                temporary = Path(file.name)
                file.write(_encoded(manifest)+'\n')
            path = target/'recording.json'
            os.replace(temporary, path)
            return path
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    finally:
        if writer is not None:
            writer.file.close()


class QuoteRecordingSet(QuoteRecordingReader):
    """Prevalidate every ordered segment, then replay with one sample in memory.

    Memory also includes the manifest (one descriptor per segment). Replay checks
    segment bytes, identities, ordering and gap continuity again. As with the
    single-file reader, do not edit inputs in place and exhaust each iterator.
    Partial sessions require allow_incomplete=True; missing/corrupt segments fail
    even with that option. A missing manifest denotes interrupted publication.
    """

    def __init__(self, path: str | Path, *, allow_incomplete: bool = False) -> None:
        manifest_path = Path(path).expanduser().resolve()
        self._directory = manifest_path.parent
        self._file = manifest_path.open(encoding='utf-8', newline='')
        self._allow_incomplete = allow_incomplete
        self._reading = Lock()
        self._active_records = None
        try:
            manifest = json.load(self._file)
            checksum = manifest.pop('sha256')
            if (hashlib.sha256(_encoded(manifest).encode('utf-8')).hexdigest() != checksum
                    or manifest['format'] != 'pyibquant.quote_recording_set'
                    or type(manifest['version']) is not int or manifest['version'] != 1
                    or not isinstance(manifest['recording_id'], str)
                    or not manifest['recording_id'] or not manifest['segments']
                    or not isinstance(manifest['segments'], list)):
                raise ValueError('Invalid recording-set manifest/integrity')
            self._manifest = manifest
            scan = _Scan()
            for record in self._records():
                scan.add(record)
            self._info = scan.info()
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            self.close()
            raise ValueError('Malformed recording-set manifest') from exc
        except BaseException:
            self.close()
            raise

    @classmethod
    def open(cls, path: str | Path, *, allow_incomplete: bool = False) -> QuoteRecordingSet:
        return cls(path, allow_incomplete=allow_incomplete)

    def _records(self) -> Iterator[dict[str, Any]]:
        header = self._manifest['header']
        end = self._manifest['end']
        digest = hashlib.sha256((_encoded(header)+'\n').encode('utf-8'))
        count = 0
        previous: dict[str, Any] | None = None
        previous_digest = None
        segments = self._manifest['segments']
        yield header
        for index, segment in enumerate(segments):
            # Only fixed local basenames are accepted; traversal, duplicates and
            # reordering fail even if the manifest checksum was recomputed.
            if (segment['file'] != f'{index:06d}.quotes.jsonl'
                    or type(segment['samples']) is not int or segment['samples'] <= 0):
                raise ValueError('Invalid recording segment order/name/count')
            rotation = dict(recording_id=self._manifest['recording_id'], index=index,
                            previous_sha256=previous_digest)
            raw_digest = hashlib.sha256()
            segment_count = 0
            segment_end = None
            with (self._directory/segment['file']).open(encoding='utf-8', newline='') as file:
                for record in _read_records(file, allow_incomplete=True, raw_digest=raw_digest):
                    if record['type'] == 'header':
                        if record != header | dict(rotation=rotation):
                            raise ValueError('Recording segment identity/chain mismatch')
                    elif record['type'] == 'sample':
                        if previous is not None:
                            quote = record['quote']
                            if (quote['sequence'] < previous['quote']['sequence'] or
                                    _aware(record['sampled_at']) < _aware(previous['sampled_at'])):
                                raise ValueError('Recording segment boundary moved backward')
                            _validate_continuity(quote, previous['quote'])
                        previous = record
                        count += 1
                        segment_count += 1
                        digest.update((_encoded(record)+'\n').encode('utf-8'))
                        yield record
                    else:
                        segment_end = record
            if (raw_digest.hexdigest() != segment['sha256']
                    or segment_count != segment['samples'] or segment_end is None):
                raise ValueError('Recording segment integrity/count check failed')
            expected_status = end['status'] if index == len(segments)-1 else 'completed'
            if segment_end['status'] != expected_status:
                raise ValueError('Recording segment completion status mismatch')
            previous_digest = segment['sha256']
        assert segment_end is not None
        if (end['type'] != 'end' or end['sha256'] != digest.hexdigest()
                or type(end['samples']) is not int or end['samples'] != count
                or end['error'] != segment_end['error']):
            raise ValueError('Recording-set integrity/count check failed')
        _aware(end['finished_at'])
        if end['status'] != 'completed' and not self._allow_incomplete:
            raise ValueError('Incomplete recording set; explicitly use allow_incomplete=True')
        yield end

    def metadata(self) -> dict[str, Any]:
        return super().metadata() | dict(segments=json.loads(_encoded(self._manifest['segments'])))

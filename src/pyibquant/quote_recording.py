"""Sampled Level-one quote recordings with provenance, integrity and offline replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Any

from .quote_stream import QuoteStream
from .quotes import DATA_TYPES


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('Recording timestamps must include a timezone')
    return result.astimezone(UTC)


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
    for name, value in [('duration', duration), ('interval', interval)]:
        if isinstance(value, bool) or not isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be positive and finite')
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    initial = stream.latest().to_dict()
    digest = hashlib.sha256()
    count = 0
    started = monotonic()
    deadline = started + duration
    next_sample = started
    with target.open('w' if overwrite else 'x', encoding='utf-8', newline='\n') as file:
        def write(record: dict[str, Any], *, hashed: bool = True) -> None:
            line = _encoded(record) + '\n'
            file.write(line)
            file.flush()
            if hashed:
                digest.update(line.encode('utf-8'))

        write(dict(type='header', format='pyibquant.quote_samples', version=1,
                   started_at=datetime.now(UTC).isoformat(), duration=duration, interval=interval,
                   instrument=initial['instrument'],
                   requested_data_type=initial['requested_data_type'],
                   sampling='latest_fields_at_local_intervals', exchange_tick_archive=False,
                   timestamp_semantics='local_sampling_and_callback_receipt_not_exchange_time'))
        while True:
            quote = stream.latest()
            write(dict(type='sample', sampled_at=datetime.now(UTC).isoformat(),
                       quote=quote.to_dict()))
            count += 1
            if stream.closed:
                break
            next_sample += interval
            now = monotonic()
            # IO/OS delays do not produce a burst of invented catch-up observations.
            if next_sample < now:
                next_sample = now + interval
            wake_at = min(deadline, next_sample)
            with stream._state.changed:
                stream._state.changed.wait_for(lambda: stream.closed,
                                               timeout=max(0, wake_at - monotonic()))
            if stream.closed:
                continue  # Include a final terminal-status observation.
            if monotonic() >= deadline:
                break
        final = stream.latest()
        status = final.status if stream.closed else 'completed'
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

    def quality(self) -> dict[str, Any]:
        """Describe sampled availability/feed labels, never execution suitability."""
        pairs = crossed = delayed = frozen = model = 0
        types: dict[str, int] = {}
        versions: set[int] = set()
        for row in self.samples():
            quote = row['quote']
            kind = quote['market_data_type'] or 'unknown'
            types[kind] = types.get(kind, 0) + 1
            versions.add(quote['sequence'])
            bid, ask = quote['bid'], quote['ask']
            pairs += bid is not None and ask is not None
            crossed += bid is not None and ask is not None and bid > ask
            delayed += quote['delayed_ticks'] or kind in {'delayed', 'delayed_frozen'}
            frozen += kind in {'frozen', 'delayed_frozen'}
            model += any(greek['source'] == 'model' and greek['implied_volatility'] is not None
                         and greek['delta'] is not None for greek in quote['greeks'])
        return dict(samples=len(self), with_bid_ask=pairs, crossed_pairs=crossed,
                    delayed_samples=delayed, frozen_samples=frozen, feed_types=types,
                    with_model_iv_delta=model, distinct_observed_versions=len(versions),
                    exchange_quote_age='unknown', executable_prices='not_verified')

    @classmethod
    def load(cls, path: str | Path, *, allow_incomplete: bool = False) -> QuoteRecording:
        header: dict[str, Any] | None = None
        end: dict[str, Any] | None = None
        samples: list[str] = []
        digest = hashlib.sha256()
        previous_sequence = -1
        try:
            with Path(path).expanduser().open(encoding='utf-8', newline='') as file:
                for line in file:
                    if end is not None:
                        raise ValueError('Recording contains data after its footer')
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        if allow_incomplete and header is not None and not file.read():
                            break
                        raise
                    _encoded(record)  # Reject NaN/infinity, including overflowing JSON numbers.
                    if header is None:
                        if (record['type'] != 'header'
                                or record['format'] != 'pyibquant.quote_samples'
                                or type(record['version']) is not int or record['version'] != 1):
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
                        samples.append(_encoded(record))
                    elif record['type'] == 'end':
                        if (record['sha256'] != digest.hexdigest()
                                or record['samples'] != len(samples)):
                            raise ValueError('Recording integrity/count check failed')
                        if record['status'] not in {
                            'completed', 'closed', 'disconnected', 'failed',
                        }:
                            raise ValueError('Invalid recording completion status')
                        if record['status'] == 'completed' and (
                            record['error'] is not None or not samples
                            or json.loads(samples[-1])['quote']['status']
                            in {'closed', 'disconnected', 'failed'}
                        ):
                            raise ValueError('Completed recording has an invalid terminal sample')
                        _aware(record['finished_at'])
                        end = record
                        continue
                    else:
                        raise ValueError('Unexpected quote recording entry')
                    digest.update(line.encode('utf-8'))
            if header is None:
                raise ValueError('Recording has no header')
            result = cls(_encoded(header), tuple(samples), _encoded(end) if end else None)
            if not result.complete and not allow_incomplete:
                raise ValueError('Incomplete recording; explicitly use '
                                 'allow_incomplete=True to inspect')
            return result
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError('Malformed quote recording') from exc

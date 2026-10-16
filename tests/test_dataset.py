"""Frozen research inputs survive disconnects, edits and calendar comparisons."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from pyibquant import Bar, BarDataset, BarSeries


def series(interval='1d'):
    result = BarSeries('DEMO', interval, live=True)
    result.instrument_id = 123
    result.multiplier = 1
    result.adjustment = 'splits_only'
    result.requested_start = date(2026, 3, 6)
    result.requested_end = date(2026, 3, 11)
    result.download_complete = True
    stamps = [date(2026, 3, 6), date(2026, 3, 9)]
    if interval != '1d':
        stamps = [datetime(2026, 3, 6, 9, 30, tzinfo=timezone(timedelta(hours=-5))),
                  datetime(2026, 3, 9, 9, 30, tzinfo=timezone(timedelta(hours=-4)))]
        result.requested_start = datetime(2026, 3, 6, tzinfo=UTC)
        result.requested_end = datetime(2026, 3, 11, tzinfo=UTC)
    for stamp in stamps:
        result.update(Bar(stamp, 100, 105, 95, 101, 500))
    result.merge_sessions([dict(start=1, end=2, regular=True, date='2026-03-06')])
    return result


@pytest.mark.parametrize('interval', ['1d', '1min'])
def test_atomic_roundtrip_preserves_identity_queries_and_timestamp_semantics(tmp_path, interval):
    source = series(interval)
    frozen = BarDataset.from_series(source)
    path = frozen.save(tmp_path / 'nested' / 'research.json')
    loaded = BarDataset.load(path)
    assert path.is_absolute()
    assert loaded.snapshot() == source.snapshot()
    assert loaded.metadata() == source.metadata()
    assert loaded.to_records() == source.to_records()
    assert loaded.metadata()['coverage']['bar_finality'] == 'not_verified'
    assert loaded.metadata()['instrument_id'] == 123
    assert loaded.metadata()['last_received_at'] == source.last_update.isoformat()
    if interval == '1min':
        assert all(bar.timestamp.tzinfo == UTC for bar in loaded.snapshot())
    else:
        assert all(type(bar.timestamp) is date for bar in loaded.snapshot())


def test_snapshot_and_nested_metadata_are_independent_of_live_updates(tmp_path):
    source = series()
    frozen = BarDataset.from_series(source)
    source.update(Bar(date(2026, 3, 10), 100, 110, 90, 105, 600))
    source.sessions[0]['start'] = 99
    metadata = frozen.metadata()
    metadata['sessions'][0]['start'] = 50
    metadata['warnings'].append('mutated')
    frozen.to_records()[0]['close'] = -10
    assert len(frozen) == 2
    assert frozen.metadata()['sessions'][0]['start'] == 1
    assert not frozen.metadata()['warnings']
    assert frozen.snapshot()[0].close == 101
    with pytest.raises(FrozenInstanceError):
        frozen._bars = ()


def test_save_failure_leaves_original_dataset_and_no_temporary_files(tmp_path):
    target = tmp_path / 'bars.json'
    target.write_text('original')
    with patch('pyibquant.dataset.os.replace', side_effect=OSError('denied')):
        with pytest.raises(OSError):
            BarDataset.from_series(series()).save(target)
    assert target.read_text() == 'original'
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('mutation', [
    'checksum', 'version', 'duplicate', 'kind', 'coverage', 'range',
])
def test_invalid_documents_rejected_even_with_recomputed_digest(tmp_path, mutation):
    import hashlib

    from pyibquant.dataset import _encoded

    path = BarDataset.from_series(series()).save(tmp_path / 'bars.json')
    doc = json.loads(path.read_text())
    payload = doc['payload']
    if mutation == 'checksum':
        payload['bars'][0]['close'] = 1
    elif mutation == 'version':
        doc['version'] = 999
    elif mutation == 'duplicate':
        payload['bars'][1]['timestamp'] = payload['bars'][0]['timestamp']
    elif mutation == 'kind':
        payload['metadata']['timestamp_kind'] = 'datetime'
    elif mutation == 'coverage':
        payload['metadata']['coverage']['rows'] = 5
    elif mutation == 'range':
        payload['metadata']['query']['end'] = '2026-03-07'
    if mutation != 'checksum':
        doc['sha256'] = hashlib.sha256(_encoded(payload).encode()).hexdigest()
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        BarDataset.load(path)


@pytest.mark.parametrize('content', ['{}', '[]', 'null', '{bad json'])
def test_malformed_document_is_actionable(tmp_path, content):
    path = tmp_path / 'bad.json'
    path.write_text(content)
    with pytest.raises(ValueError):
        BarDataset.load(path)


def test_empty_or_partial_download_preserves_status_without_certifying_coverage(tmp_path):
    source = BarSeries('EMPTY', '1d')
    source.download_complete = False
    path = BarDataset.from_series(source).save(tmp_path / 'empty.json')
    loaded = BarDataset.load(path)
    assert loaded.snapshot() == ()
    assert loaded.metadata()['download']['complete'] is False
    audit = loaded.audit([date(2026, 3, 6)])
    assert audit.missing == (date(2026, 3, 6),)
    assert not audit.matches_calendar


def test_calendar_audit_does_not_invent_weekends_holidays_or_finality():
    frozen = BarDataset.from_series(series())
    friday, monday, tuesday = date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)
    audit = frozen.audit([friday, monday, tuesday])
    assert audit.expected_count == 3 and audit.observed_count == 2
    assert audit.missing == (tuesday,)
    assert audit.unexpected == ()
    assert audit.unconfirmed == (friday, monday) and not audit.finality_checked
    audit = frozen.audit([friday], finalized_through=friday)
    assert audit.unexpected == (monday,) and audit.unconfirmed == (monday,)
    assert audit.finality_checked and not audit.matches_calendar
    assert frozen.audit([friday, monday], finalized_through=monday).matches_calendar
    assert frozen.metadata()['coverage']['gaps'] == 'not_verified'


def test_intraday_audit_handles_dst_and_rejects_naive_mixed_duplicate_calendars():
    frozen = BarDataset.from_series(series('1min'))
    expected = [row['timestamp'] for row in frozen.to_records()]
    assert frozen.audit(expected).matches_calendar
    assert frozen.audit(expected, finalized_through=expected[0]).unconfirmed == (expected[1],)
    for invalid in ([expected[0], expected[0]], [date(2026, 3, 6)], [datetime(2026, 3, 6)]):
        with pytest.raises(ValueError):
            frozen.audit(invalid)
    with pytest.raises(ValueError):
        frozen.audit(expected, finalized_through=date(2026, 3, 6))


@pytest.mark.parametrize('mode', ['success', 'missing', 'incomplete'])
def test_saved_research_example_runs_offline_and_rejects_bad_inputs(tmp_path, monkeypatch, mode):
    import runpy
    from pathlib import Path

    source = series()
    source.download_complete = mode != 'incomplete'
    dataset_path = BarDataset.from_series(source).save(tmp_path / 'bars.json')
    calendar = tmp_path / 'calendar.txt'
    calendar.write_text('2026-03-06\n2026-03-09\n' +
                        ('2026-03-10\n' if mode == 'missing' else ''))
    monkeypatch.setattr('sys.argv', ['research_saved', str(dataset_path), '--calendar',
                                   str(calendar), '--window', '2'])
    with patch('pyibquant.Market.ibkr', side_effect=AssertionError('No broker needed')):
        script = Path(__file__).resolve().parents[1] / 'examples' / 'research_saved.py'
        if mode == 'success':
            runpy.run_path(str(script), run_name='__main__')
        else:
            with pytest.raises(SystemExit, match='Calendar mismatch|incomplete'):
                runpy.run_path(str(script), run_name='__main__')

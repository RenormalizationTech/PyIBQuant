"""Sampled quote recordings preserve provenance and never silently accept partial data."""

import hashlib
import json

import pytest

from pyibquant import QuoteRecording, QuoteStream, record_quotes
from pyibquant.quotes import QuoteInstrument, _QuoteState


@pytest.fixture
def source(monkeypatch):
    instrument = QuoteInstrument('DEMO', 123, 'equity', 'USD', 'SMART', 'NASDAQ',
                                 'DEMO', 'DEMO', 1, None, None, None)
    state = _QuoteState(instrument, 'live', streaming=True)
    state.actual_type = 'live'
    state.tick(1, 100)
    state.tick(2, 102)
    stream = QuoteStream(state, lambda: state.finish('closed'))
    clock = [0.0]
    callbacks = []

    class ClockCondition:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def wait_for(self, predicate, timeout=None):
            if not predicate():
                clock[0] += timeout
                if callbacks:
                    callbacks.pop(0)()
            return predicate()

        def notify_all(self):
            pass

    state.changed = ClockCondition()
    monkeypatch.setattr('pyibquant.quote_recording.monotonic', lambda: clock[0])
    return stream, state, callbacks


def test_cadence_preserves_unchanged_receipts_and_replays_without_a_broker(source, tmp_path):
    stream, state, callbacks = source
    callbacks.extend([lambda: None, lambda: state.tick(1, 101)])
    target = record_quotes(stream, tmp_path / 'nested' / 'samples.jsonl', duration=3, interval=1)
    assert not stream.closed  # Recorder does not take ownership of the subscription.
    loaded = QuoteRecording.load(target)
    assert len(loaded) == 3 and loaded.complete
    rows = list(loaded.samples())
    assert [row['quote']['bid'] for row in rows] == [100, 100, 101]
    receipts = [row['quote']['field_received_at']['bid'] for row in rows]
    assert receipts[0] == receipts[1] and receipts[2] >= receipts[1]
    assert rows[0]['quote']['streaming'] and not rows[0]['quote']['snapshot_complete']
    assert loaded.metadata()['header']['exchange_tick_archive'] is False
    rows[0]['quote']['bid'] = -1
    assert next(loaded.samples())['quote']['bid'] == 100
    metadata = loaded.metadata()
    metadata['header']['instrument']['symbol'] = 'MUTATED'
    assert loaded.metadata()['header']['instrument']['symbol'] == 'DEMO'
    stream.close()


def test_file_is_exclusive_unless_overwrite_was_explicit(source, tmp_path):
    stream, _, _ = source
    target = tmp_path / 'samples.jsonl'
    target.write_text('original')
    with pytest.raises(FileExistsError):
        record_quotes(stream, target, duration=1)
    assert target.read_text() == 'original'
    record_quotes(stream, target, duration=1, overwrite=True)
    assert QuoteRecording.load(target).complete


@pytest.mark.parametrize('config', [{'duration': 0}, {'duration': float('nan')},
                                    {'interval': -1}, {'interval': float('inf')}])
def test_invalid_sampling_parameters_do_not_create_a_file(source, tmp_path, config):
    stream, _, _ = source
    with pytest.raises(ValueError):
        record_quotes(stream, tmp_path / 'bad.jsonl', **({'duration': 1} | config))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('status', ['closed', 'disconnected', 'failed'])
def test_terminal_streams_have_explicit_partial_status_and_require_opt_in(source, tmp_path, status):
    stream, state, callbacks = source
    callbacks.append(lambda: state.finish(status, 'provider stopped'))
    target = record_quotes(stream, tmp_path / 'partial.jsonl', duration=10)
    with pytest.raises(ValueError, match='Incomplete recording'):
        QuoteRecording.load(target)
    loaded = QuoteRecording.load(target, allow_incomplete=True)
    assert not loaded.complete and len(loaded) == 2
    assert loaded.metadata()['end']['status'] == status
    assert loaded.metadata()['end']['error'] == 'provider stopped'
    assert list(loaded.samples())[-1]['quote']['status'] == status


def test_checksum_mismatch_is_rejected_even_when_partial_replay_is_allowed(source, tmp_path):
    stream, _, _ = source
    target = record_quotes(stream, tmp_path / 'samples.jsonl', duration=1)
    target.write_text(target.read_text().replace('"bid":100', '"bid":999'))
    for allow in (False, True):
        with pytest.raises(ValueError, match='integrity'):
            QuoteRecording.load(target, allow_incomplete=allow)


def test_missing_footer_and_truncated_last_line_can_only_be_inspected_explicitly(source, tmp_path):
    stream, _, _ = source
    target = record_quotes(stream, tmp_path / 'samples.jsonl', duration=3)
    lines = target.read_text().splitlines(keepends=True)
    for ending in ('', '{"type":"sample",'):
        target.write_text(''.join(lines[:-1]) + ending)
        with pytest.raises(ValueError):
            QuoteRecording.load(target)
        recovered = QuoteRecording.load(target, allow_incomplete=True)
        assert not recovered.complete and len(recovered) == 3


@pytest.mark.parametrize('mutation', [
    'instrument', 'mode', 'sequence', 'count', 'version', 'trailing',
])
def test_inconsistent_recordings_fail_even_with_a_recomputed_digest(source, tmp_path, mutation):
    stream, _, _ = source
    target = record_quotes(stream, tmp_path / 'samples.jsonl', duration=2)
    records = [json.loads(line) for line in target.read_text().splitlines()]
    if mutation == 'instrument':
        records[1]['quote']['instrument']['instrument_id'] = 999
    elif mutation == 'mode':
        records[1]['quote']['requested_data_type'] = 'frozen'
    elif mutation == 'sequence':
        records[2]['quote']['sequence'] = -1
    elif mutation == 'count':
        records[-1]['samples'] = 999
    elif mutation == 'version':
        records[0]['version'] = 99
    lines = [json.dumps(record, sort_keys=True, separators=(',', ':'))+'\n'
             for record in records[:-1]]
    records[-1]['sha256'] = hashlib.sha256(''.join(lines).encode()).hexdigest()
    target.write_text(''.join(lines) + json.dumps(records[-1])+'\n' +
                      ('{}\n' if mutation == 'trailing' else ''))
    with pytest.raises(ValueError):
        QuoteRecording.load(target)


@pytest.mark.parametrize('text', ['', 'null\n', '{}\n', 'bad json\n'])
def test_malformed_recordings_are_rejected(tmp_path, text):
    target = tmp_path / 'bad.jsonl'
    target.write_text(text)
    with pytest.raises(ValueError):
        QuoteRecording.load(target)


def test_quality_keeps_frozen_data_distinct_from_fresh_executable_quotes(source, tmp_path):
    stream, state, _ = source
    state.actual_type = 'frozen'
    target = record_quotes(stream, tmp_path / 'frozen.jsonl', duration=2)
    quality = QuoteRecording.load(target).quality()
    assert quality['with_bid_ask'] == 2 and quality['frozen_samples'] == 2
    assert quality['feed_types'] == {'frozen': 2}
    assert quality['distinct_observed_versions'] == 1
    assert quality['exchange_quote_age'] == 'unknown'
    assert quality['executable_prices'] == 'not_verified'


@pytest.mark.parametrize('selected', [False, True])
@pytest.mark.parametrize('rotating', [False, True])
def test_options_research_example_discovers_only_or_records_one_contract(
    source, tmp_path, monkeypatch, selected, rotating,
):
    import runpy
    from datetime import UTC, date, datetime
    from pathlib import Path
    from unittest.mock import MagicMock, Mock

    from pyibquant import OptionChain, OptionChainGroup, QuoteRecordingSet

    stream, state, _ = source
    chain = OptionChain('DEMO', 123, 'USD', (
        OptionChainGroup('SMART', 'DEMO', 100, (date(2026, 11, 20),), (100,)),
    ), datetime.now(UTC))
    market = MagicMock()
    market.__enter__.return_value = market
    market.option_chain.return_value = chain
    market.stream_quote.return_value = stream
    monkeypatch.setattr('pyibquant.Market.ibkr', Mock(return_value=market))
    args = ['options_research', 'DEMO', '--output-dir', str(tmp_path), '--duration', '3']
    if selected:
        args.extend(['--expiry', '2026-11-20', '--strike', '100', '--right', 'C'])
    if rotating:
        args.extend(['--max-samples-per-file', '2'])
    monkeypatch.setattr('sys.argv', args)
    script = Path(__file__).resolve().parents[1] / 'examples' / 'options_research.py'
    runpy.run_path(str(script), run_name='__main__')
    assert len(list(tmp_path.glob('*/chain.json'))) == 1
    if selected:
        if rotating:
            manifest = next(tmp_path.glob('*/recording/recording.json'))
            with QuoteRecordingSet.open(manifest) as replay:
                assert len(replay) == 3 and replay.complete
        else:
            path = next(tmp_path.glob('*/quotes.jsonl'))
            assert len(QuoteRecording.load(path)) == 3
        assert stream.closed
        assert market.stream_quote.call_count == 1
    else:
        market.stream_quote.assert_not_called()
        assert not list(tmp_path.glob('*/quotes.jsonl'))


def test_recording_remembers_gap_even_when_disconnect_and_resume_fall_between_samples(
    source, tmp_path,
):
    stream, state, callbacks = source

    def recover():
        state.interrupt('lost socket')
        state.resume()
        state.tick(1, 101)
    callbacks.append(recover)
    path = record_quotes(stream, tmp_path/'reconnected.jsonl', duration=3)
    recording = QuoteRecording.load(path)
    assert recording.complete and recording.metadata()['header']['version'] == 2
    samples = list(recording.samples())
    assert samples[0]['quote']['generation'] == 0
    assert samples[1]['quote']['generation'] == 1
    assert samples[1]['quote']['market_data_type'] is None
    assert samples[1]['quote']['ask'] is None
    assert len(recording.quality()['gaps']) == 1
    assert recording.quality()['generation'] == 1


def test_recording_ending_during_recovery_is_incomplete_without_closing_the_handle(
    source, tmp_path,
):
    stream, state, callbacks = source
    callbacks.append(lambda: state.interrupt('lost socket'))
    path = record_quotes(stream, tmp_path/'disconnected.jsonl', duration=2)
    assert not stream.closed
    with pytest.raises(ValueError, match='Incomplete recording'):
        QuoteRecording.load(path)
    recording = QuoteRecording.load(path, allow_incomplete=True)
    assert not recording.complete
    assert recording.metadata()['end']['status'] == 'disconnected'
    assert recording.quality()['gaps'][0]['ended_at'] is None


@pytest.mark.parametrize('mutation', [
    'generation', 'erase', 'carry_price', 'carry_greek', 'revise', 'future', 'boolean',
])
def test_gap_provenance_cannot_be_erased_or_revised_with_a_recomputed_digest(
    source, tmp_path, mutation,
):
    stream, state, callbacks = source

    def recover():
        state.interrupt('lost socket')
        state.resume()
        state.tick(1, 101)
    callbacks.append(recover)
    path = record_quotes(stream, tmp_path/'reconnected.jsonl', duration=3)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    quote = records[3]['quote']
    if mutation == 'generation':
        quote['generation'] = 2
    elif mutation == 'erase':
        quote['generation'], quote['gaps'] = 0, []
    elif mutation == 'carry_price':
        quote['field_received_at']['bid'] = records[1]['quote']['field_received_at']['bid']
    elif mutation == 'carry_greek':
        quote['greeks'] = [dict(received_at=records[1]['quote']['observed_at'])]
    elif mutation == 'revise':
        quote['gaps'][0]['reason'] = 'revised history'
    elif mutation == 'future':
        quote['gaps'][0]['ended_at'] = '2099-01-01T00:00:00+00:00'
    elif mutation == 'boolean':
        quote['generation'] = True
    lines = [json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n' for row in records[:-1]]
    records[-1]['sha256'] = hashlib.sha256(''.join(lines).encode()).hexdigest()
    path.write_text(''.join(lines)+json.dumps(records[-1])+'\n')
    with pytest.raises(ValueError):
        QuoteRecording.load(path)


def test_original_version_one_recordings_without_continuity_fields_still_load(source, tmp_path):
    stream, _, _ = source
    path = record_quotes(stream, tmp_path/'legacy.jsonl', duration=2)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[0]['version'] = 1
    for row in records[1:-1]:
        row['quote'].pop('generation')
        row['quote'].pop('gaps')
    lines = [json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n' for row in records[:-1]]
    records[-1]['sha256'] = hashlib.sha256(''.join(lines).encode()).hexdigest()
    path.write_text(''.join(lines)+json.dumps(records[-1])+'\n')
    recording = QuoteRecording.load(path)
    assert recording.complete and recording.quality()['generation'] == 0
    assert not recording.quality()['gaps']


def test_disk_reader_matches_loaded_metadata_quality_and_fingerprint(source, tmp_path):
    stream, _, _ = source
    path = record_quotes(stream, tmp_path/'single.jsonl', duration=3)
    loaded = QuoteRecording.load(path)
    with QuoteRecording.open(path) as replay:
        assert replay.complete and len(replay) == len(loaded)
        assert replay.metadata() == loaded.metadata()
        assert replay.fingerprint() == loaded.fingerprint()
        assert replay.quality() == loaded.quality()
        assert list(replay.samples()) == list(loaded.samples())
        assert list(replay.samples()) == list(loaded.samples())  # Rewind without cached rows.
        iterator = replay.samples()
        next(iterator)['quote']['generation'] = 999
        assert len(list(iterator)) == 2  # Consumer edits cannot change parser state.
        iterator = replay.samples()
        next(iterator)
        with pytest.raises(RuntimeError, match='iterator is active'):
            next(replay.samples())
        iterator.close()
        assert len(list(replay.samples())) == 3
    with pytest.raises(ValueError, match='closed'):
        next(replay.samples())


def test_disk_reader_validates_before_yielding_and_keeps_original_open_file(source, tmp_path):
    stream, _, _ = source
    path = record_quotes(stream, tmp_path/'single.jsonl', duration=3)
    original = path.read_bytes()
    with QuoteRecording.open(path) as replay:
        replacement = tmp_path/'replacement.jsonl'
        replacement.write_text('not a recording')
        replacement.replace(path)
        assert len(list(replay.samples())) == 3
    with pytest.raises(ValueError):
        QuoteRecording.open(path)
    path.write_bytes(original)
    replay = QuoteRecording.open(path)
    try:
        path.write_text(path.read_text().replace('"bid":100', '"bid":999'))
        with pytest.raises(ValueError, match='integrity'):
            list(replay.samples())
    finally:
        replay.close()


def test_disk_reader_retains_partial_opt_in_and_rejects_corruption(source, tmp_path):
    stream, _, _ = source
    path = record_quotes(stream, tmp_path/'partial.jsonl', duration=2)
    path.write_text(''.join(path.read_text().splitlines(keepends=True)[:-1]))
    with pytest.raises(ValueError, match='Incomplete'):
        QuoteRecording.open(path)
    with QuoteRecording.open(path, allow_incomplete=True) as replay:
        loaded = QuoteRecording.load(path, allow_incomplete=True)
        assert not replay.complete and len(replay) == 2
        assert replay.fingerprint() == loaded.fingerprint()


@pytest.mark.parametrize('rotating', [False, True])
def test_disk_reader_and_quality_do_not_keep_all_samples_in_memory(source, tmp_path, rotating):
    import tracemalloc

    from pyibquant import QuoteRecordingSet, record_quotes_rotating

    stream, _, _ = source
    if rotating:
        path = record_quotes_rotating(stream, tmp_path/'set', duration=2000, max_samples=1000)
        assert sum(p.stat().st_size for p in path.parent.glob('*.jsonl')) > 1_000_000
        opener = QuoteRecordingSet.open
    else:
        path = record_quotes(stream, tmp_path/'large.jsonl', duration=2000)
        assert path.stat().st_size > 1_000_000
        opener = QuoteRecording.open
    tracemalloc.start()
    try:
        with opener(path) as replay:
            assert len(replay) == 2000
            assert sum(1 for _ in replay.samples()) == 2000
            assert replay.quality()['samples'] == 2000
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1_000_000  # A loaded tuple of these JSON rows alone exceeds this bound.


def test_rotation_preserves_samples_order_integrity_and_metadata(source, tmp_path):
    from pyibquant import QuoteRecordingSet, record_quotes_rotating

    stream, state, callbacks = source
    callbacks.extend([lambda: state.tick(1, 101), lambda: state.tick(2, 103)])
    path = record_quotes_rotating(stream, tmp_path/'set', duration=5, max_samples=2)
    assert not stream.closed
    manifest = json.loads(path.read_text())
    assert [s['samples'] for s in manifest['segments']] == [2, 2, 1]
    assert sorted(p.name for p in path.parent.glob('*.jsonl')) == [
        '000000.quotes.jsonl', '000001.quotes.jsonl', '000002.quotes.jsonl',
    ]
    with QuoteRecordingSet.open(path) as replay:
        assert replay.complete and len(replay) == 5
        rows = list(replay.samples())
        assert [r['quote']['bid'] for r in rows] == [100, 101, 101, 101, 101]
        assert [r['quote']['ask'] for r in rows] == [102, 102, 103, 103, 103]
        assert replay.quality()['distinct_observed_versions'] == 3
        assert len(replay.metadata()['segments']) == 3
        assert len(list(replay.samples())) == 5
        # The logical fingerprint matches the same complete recording assembled in memory.
        logical = QuoteRecording(
            json.dumps(manifest['header'], sort_keys=True, separators=(',', ':')),
            tuple(json.dumps(row, sort_keys=True, separators=(',', ':')) for row in rows),
            json.dumps(manifest['end'], sort_keys=True, separators=(',', ':')),
        )
        assert replay.fingerprint() == logical.fingerprint()


@pytest.mark.parametrize('max_samples', [0, -1, True, 1.5])
def test_rotation_rejects_invalid_limits_without_creating_directories(
    source, tmp_path, max_samples,
):
    from pyibquant import record_quotes_rotating

    stream, _, _ = source
    with pytest.raises(ValueError, match='max_samples'):
        record_quotes_rotating(stream, tmp_path/'bad', duration=2, max_samples=max_samples)
    assert not list(tmp_path.iterdir())


def test_rotation_never_overwrites_existing_directories(source, tmp_path):
    from pyibquant import record_quotes_rotating

    stream, _, _ = source
    target = tmp_path/'set'
    target.mkdir()
    (target/'keep').write_text('original')
    with pytest.raises(FileExistsError):
        record_quotes_rotating(stream, target, duration=2)
    assert (target/'keep').read_text() == 'original'


def rewrite_manifest(path, manifest):
    manifest.pop('sha256', None)
    manifest['sha256'] = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(',', ':'),
    ).encode()).hexdigest()
    path.write_text(json.dumps(manifest)+'\n')


@pytest.mark.parametrize('mutation', ['missing', 'bytes', 'reorder', 'omit', 'duplicate',
                                     'traversal', 'count', 'manifest_hash'])
def test_rotation_detects_missing_modified_reordered_or_omitted_segments(
    source, tmp_path, mutation,
):
    from pyibquant import QuoteRecordingSet, record_quotes_rotating

    stream, _, _ = source
    path = record_quotes_rotating(stream, tmp_path/'set', duration=5, max_samples=2)
    manifest = json.loads(path.read_text())
    segment = path.parent/manifest['segments'][1]['file']
    if mutation == 'missing':
        segment.unlink()
    elif mutation == 'bytes':
        segment.write_text(segment.read_text().replace('"bid":100', '"bid":999'))
    elif mutation == 'reorder':
        manifest['segments'].reverse()
    elif mutation == 'omit':
        manifest['segments'].pop()
    elif mutation == 'duplicate':
        manifest['segments'][1] = manifest['segments'][0]
    elif mutation == 'traversal':
        manifest['segments'][0]['file'] = '../outside.jsonl'
    elif mutation == 'count':
        manifest['segments'][0]['samples'] += 1
    elif mutation == 'manifest_hash':
        manifest['sha256'] = '0'*64
    if mutation == 'manifest_hash':
        path.write_text(json.dumps(manifest))
    else:
        rewrite_manifest(path, manifest)
    # Partial inspection must never bypass integrity/missing-file errors.
    for allow in (False, True):
        with pytest.raises((ValueError, OSError)):
            QuoteRecordingSet.open(path, allow_incomplete=allow)


@pytest.mark.parametrize('status', ['closed', 'disconnected', 'failed'])
def test_rotating_terminal_session_requires_partial_opt_in(source, tmp_path, status):
    from pyibquant import QuoteRecordingSet, record_quotes_rotating

    stream, state, callbacks = source
    callbacks.extend([lambda: None, lambda: state.finish(status, 'stopped')])
    path = record_quotes_rotating(stream, tmp_path/'set', duration=10, max_samples=2)
    with pytest.raises(ValueError, match='Incomplete'):
        QuoteRecordingSet.open(path)
    with QuoteRecordingSet.open(path, allow_incomplete=True) as replay:
        assert not replay.complete and len(replay) == 3
        assert replay.metadata()['end']['status'] == status
        assert list(replay.samples())[-1]['quote']['status'] == status


def test_rotation_keeps_reconnect_evidence_across_segment_boundaries(source, tmp_path):
    from pyibquant import QuoteRecordingSet, record_quotes_rotating

    stream, state, callbacks = source

    def recover():
        state.interrupt('lost socket')
        state.resume()
        state.actual_type = 'live'
        state.tick(1, 101)
    callbacks.extend([lambda: None, recover])
    path = record_quotes_rotating(stream, tmp_path/'set', duration=4, max_samples=2)
    with QuoteRecordingSet.open(path) as replay:
        assert len(replay.quality()['gaps']) == 1
        assert [r['quote']['generation'] for r in replay.samples()] == [0, 0, 1, 1]


def test_rotation_io_failure_does_not_publish_a_success_manifest(source, tmp_path, monkeypatch):
    from pyibquant import record_quotes_rotating
    from pyibquant.quote_recording_set import _SegmentWriter

    stream, _, _ = source
    original = _SegmentWriter.write
    count = 0

    def fail(self, record, **kwargs):
        nonlocal count
        if record['type'] == 'sample':
            count += 1
            if count == 3:
                raise OSError('disk full')
        return original(self, record, **kwargs)
    monkeypatch.setattr(_SegmentWriter, 'write', fail)
    with pytest.raises(OSError, match='disk full'):
        record_quotes_rotating(stream, tmp_path/'set', duration=5, max_samples=2)
    assert not (tmp_path/'set'/'recording.json').exists()
    assert QuoteRecording.load(tmp_path/'set'/'000000.quotes.jsonl').complete
    assert not stream.closed


def test_simulator_refuses_an_individual_rotation_segment(source, tmp_path):
    from pyibquant import record_quotes_rotating
    from pyibquant.option_backtest import backtest_option

    stream, _, _ = source
    manifest = record_quotes_rotating(stream, tmp_path/'set', duration=3, max_samples=2)
    segment = QuoteRecording.load(manifest.parent/'000000.quotes.jsonl')
    with pytest.raises(ValueError, match='rotated segment'):
        backtest_option(segment, [False]*len(segment))


@pytest.mark.parametrize('rotating', [False, True])
def test_offline_replay_example_handles_single_files_and_recording_sets(
    source, tmp_path, monkeypatch, capsys, rotating,
):
    import runpy
    from pathlib import Path

    from pyibquant import record_quotes_rotating

    stream, _, _ = source
    if rotating:
        path = record_quotes_rotating(stream, tmp_path/'set', duration=3, max_samples=2)
    else:
        path = record_quotes(stream, tmp_path/'single.jsonl', duration=3)
    args = ['replay_quotes', str(path)] + (['--recording-set'] if rotating else [])
    monkeypatch.setattr('sys.argv', args)
    runpy.run_path(str(Path(__file__).resolve().parents[1]/'examples'/'replay_quotes.py'),
                   run_name='__main__')
    document = json.loads(capsys.readouterr().out)
    assert document['metadata']['complete'] and document['quality']['samples'] == 3
    assert document['quality']['exchange_quote_age'] == 'unknown'


@pytest.mark.parametrize('mutation', ['sequence', 'erase_gap'])
def test_rotation_checks_cross_segment_continuity_even_when_all_hashes_are_recomputed(
    source, tmp_path, mutation,
):
    from pyibquant import QuoteRecordingSet, record_quotes_rotating

    stream, state, callbacks = source

    def recover():
        state.interrupt('lost socket')
        state.resume()
        state.tick(1, 101)
    callbacks.append(recover)
    path = record_quotes_rotating(stream, tmp_path/'set', duration=4, max_samples=2)
    manifest = json.loads(path.read_text())
    second = path.parent/manifest['segments'][1]['file']
    rows = [json.loads(line) for line in second.read_text().splitlines()]
    for row in rows[1:-1]:
        if mutation == 'sequence':
            row['quote']['sequence'] = 0
        else:
            row['quote']['generation'], row['quote']['gaps'] = 0, []
    lines = [json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n' for row in rows[:-1]]
    rows[-1]['sha256'] = hashlib.sha256(''.join(lines).encode()).hexdigest()
    second.write_text(''.join(lines)+json.dumps(rows[-1])+'\n')
    manifest['segments'][1]['sha256'] = hashlib.sha256(second.read_bytes()).hexdigest()
    logical = [manifest['header']]
    for entry in manifest['segments']:
        lines = (path.parent/entry['file']).read_text().splitlines()
        logical.extend(row for row in map(json.loads, lines)
                       if row['type'] == 'sample')
    manifest['end']['sha256'] = hashlib.sha256(''.join(
        json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n' for row in logical
    ).encode()).hexdigest()
    rewrite_manifest(path, manifest)
    with pytest.raises(ValueError, match='backward'):
        QuoteRecordingSet.open(path)


def test_closing_set_reader_closes_an_unfinished_segment_iterator(source, tmp_path, monkeypatch):
    from pathlib import Path

    from pyibquant import QuoteRecordingSet, record_quotes_rotating

    stream, _, _ = source
    path = record_quotes_rotating(stream, tmp_path/'set', duration=4, max_samples=2)
    original = Path.open
    files = []

    def track(self, *args, **kwargs):
        file = original(self, *args, **kwargs)
        files.append(file)
        return file
    monkeypatch.setattr(Path, 'open', track)
    with QuoteRecordingSet.open(path) as replay:
        iterator = replay.samples()
        next(iterator)
    assert files and all(file.closed for file in files)
    with pytest.raises(ValueError, match='closed'):
        next(iterator)

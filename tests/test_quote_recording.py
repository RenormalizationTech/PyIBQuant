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
def test_options_research_example_discovers_only_or_records_one_contract(
    source, tmp_path, monkeypatch, selected,
):
    import runpy
    from datetime import UTC, date, datetime
    from pathlib import Path
    from unittest.mock import MagicMock, Mock

    from pyibquant import OptionChain, OptionChainGroup

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
    monkeypatch.setattr('sys.argv', args)
    script = Path(__file__).resolve().parents[1] / 'examples' / 'options_research.py'
    runpy.run_path(str(script), run_name='__main__')
    assert len(list(tmp_path.glob('*/chain.json'))) == 1
    if selected:
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

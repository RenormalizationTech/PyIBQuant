"""Quality reports describe evidence without changing or certifying source data."""

import json
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from test_collection import collection, dataset

from pyibquant import Bar, BarDataset, BarDatasetCollection, BarSeries


def test_description_captures_identity_sampling_and_coverage_without_inference():
    frozen = dataset()
    description = frozen.describe()
    assert description['fingerprint'] == frozen.fingerprint()
    assert description['instrument']['symbol'] == 'A'
    assert description['instrument']['instrument_id'] is None
    assert description['sampling']['data_type'] == 'TRADES'
    assert description['sampling']['interval'] == '1d'
    assert description['rows'] == 2
    assert description['download']['complete'] is True
    assert description['coverage']['gaps'] == 'not_verified'
    description['instrument']['symbol'] = 'changed'
    assert frozen.describe()['instrument']['symbol'] == 'A'


def test_no_calendar_or_finality_stays_unknown_even_on_completed_download():
    frozen = dataset()
    original = frozen.fingerprint()
    report = frozen.quality_report()
    assert report['calendar'] is None
    assert report['finality']['basis'] == 'unknown'
    assert report['finality']['confirmed_count'] == 0
    assert report['finality']['unconfirmed_count'] == 2
    assert report['finality']['finalized_through'] is None
    assert any('missing market bars are unknown' in warning for warning in report['warnings'])
    assert frozen.fingerprint() == original
    json.dumps(report, allow_nan=False)


def test_calendar_and_finality_are_explicit_separate_assertions():
    frozen = dataset(days=(1, 3))
    report = frozen.quality_report(iter([date(2025, 1, 1), date(2025, 1, 2)]),
                                  finalized_through=date(2025, 1, 1))
    assert report['calendar'] == dict(
        basis='caller_supplied_bar_starts', expected_count=2, observed_count=2,
        matches_calendar=False, missing=['2025-01-02'], unexpected=['2025-01-03'],
        missing_count=1, unexpected_count=1,
    )
    assert report['finality']['basis'] == 'caller_asserted_inclusive_bar_start'
    assert report['finality']['confirmed_count'] == report['finality']['unconfirmed_count'] == 1
    assert frozen.metadata()['coverage']['bar_finality'] == 'not_verified'
    assert frozen.metadata()['coverage']['gaps'] == 'not_verified'
    only_finality = frozen.quality_report(finalized_through=date(2025, 1, 3))
    assert only_finality['calendar'] is None
    assert only_finality['finality']['confirmed_count'] == 2


def test_intraday_assertions_normalize_to_utc_but_confirm_starts_not_ends():
    frozen = dataset(days=(1,), interval='5min')
    local = datetime(2024, 12, 31, 19, tzinfo=timezone(timedelta(hours=-5)))
    report = frozen.quality_report([local], finalized_through=local)
    assert report['calendar']['matches_calendar']
    assert report['finality']['confirmed_count'] == 1
    assert report['finality']['finalized_through'] == '2025-01-01T00:00:00+00:00'


@pytest.mark.parametrize('kwargs', [
    {'expected': [date(2025, 1, 1), date(2025, 1, 1)]},
    {'expected': [datetime(2025, 1, 1, tzinfo=UTC)]},
    {'finalized_through': datetime(2025, 1, 1, tzinfo=UTC)},
])
def test_invalid_assertions_reuse_dataset_audit_validation(kwargs):
    with pytest.raises(ValueError):
        dataset().quality_report(**kwargs)


def test_anomaly_counts_do_not_correct_or_reject_prices():
    bars = BarSeries('A', '1d')
    bars.update(Bar(date(2025, 1, 1), 10, 8, 9, 11, -1))
    bars.update(Bar(date(2025, 1, 2), 0, 1, -1, 0, None))
    bars.update(Bar(date(2025, 1, 3), 1, 2, 0, 1, 0))
    frozen = BarDataset.from_series(bars)
    original = frozen.fingerprint()
    assert frozen.quality_report()['observations'] == dict(
        null_volume=1, zero_volume=1, negative_volume=1,
        nonpositive_price=2, inconsistent_ohlc=1,
    )
    assert frozen.fingerprint() == original
    assert frozen.snapshot() == bars.snapshot()


@pytest.mark.parametrize('complete', [None, False, True])
def test_empty_inputs_report_status_and_do_not_infer_expected_observations(complete):
    report = dataset(days=(), complete=complete).quality_report()
    assert report['description']['rows'] == 0
    assert report['description']['download']['complete'] is complete
    assert report['calendar'] is None
    assert 'Dataset has no observed bars.' in report['warnings']
    assert sum(report['observations'].values()) == 0
    if complete is not True:
        assert any('Download' in warning for warning in report['warnings'])


def test_provider_errors_warnings_empty_windows_preserved(tmp_path):
    bars = BarSeries('A', '1d')
    bars.download_complete = True
    bars.empty_windows = [(date(2025, 1, 1), date(2025, 1, 2))]
    bars.error, bars.schedule_error = 'provider failure', 'schedule unavailable'
    bars.warnings = ['original provider warning']
    frozen = BarDataset.from_series(bars)
    loaded = BarDataset.load(frozen.save(tmp_path / 'input.json'))
    report = loaded.quality_report()
    assert report['description']['download']['empty_windows'] == [['2025-01-01', '2025-01-02']]
    assert 'original provider warning' in report['warnings']
    assert 'error: provider failure' in report['warnings']
    assert 'schedule_error: schedule unavailable' in report['warnings']
    report['warnings'].clear()
    assert frozen.quality_report() == loaded.quality_report()


def test_collection_reports_source_calendars_and_alignment_without_mutating(tmp_path):
    inputs = collection()
    original = inputs.fingerprint()
    report = inputs.quality_report(
        {'A': [date(2025, 1, 1), date(2025, 1, 2)], 'B': []},
        finalized_through={'A': date(2025, 1, 2)}, join='inner',
    )
    assert report['datasets']['A']['calendar']['matches_calendar']
    assert report['datasets']['A']['finality']['confirmed_count'] == 2
    assert report['datasets']['B']['calendar']['unexpected_count'] == 2
    assert report['datasets']['B']['finality']['basis'] == 'unknown'
    assert report['alignment']['status'] == 'available'
    assert report['alignment']['sources']['A']['dropped_rows'] == 1
    assert inputs.quality_report()['alignment'] is None
    assert inputs.quality_report()['datasets']['A']['calendar'] is None
    assert inputs.fingerprint() == original
    loaded = BarDatasetCollection.load(inputs.save(tmp_path / 'inputs.json'))
    assert loaded.describe() == inputs.describe()
    assert loaded.quality_report(join='outer') == inputs.quality_report(join='outer')
    json.dumps(report, allow_nan=False)


def test_collection_quality_remains_available_when_alignment_cannot_run():
    inputs = BarDatasetCollection({'A': dataset(), 'partial': dataset(complete=False)})
    report = inputs.quality_report(join='outer')
    assert report['alignment']['status'] == 'unavailable'
    assert 'partial' in report['alignment']['reason']
    assert report['datasets']['partial']['description']['download']['complete'] is False
    mixed = BarDatasetCollection({'daily': dataset(), 'intraday': dataset(interval='5min')})
    report = mixed.quality_report(join='inner')
    assert report['differences']['interval'] == dict(daily='1d', intraday='5min')
    assert report['alignment']['status'] == 'unavailable'
    assert len(report['datasets']) == 2


@pytest.mark.parametrize('kwargs', [
    {'expected': {'wrong': []}}, {'finalized_through': {'wrong': date(2025, 1, 1)}},
    {'join': 'left'}, {'field': 'returns'},
])
def test_collection_rejects_typo_labels_and_unsupported_views(kwargs):
    with pytest.raises(ValueError):
        collection().quality_report(**kwargs)


def test_collection_report_surfaces_different_price_sources_and_currencies():
    bars = BarSeries('B', '1d')
    bars.data_type, bars.currency, bars.adjustment = 'MIDPOINT', 'EUR', 'unknown'
    bars.update(Bar(date(2025, 1, 1), 1, 2, 0, 1, None))
    inputs = BarDatasetCollection({'A': dataset(), 'B': BarDataset.from_series(bars)})
    report = inputs.quality_report(join='outer')
    assert report['differences']['data_type'] == dict(A='TRADES', B='MIDPOINT')
    assert report['differences']['currency'] == dict(A='USD', B='EUR')
    assert report['datasets']['B']['observations']['null_volume'] == 1
    assert report['alignment']['status'] == 'available'


def test_example_writes_quality_json_offline_even_when_alignment_is_unavailable(
    tmp_path, monkeypatch, capsys,
):
    import runpy
    import sys
    from unittest.mock import patch

    inputs = BarDatasetCollection({'A': dataset(complete=False)})
    source = inputs.save(tmp_path / 'inputs.json')
    output = tmp_path / 'quality.json'
    monkeypatch.setattr(sys, 'argv', ['research_collection.py', 'inspect', str(source),
                                     '--join', 'outer', '--quality-report', str(output)])
    with patch('pyibquant.Market.ibkr', side_effect=AssertionError('must be offline')):
        runpy.run_path('examples/research_collection.py', run_name='__main__')
    report = json.loads(output.read_text())
    assert report == inputs.quality_report(join='outer')
    assert report['alignment']['status'] == 'unavailable'
    assert 'incomplete' in capsys.readouterr().out


@pytest.mark.parametrize('which', ['csv', 'quality-report', 'same_outputs'])
def test_example_prevents_output_paths_from_overwriting_inputs(tmp_path, monkeypatch, which):
    import runpy
    import sys

    inputs = collection()
    source = inputs.save(tmp_path / 'inputs.json')
    original = source.read_bytes()
    extra = ([f'--{which}', str(source)] if which != 'same_outputs' else
             ['--csv', str(tmp_path / 'output'), '--quality-report', str(tmp_path / 'output')])
    monkeypatch.setattr(sys, 'argv', ['research_collection.py', 'inspect', str(source),
                                     '--join', 'outer', *extra])
    with pytest.raises(SystemExit):
        runpy.run_path('examples/research_collection.py', run_name='__main__')
    assert source.read_bytes() == original

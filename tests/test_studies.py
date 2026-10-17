"""Hand-calculated study starters and gap isolation without scientific packages."""

import json
import runpy
from datetime import UTC, date, datetime, timedelta
from math import exp
from unittest.mock import patch

import pytest

from pyibquant import Bar, BarDataset, BarDatasetCollection, BarSeries
from pyibquant.studies import daily_correlations, intraday_scaling


def frozen(logs, *, interval='1d', offsets=None, complete=True, start=None):
    series = BarSeries('DEMO', interval)
    series.download_complete = complete
    series.session_timezone = 'America/New_York'
    if offsets is None:
        offsets = range(len(logs))
    for offset, value in zip(offsets, logs, strict=True):
        stamp = (date(2025, 1, 1) + timedelta(days=offset) if interval == '1d' else
                 (start or datetime(2025, 1, 2, 14, 30, tzinfo=UTC))
                 + timedelta(minutes=5 * offset))
        price = exp(value)
        series.update(Bar(stamp, price, price, price, price, 10))
    return BarDataset.from_series(series)


def test_daily_returns_and_hand_known_inverse_correlation():
    inputs = BarDatasetCollection({'A': frozen([0, .1, .3, .2]),
                                   'B': frozen([0, -.1, -.3, -.2])})
    original = inputs.fingerprint()
    report = daily_correlations(inputs)
    assert [row['values']['A'] for row in report['returns']] == pytest.approx([.1, .2, -.1])
    assert report['correlation']['samples'] == 3
    assert report['correlation']['matrix']['A']['B'] == pytest.approx(-1)
    assert report['correlation']['matrix']['A']['A'] == pytest.approx(1)
    assert inputs.fingerprint() == original
    json.dumps(report, allow_nan=False)


def test_missing_prices_never_produce_mismatched_multi_day_returns():
    inputs = BarDatasetCollection({'A': frozen([0, .1, .3, .2, .4]),
                                   'B': frozen([0, .3, .2, .4], offsets=[0, 2, 3, 4])})
    report = daily_correlations(inputs)
    assert report['returns'][0]['values']['B'] is None
    assert report['returns'][1]['values']['B'] is None
    assert report['correlation']['samples'] == 2
    assert report['correlation']['excluded_rows'] == 2
    assert report['correlation']['matrix']['A']['B'] == pytest.approx(1)


@pytest.mark.parametrize('logs', [[0], [0, 0, 0]])
def test_insufficient_or_constant_samples_are_undefined_not_zero(logs):
    report = daily_correlations(BarDatasetCollection({'A': frozen(logs)}))
    assert report['correlation']['matrix']['A']['A'] is None


def test_daily_rejects_intraday_and_preserves_quality_unknowns():
    with pytest.raises(ValueError, match='daily inputs'):
        daily_correlations(BarDatasetCollection({'A': frozen([0, 1], interval='5min')}))
    result = daily_correlations(BarDatasetCollection({'A': frozen([0, 1])}))
    assert result['quality']['datasets']['A']['calendar'] is None
    assert result['quality']['datasets']['A']['finality']['basis'] == 'unknown'


def test_scaling_increments_and_moments_by_hand():
    inputs = frozen([0, 1, 2, 3], interval='5min')
    original = inputs.fingerprint()
    report = intraday_scaling(inputs, lags=[1, 2, 8])
    one, two, empty = report['moments']
    assert one['samples'] == 3
    assert one['mean_absolute_increment'] == pytest.approx(1)
    assert one['mean_squared_increment'] == pytest.approx(1)
    assert two['samples'] == 2
    assert two['elapsed_seconds'] == 600
    assert two['mean_absolute_increment'] == pytest.approx(2)
    assert two['mean_squared_increment'] == pytest.approx(4)
    assert empty['samples'] == 0
    assert empty['mean_squared_increment'] is None
    assert report['settings']['overlapping'] is True
    assert len(report['increments']) == 5
    assert inputs.fingerprint() == original
    json.dumps(report, allow_nan=False)


def test_scaling_rejects_gap_bridging_even_when_only_endpoints_would_match():
    inputs = frozen([0, 1, 3, 4], interval='5min', offsets=[0, 1, 3, 4])
    report = intraday_scaling(inputs, lags=[1, 2, 3])
    assert [item['samples'] for item in report['moments']] == [2, 0, 0]
    assert report['moments'][0]['excluded_candidates'] == 1


def test_scaling_does_not_cross_local_midnight_even_on_a_continuous_grid():
    # 05:00 UTC is midnight in New York in January.
    inputs = frozen([0, 1, 2, 3], interval='5min',
                    start=datetime(2025, 1, 2, 4, 50, tzinfo=UTC))
    local = intraday_scaling(inputs, lags=[1, 2], session_timezone='America/New_York')
    assert [item['samples'] for item in local['moments']] == [2, 0]
    utc = intraday_scaling(inputs, lags=[1], session_timezone='UTC')
    assert utc['moments'][0]['samples'] == 3


@pytest.mark.parametrize('lags', [[], [0], [-1], [1, 1], [True], [1.5]])
def test_invalid_lag_definitions(lags):
    with pytest.raises(ValueError):
        intraday_scaling(frozen([0, 1], interval='5min'), lags=lags)


def test_scaling_rejects_daily_and_unknown_timezone():
    with pytest.raises(ValueError, match='intraday'):
        intraday_scaling(frozen([0, 1]))
    source = frozen([0, 1], interval='5min')
    metadata = source.metadata()
    metadata['session_timezone'] = None
    unknown = BarDataset._create(source.snapshot(), metadata)
    with pytest.raises(ValueError, match='session_timezone'):
        intraday_scaling(unknown)
    assert intraday_scaling(unknown, session_timezone='UTC')['moments'][0]['samples'] == 1


@pytest.mark.parametrize('complete,logs', [(False, [0, 1]), (None, [0, 1]), (True, [])])
def test_empty_incomplete_unknown_downloads_rejected(complete, logs):
    with pytest.raises(ValueError):
        daily_correlations(BarDatasetCollection({'A': frozen(logs, complete=complete)}))
    with pytest.raises(ValueError):
        intraday_scaling(frozen(logs, interval='5min', complete=complete))


def test_nonpositive_close_is_explicit_in_both_workflows():
    for interval in ['1d', '5min']:
        series = BarSeries('A', interval)
        series.download_complete = True
        stamp = date(2025, 1, 1) if interval == '1d' else datetime(2025, 1, 1, tzinfo=UTC)
        series.update(Bar(stamp, 0, 0, 0, 0, 0))
        inputs = BarDataset.from_series(series)
        with pytest.raises(ValueError, match='strictly positive'):
            if interval == '1d':
                daily_correlations(BarDatasetCollection({'A': inputs}))
            else:
                intraday_scaling(inputs)


@pytest.mark.parametrize('study', ['correlations', 'scaling'])
def test_offline_examples_write_study_data_and_provenance(tmp_path, monkeypatch, study):
    import sys

    interval = '1d' if study == 'correlations' else '5min'
    inputs = BarDatasetCollection({'A': frozen([0, .1, .3, .2], interval=interval)})
    source = inputs.save(tmp_path / 'inputs.json')
    output = tmp_path / 'report.json'
    extras = [] if study == 'correlations' else ['--instrument', 'A', '--lags', '1', '2']
    monkeypatch.setattr(sys, 'argv', ['research_studies.py', study, str(source),
                                     '--output', str(output), *extras])
    with patch('pyibquant.Market.ibkr', side_effect=AssertionError('must be offline')):
        runpy.run_path('examples/research_studies.py', run_name='__main__')
    result = json.loads(output.read_text())
    assert result['quality']
    if study == 'scaling':
        assert result['collection_fingerprint'] == inputs.fingerprint()
        assert result['instrument_label'] == 'A'
    else:
        assert result['correlation']['samples'] == 3


def test_example_prevents_overwriting_collection(tmp_path, monkeypatch):
    import sys

    source = BarDatasetCollection({'A': frozen([0, 1])}).save(tmp_path / 'inputs.json')
    original = source.read_bytes()
    monkeypatch.setattr(sys, 'argv', ['research_studies.py', 'correlations', str(source),
                                     '--output', str(source)])
    with pytest.raises(SystemExit):
        runpy.run_path('examples/research_studies.py', run_name='__main__')
    assert source.read_bytes() == original

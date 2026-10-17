"""Collection integrity, exact alignment and bounded acquisition behavior."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from pyibquant import Bar, BarDataset, BarDatasetCollection, BarSeries
from pyibquant.dataset import _encoded


def dataset(symbol='A', days=(1, 2), *, interval='1d', complete=True, volume=10):
    bars = BarSeries(symbol, interval)
    bars.asset_type, bars.currency, bars.data_type = 'equity', 'USD', 'TRADES'
    bars.download_complete = complete
    for day in days:
        stamp = date(2025, 1, day) if interval == '1d' else datetime(2025, 1, day, tzinfo=UTC)
        bars.update(Bar(stamp, 10, 12, 9, 11 + day, volume))
    return BarDataset.from_series(bars)


def collection():
    return BarDatasetCollection({'A': dataset(), 'B': dataset('B', (2, 3))})


def test_inner_outer_exact_alignment_reports_dropped_and_missing_rows():
    inputs = collection()
    inner = inputs.align(join='inner')
    assert inner.to_records() == [dict(timestamp=date(2025, 1, 2), A=13, B=13)]
    assert inner.metadata()['sources']['A']['dropped_rows'] == 1
    assert inner.metadata()['sources']['B']['dropped_rows'] == 1
    outer = inputs.align(join='outer')
    assert outer.columns['A'] == (12, 13, None)
    assert outer.columns['B'] == (None, 13, 14)
    for source in outer.metadata()['sources'].values():
        assert source['absent_rows'] == source['null_values'] == 1
        assert source['dropped_rows'] == 0
    assert inputs['A'].snapshot() == dataset().snapshot()
    assert outer.metadata()['gaps'] == outer.metadata()['bar_finality'] == 'not_verified'
    assert outer.metadata()['fill'] == 'none'
    assert outer.metadata()['sources']['A']['fingerprint'] == inputs['A'].fingerprint()


def test_missing_volume_is_distinct_from_absent_bar():
    inputs = BarDatasetCollection({'A': dataset(volume=None), 'B': dataset('B', (2, 3))})
    view = inputs.align(field='volume', join='outer')
    assert view.columns['A'] == (None, None, None)
    assert view.metadata()['sources']['A']['null_values'] == 3
    assert view.metadata()['sources']['A']['absent_rows'] == 1


def test_collection_is_frozen_and_outputs_are_independent():
    source = {'A': dataset()}
    inputs = BarDatasetCollection(source)
    source.clear()
    assert list(inputs) == ['A']
    view = inputs.align(join='outer')
    with pytest.raises(TypeError):
        view.columns['A'] = ()
    view.to_records()[0]['A'] = 100
    view.metadata()['sources']['A']['metadata']['symbol'] = 'edited'
    assert view.columns['A'][0] == 12
    assert view.metadata()['sources']['A']['metadata']['symbol'] == 'A'


@pytest.mark.parametrize('interval', ['1d', '5min'])
def test_roundtrip_preserves_column_order_sources_and_fingerprints(tmp_path, interval):
    inputs = BarDatasetCollection({'z': dataset(interval=interval),
                                   'a': dataset('B', (2, 3), interval=interval)})
    target = inputs.save(tmp_path / 'nested' / 'inputs.json')
    loaded = BarDatasetCollection.load(target)
    assert list(loaded) == ['z', 'a']
    assert loaded.fingerprint() == inputs.fingerprint()
    for key in inputs:
        assert loaded[key].fingerprint() == inputs[key].fingerprint()
        assert loaded[key].snapshot() == inputs[key].snapshot()
    assert loaded.align(join='outer').to_records() == inputs.align(join='outer').to_records()


def test_failed_save_preserves_destination(tmp_path):
    target = tmp_path / 'inputs.json'
    target.write_text('original')
    with patch('pyibquant.collection.os.replace', side_effect=OSError('failure')):
        with pytest.raises(OSError):
            collection().save(target)
    assert target.read_text() == 'original'
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('mutation', [
    'checksum', 'nested_checksum', 'duplicate', 'version', 'bars',
])
def test_integrity_and_structural_checks(tmp_path, mutation):
    target = collection().save(tmp_path / 'inputs.json')
    doc = json.loads(target.read_text())
    entry = doc['payload']['datasets'][0]
    if mutation == 'checksum':
        entry['key'] = 'changed'
    elif mutation == 'nested_checksum':
        entry['dataset']['sha256'] = 'invalid'
    elif mutation == 'duplicate':
        doc['payload']['datasets'].append(entry)
    elif mutation == 'version':
        doc['version'] = 100
    else:
        nested = entry['dataset']['payload']
        nested['bars'].append(nested['bars'][0])
        entry['dataset']['sha256'] = hashlib.sha256(_encoded(nested).encode()).hexdigest()
    if mutation != 'checksum':
        doc['sha256'] = hashlib.sha256(_encoded(doc['payload']).encode()).hexdigest()
    target.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        BarDatasetCollection.load(target)


@pytest.mark.parametrize('text', ['{}', '[]', 'null', '{bad'])
def test_malformed_documents(tmp_path, text):
    target = tmp_path / 'bad.json'
    target.write_text(text)
    with pytest.raises(ValueError):
        BarDatasetCollection.load(target)


@pytest.mark.parametrize('inputs', [{}, {'timestamp': dataset()}, {' ': dataset()},
                                   {1: dataset()}, {'A': object()}])
def test_invalid_collection_inputs(inputs):
    with pytest.raises(ValueError):
        BarDatasetCollection(inputs)


@pytest.mark.parametrize('join,field', [('left', 'close'), ('outer', 'returns')])
def test_invalid_alignment_arguments(join, field):
    with pytest.raises(ValueError):
        collection().align(join=join, field=field)


def test_join_is_required():
    with pytest.raises(TypeError):
        collection().align()


def test_empty_disjoint_and_unknown_completeness():
    inputs = BarDatasetCollection({'A': dataset(days=(), complete=None), 'B': dataset()})
    assert inputs.align(join='inner').to_records() == []
    assert inputs.align(join='outer').columns['A'] == (None, None)
    assert inputs.align(join='outer').metadata()['sources']['A']['metadata']['download'][
        'complete'] is None
    assert BarDatasetCollection({'A': dataset(days=(1,)), 'B': dataset(days=(2,))}).align(
        join='inner').timestamps == ()


@pytest.mark.parametrize('setting,value', [('interval', '5min'), ('regular_hours', False),
                                          ('session_timezone', 'Europe/London')])
def test_incompatible_sampling_and_sessions_rejected(setting, value):
    other = BarSeries('B', '1d')
    other.update(Bar(date(2025, 1, 1), 10, 12, 9, 11, 10))
    if setting == 'interval':
        frozen = dataset(interval=value)
    else:
        setattr(other, setting, value)
        frozen = BarDataset.from_series(other)
    with pytest.raises(ValueError, match='incompatible'):
        BarDatasetCollection({'A': dataset(), 'B': frozen}).align(join='outer')


def test_known_partial_rejected_and_heterogeneous_sources_preserved(tmp_path):
    inputs = BarDatasetCollection({'A': dataset(complete=False)})
    loaded = BarDatasetCollection.load(inputs.save(tmp_path / 'partial.json'))
    with pytest.raises(ValueError, match='incomplete'):
        loaded.align(join='outer')
    other = BarSeries('OPTION', '1d')
    other.data_type, other.currency, other.multiplier = 'MIDPOINT', 'EUR', 50
    other.update(Bar(date(2025, 1, 1), 10, 12, 9, 11, None))
    mixed = BarDatasetCollection({'A': dataset(), 'B': BarDataset.from_series(other)})
    source = mixed.align(join='outer').metadata()['sources']['B']['metadata']
    assert (source['data_type'], source['currency'], source['multiplier']) == (
        'MIDPOINT', 'EUR', 50)


def test_utc_matching_uses_instants_not_offset_strings():
    other = BarSeries('B', '5min')
    local = datetime(2024, 12, 31, 19, tzinfo=timezone(timedelta(hours=-5)))
    other.update(Bar(local, 10, 12, 9, 11, 10))
    inputs = BarDatasetCollection({'A': dataset(interval='5min'),
                                   'B': BarDataset.from_series(other)})
    assert inputs.align(join='inner').timestamps == (datetime(2025, 1, 1, tzinfo=UTC),)


def test_optional_pandas_preserves_missing_and_empty_schemas():
    pd = pytest.importorskip('pandas')
    frame = collection().align(join='outer').to_dataframe()
    assert list(frame.columns) == ['A', 'B']
    assert frame.index[0] == date(2025, 1, 1)
    assert pd.isna(frame.loc[date(2025, 1, 1), 'B'])
    for days in [(), (1, 2)]:
        view = BarDatasetCollection({'A': dataset(days=days, interval='5min')}).align(join='outer')
        frame = view.to_dataframe()
        assert str(frame.index.tz) == 'UTC'
        assert str(frame.dtypes['A']) == 'float64'


def test_example_fetch_and_offline_inspection(tmp_path, monkeypatch, capsys):
    import runpy
    import sys

    class FakeMarket:
        calls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def datasets(self, instruments, **kwargs):
            from unittest.mock import Mock

            from pyibquant import Market
            market = Market(Mock())
            market.bars = self.bars
            return market.datasets(instruments, **kwargs)

        def bars(self, symbol, **kwargs):
            self.calls.append((symbol, kwargs))
            bars = BarSeries(symbol, kwargs['interval'])
            bars.download_complete = True
            bars.update(Bar(date(2025, 1, 1), 10, 12, 9, 11, 10))
            return bars

    target = tmp_path / 'inputs.json'
    monkeypatch.setattr(sys, 'argv', ['research_collection.py', 'fetch', 'A', 'B', '--start',
                                     '2025-01-01', '--end', '2025-01-03', '--output', str(target)])
    with patch('pyibquant.Market.ibkr', return_value=FakeMarket()):
        runpy.run_path('examples/research_collection.py', run_name='__main__')
    assert [key for key, _ in FakeMarket.calls] == ['A', 'B']
    assert all(kwargs == dict(interval='1d', start=date(2025, 1, 1), end=date(2025, 1, 3),
                              regular_hours=True, primary_exchange='', refresh=False,
                              include_sessions=False, data_type='TRADES')
               for _, kwargs in FakeMarket.calls)
    output = tmp_path / 'values.csv'
    monkeypatch.setattr(sys, 'argv', ['research_collection.py', 'inspect', str(target),
                                     '--join', 'outer', '--csv', str(output)])
    with patch('pyibquant.Market.ibkr', side_effect=AssertionError('must be offline')):
        runpy.run_path('examples/research_collection.py', run_name='__main__')
    assert output.read_text().splitlines() == ['timestamp,A,B', '2025-01-01,11,11']
    assert 'not_verified' in capsys.readouterr().out


@pytest.mark.parametrize('failure', ['empty', 'partial', 'provider'])
def test_example_failed_fetch_does_not_replace_existing_collection(tmp_path, monkeypatch, failure):
    import runpy
    import sys
    from contextlib import nullcontext

    target = collection().save(tmp_path / 'inputs.json')
    original = target.read_bytes()
    first = BarSeries('A', '1d')
    first.download_complete = True
    first.update(Bar(date(2025, 1, 1), 10, 12, 9, 11, 10))
    second = BarSeries('B', '1d')
    second.download_complete = failure != 'partial'
    if failure != 'empty':
        second.update(Bar(date(2025, 1, 1), 10, 12, 9, 11, 10))
    from unittest.mock import Mock

    from pyibquant import Market
    market = Market(Mock())
    market.bars = Mock()
    market.bars.side_effect = [first, RuntimeError('permission failure')
                              if failure == 'provider' else second]
    monkeypatch.setattr(sys, 'argv', ['research_collection.py', 'fetch', 'A', 'B', '--start',
                                     '2025-01-01', '--end', '2025-01-03', '--output', str(target)])
    with patch('pyibquant.Market.ibkr', return_value=nullcontext(market)):
        with pytest.raises((SystemExit, RuntimeError)):
            runpy.run_path('examples/research_collection.py', run_name='__main__')
    assert target.read_bytes() == original

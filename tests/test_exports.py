"""Research exports use frozen bar snapshots and require no broker connection."""

import csv
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from pyibquant import Bar, BarSeries


def make_series(stamp, interval='1min'):
    bars = BarSeries('DEMO', interval, live=True)
    bars.update(Bar(stamp + timedelta(days=1), 110, 115, 105, 112, 2000))
    bars.update(Bar(stamp, 100, 105, 95, 102, 1000))
    bars.update(Bar(stamp, 100, 106, 95, 103, 1100))  # Replacement, not a duplicate row.
    return bars


@pytest.mark.parametrize('stamp,interval', [
    (datetime(2026, 3, 6, 9, 30, tzinfo=timezone(timedelta(hours=-5))), '1min'),
    (date(2026, 3, 6), '1d'),
    (date(2026, 3, 2), '1w'),
    (date(2026, 1, 1), '1y'),
])
def test_records_and_csv_preserve_ohlcv_and_timestamp_identity(tmp_path, stamp, interval):
    series = make_series(stamp, interval)
    records = series.to_records()
    assert len(records) == 2
    expected = stamp.astimezone(UTC) if isinstance(stamp, datetime) else stamp
    assert records[0] == dict(timestamp=expected, open=100, high=106, low=95,
                              close=103, volume=1100)
    assert records[1]['timestamp'] > records[0]['timestamp']
    path = series.to_csv(tmp_path / 'nested' / 'bars.csv')
    assert path.is_absolute()
    with path.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    assert rows[0]['timestamp'] == expected.isoformat()
    for record, row in zip(records, rows, strict=True):
        assert all(float(row[key]) == record[key]
                   for key in ('open', 'high', 'low', 'close', 'volume'))
    records[0]['close'] = -1
    assert series.snapshot()[0].close == 103
    assert series.to_records()[0]['close'] == 103


def test_exports_take_one_snapshot_even_if_live_series_changes(tmp_path):
    series = make_series(date(2026, 3, 6), '1d')
    snapshot = series.snapshot()

    def capture_then_update():
        series.update(Bar(date(2026, 3, 8), 200, 205, 195, 202, 3000))
        return snapshot

    with patch.object(series, 'snapshot', side_effect=capture_then_update) as capture:
        path = series.to_csv(tmp_path / 'snapshot.csv')
        capture.assert_called_once()
    with path.open(newline='') as stream:
        assert len(list(csv.DictReader(stream))) == 2
    assert len(series) == 3


def test_empty_exports_have_stable_csv_schema(tmp_path):
    series = BarSeries('DEMO', '1min')
    assert series.to_records() == []
    path = series.to_csv(tmp_path / 'empty.csv')
    assert path.read_text() == 'timestamp,open,high,low,close,volume\n'


def test_csv_failure_preserves_existing_file_and_cleans_temporary(tmp_path):
    series = make_series(date(2026, 3, 6), '1d')
    path = tmp_path / 'bars.csv'
    path.write_text('original')
    with patch('pyibquant.bars.os.replace', side_effect=OSError('write denied')):
        with pytest.raises(OSError, match='write denied'):
            series.to_csv(path)
    assert path.read_text() == 'original'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['bars.csv']


def test_csv_expands_user_path(tmp_path, monkeypatch):
    # Path.expanduser is the only substitution; no write to the actual home directory.
    monkeypatch.setattr('pathlib.Path.expanduser', lambda self: tmp_path / 'chosen.csv')
    assert BarSeries('DEMO', '1d').to_csv('~/chosen.csv') == tmp_path / 'chosen.csv'


def test_missing_pandas_is_actionable_and_does_not_affect_other_exports():
    import builtins

    original = builtins.__import__

    def without_pandas(name, *args, **kwargs):
        if name == 'pandas' or name.startswith('pandas.'):
            raise ImportError('not installed')
        return original(name, *args, **kwargs)

    series = make_series(date(2026, 3, 6), '1d')
    with patch('builtins.__import__', side_effect=without_pandas):
        assert len(series.to_records()) == 2
        with pytest.raises(ImportError, match=r'pyibquant\[pandas\]'):
            series.to_dataframe()


@pytest.mark.parametrize('stamp,interval', [
    (datetime(2026, 3, 6, 9, 30, tzinfo=timezone(timedelta(hours=-5))), '1min'),
    (date(2026, 3, 6), '1d'),
    (date(2026, 1, 1), '1y'),
])
def test_dataframe_matches_records_and_is_independent(stamp, interval):
    pd = pytest.importorskip('pandas')
    series = make_series(stamp, interval)
    frame = series.to_dataframe()
    assert frame.index.name == 'timestamp'
    assert list(frame.columns) == ['open', 'high', 'low', 'close', 'volume']
    assert all(str(dtype) == 'float64' for dtype in frame.dtypes)
    records = series.to_records()
    if isinstance(stamp, datetime):
        assert isinstance(frame.index, pd.DatetimeIndex)
        assert str(frame.index.tz) == 'UTC'
        assert frame.index[0].to_pydatetime() == records[0]['timestamp']
    else:
        assert not isinstance(frame.index, pd.DatetimeIndex)
        assert type(frame.index[0]) is date
        assert frame.index[0] == records[0]['timestamp']
    assert frame['close'].tolist() == [103, 112]
    frame.iloc[0, frame.columns.get_loc('close')] = -1
    assert series.snapshot()[0].close == 103
    assert series.to_dataframe()['close'].iloc[0] == 103


@pytest.mark.parametrize('interval', ['1min', '1d'])
def test_empty_dataframe_preserves_numeric_columns(interval):
    pytest.importorskip('pandas')
    frame = BarSeries('DEMO', interval).to_dataframe()
    assert frame.empty
    assert frame.index.name == 'timestamp'
    assert list(frame.columns) == ['open', 'high', 'low', 'close', 'volume']
    assert all(str(dtype) == 'float64' for dtype in frame.dtypes)


def test_dataframe_uses_one_snapshot():
    pytest.importorskip('pandas')
    series = make_series(date(2026, 3, 6), '1d')
    series.snapshot = Mock(return_value=series.snapshot())
    assert len(series.to_dataframe()) == 2
    series.snapshot.assert_called_once()

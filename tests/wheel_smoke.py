"""Run with python -I after installing a wheel into a fresh, SDK-free environment."""

import importlib.util
import sys
from datetime import date
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import pyibquant
from pyibquant import Bar, BarDataset, BarSeries, HistoricalRangeError, Market
from pyibquant.data.history import normalize_range
from pyibquant.research import simple_returns, sma

assert Path(pyibquant.__file__).is_relative_to(Path(sys.prefix)), pyibquant.__file__
assert importlib.util.find_spec('ibapi') is None, 'Use an environment without the SDK'
assert importlib.util.find_spec('pyarrow') is None, 'Base wheel must work without Parquet'
assert 'ibapi' not in sys.modules
assert 'pyarrow' not in sys.modules
assert importlib.util.find_spec('pandas') is None, 'Base exports must work without pandas'
assert 'pandas' not in sys.modules
resources = files('pyibquant')
assert resources.joinpath('py.typed').is_file()
assert resources.joinpath('visualization', 'chart.js').is_file()
bars = BarSeries('DEMO', '1d')
bars.update(Bar(date(2026, 1, 1), 100, 103, 99, 102, 10))
assert bars.metadata()['coverage']['rows'] == 1
assert simple_returns([100, 110])[0] is None
assert sma([100, 110], 2) == (None, 105)
bounds = normalize_range('2026-01-01', '2026-01-02', '1d')
assert bounds.contains(date(2026, 1, 1))
assert HistoricalRangeError('failed', bars, remaining_start=bounds.start,
                            remaining_end=bounds.end).partial is bars
with TemporaryDirectory() as directory:
    html = bars.plot(Path(directory) / 'chart.html', open_browser=False).read_text()
    assert 'class MarketChart' in html
    assert 'function freshness' in html
    assert '__CHART_' not in html
    assert '<script src=' not in html
    assert bars.to_records()[0]['timestamp'] == date(2026, 1, 1)
    assert bars.to_csv(Path(directory) / 'bars.csv').is_file()
    dataset = BarDataset.load(BarDataset.from_series(bars).save(Path(directory) / 'bars.json'))
    assert dataset.snapshot() == bars.snapshot()
    assert dataset.audit([date(2026, 1, 1)]).matches_calendar
    try:
        bars.to_dataframe()
    except ImportError as exc:
        assert 'pyibquant[pandas]' in str(exc)
    else:
        raise AssertionError('Missing pandas should give an optional-dependency error')
try:
    Market.ibkr()
except ImportError as exc:
    assert 'official TWS API' in str(exc)
else:
    raise AssertionError('Missing SDK should give an actionable installation error')
print('PASS: isolated wheel imports, packaged assets, offline export and missing-SDK error')

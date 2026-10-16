"""Run with python -I after installing a wheel into a fresh, SDK-free environment."""

import importlib.util
import sys
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import pyibquant
from pyibquant import (
    Bar,
    BarDataset,
    BarSeries,
    HistoricalRangeError,
    Market,
    Option,
    OptionChain,
    OptionChainGroup,
    QuoteStream,
)
from pyibquant.backtest import backtest_equity
from pyibquant.data.history import normalize_range
from pyibquant.quotes import QuoteInstrument, _QuoteState
from pyibquant.research import simple_returns, sma

assert Path(pyibquant.__file__).is_relative_to(Path(sys.prefix)), pyibquant.__file__
assert importlib.util.find_spec('ibapi') is None, 'Use an environment without the SDK'
assert importlib.util.find_spec('pyarrow') is None, 'Base wheel must work without Parquet'
assert 'ibapi' not in sys.modules
assert 'pyarrow' not in sys.modules
assert importlib.util.find_spec('pandas') is None, 'Base exports must work without pandas'
assert 'pandas' not in sys.modules
assert Option('demo', date(2026, 11, 20), 100, 'c').symbol == 'DEMO'
resources = files('pyibquant')
assert resources.joinpath('py.typed').is_file()
assert resources.joinpath('visualization', 'chart.js').is_file()
bars = BarSeries('DEMO', '1d')
bars.update(Bar(date(2026, 1, 1), 100, 103, 99, 102, 10))
bars.asset_type, bars.multiplier, bars.data_type = 'equity', 1, 'TRADES'
bars.adjustment = 'splits_only'
assert bars.metadata()['coverage']['rows'] == 1
assert simple_returns([100, 110])[0] is None
assert sma([100, 110], 2) == (None, 105)
bounds = normalize_range('2026-01-01', '2026-01-02', '1d')
assert bounds.contains(date(2026, 1, 1))
assert HistoricalRangeError('failed', bars, remaining_start=bounds.start,
                            remaining_end=bounds.end).partial is bars
with TemporaryDirectory() as directory:
    chain = OptionChain('DEMO', 123, 'USD', (
        OptionChainGroup('SMART', 'DEMO', 100, (date(2026, 11, 20),), (100,)),
    ), datetime.now(UTC))
    assert chain.select(date(2026, 11, 20), 100, 'C').trading_class == 'DEMO'
    instrument = QuoteInstrument('DEMO', 123, 'equity', 'USD', 'SMART', '',
                                 'DEMO', 'DEMO', 1, None, None, None)
    state = _QuoteState(instrument, 'live', streaming=True)
    with QuoteStream(state, lambda: state.finish('closed')) as stream:
        state.tick(1, 100)
        state.tick(2, 102)
        quote = stream.latest()
        assert quote.bid == 100 and quote.ask == 102 and quote.spread == 2
        assert stream.wait_for_update(0, timeout=0).sequence == quote.sequence
    assert stream.closed
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
    bars.update(Bar(date(2026, 1, 2), 104, 106, 103, 105, 10))
    bars.requested_start, bars.requested_end = date(2026, 1, 1), date(2026, 1, 3)
    bars.download_complete = True
    result = backtest_equity(BarDataset.from_series(bars), [True, False],
                             finalized_through=date(2026, 1, 2))
    assert result.metrics()['ending_shares'] == 1
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

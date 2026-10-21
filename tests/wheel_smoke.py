"""Run with python -I after installing a wheel into a fresh, SDK-free environment."""

import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pyibquant
from pyibquant import (
    Bar,
    BarDataset,
    BarDatasetCollection,
    BarRequest,
    BarSeries,
    HistoricalRangeError,
    Market,
    Option,
    OptionChain,
    OptionChainGroup,
    PaperBroker,
    QuoteStream,
)
from pyibquant.backtest import backtest_equity
from pyibquant.data.history import normalize_range
from pyibquant.option_backtest import backtest_option
from pyibquant.quotes import QuoteInstrument, _QuoteState
from pyibquant.research import simple_returns, sma
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate
from pyibquant.studies import daily_correlations, intraday_scaling
from pyibquant.trading.cancel_check import check_tag
from pyibquant.trading.funding import SettlementPolicy
from pyibquant.trading.option_runner import OptionRunner
from pyibquant.trading.profile import PaperProfile

assert Path(pyibquant.__file__).is_relative_to(Path(sys.prefix)), pyibquant.__file__
assert importlib.util.find_spec('ibapi') is None, 'Use an environment without the SDK'
assert importlib.util.find_spec('pyarrow') is None, 'Base wheel must work without Parquet'
assert OptionRunner is not None
assert SettlementPolicy.from_dict(SettlementPolicy().to_dict()) == SettlementPolicy()
assert 'ibapi' not in sys.modules
assert 'pyarrow' not in sys.modules
assert importlib.util.find_spec('pandas') is None, 'Base exports must work without pandas'
assert 'pandas' not in sys.modules
assert PaperProfile().runner_config().dry_run
assert PaperProfile().broker_options(preflight=True)['readonly']
assert check_tag('a' * 32) == 'cancel-check-' + 'a' * 32
assert Option('demo', date(2026, 11, 20), 100, 'c').symbol == 'DEMO'
resources = files('pyibquant')
assert resources.joinpath('py.typed').is_file()
assert resources.joinpath('visualization', 'chart.js').is_file()
bars = BarSeries('DEMO', '1d')
bars.update(Bar(date(2026, 1, 1), 100, 103, 99, 102, 10))
bars.asset_type, bars.currency, bars.multiplier, bars.data_type = 'equity', 'USD', 1, 'TRADES'
bars.adjustment = 'splits_only'
assert bars.metadata()['coverage']['rows'] == 1
assert simple_returns([100, 110])[0] is None
assert sma([100, 110], 2) == (None, 105)
bounds = normalize_range('2026-01-01', '2026-01-02', '1d')
assert bounds.contains(date(2026, 1, 1))
assert HistoricalRangeError('failed', bars, remaining_start=bounds.start,
                            remaining_end=bounds.end).partial is bars
with TemporaryDirectory() as directory:
    adapter = SimpleNamespace(client_id=987, close=lambda: None)
    with PaperBroker(adapter, Path(directory) / 'account.sqlite3', account='DU123') as broker:
        assert broker.readonly and not broker.snapshot().complete
        assert broker.funding()['usable'] is None
        assert broker.report(Path(directory) / 'account.html').is_file()
        assert broker.strategy_ledger('smoke').complete
        assert broker.export_strategy('smoke', Path(directory) / 'strategy.json').is_file()
        from pyibquant.trading.offline import load_account
        assert load_account(broker.journal.path)[1].status == 'offline'
    assert 'ibapi' not in sys.modules
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
    collection = BarDatasetCollection({'demo': dataset})
    loaded = BarDatasetCollection.load(collection.save(Path(directory) / 'inputs.json'))
    assert loaded.fingerprint() == collection.fingerprint()
    assert loaded.align(join='outer').to_records() == [dict(timestamp=date(2026, 1, 1), demo=102)]
    quality = loaded.quality_report({'demo': [date(2026, 1, 1)]}, join='outer')
    assert quality['datasets']['demo']['calendar']['matches_calendar']
    assert quality['datasets']['demo']['finality']['basis'] == 'unknown'
    assert BarRequest('demo').instrument == 'DEMO'
    bars.update(Bar(date(2026, 1, 2), 104, 106, 103, 105, 10))
    bars.requested_start, bars.requested_end = date(2026, 1, 1), date(2026, 1, 3)
    bars.download_complete = True
    result = backtest_equity(BarDataset.from_series(bars), [True, False],
                             finalized_through=date(2026, 1, 2))
    assert result.metrics()['ending_shares'] == 1
    option_bars = BarSeries('DEMO', '5min')
    option_bars.asset_type, option_bars.currency = 'option', 'USD'
    option_bars.instrument_id, option_bars.multiplier, option_bars.data_type = 456, 150, 'MIDPOINT'
    option_bars.option_metadata = dict(expiry='20261120', strike=100, right='C')
    option_bars.requested_start = datetime(2026, 10, 16, 13, 30, tzinfo=UTC)
    option_bars.requested_end = datetime(2026, 10, 16, 14, tzinfo=UTC)
    option_bars.download_complete = True
    option_bars.update(Bar(datetime(2026, 10, 16, 13, 30, tzinfo=UTC), 10, 11, 10, 11, None))
    option_bars.update(Bar(datetime(2026, 10, 16, 13, 35, tzinfo=UTC), 12, 13, 12, 13, None))
    frozen_option = BarDataset.from_series(option_bars)
    loaded_option = BarDataset.load(frozen_option.save(Path(directory)/'option.json'))
    assert loaded_option.fingerprint() == frozen_option.fingerprint()
    daily_study = daily_correlations(BarDatasetCollection({'demo': BarDataset.from_series(bars)}))
    assert daily_study['correlation']['samples'] == 1
    assert daily_study['correlation']['matrix']['demo']['demo'] is None
    scaling_study = intraday_scaling(loaded_option, lags=(1,), session_timezone='UTC')
    assert scaling_study['moments'][0]['samples'] == 1
    assert 'numpy' not in sys.modules and 'scipy' not in sys.modules
    option_result = backtest_option(loaded_option, [True, False], fill_model='next_bar_open',
                                    finalized_through=option_bars.requested_end)
    assert option_result.metrics()['unrealized_net_pnl'] == 150
    for key, frozen, finality in [
        ('equity', BarDataset.from_series(bars), date(2026, 1, 2)),
        ('option', loaded_option, option_bars.requested_end),
    ]:
        simulation = simulate(
            {key: Feed(frozen, finality)}, TargetStrategy(key, lambda context: 2),
            execution=NextOpen(commission_per_unit=.5), strategy_settings=dict(name='hold_two'),
        )
        assert simulation.portfolio.positions[key].quantity == 2
        restored = json.loads(simulation.save(Path(directory)/f'{key}-simulation.json').read_text())
        assert restored['provenance']['inputs'][key]['fingerprint'] == frozen.fingerprint()
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
print('PASS: isolated wheel imports, assets, exports, strategy simulation and missing-SDK error')

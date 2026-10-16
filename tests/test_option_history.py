"""On-demand option history preserves source semantics and never requests live quotes."""

import csv
import runpy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import BarDataset, HistoricalRangeError, Market, Option
from pyibquant.data.providers.ibkr import IBKRProvider
from pyibquant.errors import DataError

START = datetime(2026, 10, 15, 13, 30, tzinfo=UTC)
END = START + timedelta(minutes=30)
OPTION = Option('AAPL', date(2026, 11, 20), 340, 'C', 'AAPL1', 150)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr('pyibquant.data.providers.ibkr.current_time',
                        lambda: datetime(2026, 10, 16, 22, tzinfo=UTC).timestamp())
    broker = IBKRProvider('127.0.0.1', 7497, 220, .02)
    broker.isConnected = Mock(return_value=True)
    broker.cancelHistoricalData = Mock()
    broker.reqMktData = Mock()
    broker.reqMarketDataType = Mock()
    broker._pacer = Mock()

    def resolve(req_id, contract):
        contract.conId = 999
        contract.multiplier = contract.multiplier or '100'
        contract.tradingClass = contract.tradingClass or 'AAPL'
        contract.localSymbol = 'AAPL ADJUSTED CALL'
        broker.contractDetails(req_id, SimpleNamespace(contract=contract))
        broker.contractDetailsEnd(req_id)
    broker.reqContractDetails = Mock(side_effect=resolve)

    def history(req_id, *args):
        for minutes in (-5, 0, 5, 30):
            stamp = START + timedelta(minutes=minutes)
            broker.historicalData(req_id, SimpleNamespace(
                date=str(int(stamp.timestamp())), open=10, high=12, low=9, close=11, volume=42,
            ))
        broker.historicalDataEnd(req_id, '', '')
    broker.reqHistoricalData = Mock(side_effect=history)
    return broker


@pytest.mark.parametrize('data_type', ['TRADES', 'MIDPOINT', 'BID', 'ASK'])
def test_fixed_range_uses_exact_option_and_price_source_without_quote_requests(provider, data_type):
    series = Market(provider).bars(OPTION, interval='5min', start=START, end=END,
                                   data_type=data_type)
    assert [bar.timestamp for bar in series.snapshot()] == [START, START+timedelta(minutes=5)]
    assert [bar.volume for bar in series.snapshot()] == ([42, 42] if data_type == 'TRADES'
                                                        else [None, None])
    args = provider.reqHistoricalData.call_args.args
    assert args[1].secType == 'OPT' and args[1].conId == 999
    assert args[2] == END.strftime('%Y%m%d %H:%M:%S UTC')
    assert args[4:9] == ('5 mins', data_type, 1, 2, False)
    metadata = series.metadata()
    assert metadata['asset_type'] == 'option' and metadata['multiplier'] == 150
    assert metadata['data_type'] == data_type and metadata['adjustment'] == 'not_verified'
    assert metadata['option']['requested']['expiry'] == '2026-11-20'
    assert metadata['option']['expiry'] == '20261120'
    assert metadata['option']['trading_class'] == 'AAPL1'
    assert metadata['volume_available'] == (data_type == 'TRADES')
    assert metadata['download']['complete'] and metadata['download']['pages'] == 1
    assert metadata['coverage']['bar_finality'] == 'not_verified'
    metadata['option']['requested']['strike'] = -1
    assert series.metadata()['option']['requested']['strike'] == 340
    provider.reqMktData.assert_not_called()
    provider.reqMarketDataType.assert_not_called()
    assert provider.reqContractDetails.call_count == 1 and not provider._requests


@pytest.mark.parametrize('changes', [
    dict(start=None), dict(end=None), dict(duration='1 D'), dict(live=True),
    dict(include_sessions=True), dict(primary_exchange='NASDAQ'), dict(interval='1d'),
    dict(interval='1w'), dict(data_type='BID_ASK'), dict(data_type='OPTION_IMPLIED_VOLATILITY'),
])
def test_unsupported_option_modes_fail_before_provider_io(changes):
    broker = Mock()
    with pytest.raises(ValueError):
        Market(broker).bars(OPTION, **(dict(start=START, end=END, interval='5min') | changes))
    broker.bars_range.assert_not_called()
    broker.bars.assert_not_called()


def test_expired_and_future_requests_fail_before_contract_or_history_io(provider):
    expired = Option('AAPL', date(2026, 10, 15), 340, 'C')
    with pytest.raises(DataError, match='expired options'):
        Market(provider).bars(expired, start=START, end=END)
    with pytest.raises(ValueError, match='future'):
        Market(provider).bars(OPTION, start=START, end='2027-01-01')
    provider.reqContractDetails.assert_not_called()
    provider.reqHistoricalData.assert_not_called()


@pytest.mark.parametrize('change', ['multiplier', 'strike', 'expiry', 'type'])
def test_invalid_resolved_contracts_do_not_reach_history(provider, change):
    original = provider.reqContractDetails.side_effect

    def mismatch(req_id, contract):
        if change == 'multiplier':
            contract.multiplier = ''  # Original callback supplies 100 instead of requested 150.
        elif change == 'strike':
            contract.strike = 999
        elif change == 'expiry':
            contract.lastTradeDateOrContractMonth = '20261218'
        else:
            contract.secType = 'STK'
        original(req_id, contract)
    provider.reqContractDetails.side_effect = mismatch
    with pytest.raises(HistoricalRangeError):
        Market(provider).bars(OPTION, start=START, end=END)
    provider.reqHistoricalData.assert_not_called()
    assert not provider._requests


@pytest.mark.parametrize('error_code,message', [
    (354, 'Not subscribed'), (162, 'Permission denied'),
])
def test_permissions_are_failures_not_empty_success(provider, error_code, message):
    provider.reqHistoricalData.side_effect = lambda req_id, *args: provider.error(
        req_id, 0, error_code, message,
    )
    with pytest.raises(HistoricalRangeError) as failure:
        Market(provider).bars(OPTION, start=START, end=END)
    assert not failure.value.partial.download_complete
    assert str(error_code) in str(failure.value)
    assert not provider._requests


def test_empty_history_is_explicitly_unverified_and_not_fabricated(provider):
    provider.reqHistoricalData.side_effect = lambda req_id, *args: provider.historicalDataEnd(
        req_id, '', '',
    )
    series = Market(provider).bars(OPTION, start=START, end=END)
    assert not series.snapshot() and series.empty_windows == [(START, END)]
    assert series.download_complete and series.warnings
    assert series.metadata()['coverage']['gaps'] == 'not_verified'


def test_multiple_pages_keep_one_contract_and_disconnect_preserves_partial_metadata(provider):
    calls = 0

    def history(req_id, contract, end, *args):
        nonlocal calls
        calls += 1
        if calls == 2:
            provider.connectionClosed()
            return
        stamp = datetime.strptime(end, '%Y%m%d %H:%M:%S UTC').replace(tzinfo=UTC)
        provider.historicalData(req_id, SimpleNamespace(date=str(int((stamp-timedelta(minutes=5))
                                                                   .timestamp())),
                               open=10, high=12, low=9, close=11, volume=-1))
        provider.historicalDataEnd(req_id, '', '')
    provider.reqHistoricalData.side_effect = history
    with pytest.raises(HistoricalRangeError) as failure:
        Market(provider).bars(OPTION, interval='1min', start='2026-10-13', end='2026-10-16',
                              data_type='MIDPOINT')
    partial = failure.value.partial
    assert len(partial) == 1 and partial.download_pages == 1 and not partial.download_complete
    assert partial.metadata()['option']['strike'] == 340
    assert partial.snapshot()[0].volume is None
    assert provider.reqContractDetails.call_count == 1 and not provider._requests


def test_missing_volume_and_full_identity_survive_csv_dataset_and_pandas(provider, tmp_path):
    series = Market(provider).bars(OPTION, start=START, end=END, data_type='MIDPOINT')
    path = BarDataset.from_series(series).save(tmp_path/'option.json')
    loaded = BarDataset.load(path)
    assert loaded.metadata() == series.metadata() and loaded.snapshot() == series.snapshot()
    with series.to_csv(tmp_path/'option.csv').open(newline='') as file:
        assert all(row['volume'] == '' for row in csv.DictReader(file))
    pytest.importorskip('pandas')
    assert series.to_dataframe()['volume'].isna().all()


def test_option_cache_separates_sources_and_preserves_missing_volume(provider, tmp_path):
    pytest.importorskip('pyarrow')
    from pyibquant import HistoricalCache

    provider.cache = HistoricalCache(tmp_path)
    market = Market(provider)
    first = market.bars(OPTION, start=START, end=END, data_type='MIDPOINT')
    second = market.bars(OPTION, start=START, end=END, data_type='MIDPOINT')
    third = market.bars(OPTION, start=START, end=END, data_type='TRADES')
    assert first.snapshot() == second.snapshot() and second.download_cached_pages == 1
    assert provider.reqHistoricalData.call_count == 2
    assert third.snapshot()[0].volume == 42 and second.snapshot()[0].volume is None


@pytest.mark.parametrize('empty', [False, True])
def test_research_example_saves_reusable_inputs_and_refuses_empty_history(
    provider, monkeypatch, tmp_path, empty,
):
    market = Market(provider)
    market.close = Mock()
    monkeypatch.setattr(Market, 'ibkr', Mock(return_value=market))
    if empty:
        provider.reqHistoricalData.side_effect = lambda req_id, *args: \
            provider.historicalDataEnd(req_id, '', '')
    target = tmp_path/'research'
    monkeypatch.setattr('sys.argv', [
        'research_option_history.py', 'AAPL', '--expiry', '2026-11-20',
        '--strike', '340', '--right', 'C', '--trading-class', 'AAPL1', '--multiplier', '150',
        '--start', START.isoformat(), '--end', END.isoformat(), '--output-dir', str(target),
    ])
    script = Path(__file__).resolve().parents[1]/'examples/research_option_history.py'
    if empty:
        with pytest.raises(SystemExit, match='no bars'):
            runpy.run_path(str(script), run_name='__main__')
        assert not target.exists()
    else:
        runpy.run_path(str(script), run_name='__main__')
        dataset = BarDataset.load(target/'bars.dataset.json')
        assert len(dataset) == 2 and dataset.metadata()['data_type'] == 'MIDPOINT'
        assert all(bar.volume is None for bar in dataset.snapshot())
        assert (target/'signals.csv').is_file()
        assert (target/'bars.metadata.json').is_file()
    market.close.assert_called_once()


def test_option_chart_cannot_request_stock_sessions_or_switch_to_underlying(provider, monkeypatch):
    series = Market(provider).bars(OPTION, start=START, end=END, data_type='MIDPOINT')
    serve = Mock()
    monkeypatch.setattr('pyibquant.visualization.chart.serve_chart', serve)
    provider.load_sessions = Mock()
    market = Market(provider)
    market.serve(series, open_browser=False)
    serve.assert_called_once_with(series, port=0, open_browser=False)
    provider.load_sessions.assert_not_called()
    with pytest.raises(ValueError, match='Fixed-range'):
        market.load_older(series)

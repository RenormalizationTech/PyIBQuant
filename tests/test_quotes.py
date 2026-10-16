"""Quote requests use SDK callbacks, explicit feed types and immutable results."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date
from decimal import Decimal
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import Market, Option
from pyibquant.data.providers.ibkr import IBKRProvider
from pyibquant.errors import ConnectionError, DataError, RequestTimeout


@pytest.fixture
def provider():
    result = IBKRProvider('127.0.0.1', 7497, 193, .02)
    result.isConnected = Mock(return_value=True)
    result.reqMarketDataType = Mock()
    result.cancelMktData = Mock()

    def resolve(req_id, contract):
        contract.conId = 123
        contract.localSymbol = 'DEMO'
        if contract.secType == 'OPT':
            contract.multiplier = '100'
            contract.tradingClass = 'AAPL'
        result.contractDetails(req_id, SimpleNamespace(contract=contract))
        result.contractDetailsEnd(req_id)

    result.reqContractDetails = Mock(side_effect=resolve)
    return result


def response(provider, *, data_type=1, delayed=False, bid=100, ask=102):
    def send(req_id, *args):
        if data_type is not None:
            provider.marketDataType(req_id, data_type)
        provider.tickPrice(req_id, 66 if delayed else 1, bid, None)
        provider.tickPrice(req_id, 67 if delayed else 2, ask, None)
        provider.tickSize(req_id, 69 if delayed else 0, Decimal('20.5'))
        provider.tickSize(req_id, 70 if delayed else 3, Decimal(40))
        provider.tickSnapshotEnd(req_id)
    return send


def test_standard_snapshot_resolves_contract_and_never_requests_paid_regulatory_data(provider):
    provider.reqMktData = Mock(side_effect=response(provider))
    quote = Market(provider).quote(' aapl ')
    assert quote.instrument.symbol == 'AAPL' and quote.instrument.instrument_id == 123
    assert quote.instrument.asset_type == 'equity' and quote.instrument.multiplier == 1
    assert quote.bid == 100 and quote.ask == 102 and quote.last is None
    assert quote.bid_size == 20.5 and quote.ask_size == 40
    assert quote.midpoint == 101 and quote.spread == 2 and not quote.crossed
    assert quote.market_data_type == 'live' and not quote.is_delayed
    assert quote.requested_at <= quote.completed_at
    assert all(stamp.tzinfo == UTC for _, stamp in quote.field_received_at)
    provider.reqMarketDataType.assert_called_once_with(1)
    assert provider.reqMktData.call_args.args[2:] == ('', True, False, [])
    provider.cancelMktData.assert_not_called()  # Snapshot auto-ends at tickSnapshotEnd.
    assert not provider._requests
    doc = quote.to_dict()
    assert doc['timestamp_semantics'] == 'local_callback_receipt_not_exchange_time'
    assert json.loads(json.dumps(doc)) == doc
    doc['instrument']['symbol'] = 'MUTATED'
    assert quote.instrument.symbol == 'AAPL'
    with pytest.raises(FrozenInstanceError):
        quote.bid = -1


@pytest.mark.parametrize('kind,actual,delayed', [
    ('live', 3, True), ('delayed', 1, False), ('frozen', 2, False),
    ('delayed_frozen', 4, True), ('live', None, True),
])
def test_actual_feed_type_and_delayed_ticks_are_not_inferred_from_request(provider, kind, actual,
                                                                        delayed):
    provider.reqMktData = Mock(side_effect=response(provider, data_type=actual, delayed=delayed))
    quote = provider.quote('AAPL', market_data_type=kind)
    assert quote.requested_data_type == kind
    assert quote.market_data_type == {1: 'live', 2: 'frozen', 3: 'delayed',
                                     4: 'delayed_frozen'}.get(actual)
    assert quote.is_delayed == delayed
    assert quote.delayed_ticks == delayed


@pytest.mark.parametrize('bid,ask', [(-1, -1), (0, 0), (float('nan'), 102), (1.797e308, 102)])
def test_missing_unset_or_invalid_prices_stay_none(provider, bid, ask):
    provider.reqMktData = Mock(side_effect=response(provider, bid=bid, ask=ask))
    quote = provider.quote('AAPL')
    assert quote.bid is None and quote.spread is None and quote.midpoint is None
    assert any('no complete bid/ask' in message for message in quote.warnings)
    json.dumps(quote.to_dict(), allow_nan=False)


def test_crossed_quotes_are_preserved_without_a_misleading_midpoint(provider):
    provider.reqMktData = Mock(side_effect=response(provider, bid=103, ask=102))
    quote = provider.quote('AAPL')
    assert quote.crossed and quote.bid == 103 and quote.ask == 102
    assert quote.midpoint is None and quote.spread is None


def test_empty_snapshot_does_not_invent_prices_or_confirmed_feed_type(provider):
    provider.reqMktData = Mock(side_effect=lambda req_id, *args: provider.tickSnapshotEnd(req_id))
    quote = provider.quote('AAPL')
    assert quote.bid is None and quote.ask is None and quote.market_data_type is None
    assert len(quote.warnings) == 2


def test_timeout_and_permission_failures_cancel_only_the_quote_request(provider):
    provider.reqMktData = Mock()
    provider.cancelHistoricalData = Mock()
    with pytest.raises(RequestTimeout):
        provider.quote('AAPL')
    req_id = provider.reqMktData.call_args.args[0]
    provider.cancelMktData.assert_called_once_with(req_id)
    provider.cancelHistoricalData.assert_not_called()
    assert not provider._requests
    provider.reqMktData = Mock(side_effect=lambda req_id, *args:
                              provider.error(req_id, 0, 354, 'Not subscribed'))
    with pytest.raises(DataError, match='Not subscribed'):
        provider.quote('AAPL')
    assert not provider._requests


def test_partial_entitlement_warning_preserves_fields_and_labels_them(provider):
    send = response(provider, data_type=3, delayed=True)

    def reply(req_id, *args):
        provider.error(req_id, 0, 10167, 'Displaying delayed data')
        send(req_id, *args)
    provider.reqMktData = Mock(side_effect=reply)
    quote = provider.quote('AAPL')
    assert quote.is_delayed and quote.bid == 100
    assert any('10167' in warning for warning in quote.warnings)


def test_feed_type_change_discards_fields_from_earlier_mode(provider):
    def reply(req_id, *args):
        provider.marketDataType(req_id, 1)
        provider.tickPrice(req_id, 1, 100, None)
        provider.marketDataType(req_id, 3)
        provider.tickPrice(req_id, 67, 102, None)
        provider.tickSnapshotEnd(req_id)
        # Late callbacks cannot change completed snapshots.
        provider.tickPrice(req_id, 66, 99, None)
    provider.reqMktData = Mock(side_effect=reply)
    quote = provider.quote('AAPL')
    assert quote.bid is None and quote.ask == 102 and quote.is_delayed
    assert any('earlier fields discarded' in warning for warning in quote.warnings)


def test_options_resolve_actual_multiplier_and_keep_greeks_sources_separate(provider):
    send = response(provider)

    def reply(req_id, *args):
        provider.tickOptionComputation(req_id, 10, 0, .3, .5, 4, .1, .02, .4, -.1, 100)
        provider.tickOptionComputation(req_id, 13, 0, .31, .51, 4.1, .1, .021, .41, -.11, 101)
        send(req_id, *args)
    provider.reqMktData = Mock(side_effect=reply)
    option = Option(' aapl ', date(2026, 11, 20), 100, 'c')
    quote = provider.quote(option)
    contract = provider.reqContractDetails.call_args.args[1]
    assert contract.secType == 'OPT' and contract.lastTradeDateOrContractMonth == '20261120'
    assert contract.right == 'C' and contract.multiplier == '100'
    assert quote.instrument.multiplier == 100 and quote.instrument.asset_type == 'option'
    assert quote.instrument.expiry == '20261120' and quote.instrument.strike == 100
    assert [greeks.source for greeks in quote.greeks] == ['bid', 'model']
    assert quote.greeks[0].delta == .5 and quote.greeks[1].delta == .51
    assert quote.greeks[1].theta == -.11


def test_unavailable_greeks_sentinels_and_delayed_source_are_explicit(provider):
    def reply(req_id, *args):
        provider.tickOptionComputation(req_id, 83, 0, -1, -2, -1, -1, -2, -2, -2, -1)
        provider.tickSnapshotEnd(req_id)
    provider.reqMktData = Mock(side_effect=reply)
    quote = provider.quote(Option('AAPL', date(2026, 11, 20), 100, 'P'))
    greek = quote.greeks[0]
    assert greek.source == 'model' and greek.delayed and quote.is_delayed
    assert greek.implied_volatility is None and greek.delta is None
    assert greek.theta is None and greek.underlying_price is None


def test_ambiguous_option_is_rejected_without_requesting_market_data(provider):
    def reply(req_id, contract):
        provider.contractDetails(req_id, SimpleNamespace(contract=contract))
        provider.contractDetails(req_id, SimpleNamespace(contract=contract))
        provider.contractDetailsEnd(req_id)
    provider.reqContractDetails = Mock(side_effect=reply)
    provider.reqMktData = Mock()
    with pytest.raises(DataError, match='Expected one option'):
        provider.quote(Option('AAPL', date(2026, 11, 20), 100, 'C'))
    provider.reqMktData.assert_not_called()
    assert not provider._requests


def test_invalid_quotes_rejected_before_any_provider_request(provider):
    for symbol, kind in [('', 'live'), (123, 'live'), ('AAPL', 'automatic')]:
        with pytest.raises(ValueError):
            provider.quote(symbol, market_data_type=kind)
    provider.reqContractDetails.assert_not_called()


def test_disconnect_wakes_quote_wait_without_silent_retry(provider):
    provider.reqMktData = Mock(side_effect=lambda *args: provider.connectionClosed())
    with pytest.raises(ConnectionError):
        Market(provider).quote('AAPL')
    assert provider.reqMktData.call_count == 1 and not provider._requests


def test_market_controls_are_responsive_during_snapshot_wait(provider):
    waiting, release = Event(), Event()
    provider.timeout = 2

    def reply(req_id, *args):
        waiting.set()
        assert release.wait(1)
        response(provider)(req_id, *args)
    provider.reqMktData = Mock(side_effect=reply)
    market = Market(provider)
    provider.cancel_bars = Mock()
    outcomes = []
    worker = Thread(target=lambda: outcomes.append(market.quote('AAPL')))
    worker.start()
    try:
        assert waiting.wait(1)
        assert market._operation_lock.acquire(timeout=.1)
        market._operation_lock.release()
    finally:
        release.set()
        worker.join(2)
    assert len(outcomes) == 1 and outcomes[0].bid == 100


def test_partial_permission_message_without_prices_is_not_a_successful_live_bbo(provider):
    def reply(req_id, *args):
        provider.marketDataType(req_id, 1)
        provider.error(req_id, 0, 10091, 'Additional subscription for API: SPY ARCA/TOP/ALL')
        provider.tickSize(req_id, 0, 0)
        provider.tickSize(req_id, 3, 0)
        provider.tickSnapshotEnd(req_id)
    provider.reqMktData = Mock(side_effect=reply)
    quote = provider.quote(Option('SPY', date(2026, 11, 20), 770, 'C'))
    assert quote.market_data_type == 'live'  # Feed type is not availability of every field.
    assert quote.bid is None and quote.ask is None and quote.greeks == ()
    assert quote.bid_size == 0 and quote.ask_size == 0
    assert any('10091' in warning for warning in quote.warnings)
    assert quote.spread is None


def test_sdk_normalized_none_greeks_do_not_break_connection_or_discard_quotes(provider):
    send = response(provider)

    def reply(req_id, *args):
        provider.tickOptionComputation(req_id, 10, 0, None, None, None, None,
                                       None, None, None, None)
        provider.tickOptionComputation(req_id, 13, 0, .3, .5, 4, 0, 0, 0, None, 340)
        send(req_id, *args)
    provider.reqMktData = Mock(side_effect=reply)
    quote = provider.quote(Option('AAPL', date(2026, 11, 20), 340, 'C'))
    bid, model = quote.greeks
    assert bid.source == 'bid' and bid.delta is None and bid.implied_volatility is None
    assert model.source == 'model' and model.delta == .5 and model.theta is None
    assert model.gamma == 0 and model.vega == 0 and model.pv_dividend == 0
    assert quote.bid == 100 and quote.ask == 102
    assert provider._connection_error is None and not provider._requests

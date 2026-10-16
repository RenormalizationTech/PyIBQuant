"""Option-chain callbacks describe partitions, not verified Cartesian contracts."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import Market, Option
from pyibquant.data.providers.ibkr import IBKRProvider
from pyibquant.errors import ConnectionError, DataError, RequestTimeout


@pytest.fixture
def provider():
    broker = IBKRProvider('127.0.0.1', 7497, 195, .01)
    broker.isConnected = Mock(return_value=True)

    def resolve(req_id, contract):
        contract.conId = 265598
        broker.contractDetails(req_id, SimpleNamespace(contract=contract))
        broker.contractDetailsEnd(req_id)
    broker.reqContractDetails = Mock(side_effect=resolve)
    broker.reqMktData = Mock()
    return broker


def test_groups_are_sorted_deduplicated_and_never_trigger_quote_requests(provider):
    def respond(req_id, *args):
        for exchange, trading_class, multiplier, dates, strikes in [
            ('SMART', 'AAPL', '100', {'20261120'}, {350, 340}),
            ('CBOE', 'AAPL', '100', {'20261120'}, {340}),
            ('SMART', 'AAPL', '100.0', {'20261218'}, {330, 340}),
        ]:
            provider.securityDefinitionOptionParameter(req_id, exchange, 265598,
                                                       trading_class, multiplier, dates, strikes)
        provider.securityDefinitionOptionParameterEnd(req_id)
    provider.reqSecDefOptParams = Mock(side_effect=respond)
    chain = Market(provider).option_chain(' aapl ')
    assert chain.symbol == 'AAPL' and chain.underlying_instrument_id == 265598
    assert [group.exchange for group in chain.groups] == ['CBOE', 'SMART']
    assert chain.groups[1].strikes == (330, 340, 350)
    assert chain.groups[1].expirations == (date(2026, 11, 20), date(2026, 12, 18))
    assert chain.select(date(2026, 11, 20), 340, 'c') == Option(
        'AAPL', date(2026, 11, 20), 340, 'C', 'AAPL', 100)
    assert chain.to_dict()['combinations_verified'] is False
    provider.reqSecDefOptParams.assert_called_once_with(2, 'AAPL', '', 'STK', 265598)
    provider.reqMktData.assert_not_called()
    assert not provider._requests


def test_selection_does_not_silently_choose_between_adjusted_classes(provider):
    def respond(req_id, *args):
        for trading_class, multiplier in [('AAPL', '100'), ('AAPL1', '150')]:
            provider.securityDefinitionOptionParameter(req_id, 'SMART', 265598,
                                                       trading_class, multiplier,
                                                       {'20261120'}, {340})
        provider.securityDefinitionOptionParameterEnd(req_id)
    provider.reqSecDefOptParams = Mock(side_effect=respond)
    chain = provider.option_chain('AAPL')
    with pytest.raises(ValueError, match='got 2'):
        chain.select(date(2026, 11, 20), 340, 'C')
    adjusted = chain.select(date(2026, 11, 20), 340, 'P', trading_class='aapl1')
    assert adjusted.multiplier == 150 and adjusted.trading_class == 'AAPL1'
    with pytest.raises(ValueError, match='got 0'):
        chain.select(date(2026, 11, 20), 341, 'C')


@pytest.mark.parametrize('bad', ['underlying', 'expiry', 'strike', 'multiplier'])
def test_bad_callbacks_fail_cleanly_without_throwing_on_the_reader_thread(provider, bad):
    def respond(req_id, *args):
        provider.securityDefinitionOptionParameter(
            req_id, 'SMART', 123 if bad == 'underlying' else 265598, 'AAPL',
            '' if bad == 'multiplier' else '100',
            {'bad'} if bad == 'expiry' else {'20261120'},
            {float('nan')} if bad == 'strike' else {340},
        )
    provider.reqSecDefOptParams = Mock(side_effect=respond)
    with pytest.raises(DataError, match='Invalid IBKR option-chain response'):
        provider.option_chain('AAPL')
    assert not provider._requests


def test_empty_chain_is_distinct_from_timeout_permission_or_disconnect(provider):
    provider.reqSecDefOptParams = Mock(side_effect=lambda req_id, *args:
                                     provider.securityDefinitionOptionParameterEnd(req_id))
    assert provider.option_chain('AAPL').groups == ()
    provider.reqSecDefOptParams = Mock()
    with pytest.raises(RequestTimeout):
        provider.option_chain('AAPL')
    provider.reqSecDefOptParams = Mock(side_effect=lambda req_id, *args:
                                     provider.error(req_id, 0, 200, 'No security definition'))
    with pytest.raises(DataError, match='No security definition'):
        provider.option_chain('AAPL')
    provider.reqSecDefOptParams = Mock(side_effect=lambda *args: provider.connectionClosed())
    with pytest.raises(ConnectionError):
        provider.option_chain('AAPL')
    assert not provider._requests

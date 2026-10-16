"""SDK-free chain metadata keeps candidates distinct from verified contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from pyibquant import OptionChain, OptionChainGroup


def test_chain_json_is_independent_and_candidate_keeps_class_and_multiplier():
    chain = OptionChain('DEMO', 123, 'USD', (
        OptionChainGroup('SMART', 'DEMO1', 150, (date(2026, 11, 20),), (100, 110)),
    ), datetime.now(UTC))
    candidate = chain.select(date(2026, 11, 20), 100, 'p')
    assert candidate.trading_class == 'DEMO1' and candidate.multiplier == 150
    assert candidate.right == 'P'
    document = chain.to_dict()
    assert document['combinations_verified'] is False
    document['groups'][0]['strikes'].append(999)
    assert chain.groups[0].strikes == (100, 110)
    with pytest.raises(FrozenInstanceError):
        chain.groups[0].multiplier = 100


def test_missing_smart_group_does_not_silently_route_to_another_exchange():
    chain = OptionChain('DEMO', 123, 'USD', (
        OptionChainGroup('CBOE', 'DEMO', 100, (date(2026, 11, 20),), (100,)),
    ), datetime.now(UTC))
    with pytest.raises(ValueError, match='SMART chain group'):
        chain.select(date(2026, 11, 20), 100, 'C')

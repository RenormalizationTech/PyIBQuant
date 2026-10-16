"""Option-chain discovery metadata; candidates still require contract resolution."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from .quotes import Option


@dataclass(frozen=True)
class OptionChainGroup:
    exchange: str
    trading_class: str
    multiplier: float
    expirations: tuple[date, ...]
    strikes: tuple[float, ...]


@dataclass(frozen=True)
class OptionChain:
    """IBKR chain partitions, not a Cartesian product of verified contracts.

    Expiries and strikes are separate sets. A pair may not exist for both rights
    or at all. select() creates a candidate that quote/stream_quote resolves before
    requesting data. Discovery itself never subscribes to any option quotes.
    """

    symbol: str
    underlying_instrument_id: int
    currency: str
    groups: tuple[OptionChainGroup, ...]
    received_at: datetime

    def select(
        self, expiry: date, strike: float, right: str, *,
        trading_class: str = '', multiplier: float | None = None,
    ) -> Option:
        candidate = Option(self.symbol, expiry, strike, right, trading_class, multiplier)
        matches = [group for group in self.groups if group.exchange == 'SMART'
                   and expiry in group.expirations and strike in group.strikes
                   and (not candidate.trading_class
                        or group.trading_class == candidate.trading_class)
                   and (multiplier is None or group.multiplier == multiplier)]
        if len(matches) != 1:
            raise ValueError(f'Expected one SMART chain group, got {len(matches)}. '
                             'Check expiry/strike and specify trading_class/multiplier.')
        group = matches[0]
        return Option(self.symbol, expiry, strike, candidate.right,
                      group.trading_class, group.multiplier)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.update(provider='IBKR', source='reqSecDefOptParams',
                      combinations_verified=False, timestamp_semantics='local_request_completion')
        return json.loads(json.dumps(result, default=lambda value: value.isoformat(),
                                     allow_nan=False))

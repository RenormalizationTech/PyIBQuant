"""Level-one quote snapshots and explicit option selectors, without SDK objects."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from math import isfinite
from threading import RLock
from typing import Any

DATA_TYPES = {'live': 1, 'frozen': 2, 'delayed': 3, 'delayed_frozen': 4}


@dataclass(frozen=True)
class Option:
    """Explicit US equity/ETF option selector; ambiguous contracts are rejected.

    Optional trading class/multiplier disambiguate standard and adjusted series.
    No multiplier is assumed. A selector is resolved by IBKR before requesting data.
    """

    symbol: str
    expiry: date
    strike: float
    right: str
    trading_class: str = ''
    multiplier: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip() or isinstance(self.expiry, datetime) \
                or not isinstance(self.expiry, date):
            raise ValueError('Option requires a symbol and calendar expiry date')
        if isinstance(self.strike, bool) or not isfinite(self.strike) or self.strike <= 0:
            raise ValueError('Option strike must be positive and finite')
        if self.right.strip().upper() not in {'C', 'P'}:
            raise ValueError('Option right must be C or P')
        if self.multiplier is not None and (
            isinstance(self.multiplier, bool) or not isfinite(self.multiplier)
            or self.multiplier <= 0
        ):
            raise ValueError('Option multiplier must be positive and finite')
        object.__setattr__(self, 'symbol', self.symbol.strip().upper())
        object.__setattr__(self, 'right', self.right.strip().upper())
        object.__setattr__(self, 'trading_class', self.trading_class.strip().upper())


@dataclass(frozen=True)
class QuoteInstrument:
    symbol: str
    instrument_id: int
    asset_type: str
    currency: str
    exchange: str
    primary_exchange: str
    local_symbol: str
    trading_class: str
    multiplier: float | None
    expiry: str | None
    strike: float | None
    right: str | None


@dataclass(frozen=True)
class OptionGreeks:
    source: str
    delayed: bool
    received_at: datetime
    implied_volatility: float | None
    delta: float | None
    option_price: float | None
    pv_dividend: float | None
    gamma: float | None
    vega: float | None
    theta: float | None
    underlying_price: float | None


@dataclass(frozen=True)
class Quote:
    """Available fields from one reqMktData snapshot; absence is represented by None.

    Callback receipt times are local UTC times, not exchange timestamps or proof
    of a fresh/tradable quote. Bid/ask fields arrive independently. Level one is
    not order-book depth. Delayed/frozen data must never be treated as live data.
    """

    instrument: QuoteInstrument
    requested_data_type: str
    market_data_type: str | None
    delayed_ticks: bool
    requested_at: datetime
    completed_at: datetime
    bid: float | None
    ask: float | None
    last: float | None
    bid_size: float | None
    ask_size: float | None
    last_size: float | None
    field_received_at: tuple[tuple[str, datetime], ...]
    field_tick_types: tuple[tuple[str, int], ...]
    greeks: tuple[OptionGreeks, ...]
    warnings: tuple[str, ...]

    @property
    def crossed(self) -> bool:
        return self.bid is not None and self.ask is not None and self.ask < self.bid

    @property
    def spread(self) -> float | None:
        return self.ask - self.bid if self.bid is not None and self.ask is not None \
            and not self.crossed else None

    @property
    def midpoint(self) -> float | None:
        spread = self.spread
        return self.bid + spread / 2 if self.bid is not None and spread is not None else None

    @property
    def is_delayed(self) -> bool:
        return self.delayed_ticks or self.market_data_type in {'delayed', 'delayed_frozen'}

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result['field_received_at'] = dict(self.field_received_at)
        result['field_tick_types'] = dict(self.field_tick_types)
        result.update(provider='IBKR', source='reqMktData', snapshot_complete=True,
                      timestamp_semantics='local_callback_receipt_not_exchange_time',
                      spread=self.spread, midpoint=self.midpoint, crossed=self.crossed,
                      is_delayed=self.is_delayed)
        return json.loads(json.dumps(result, default=lambda value: value.isoformat(),
                                     allow_nan=False))


def _number(value: Any, *, minimum: float = 0, allow_zero: bool = True) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    # SDK unset Decimal is 2**127-1; unset double is near 1.8e308. Compare
    # after float conversion to handle both native Decimal and decoded floats.
    if not isfinite(result) or result == float(2**127 - 1) \
            or abs(result) >= 1e100 or result < minimum \
            or (not allow_zero and result == 0):
        return None
    return result


@dataclass
class _QuoteState:
    instrument: QuoteInstrument
    requested_type: str
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    actual_type: str | None = None
    delayed: bool = False
    completed_at: datetime | None = None
    values: dict[str, float | None] = field(default_factory=dict)
    receipts: dict[str, datetime] = field(default_factory=dict)
    tick_types: dict[str, int] = field(default_factory=dict)
    greeks: dict[str, OptionGreeks] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    lock: Any = field(default_factory=RLock)

    def tick(self, tick_type: int, value: Any, *, size: bool = False) -> None:
        mapping = {0: 'bid_size', 3: 'ask_size', 5: 'last_size',
                   69: 'bid_size', 70: 'ask_size', 71: 'last_size'} if size else {
                       1: 'bid', 2: 'ask', 4: 'last', 66: 'bid', 67: 'ask', 68: 'last'}
        name = mapping.get(tick_type)
        if name is None:
            return
        with self.lock:
            if self.completed_at is not None:
                return
            self.values[name] = _number(value, allow_zero=size)
            self.receipts[name] = datetime.now(UTC)
            self.tick_types[name] = tick_type
            self.delayed |= tick_type >= 66

    def computation(self, tick_type: int, values: tuple[float | None, ...]) -> None:
        source = {10: 'bid', 11: 'ask', 12: 'last', 13: 'model',
                  80: 'bid', 81: 'ask', 82: 'last', 83: 'model'}.get(tick_type)
        if source is None:
            return
        iv, delta, price, dividend, gamma, vega, theta, underlying = values
        normalized_delta = _number(delta, minimum=-1)
        if normalized_delta is not None and normalized_delta > 1:
            normalized_delta = None
        with self.lock:
            if self.completed_at is not None:
                return
            self.delayed |= tick_type >= 80
            self.greeks[source] = OptionGreeks(
                source, tick_type >= 80, datetime.now(UTC), _number(iv),
                normalized_delta,
                _number(price), _number(dividend), _number(gamma), _number(vega),
                _number(theta, minimum=-1e99) if theta != -2 else None,
                _number(underlying, allow_zero=False),
            )

    def snapshot(self) -> Quote:
        with self.lock:
            assert self.completed_at is not None
            warnings = list(self.warnings)
            if self.values.get('bid') is None or self.values.get('ask') is None:
                warnings.append('Snapshot has no complete bid/ask pair; '
                                'missing fields remain None.')
            if self.actual_type is None:
                warnings.append('IBKR did not confirm the market data type.')
            if self.actual_type is not None and self.actual_type != self.requested_type:
                warnings.append(f'Requested {self.requested_type}, '
                                f'IBKR reported {self.actual_type}.')
            if self.delayed and self.actual_type in {'live', 'frozen'}:
                warnings.append('Delayed ticks were received despite the reported feed type; '
                                'do not treat this snapshot as live.')
            if self.values.get('bid') is not None and self.values.get('ask') is not None:
                bid, ask = self.values['bid'], self.values['ask']
                assert bid is not None and ask is not None
                if ask < bid:
                    warnings.append('Bid exceeds ask; independent callbacks do not form an '
                                    'atomic or executable bid/ask pair.')
            return Quote(
                self.instrument, self.requested_type, self.actual_type, self.delayed,
                self.requested_at, self.completed_at,
                self.values.get('bid'), self.values.get('ask'), self.values.get('last'),
                self.values.get('bid_size'), self.values.get('ask_size'),
                self.values.get('last_size'),
                tuple(sorted(self.receipts.items())), tuple(sorted(self.tick_types.items())),
                tuple(self.greeks[key] for key in sorted(self.greeks)), tuple(warnings),
            )

"""Small, broker-free bar simulation with user-owned strategy and execution logic.

At a timestamp: publish completed bars, call the strategy once, then process opens.
Only completed bars enter strategy history. Orders can fill at an adjacent open,
but never at the open of the bar whose close caused their submission.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from .bars import Bar
from .dataset import BarDataset

_SPANS = {'30s': 30, '1min': 60, '5min': 300, '15min': 900, '30min': 1800,
          '1h': 3600, '2h': 7200, '4h': 14400, '1d': 86400}
Side = Literal['buy', 'sell']
Status = Literal['pending', 'filled', 'rejected', 'canceled']


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        valid = not isinstance(value, bool) and isfinite(value)
        valid = valid and (value > 0 if positive else value >= 0)
    except (TypeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError(f'{name} must be finite and {"positive" if positive else "nonnegative"}')
    return float(value)


def _finite(value: float) -> float:
    if not isfinite(value):
        raise ValueError('Simulation accounting overflowed')
    return value


def _quantity(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('quantity must be a positive whole number')
    _number(value, 'quantity', positive=True)
    return value


def _instant(stamp: date) -> datetime:
    return (stamp.astimezone(UTC) if isinstance(stamp, datetime)
            else datetime.combine(stamp, time(), UTC))


@dataclass(frozen=True)
class Instrument:
    key: str
    symbol: str
    asset_type: str
    currency: str
    multiplier: float
    interval: str
    data_type: str
    instrument_id: int | None
    expiry: date | None = None


@dataclass(frozen=True)
class Feed:
    """Frozen input plus explicit finality/calendar assertions.

    Intraday finality confirms starts AND completion at start + interval. Daily
    finality confirms calendar dates; daily event times use synthetic UTC days.
    Do not mix daily and intraday feeds without an explicit session-time model.
    """

    dataset: BarDataset
    finalized_through: date | datetime
    expected_starts: tuple[date | datetime, ...] | None = None

    def __post_init__(self) -> None:
        if self.expected_starts is not None:
            object.__setattr__(self, 'expected_starts', tuple(self.expected_starts))


@dataclass(frozen=True)
class Order:
    id: int
    instrument: str
    side: Side
    quantity: int
    submitted_at: datetime
    status: Status = 'pending'
    updated_at: datetime | None = None
    reason: str | None = None
    tag: str | None = None


@dataclass(frozen=True)
class OpenEvent:
    """Execution input deliberately excludes the opening bar's future OHLCV."""

    timestamp: datetime
    price: float


@dataclass(frozen=True)
class Execution:
    price: float
    commission: float = 0


class ExecutionModel(Protocol):
    """Return a full fill or None to leave the order pending for a later open.

    Models own their assumptions/settings. They receive no future bar fields.
    Exceptions and invalid prices/costs fail the run rather than fabricate fills.
    """

    def execute(self, order: Order, instrument: Instrument, opening: OpenEvent,
                portfolio: Portfolio) -> Execution | None: ...

    def settings(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class NextOpen:
    """Synthetic market fills; flat fee plus per-unit fee, adverse bps slippage."""

    commission: float = 0
    commission_per_unit: float = 0
    slippage_bps: float = 0

    def __post_init__(self) -> None:
        for name in ('commission', 'commission_per_unit', 'slippage_bps'):
            _number(getattr(self, name), name)
        if self.slippage_bps >= 10000:
            raise ValueError('slippage_bps must be below 10000')

    def execute(self, order: Order, instrument: Instrument, opening: OpenEvent,
                portfolio: Portfolio) -> Execution:
        direction = 1 if order.side == 'buy' else -1
        return Execution(opening.price * (1 + direction * self.slippage_bps / 10000),
                         self.commission + order.quantity * self.commission_per_unit)

    def settings(self) -> Mapping[str, Any]:
        return dict(model='synthetic_next_open', **asdict(self))


@dataclass(frozen=True)
class Position:
    quantity: int = 0
    average_price: float = 0
    cost_basis: float = 0  # Includes unallocated entry commissions.
    realized_pnl: float = 0
    mark: float | None = None
    marked_at: datetime | None = None
    multiplier: float = 1

    @property
    def market_value(self) -> float:
        return _finite(self.quantity * (self.mark or 0) * self.multiplier)

    @property
    def unrealized_pnl(self) -> float:
        return _finite(self.market_value - self.cost_basis)


@dataclass(frozen=True)
class Portfolio:
    cash: float
    positions: Mapping[str, Position]

    @property
    def equity(self) -> float:
        return _finite(self.cash + sum(p.market_value for p in self.positions.values()))

    @property
    def realized_pnl(self) -> float:
        return _finite(sum(p.realized_pnl for p in self.positions.values()))

    @property
    def unrealized_pnl(self) -> float:
        return _finite(sum(p.unrealized_pnl for p in self.positions.values()))


@dataclass(frozen=True)
class Fill:
    order_id: int
    instrument: str
    timestamp: datetime
    side: Side
    quantity: int
    price: float
    commission: float
    slippage_cost: float
    realized_pnl: float
    cash_after: float


@dataclass(frozen=True)
class DataView:
    """Only completed bars; available_at and age expose missing/stale inputs."""

    bars: tuple[Bar, ...]
    available_at: datetime | None
    age: timedelta | None

    @property
    def latest(self) -> Bar | None:
        return self.bars[-1] if self.bars else None


@dataclass(frozen=True)
class Context:
    """Immutable decision snapshot. Keep strategy state on your strategy object.

    submit/cancel work only during this callback. Orders execute in submission
    order with shared cash; there is no implicit sell-first sorting or reservation.
    """

    timestamp: datetime
    updated: tuple[str, ...]
    data: Mapping[str, DataView]
    instruments: Mapping[str, Instrument]
    portfolio: Portfolio
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    _submit: Callable[[str, Side, int, str, str | None], int]
    _cancel: Callable[[int], bool]

    def submit(self, instrument: str, side: Side, quantity: int, *,
               order_type: str = 'market', tag: str | None = None) -> int:
        return self._submit(instrument, side, quantity, order_type, tag)

    def cancel(self, order_id: int) -> bool:
        return self._cancel(order_id)


class Strategy(Protocol):
    def on_bar(self, context: Context) -> None: ...


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    phase: Literal['close', 'open']
    cash: float
    equity: float
    period_return: float
    drawdown: float
    positions: Mapping[str, Position]


@dataclass(frozen=True)
class SimulationResult:
    initial_cash: float
    currency: str
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    equity_curve: tuple[EquityPoint, ...]
    portfolio: Portfolio
    warnings: tuple[str, ...]
    _provenance_json: str

    def metrics(self) -> dict[str, float | int]:
        return dict(final_cash=self.portfolio.cash, final_equity=self.portfolio.equity,
                    total_return=self.portfolio.equity / self.initial_cash - 1,
                    max_drawdown=min(p.drawdown for p in self.equity_curve),
                    realized_net_pnl=self.portfolio.realized_pnl,
                    unrealized_net_pnl=self.portfolio.unrealized_pnl,
                    commissions=_finite(sum(f.commission for f in self.fills)),
                    slippage_cost=_finite(sum(f.slippage_cost for f in self.fills)),
                    filled_orders=len(self.fills),
                    rejected_orders=sum(o.status == 'rejected' for o in self.orders))

    def to_dict(self) -> dict[str, Any]:
        def positions(items: Mapping[str, Position]) -> dict[str, Any]:
            return {key: asdict(value) for key, value in items.items()}

        document = dict(
            schema_version=1, initial_cash=self.initial_cash, currency=self.currency,
            provenance=json.loads(self._provenance_json), metrics=self.metrics(),
            warnings=self.warnings, orders=[asdict(o) for o in self.orders],
            fills=[asdict(f) for f in self.fills],
            portfolio=dict(cash=self.portfolio.cash, positions=positions(self.portfolio.positions)),
            equity_curve=[dict(timestamp=p.timestamp, phase=p.phase, cash=p.cash, equity=p.equity,
                               period_return=p.period_return, drawdown=p.drawdown,
                               positions=positions(p.positions)) for p in self.equity_curve],
        )
        return json.loads(json.dumps(document, default=_json_default, allow_nan=False))

    def save(self, path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        content = json.dumps(self.to_dict(), indent=2, allow_nan=False) + '\n'
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=target.parent,
                prefix=f'.{target.name}.', suffix='.tmp', delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target


def _json_default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f'Not JSON serializable: {type(value).__name__}')


def _validate(key: str, feed: Feed) -> Instrument:
    metadata = feed.dataset.metadata()
    bars = feed.dataset.snapshot()
    interval = metadata.get('interval')
    if interval not in _SPANS or not bars:
        raise ValueError('Use nonempty daily or supported intraday datasets')
    if (metadata.get('query', {}).get('mode') != 'range'
            or metadata.get('download', {}).get('complete') is not True or metadata.get('error')):
        raise ValueError('Simulation requires successfully completed fixed-range inputs')
    daily = interval == '1d'
    finality = feed.finalized_through
    if daily:
        if not isinstance(finality, date) or isinstance(finality, datetime):
            raise ValueError('Daily finality must be a calendar date')
    elif not isinstance(finality, datetime) or finality.utcoffset() is None:
        raise ValueError('Intraday finality must be timezone-aware')
    if bars[-1].timestamp > finality:
        raise ValueError('All supplied bars must be confirmed final')
    multiplier = _number(metadata.get('multiplier'), 'multiplier', positive=True)
    asset = metadata.get('asset_type')
    expiry = None
    if metadata.get('currency') != 'USD':
        raise ValueError('Initial ledger supports USD inputs only; no implicit FX conversion')
    if asset == 'equity':
        if (multiplier != 1 or metadata.get('data_type') != 'TRADES'
                or metadata.get('adjustment') != 'splits_only'):
            raise ValueError('Use split-adjusted equity TRADES bars with multiplier one')
    elif asset == 'option':
        if (daily or metadata.get('data_type') not in {'TRADES', 'MIDPOINT'}
                or type(metadata.get('instrument_id')) is not int
                or metadata['instrument_id'] <= 0):
            raise ValueError('Use exact-identity intraday option TRADES/MIDPOINT inputs')
        try:
            identity = metadata['option']
            expiry = datetime.strptime(identity['expiry'], '%Y%m%d').date()
            if identity['right'] not in {'C', 'P'}:
                raise ValueError('Invalid option right')
            _number(identity['strike'], 'strike', positive=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Invalid option identity') from exc
    else:
        raise ValueError('Only equities and options are supported')
    previous_end = None
    span = timedelta(seconds=_SPANS[interval])
    for bar in bars:
        start = _instant(bar.timestamp)
        end = start + span
        if previous_end is not None and start < previous_end:
            raise ValueError('Overlapping bars are unsupported')
        if not daily and end > finality:
            raise ValueError('Finality must cover bar completion, not just its start')
        if (min(bar.open, bar.high, bar.low, bar.close) <= 0
                or bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close)
                or bar.volume is not None and bar.volume < 0):
            raise ValueError('Use positive consistent OHLC and nonnegative available volume')
        if expiry and end.astimezone(ZoneInfo('America/New_York')).date() >= expiry:
            raise ValueError('Expiry-day/later data requires a lifecycle model')
        previous_end = end
    if feed.expected_starts is not None:
        if any((isinstance(stamp, datetime) == daily)
               or not isinstance(stamp, date)
               or isinstance(stamp, datetime) and stamp.utcoffset() is None
               for stamp in feed.expected_starts):
            raise ValueError('Expected starts must match the feed timestamp kind and timezone')
        if not feed.dataset.audit(feed.expected_starts,
                                  finalized_through=finality).matches_calendar:
            raise ValueError('Calendar mismatch')
    return Instrument(key, metadata['symbol'], asset, 'USD', multiplier, interval,
                      metadata['data_type'], metadata.get('instrument_id'), expiry)


def simulate(
    feeds: Mapping[str, Feed], strategy: Strategy, *, initial_cash: float = 10000,
    execution: ExecutionModel | None = None, strategy_settings: Mapping[str, Any] | None = None,
) -> SimulationResult:
    """Run deterministic close decisions / next-eligible-open market execution.

    Feeds share USD cash. Long-only whole quantities; no borrowing, reservation,
    shorts, partial fills, settlement or lifecycle processing. Unfilled orders are
    canceled at the end. Stale closes are retained with explicit ages/mark times;
    only an instrument's actual supplied open can fill its orders. No forced exit.
    Input/calendar assertions and model/strategy settings are retained in results.
    User code and external signals remain responsible for their own lookahead.
    """
    initial_cash = _number(initial_cash, 'initial_cash', positive=True)
    feeds = dict(feeds)
    if not feeds or any(not isinstance(key, str) or not key for key in feeds):
        raise ValueError('Supply nonempty named feeds')
    feeds = dict(sorted(feeds.items()))
    instruments = {key: _validate(key, feed) for key, feed in feeds.items()}
    kinds = {feed.dataset.metadata()['timestamp_kind'] for feed in feeds.values()}
    if len(kinds) != 1:
        raise ValueError('Daily/intraday mixing requires an explicit session-time model')
    identities = [(i.asset_type, i.instrument_id if i.instrument_id is not None else i.symbol)
                  for i in instruments.values()]
    if len(set(identities)) != len(identities):
        raise ValueError('Supply each instrument once; aliases cannot create separate positions')
    model = execution if execution is not None else NextOpen()
    provenance = dict(
        strategy=dict(strategy_settings or {}), execution=dict(model.settings()),
        timing='completed bars -> strategy -> opens at the same timestamp',
        daily_clock='synthetic UTC calendar days; no daily/intraday mixing',
        order_priority='submission order; no cash or position reservation',
        supported_orders='market; full fills or defer; long-only whole quantities',
        equity_sampling='completed closes before opens, then opens after executions',
        cost_basis='weighted average including entry fees',
        inputs={key: dict(fingerprint=feed.dataset.fingerprint(), metadata=feed.dataset.metadata(),
                          finalized_through=feed.finalized_through,
                          expected_starts=feed.expected_starts) for key, feed in feeds.items()},
    )
    provenance_json = json.dumps(provenance, default=_json_default, allow_nan=False)
    # Sorted feed keys make simultaneous publication independent of mapping insertion order.
    opens: dict[datetime, list[tuple[str, Bar]]] = defaultdict(list)
    closes: dict[datetime, list[tuple[str, Bar]]] = defaultdict(list)
    for key in sorted(feeds):
        span = timedelta(seconds=_SPANS[instruments[key].interval])
        for bar in feeds[key].dataset.snapshot():
            start = _instant(bar.timestamp)
            opens[start].append((key, bar))
            closes[start + span].append((key, bar))
    times = sorted(opens.keys() | closes.keys())
    for instrument in instruments.values():
        if instrument.expiry and times[-1].astimezone(ZoneInfo('America/New_York')).date() \
                >= instrument.expiry:
            raise ValueError('Simulation horizon crosses option expiry; lifecycle model required')
    positions = {key: Position(multiplier=i.multiplier) for key, i in instruments.items()}
    cash = initial_cash
    orders: dict[int, Order] = {}
    fills: list[Fill] = []
    curve: list[EquityPoint] = []
    history: dict[str, list[Bar]] = {key: [] for key in feeds}
    available: dict[str, datetime | None] = dict.fromkeys(feeds)
    active = False
    now = times[0]

    def portfolio() -> Portfolio:
        return Portfolio(cash, MappingProxyType(dict(positions)))

    def submit(key: str, side: Side, quantity: int, order_type: str, tag: str | None) -> int:
        if not active:
            raise RuntimeError('Orders may only be submitted during the strategy callback')
        if key not in instruments or side not in {'buy', 'sell'}:
            raise ValueError('Unknown instrument or unsupported order side')
        _quantity(quantity)
        if order_type != 'market':
            raise ValueError('Only market orders are implemented')
        if tag is not None and not isinstance(tag, str):
            raise ValueError('tag must be a string or None')
        order_id = len(orders) + 1
        orders[order_id] = Order(order_id, key, side, quantity, now, tag=tag)
        return order_id

    def cancel(order_id: int) -> bool:
        if not active:
            raise RuntimeError('Orders may only be canceled during the strategy callback')
        if type(order_id) is not int or order_id not in orders:
            raise ValueError('Unknown order ID')
        order = orders[order_id]
        if order.status != 'pending':
            return False
        orders[order_id] = replace(order, status='canceled', updated_at=now,
                                   reason='strategy_cancel')
        return True

    peak = previous_equity = initial_cash

    def record(phase: Literal['close', 'open']) -> None:
        nonlocal peak, previous_equity
        snapshot = portfolio()
        equity = snapshot.equity
        peak = max(peak, equity)
        change = _finite(equity / previous_equity - 1) if previous_equity else 0.0
        curve.append(EquityPoint(now, phase, cash, equity, change, equity / peak - 1,
                                 snapshot.positions))
        previous_equity = equity

    for now in times:
        completed = closes.get(now, [])
        for key, bar in completed:
            history[key].append(bar)
            available[key] = now
            positions[key] = replace(positions[key], mark=bar.close, marked_at=now)
        if completed:
            record('close')
            views = {key: DataView(tuple(history[key]), stamp,
                                   now - stamp if stamp is not None else None)
                     for key, stamp in available.items()}
            # A retained old context cannot submit through a later callback.
            def bound_submit(key: str, side: Side, quantity: int, order_type: str,
                             tag: str | None, *, decision_time: datetime = now) -> int:
                if decision_time != now:
                    raise RuntimeError('This strategy context is no longer active')
                return submit(key, side, quantity, order_type, tag)

            def bound_cancel(order_id: int, *, decision_time: datetime = now) -> bool:
                if decision_time != now:
                    raise RuntimeError('This strategy context is no longer active')
                return cancel(order_id)

            context = Context(now, tuple(key for key, _ in completed), MappingProxyType(views),
                              MappingProxyType(instruments), portfolio(), tuple(orders.values()),
                              tuple(fills), bound_submit, bound_cancel)
            active = True
            try:
                strategy.on_bar(context)
            finally:
                active = False
        opening = {key: OpenEvent(now, bar.open) for key, bar in opens.get(now, [])}
        for key, event in opening.items():
            positions[key] = replace(positions[key], mark=event.price, marked_at=now)
        for order_id, order in list(orders.items()):
            if order.status != 'pending' or order.instrument not in opening:
                continue
            key = order.instrument
            position = positions[key]
            event = opening[key]
            quote = model.execute(order, instruments[key], event, portfolio())
            if quote is None:
                continue
            price = _number(quote.price, 'execution price', positive=True)
            fee = _number(quote.commission, 'execution commission')
            notional = _finite(order.quantity * position.multiplier * price)
            if notional <= 0:
                raise ValueError('Execution notional underflowed')
            next_cash = _finite(cash + (notional if order.side == 'sell' else -notional) - fee)
            reason = ('insufficient_position' if order.side == 'sell'
                      and order.quantity > position.quantity else
                      'insufficient_cash' if next_cash < 0 else None)
            if reason:
                orders[order_id] = replace(order, status='rejected', updated_at=now, reason=reason)
                continue
            realized = 0.0
            if order.side == 'buy':
                quantity = position.quantity + order.quantity
                average = _finite((position.quantity * position.average_price
                                   + order.quantity * price) / quantity)
                basis = _finite(position.cost_basis + notional + fee)
            else:
                quantity = position.quantity - order.quantity
                allocated = position.cost_basis * (order.quantity / position.quantity)
                realized = _finite(notional - fee - allocated)
                basis = _finite(position.cost_basis - allocated) if quantity else 0.0
                average = position.average_price if quantity else 0.0
            cash = next_cash
            positions[key] = replace(position, quantity=quantity, average_price=average,
                                     cost_basis=basis,
                                     realized_pnl=_finite(position.realized_pnl + realized))
            fills.append(Fill(order_id, key, now, order.side, order.quantity, price, fee,
                              _finite(order.quantity * position.multiplier
                                      * (price - event.price)
                                      * (1 if order.side == 'buy' else -1)), realized, cash))
            orders[order_id] = replace(order, status='filled', updated_at=now)
        if opening:
            record('open')
    for order_id, order in orders.items():
        if order.status == 'pending':
            orders[order_id] = replace(order, status='canceled', updated_at=now,
                                       reason='end_of_data')
    warnings = (
        'Synthetic fills on supplied opens; spread, liquidity and partial fills are not modeled '
        'by NextOpen. Custom execution assumptions are user supplied.',
        'Calendar coverage is only checked for feeds with expected_starts; stale marks remain '
        'valued at their last observed price. Finality is asserted by the caller.',
        'Long-only USD cash ledger; no margin, FX, dividends, interest, settlement, taxes, '
        'adjusted option deliverables or exercise/assignment. No forced final exit.',
        'Equities use split-adjusted prices/quantities; nominal corporate actions are not rebuilt.',
        'Engine histories exclude future bars; user strategy code and external inputs '
        'are unaudited.',
    )
    return SimulationResult(initial_cash, 'USD', tuple(orders.values()), tuple(fills), tuple(curve),
                            portfolio(), warnings, provenance_json)


class TargetStrategy:
    """Convenience adapter: a per-bar target quantity function plus pending-order control.

    Targets may scale in/out. The adapter owns orders for this instrument and
    cancels its pending orders before recomputing the desired quantity. Other
    instruments can be read through the same context.
    """

    def __init__(self, instrument: str, target: Callable[[Context], int], *,
                 decision_feed: str | None = None) -> None:
        self.instrument = instrument
        self.target = target
        self.decision_feed = decision_feed if decision_feed is not None else instrument

    def on_bar(self, context: Context) -> None:
        if self.instrument not in context.instruments or self.decision_feed not in context.data:
            raise ValueError('Unknown target instrument or decision feed')
        if self.decision_feed not in context.updated:
            return
        target = self.target(context)
        if type(target) is not int or target < 0:
            raise ValueError('Target must be a nonnegative whole quantity')
        for order in context.orders:
            if order.instrument == self.instrument and order.status == 'pending':
                context.cancel(order.id)
        delta = target - context.portfolio.positions[self.instrument].quantity
        if delta:
            context.submit(self.instrument, 'buy' if delta > 0 else 'sell', abs(delta))

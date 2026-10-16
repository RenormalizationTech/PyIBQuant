"""Single-option premium-price research simulation on frozen intraday bars."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .backtest import _finite, _json_date
from .dataset import BarDataset


@dataclass(frozen=True)
class OptionFill:
    signal_bar_start: datetime
    execution_time: datetime
    side: Literal['buy', 'sell']
    contracts: int
    price: float
    commission: float
    slippage_cost: float
    cash_after: float


@dataclass(frozen=True)
class OptionTrade:
    entry_time: datetime
    exit_time: datetime
    contracts: int
    entry_price: float
    exit_price: float
    commissions: float
    net_pnl: float
    return_fraction: float


@dataclass(frozen=True)
class OptionRejection:
    signal_bar_start: datetime
    execution_time: datetime
    side: Literal['buy', 'sell']
    reason: str


@dataclass(frozen=True)
class OptionEquityPoint:
    timestamp: datetime
    cash: float
    contracts: int
    close: float
    equity: float
    period_return: float
    drawdown: float


@dataclass(frozen=True)
class OptionBacktestResult:
    symbol: str
    instrument_id: int
    currency: str
    multiplier: float
    data_type: str
    initial_cash: float
    contracts_per_entry: int
    commission_per_contract: float
    slippage_bps: float
    finalized_through: datetime
    calendar_times: tuple[datetime, ...] | None
    input_fingerprint: str
    signals: tuple[bool, ...]
    fills: tuple[OptionFill, ...]
    trades: tuple[OptionTrade, ...]
    rejections: tuple[OptionRejection, ...]
    equity_curve: tuple[OptionEquityPoint, ...]
    warnings: tuple[str, ...]
    _input_metadata_json: str

    def metrics(self) -> dict[str, Any]:
        """Cash-valued premium P&L, with open positions marked at the last close."""
        last = self.equity_curve[-1]
        entry = self.fills[-1] if last.contracts else None
        unrealized = (_finite(last.contracts * self.multiplier * (last.close - entry.price)
                              - entry.commission) if entry is not None else 0.0)
        return dict(
            initial_cash=self.initial_cash, final_cash=last.cash,
            final_equity=last.equity, ending_contracts=last.contracts,
            total_return=last.equity / self.initial_cash - 1,
            max_drawdown=min(point.drawdown for point in self.equity_curve),
            realized_net_pnl=_finite(sum(trade.net_pnl for trade in self.trades)),
            unrealized_net_pnl=unrealized,
            commissions=_finite(sum(fill.commission for fill in self.fills)),
            slippage_cost=_finite(sum(fill.slippage_cost for fill in self.fills)),
            completed_trades=len(self.trades), rejected_orders=len(self.rejections),
            win_rate=(sum(trade.net_pnl > 0 for trade in self.trades) / len(self.trades)
                      if self.trades else None),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop('_input_metadata_json')
        result['schema_version'] = 1
        result['input_metadata'] = json.loads(self._input_metadata_json)
        result['metrics'] = self.metrics()
        result['execution'] = dict(
            fill_model='next_bar_open', signal_timing='after_close',
            fill_timing='next_supplied_open', price_source=self.data_type,
            prices='premium_per_multiplier_unit', sizing='fixed_whole_contracts',
            commission='per_contract_per_side', cash_borrowing=False, shorting=False,
            final_position='marked_at_last_close', calendar_checked=self.calendar_times is not None,
            bid_ask_spread=False, liquidity_constraints=False, partial_fills=False,
            expiry_exercise_assignment=False, settlement_constraints=False,
            interest=False, taxes=False,
        )
        return json.loads(json.dumps(result, default=_json_date, allow_nan=False))

    def save(self, path: str | Path) -> Path:
        """Atomically save provenance, explicit assumptions, accounting and logs."""
        document = json.dumps(self.to_dict(), indent=2, allow_nan=False) + '\n'
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=target.parent,
                prefix=f'.{target.name}.', suffix='.tmp', delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(document)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target


def backtest_option(
    dataset: BarDataset, signals: Iterable[bool], *, fill_model: Literal['next_bar_open'],
    finalized_through: datetime, initial_cash: float = 10_000, contracts: int = 1,
    commission_per_contract: float = 0, slippage_bps: float = 0,
    expected_times: Iterable[datetime] | None = None,
) -> OptionBacktestResult:
    """Simulate one option long/flat using explicit synthetic next-open fills.

    Signals computed after each close first act at the next supplied open. Premium
    cash flows and marks use the resolved multiplier; commission is cash per
    contract per side. No shorts, borrowing, scaling, forced final exit or lifecycle
    settlement. Last-bar targets cannot execute. Insufficient cash rejects a fill;
    subsequent targets retry. TRADES and MIDPOINT are descriptive input sources,
    neither establishes an executable price. BID/ASK require a separate spread
    model and are deliberately unsupported by this single-source model.

    Requires a complete bounded USD option dataset, positive consistent intraday
    OHLC, exact identity/multiplier and bars strictly before the expiry date in
    New York. The caller asserts finality for all bars starting at or before
    finalized_through; optional expected_times audits coverage without guessing
    sessions. Timing does not validate caller-supplied signals for lookahead.
    """
    if fill_model != 'next_bar_open':
        raise ValueError('Explicitly select fill_model=next_bar_open for synthetic fills')
    if not isinstance(finalized_through, datetime) or finalized_through.utcoffset() is None:
        raise ValueError('finalized_through must be a timezone-aware datetime')
    if isinstance(contracts, bool) or not isinstance(contracts, int) or contracts <= 0:
        raise ValueError('contracts must be a positive whole number')
    try:
        _finite(float(contracts))
    except OverflowError as exc:
        raise ValueError('contracts is too large') from exc
    for name, value in [('initial_cash', initial_cash),
                        ('commission_per_contract', commission_per_contract),
                        ('slippage_bps', slippage_bps)]:
        try:
            valid = not isinstance(value, bool) and isfinite(value) and value >= 0
        except (TypeError, OverflowError):
            valid = False
        if not valid:
            raise ValueError(f'{name} must be finite and nonnegative')
    if initial_cash == 0 or slippage_bps >= 10_000:
        raise ValueError('initial_cash must be positive and slippage_bps below 10000')
    metadata = dataset.metadata()
    multiplier = metadata.get('multiplier')
    identity = metadata.get('option')
    if (metadata.get('asset_type') != 'option' or metadata.get('currency') != 'USD'
            or metadata.get('timestamp_kind') != 'datetime'
            or metadata.get('interval') not in {'30s', '1min', '5min', '15min', '30min',
                                                '1h', '2h', '4h'}
            or metadata.get('data_type') not in {'TRADES', 'MIDPOINT'}):
        raise ValueError('Use USD intraday option TRADES or MIDPOINT bars; '
                         'BID/ASK need a separate spread fill model')
    if (isinstance(multiplier, bool) or not isinstance(multiplier, (int, float))
            or not isfinite(multiplier) or multiplier <= 0
            or type(metadata.get('instrument_id')) is not int or metadata['instrument_id'] <= 0
            or not isinstance(identity, dict)):
        raise ValueError('Option backtest requires exact contract identity and positive multiplier')
    try:
        expiry = datetime.strptime(identity['expiry'], '%Y%m%d').date()
        strike = identity['strike']
        if (identity['right'] not in {'C', 'P'} or isinstance(strike, bool)
                or not isfinite(strike) or strike <= 0):
            raise ValueError('Invalid option strike/right')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Option backtest requires valid expiry/strike/right metadata') from exc
    if (metadata['query']['mode'] != 'range' or metadata['download']['complete'] is not True
            or metadata.get('error')):
        raise ValueError('Backtest requires a successfully completed fixed-range dataset')
    bars = dataset.snapshot()
    if len(bars) < 2:
        raise ValueError('Backtest requires at least two bars')
    stamps: list[datetime] = []
    minutes = {'30s': .5, '1min': 1, '5min': 5, '15min': 15, '30min': 30,
               '1h': 60, '2h': 120, '4h': 240}[metadata['interval']]
    bar_span = timedelta(minutes=minutes)
    for bar in bars:
        stamp = bar.timestamp
        if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
            raise ValueError('Option bar timestamps must be timezone-aware')
        if stamp > finalized_through:
            raise ValueError('All input bars must be confirmed final through finalized_through')
        if stamps and stamp < stamps[-1] + bar_span:
            raise ValueError('Overlapping bars would execute before the previous signal closes')
        if stamp.astimezone(ZoneInfo('America/New_York')).date() >= expiry:
            raise ValueError('Expiry-day and later bars require an option lifecycle model')
        if (min(bar.open, bar.high, bar.low, bar.close) <= 0
                or bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close)
                or bar.volume is not None and bar.volume < 0):
            raise ValueError('Backtest requires positive consistent OHLC and nonnegative '
                             'volume when available')
        stamps.append(stamp)
    targets = tuple(signals)
    if len(targets) != len(bars) or any(type(value) is not bool for value in targets):
        raise ValueError('Supply exactly one boolean target signal per input bar')
    calendar = tuple(expected_times) if expected_times is not None else None
    if calendar is not None:
        if any(not isinstance(stamp, datetime) or stamp.utcoffset() is None for stamp in calendar):
            raise ValueError('expected_times must contain timezone-aware datetimes')
        audit = dataset.audit(calendar, finalized_through=finalized_through)
        if not audit.matches_calendar:
            raise ValueError(f'Calendar mismatch: {len(audit.missing)} missing, '
                             f'{len(audit.unexpected)} unexpected bars')
    warnings = list(metadata.get('warnings', [])) + [
        'Synthetic next-supplied-open fills; TRADES and MIDPOINT do not establish executable '
        'bid/ask prices. Spread, liquidity, sizes and partial fills are not modeled.',
        'Signals must use only information available at their close; '
        'caller signals are not audited.',
        'Resolved multiplier scales premium cash flows; adjusted deliverables, exercise, '
        'assignment and expiry settlement are not modeled. Expiry-day inputs are rejected.',
        'Final positions are marked at the last source close without exit costs or forced sale.',
        'Bar finality is asserted by the caller, not established by provider download completion.',
        'Interest, taxes, settlement restrictions and account-specific broker rules are excluded.',
    ]
    if calendar is None:
        warnings.append('Calendar coverage is unverified; the next supplied bar may follow a gap.')
    cash, held = float(initial_cash), 0
    peak, previous_equity = cash, cash
    units = _finite(contracts * float(multiplier))
    commission = _finite(contracts * float(commission_per_contract))
    fills: list[OptionFill] = []
    trades: list[OptionTrade] = []
    rejections: list[OptionRejection] = []
    curve: list[OptionEquityPoint] = []
    entry: OptionFill | None = None
    for index, (stamp, bar) in enumerate(zip(stamps, bars, strict=True)):
        if index and targets[index - 1] != bool(held):
            side: Literal['buy', 'sell'] = 'sell' if held else 'buy'
            price = _finite(bar.open * (1 + (1 if side == 'buy' else -1) * slippage_bps / 10000))
            notional = _finite(units * price)
            if price <= 0 or notional <= 0:
                raise ValueError('Fill price or notional underflowed; inspect prices and costs')
            next_cash = _finite(cash + (notional if side == 'sell' else -notional) - commission)
            if next_cash < 0:
                rejections.append(OptionRejection(stamps[index - 1], stamp, side,
                                                   'insufficient_cash'))
            else:
                cash = next_cash
                fill = OptionFill(stamps[index - 1], stamp, side, contracts, price, commission,
                                  _finite(units * abs(price - bar.open)), cash)
                fills.append(fill)
                if side == 'buy':
                    held, entry = contracts, fill
                else:
                    assert entry is not None
                    cost = _finite(units * entry.price + entry.commission)
                    pnl = _finite(notional - commission - cost)
                    trades.append(OptionTrade(entry.execution_time, stamp, contracts,
                                              entry.price, price, entry.commission + commission,
                                              pnl, _finite(pnl / cost)))
                    held, entry = 0, None
        equity = _finite(cash + _finite(held * float(multiplier) * bar.close))
        peak = max(peak, equity)
        change = _finite(equity / previous_equity - 1) if previous_equity else 0.0
        curve.append(OptionEquityPoint(stamp, cash, held, bar.close, equity,
                                       change, equity / peak - 1))
        previous_equity = equity
    return OptionBacktestResult(
        metadata['symbol'], metadata['instrument_id'], metadata['currency'], float(multiplier),
        metadata['data_type'], float(initial_cash), contracts, float(commission_per_contract),
        float(slippage_bps), finalized_through, calendar, dataset.fingerprint(), targets,
        tuple(fills), tuple(trades), tuple(rejections), tuple(curve), tuple(warnings),
        json.dumps(metadata, sort_keys=True, allow_nan=False),
    )

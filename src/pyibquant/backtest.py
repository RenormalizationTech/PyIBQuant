"""Small daily equity simulator on frozen inputs; no broker or order API calls."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from .dataset import BarDataset


@dataclass(frozen=True)
class Fill:
    signal_date: date
    execution_date: date
    side: Literal["buy", "sell"]
    shares: int
    price: float
    commission: float
    slippage_cost: float
    cash_after: float


@dataclass(frozen=True)
class Trade:
    entry_date: date
    exit_date: date
    shares: int
    entry_price: float
    exit_price: float
    commissions: float
    net_pnl: float
    return_fraction: float


@dataclass(frozen=True)
class Rejection:
    signal_date: date
    execution_date: date
    side: Literal["buy", "sell"]
    reason: str


@dataclass(frozen=True)
class EquityPoint:
    timestamp: date
    cash: float
    shares: int
    close: float
    equity: float
    period_return: float
    drawdown: float


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    currency: str | None
    initial_cash: float
    shares_per_entry: int
    commission_per_fill: float
    slippage_bps: float
    finalized_through: date
    calendar_checked: bool
    calendar_dates: tuple[date, ...] | None
    input_fingerprint: str
    signals: tuple[bool, ...]
    fills: tuple[Fill, ...]
    trades: tuple[Trade, ...]
    rejections: tuple[Rejection, ...]
    equity_curve: tuple[EquityPoint, ...]
    warnings: tuple[str, ...]
    _input_metadata_json: str

    def metrics(self) -> dict[str, Any]:
        """Fractional returns/drawdown; ending positions are marked at last close."""
        last = self.equity_curve[-1]
        realized = sum(trade.net_pnl for trade in self.trades)
        last_entry = self.fills[-1] if last.shares else None
        unrealized = (last.shares * (last.close - last_entry.price) - last_entry.commission
                      if last_entry is not None else 0.0)
        return dict(
            initial_cash=self.initial_cash, final_cash=last.cash,
            final_equity=last.equity, ending_shares=last.shares,
            total_return=last.equity / self.initial_cash - 1,
            max_drawdown=min(point.drawdown for point in self.equity_curve),
            realized_net_pnl=realized,
            unrealized_net_pnl=unrealized,
            commissions=sum(fill.commission for fill in self.fills),
            slippage_cost=sum(fill.slippage_cost for fill in self.fills),
            completed_trades=len(self.trades), rejected_orders=len(self.rejections),
            win_rate=(sum(trade.net_pnl > 0 for trade in self.trades) / len(self.trades)
                      if self.trades else None),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return independent JSON-compatible assumptions, provenance and results."""
        result = asdict(self)
        result.pop('_input_metadata_json')
        result['input_metadata'] = json.loads(self._input_metadata_json)
        result['metrics'] = self.metrics()
        result['schema_version'] = 1
        result['execution'] = dict(
            signal_timing='after_close', fill_timing='next_supplied_open',
            sizing='fixed_whole_shares', cash_borrowing=False, shorting=False,
            final_position='marked_at_last_close', price_basis='split_adjusted',
            dividends=False, interest=False, volume_constraints=False,
            settlement_constraints=False, taxes=False,
        )
        # Round-trip converts date values and tuples without exposing mutable state.
        return json.loads(json.dumps(result, default=_json_date, allow_nan=False))

    def save(self, path: str | Path) -> Path:
        """Atomically save assumptions, inputs' metadata, fill log and equity curve."""
        document = json.dumps(self.to_dict(), indent=2, allow_nan=False) + '\n'
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=target.parent, prefix=f'.{target.name}.',
                suffix='.tmp', delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(document)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target


def _json_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f'Not JSON serializable: {type(value).__name__}')


def _finite(value: float) -> float:
    if not isfinite(value):
        raise ValueError('Backtest calculation overflowed; inspect prices, sizing and costs')
    return value


def backtest_equity(
    dataset: BarDataset, signals: Iterable[bool], *, finalized_through: date,
    initial_cash: float = 10_000, shares: int = 1, commission: float = 0,
    slippage_bps: float = 0, expected_dates: Iterable[date] | None = None,
) -> BacktestResult:
    """Simulate fixed whole-share long/flat targets on daily regular-hours equities.

    Each signal is a target computed after that bar closes; it first acts at the
    following supplied bar's open. True enters if flat, False exits if long; an
    unchanged position never rebalances. Insufficient cash rejects the order and
    the next target retries at the next open. No borrowing, shorting, forced final
    sale, dividends, interest or volume-based fill model. The last signal cannot
    execute. Slippage moves buys up and sells down; flat commission is per fill.

    Inputs must be complete fixed-range split-adjusted TRADES equity bars with
    multiplier one. Prices and quantities remain in that adjusted price basis;
    simulated fills are not historical nominal-share broker executions. The caller
    confirms bar finality through a date; calendar coverage is only checked when
    expected_dates from an independent calendar are supplied. Signals are supplied
    by the caller; delaying execution does not validate how they were computed.
    """
    if isinstance(finalized_through, datetime) or not isinstance(finalized_through, date):
        raise ValueError('finalized_through must be a calendar date')
    if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0:
        raise ValueError('shares must be a positive whole number')
    try:
        _finite(float(shares))
    except OverflowError as exc:
        raise ValueError('shares is too large') from exc
    for name, value in [('initial_cash', initial_cash), ('commission', commission),
                        ('slippage_bps', slippage_bps)]:
        try:
            valid = not isinstance(value, bool) and isfinite(value) and value >= 0
        except (TypeError, OverflowError):
            valid = False
        if not valid:
            raise ValueError(f'{name} must be a finite nonnegative number')
    if initial_cash == 0 or slippage_bps >= 10_000:
        raise ValueError('initial_cash must be positive and slippage_bps below 10000')
    metadata = dataset.metadata()
    if (metadata['interval'] != '1d' or metadata.get('asset_type') != 'equity'
            or metadata.get('multiplier') != 1 or metadata.get('data_type') != 'TRADES'
            or metadata.get('adjustment') != 'splits_only'
            or metadata.get('regular_hours') is not True):
        raise ValueError('Use daily regular-hours split-adjusted TRADES equities, multiplier one')
    if (metadata['query']['mode'] != 'range' or metadata['download']['complete'] is not True
            or metadata.get('error')):
        raise ValueError('Backtest requires a successfully completed fixed-range dataset')
    bars = dataset.snapshot()
    if len(bars) < 2:
        raise ValueError('Backtest requires at least two bars')
    if bars[-1].timestamp > finalized_through:
        raise ValueError('All input bars must be confirmed final through finalized_through')
    for bar in bars:
        if (min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.volume < 0
                or bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close)):
            raise ValueError('Backtest requires positive, consistent OHLC prices '
                             'and nonnegative volume')
    targets = tuple(signals)
    if len(targets) != len(bars) or any(type(value) is not bool for value in targets):
        raise ValueError('Supply exactly one boolean target signal per input bar')
    calendar_checked = expected_dates is not None
    calendar_dates = tuple(expected_dates) if expected_dates is not None else None
    if calendar_dates is not None:
        audit = dataset.audit(calendar_dates, finalized_through=finalized_through)
        if not audit.matches_calendar:
            raise ValueError(f'Calendar mismatch: {len(audit.missing)} missing, '
                             f'{len(audit.unexpected)} unexpected bars')
    warnings = list(metadata.get('warnings', []))
    warnings.extend([
        'Adjusted-price research simulation: dividends, interest and corporate-action cash flows '
        'are excluded; historical nominal-share execution is not reconstructed.',
        'Signals must use only data available at their close; '
        'caller-provided signals are not audited.',
        'Fills assume the next supplied open with fixed costs; '
        'liquidity and volume are not modeled.',
        'Final positions are marked at the last close, without a forced exit '
        'or estimated exit costs.',
        'Bar finality is asserted by the caller, not established by provider download completion.',
        'Settlement restrictions, taxes and account-specific broker rules are not modeled.',
    ])
    if not calendar_checked:
        warnings.append('Calendar coverage is unverified; '
                        'the next supplied bar may follow a data gap.')
    cash, held = float(initial_cash), 0
    peak, previous_equity = cash, cash
    fills: list[Fill] = []
    trades: list[Trade] = []
    rejections: list[Rejection] = []
    curve: list[EquityPoint] = []
    entry: Fill | None = None
    for index, bar in enumerate(bars):
        # Daily timestamps are validated by BarDataset; datetime is never used here.
        stamp = bar.timestamp
        if index and targets[index - 1] != bool(held):
            side: Literal['buy', 'sell'] = 'sell' if held else 'buy'
            price = _finite(bar.open * (1 + (1 if side == 'buy' else -1) * slippage_bps / 10000))
            notional = _finite(shares * price)
            if price <= 0 or notional <= 0:
                raise ValueError('Fill price or notional underflowed; inspect prices and costs')
            next_cash = _finite(cash + (notional if side == 'sell' else -notional) - commission)
            if next_cash < 0:
                rejections.append(Rejection(bars[index - 1].timestamp, stamp, side,
                                            'insufficient_cash'))
            else:
                cash = next_cash
                fill = Fill(bars[index - 1].timestamp, stamp, side, shares, price,
                            float(commission), _finite(shares * abs(price - bar.open)), cash)
                fills.append(fill)
                if side == 'buy':
                    held, entry = shares, fill
                else:
                    assert entry is not None
                    cost = _finite(shares * entry.price + entry.commission)
                    pnl = _finite(notional - commission - cost)
                    trades.append(Trade(
                        entry.execution_date, stamp, shares, entry.price, price,
                        entry.commission + commission, pnl, _finite(pnl / cost),
                    ))
                    held, entry = 0, None
        equity = _finite(cash + _finite(held * bar.close))
        peak = max(peak, equity)
        change = _finite(equity / previous_equity - 1) if previous_equity else 0.0
        curve.append(EquityPoint(stamp, cash, held, bar.close, equity, change, equity / peak - 1))
        previous_equity = equity
    return BacktestResult(
        metadata['symbol'], metadata.get('currency'), float(initial_cash), shares,
        float(commission), float(slippage_bps), finalized_through, calendar_checked, calendar_dates,
        dataset.fingerprint(),
        targets, tuple(fills), tuple(trades), tuple(rejections), tuple(curve), tuple(warnings),
        json.dumps(metadata, sort_keys=True, allow_nan=False),
    )

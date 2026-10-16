"""Causal, single-contract intraday simulations from sampled live option recordings."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .quote_recording import QuoteRecording


@dataclass(frozen=True)
class OptionFill:
    signal_time: datetime
    execution_time: datetime
    side: Literal['buy', 'sell']
    contracts: int
    multiplier: float
    price: float
    commission: float
    slippage_cost: float
    cash_after: float
    quote_sequence: int
    price_received_at: datetime
    size_received_at: datetime
    side_received_at: datetime


@dataclass(frozen=True)
class OptionTrade:
    entry_time: datetime
    exit_time: datetime
    contracts: int
    multiplier: float
    entry_price: float
    exit_price: float
    commissions: float
    net_pnl: float
    return_fraction: float


@dataclass(frozen=True)
class SkippedFill:
    signal_time: datetime
    observation_time: datetime
    side: Literal['buy', 'sell']
    reason: str


@dataclass(frozen=True)
class OptionEquityPoint:
    timestamp: datetime
    cash: float
    contracts: int
    equity: float | None
    valuation_reason: str | None
    period_return: float | None
    drawdown: float | None


@dataclass(frozen=True)
class OptionBacktestResult:
    input_fingerprint: str
    initial_cash: float
    contracts_per_entry: int
    commission_per_contract: float
    slippage_bps: float
    max_quote_age: float
    max_side_skew: float
    max_gap: float
    latency: float
    quote_age_basis: str
    signals: tuple[bool, ...]
    fills: tuple[OptionFill, ...]
    trades: tuple[OptionTrade, ...]
    skipped_fills: tuple[SkippedFill, ...]
    equity_curve: tuple[OptionEquityPoint, ...]
    warnings: tuple[str, ...]
    _metadata_json: str

    def metrics(self) -> dict[str, Any]:
        last = self.equity_curve[-1]
        unpriced = sum(point.equity is None for point in self.equity_curve)
        realized = sum(trade.net_pnl for trade in self.trades)
        entry = self.fills[-1] if last.contracts else None
        unrealized = (last.equity - last.cash - entry.contracts * entry.multiplier * entry.price
                      - entry.commission if entry is not None and last.equity is not None
                      else None if last.contracts else 0.0)
        return dict(
            initial_cash=self.initial_cash, final_cash=last.cash, final_equity=last.equity,
            ending_contracts=last.contracts,
            total_return=last.equity / self.initial_cash - 1 if last.equity is not None else None,
            max_drawdown=(min(point.drawdown for point in self.equity_curve
                              if point.drawdown is not None) if not unpriced else None),
            valuation_complete=not unpriced, unpriced_observations=unpriced,
            realized_net_pnl=realized, unrealized_net_pnl=unrealized,
            commissions=sum(fill.commission for fill in self.fills),
            slippage_cost=sum(fill.slippage_cost for fill in self.fills),
            completed_trades=len(self.trades), skipped_fill_observations=len(self.skipped_fills),
            win_rate=(sum(trade.net_pnl > 0 for trade in self.trades) / len(self.trades)
                      if self.trades else None),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop('_metadata_json')
        result.update(schema_version=2, input_metadata=json.loads(self._metadata_json),
                      metrics=self.metrics(), execution=dict(
                          source='sampled_option_quotes', signal_timing='after_observation',
                          fill_timing=('later_sample_and_new_side_price_receipt_after_signal'
                                       if self.quote_age_basis == 'price_receipt' else
                                       'later_sample_and_new_side_size_receipt_after_signal'),
                          entry='ask_plus_slippage', exit='bid_minus_slippage',
                          size='full_fixed_contract_quantity_with_observed_top_size',
                          valuation='fresh_bid_without_forced_sale_or_exit_cost_estimate',
                          quote_age='local_callback_receipt_proxy_not_exchange_age',
                          quote_age_basis=self.quote_age_basis,
                          position='long_or_flat', exercise=False, assignment=False,
                          settlement=False, interest=False, taxes=False,
                      ))
        return json.loads(json.dumps(result, default=lambda value: value.isoformat(),
                                     allow_nan=False))

    def save(self, path: str | Path) -> Path:
        text = json.dumps(self.to_dict(), indent=2, allow_nan=False) + '\n'
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                    prefix=f'.{target.name}.', suffix='.tmp', delete=False) as file:
                temporary = Path(file.name)
                file.write(text)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target


def _time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError('Option replay timestamps must be ISO strings')
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('Option replay timestamps must be timezone-aware')
    return result.astimezone(UTC)


def _finite(value: float) -> float:
    if not isfinite(value):
        raise ValueError('Option backtest arithmetic overflowed')
    return value


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f'{name} must be finite and nonnegative') from exc
    if isinstance(value, bool) or not isfinite(result) or result < 0 or positive and result == 0:
        raise ValueError(f'{name} must be finite and {"positive" if positive else "nonnegative"}')
    return result


def _eligible(
    quote: dict[str, Any], now: datetime, contracts: int, *,
    side: Literal['buy', 'sell'], max_age: float, max_skew: float,
    quote_age_basis: str,
) -> tuple[str | None, datetime | None, datetime | None, datetime | None]:
    if quote['market_data_type'] != 'live' or quote['delayed_ticks']:
        return 'unconfirmed_live_feed', None, None, None
    if quote['status'] != 'active' or quote['error'] is not None:
        return 'inactive_quote', None, None, None
    if quote['bid'] is None or quote['ask'] is None or min(quote['bid'], quote['ask']) <= 0:
        return 'missing_bid_ask', None, None, None
    if quote['bid'] > quote['ask']:
        return 'crossed_quote', None, None, None
    names = ('bid', 'ask', 'bid_size', 'ask_size')
    receipts = quote['field_received_at']
    if any(receipts.get(name) is None for name in names):
        return 'missing_receipt_time', None, None, None
    times = {name: _time(receipts[name]) for name in names}
    clocks = times
    if quote_age_basis == 'side_update':
        # IBKR sends independent tickSize callbacks for unchanged prices. Require
        # matching live tick families and a size receipt at/after each side's
        # current price; a new price must wait for its own following size update.
        if (quote.get('provider') != 'IBKR' or quote.get('source') != 'reqMktData'
                or any(quote['field_tick_types'].get(name) != tick
                       for name, tick in {'bid': 1, 'ask': 2,
                                          'bid_size': 0, 'ask_size': 3}.items())):
            return 'unverified_side_update', None, None, None
        if any(times[name+'_size'] < times[name] for name in ('bid', 'ask')):
            return 'waiting_side_size', None, None, None
        if any(quote[name] is None for name in ('bid_size', 'ask_size')):
            return 'missing_side_size', None, None, None
        clocks = {name: times[name] for name in ('bid_size', 'ask_size')}
    if any((now - stamp).total_seconds() > max_age for stamp in clocks.values()):
        return 'stale_quote', None, None, None
    if (max(clocks.values()) - min(clocks.values())).total_seconds() > max_skew:
        return 'asynchronous_sides', None, None, None
    price_name, size_name = ('ask', 'ask_size') if side == 'buy' else ('bid', 'bid_size')
    if quote[size_name] is None or quote[size_name] < contracts:
        return 'insufficient_displayed_size', None, None, None
    side_time = times[size_name] if quote_age_basis == 'side_update' else times[price_name]
    return None, times[price_name], times[size_name], side_time


def backtest_option(
    recording: QuoteRecording, signals: Iterable[bool], *, initial_cash: float = 10_000,
    contracts: int = 1, commission: float = 0, slippage_bps: float = 0,
    max_quote_age: float = 2, max_side_skew: float = 1, max_gap: float = 5,
    latency: float = 0,
    quote_age_basis: str = 'price_receipt',
) -> OptionBacktestResult:
    """Replay one complete, same-NY-date option recording strictly before expiry.

    Confirmed-live fields only; frozen/delayed records are rejected, initial unknown
    fields are ineligible. Each signal is a long/flat target after its observation.
    By default an intent may fill on a later sample after latency and a side-price
    receipt newer than its signal. Unchanged targets retain a pending intent; changed
    targets replace/cancel it after processing the current observation. A position
    never rebalances. Missing/stale/crossed/undersized quotes skip fills. No borrowing,
    shorting, partial fills or invented final exit. Open positions use a qualified
    bid mark; unavailable valuation remains None and drawdown becomes unverified.

    Local receipt age/skew are proxies, not proof of exchange freshness. Recorded
    top sizes do not establish fillability or account for queue/market impact.
    Caller-provided signals must not use future data. No exercise/assignment,
    expiry payoff, overnight carry, account settlement or broker execution model.

    quote_age_basis='side_update' explicitly uses matching IBKR bid/ask size
    receipts at/after their prices for age/skew and post-signal evidence. Original
    price receipts remain unchanged. The default requires new price receipts.
    """
    if not recording.complete:
        raise ValueError('Option backtest requires a complete recording')
    if quote_age_basis not in {'price_receipt', 'side_update'}:
        raise ValueError('quote_age_basis must be price_receipt or side_update')
    if isinstance(contracts, bool) or not isinstance(contracts, int) or contracts <= 0:
        raise ValueError('contracts must be a positive whole number')
    _number(contracts, 'contracts', positive=True)
    initial_cash = _number(initial_cash, 'initial_cash', positive=True)
    commission = _number(commission, 'commission')
    slippage_bps = _number(slippage_bps, 'slippage_bps')
    max_quote_age = _number(max_quote_age, 'max_quote_age', positive=True)
    max_side_skew = _number(max_side_skew, 'max_side_skew')
    max_gap = _number(max_gap, 'max_gap', positive=True)
    latency = _number(latency, 'latency')
    if slippage_bps >= 10000:
        raise ValueError('slippage_bps must be below 10000')
    metadata = recording.metadata()
    instrument = metadata['header']['instrument']
    if instrument.get('asset_type') != 'option' or not instrument.get('instrument_id'):
        raise ValueError('Option replay requires a resolved option contract')
    multiplier = _number(instrument.get('multiplier'), 'recorded multiplier', positive=True)
    expiry_text = instrument.get('expiry')
    if not isinstance(expiry_text, str) or len(expiry_text) < 8:
        raise ValueError('Option recording requires an expiry date')
    expiry = datetime.strptime(expiry_text[:8], '%Y%m%d').date()
    rows = list(recording.samples())
    if len(rows) < 2:
        raise ValueError('Option backtest requires at least two observations')
    targets = tuple(signals)
    if len(targets) != len(rows) or any(type(value) is not bool for value in targets):
        raise ValueError('Supply exactly one boolean target per recorded observation')
    stamps = [_time(row['sampled_at']) for row in rows]
    days = {stamp.astimezone(ZoneInfo('America/New_York')).date() for stamp in stamps}
    if len(days) != 1 or max(days) >= expiry:
        raise ValueError('Use one New York date strictly before expiry; '
                         'overnight/expiry not modeled')
    for index, (stamp, row) in enumerate(zip(stamps, rows, strict=True)):
        if index and (stamp <= stamps[index - 1]
                      or (stamp - stamps[index - 1]).total_seconds() > max_gap):
            raise ValueError('Recording has nonincreasing times or a gap exceeding max_gap')
        quote = row['quote']
        if quote.get('generation', 0) != 0 or quote.get('gaps'):
            raise ValueError('Recording crosses a quote reconnect gap; '
                             'cross-generation simulation is not modeled')
        if quote['market_data_type'] not in {None, 'live'} or quote['delayed_ticks']:
            raise ValueError('Frozen/delayed recordings are replay inputs, '
                             'not live backtest inputs')
        if quote['status'] in {'closed', 'disconnected', 'failed'} or quote['error'] is not None:
            raise ValueError('Recording contains a terminal stream state')
        observed = _time(quote['observed_at'])
        if observed > stamp or any(_time(value) > observed
                                   for value in quote['field_received_at'].values()):
            raise ValueError('Recording has receipt/observation times later than its sampled time')
    if not any(row['quote']['market_data_type'] == 'live' for row in rows):
        raise ValueError('Recording has no confirmed-live observations')
    cash, held = initial_cash, 0
    pending: tuple[bool, datetime] | None = None
    entry: OptionFill | None = None
    peak, path_complete = cash, True
    previous_equity: float | None = cash
    fills: list[OptionFill] = []
    trades: list[OptionTrade] = []
    skipped: list[SkippedFill] = []
    curve: list[OptionEquityPoint] = []
    fee = _finite(contracts * commission)
    for stamp, row, target in zip(stamps, rows, targets, strict=True):
        quote = row['quote']
        if pending is not None:
            desired, signal_time = pending
            side: Literal['buy', 'sell'] = 'buy' if desired else 'sell'
            reason, price_time, size_time, side_time = _eligible(
                quote, stamp, contracts, side=side, max_age=max_quote_age, max_skew=max_side_skew,
                quote_age_basis=quote_age_basis)
            if (stamp - signal_time).total_seconds() < latency:
                reason = 'waiting_latency'
            elif reason is None and (side_time is None or side_time <= signal_time):
                reason = ('waiting_new_side_price' if quote_age_basis == 'price_receipt'
                          else 'waiting_new_side_update')
            if reason is None:
                reference = quote['ask'] if desired else quote['bid']
                price = _finite(reference * (1 + (1 if desired else -1) * slippage_bps / 10000))
                notional = _finite(contracts * multiplier * price)
                if price <= 0 or notional <= 0:
                    raise ValueError('Option fill price/notional underflowed')
                next_cash = _finite(cash + (-notional if desired else notional) - fee)
                if next_cash < 0:
                    reason = 'insufficient_cash'
                else:
                    assert price_time is not None and size_time is not None
                    assert side_time is not None
                    cash = next_cash
                    fill = OptionFill(signal_time, stamp, side, contracts, multiplier, price,
                                      fee, _finite(contracts * multiplier * abs(price-reference)),
                                      cash, quote['sequence'], price_time, size_time, side_time)
                    fills.append(fill)
                    if desired:
                        held, entry = contracts, fill
                    else:
                        assert entry is not None
                        cost = _finite(contracts * multiplier * entry.price + entry.commission)
                        pnl = _finite(notional - fee - cost)
                        trades.append(OptionTrade(
                            entry.execution_time, stamp, contracts, multiplier, entry.price, price,
                            entry.commission+fee, pnl, _finite(pnl/cost),
                        ))
                        held, entry = 0, None
                    pending = None
            if reason is not None:
                skipped.append(SkippedFill(signal_time, stamp, side, reason))
        valuation_reason = None
        equity: float | None = cash
        if held:
            valuation_reason, _, _, _ = _eligible(
                quote, stamp, held, side='sell', max_age=max_quote_age, max_skew=max_side_skew,
                quote_age_basis=quote_age_basis)
            equity = (_finite(cash + held * multiplier * quote['bid'])
                      if valuation_reason is None else None)
        change = (_finite(equity/previous_equity-1) if equity is not None
                  and previous_equity is not None and previous_equity else None)
        path_complete &= equity is not None
        if equity is not None:
            peak = max(peak, equity)
        drawdown = equity/peak-1 if path_complete and equity is not None else None
        curve.append(OptionEquityPoint(stamp, cash, held, equity, valuation_reason,
                                      change, drawdown))
        previous_equity = equity
        if target == bool(held):
            pending = None
        elif pending is None or pending[0] != target:
            pending = target, stamp
    return OptionBacktestResult(
        recording.fingerprint(), initial_cash, contracts, commission, slippage_bps,
        max_quote_age, max_side_skew, max_gap, latency, quote_age_basis,
        targets, tuple(fills), tuple(trades),
        tuple(skipped), tuple(curve), (
            'Sampled recorded quotes are not an exchange tick archive '
            'or proof of executable prices.',
            'Age/skew checks use local receipt times, not exchange quote timestamps.',
            ('Quote clock: matching IBKR side-size receipts confirm accumulated prices; '
             'price receipt timestamps are preserved.' if quote_age_basis == 'side_update'
             else 'Quote clock: original price/size receipts; new price after signal required.'),
            'Caller signals must use only information available at their observation time.',
            'Buy at ask/sell at bid with adverse slippage and per-contract commission; '
            'full fills only.',
            'No book reservation, queue priority, market impact, shorting or borrowing is modeled.',
            'Intraday pre-expiry only; exercise, assignment, settlement, interest '
            'and taxes excluded.',
            'Final positions remain marked at a qualified bid; '
            'no forced exit or final signal fill.',
        ), json.dumps(metadata, sort_keys=True, allow_nan=False),
    )


def hold_window(recording: QuoteRecording, seconds: float = 5) -> tuple[bool, ...]:
    """Long until a configured time after recording start; independent of future prices."""
    seconds = _number(seconds, 'seconds', positive=True)
    start = _time(recording.metadata()['header']['started_at'])
    return tuple((_time(row['sampled_at']) - start).total_seconds() < seconds
                 for row in recording.samples())


def spread_targets(recording: QuoteRecording, max_fraction: float = .05) -> tuple[bool, ...]:
    """Long while the current relative spread is below a threshold; no fill guarantee."""
    max_fraction = _number(max_fraction, 'max_fraction', positive=True)
    targets = []
    for row in recording.samples():
        quote = row['quote']
        bid, ask = quote['bid'], quote['ask']
        valid = (quote['market_data_type'] == 'live' and not quote['delayed_ticks']
                 and bid is not None and ask is not None and 0 < bid <= ask)
        targets.append(bool(valid and (ask-bid)/(bid+(ask-bid)/2) <= max_fraction))
    return tuple(targets)

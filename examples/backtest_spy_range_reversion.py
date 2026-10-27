"""Backtest an intraday SPY range-reversion rule on September 2026 one-minute bars.

Download the bars once (IBKR data; no orders), then backtest offline:
    python examples/backtest_spy_range_reversion.py --download
    python examples/backtest_spy_range_reversion.py
    python examples/backtest_spy_range_reversion.py --rule scaled

Rule, in New York time: stay flat before 12:00. Buy when the latest close is in
the bottom 20% of today's high-low range so far; sell in the top 20%. A stop loss
exits below the entry price and keeps the strategy flat for the rest of that day.
Everything is sold by 15:00. Without --download, no broker connection is made.

--rule scaled builds the position in steps instead: the lower the close sits in
today's range, the more shares are held, like a market maker's inventory curve.
It still trades at market and pays costs; it does not post quotes or earn a spread.
"""

import argparse
import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pyibquant import BarDataset, Market
from pyibquant.simulation import Context, Feed, NextOpen, TargetStrategy, simulate

NY = ZoneInfo("America/New_York")
DATASET = Path("charts/spy-sep2026-1min.bars.json")
OUTPUT = Path("charts/backtest")

INITIAL_CASH = 10_000
# Keep the largest position x SPY price well below INITIAL_CASH; otherwise buys
# are rejected for insufficient cash as soon as equity falls.
SHARES = 5  # Fixed rule: all or nothing
STEP_SHARES = 2  # Scaled rule: shares added or removed per step...
MAX_STEPS = 3  # ...up to STEP_SHARES x MAX_STEPS shares
BUY_LEVEL = 0.20
SELL_LEVEL = 0.80
# Dollars per share below the entry fill price. Keep it well above the slippage
# per share (price x SLIPPAGE_BPS / 10000), or costs alone trigger the stop.
STOP_LOSS = 1.00

# Illustrative costs per fill; these are not an IBKR fee quote.
COMMISSION = 1.00
SLIPPAGE_BPS = 1.0


def download() -> None:
    """Save SPY regular-session one-minute bars for September 2026."""
    with Market.ibkr(client_id=72) as market:
        series = market.bars(
            "SPY",
            interval="1min",
            start="2026-09-01T00:00:00-04:00",
            end="2026-10-01T00:00:00-04:00",
            regular_hours=True,
        )
        if len(series) < 2 or series.download_complete is not True:
            raise RuntimeError("Download incomplete; inspect the download metadata.")
        BarDataset.from_series(series).save(DATASET)
    print(f"Saved {len(series)} bars to {DATASET}")


def expected_starts() -> tuple[datetime, ...]:
    """All regular-session one-minute bar starts in September 2026."""
    starts: list[datetime] = []
    for day in range(1, 31):
        session = date(2026, 9, day)
        if session.weekday() >= 5 or session == date(2026, 9, 7):  # Labor Day
            continue
        opening = datetime.combine(session, time(9, 30), tzinfo=NY)
        starts.extend(opening + timedelta(minutes=i) for i in range(390))  # 09:30-15:59
    return tuple(starts)


class RangeReversion:
    """Target-quantity rule that remembers stop-loss days to avoid re-entering."""

    max_shares = SHARES
    settings = {"shares": SHARES}

    def __init__(self) -> None:
        self.stopped_on: date | None = None

    def __call__(self, context: Context) -> int:
        now = context.timestamp.astimezone(NY)
        position = context.portfolio.positions["spy"]
        held = position.quantity

        # Stay flat before noon and after a stop; liquidate at 15:00.
        if not time(12) <= now.time() < time(15) or self.stopped_on == now.date():
            return 0

        latest = context.data["spy"].latest
        assert latest is not None

        # Stop loss takes priority over the normal trading rules.
        if held > 0 and latest.close <= position.average_price - STOP_LOSS:
            self.stopped_on = now.date()
            return 0  # Sell all held shares at the next bar's open.

        today = [
            bar for bar in context.data["spy"].bars
            if isinstance(bar.timestamp, datetime)  # Intraday bars carry datetimes
            and bar.timestamp.astimezone(NY).date() == now.date()
        ]
        low = min(bar.low for bar in today)
        high = max(bar.high for bar in today)
        if high == low:
            return held

        return self.size((latest.close - low) / (high - low), held)

    def size(self, location: float, held: int) -> int:
        """Shares to hold, given the close's position in today's range (0 = low)."""
        if location <= BUY_LEVEL:
            return SHARES
        if location >= SELL_LEVEL:
            return 0
        return held


class ScaledRangeReversion(RangeReversion):
    """Hold more shares the lower the close sits in today's range."""

    max_shares = STEP_SHARES * MAX_STEPS
    settings = {"step_shares": STEP_SHARES, "max_steps": MAX_STEPS}

    def size(self, location: float, held: int) -> int:
        # MAX_STEPS at or below BUY_LEVEL, none at or above SELL_LEVEL, linear between.
        fraction = (SELL_LEVEL - location) / (SELL_LEVEL - BUY_LEVEL)
        wanted = MAX_STEPS * min(1.0, max(0.0, fraction))
        steps = held // STEP_SHARES
        # Move only once the target is a full step away, so a price hovering at a
        # step boundary does not trade back and forth and pay a commission each time.
        if wanted >= steps + 1:
            steps = math.floor(wanted)
        elif wanted <= steps - 1:
            steps = math.ceil(wanted)
        return STEP_SHARES * steps


RULES = {"fixed": RangeReversion, "scaled": ScaledRangeReversion}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true",
                        help="download the bars from IBKR first (requires TWS/Gateway)")
    parser.add_argument("--rule", choices=RULES, default="fixed",
                        help="fixed: all-or-nothing position; scaled: step-sized inventory")
    args = parser.parse_args()
    rule = RULES[args.rule]()
    output = OUTPUT / f"spy-range-reversion-sep2026-{args.rule}"
    if args.download:
        download()
    elif not DATASET.exists():
        parser.error(f"{DATASET} not found; run once with --download (requires TWS)")

    dataset = BarDataset.load(DATASET)
    metadata = dataset.metadata()
    if metadata["symbol"] != "SPY" or metadata["interval"] != "1min":
        raise ValueError("This example requires SPY one-minute bars.")
    first_open = dataset.snapshot()[0].open
    if rule.max_shares * first_open > INITIAL_CASH:
        raise ValueError(f"{rule.max_shares} shares at {first_open:.2f} exceed the initial cash")

    result = simulate(
        {
            "spy": Feed(
                dataset,
                finalized_through=datetime(2026, 9, 30, 16, tzinfo=NY),
                expected_starts=expected_starts(),
            )
        },
        TargetStrategy("spy", rule),
        initial_cash=INITIAL_CASH,
        execution=NextOpen(commission=COMMISSION, slippage_bps=SLIPPAGE_BPS),
        strategy_settings={
            "name": f"spy_intraday_range_reversion_{args.rule}",
            "reference": "regular-session high/low so far",
            "timezone": "America/New_York",
            "entry_start": "12:00",
            "flatten_at": "15:00",
            **rule.settings,
            "buy_level": BUY_LEVEL,
            "sell_level": SELL_LEVEL,
            "stop_loss_dollars_per_share": STOP_LOSS,
            "after_stop": "flat for the rest of the day",
        },
    )

    # Verify the intended execution window and final position.
    for fill in result.fills:
        local_time = fill.timestamp.astimezone(NY).time()
        assert time(12) <= local_time <= time(15)
    assert result.portfolio.positions["spy"].quantity == 0

    result.save(output / "results.json")
    dataset.save(output / "inputs.dataset.json")

    print(json.dumps(result.metrics(), indent=2))
    for fill in result.fills:
        stamp = fill.timestamp.astimezone(NY)
        print(f"{stamp:%Y-%m-%d %H:%M} {fill.side:4} {fill.quantity:3} shares "
              f"@ {fill.price:.4f}")
    for warning in result.warnings:
        print("Assumption:", warning)
    print("Saved to:", output.resolve())


if __name__ == "__main__":
    main()

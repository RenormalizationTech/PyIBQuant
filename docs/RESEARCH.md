# Research, backtesting and simulation API

[Documentation home](README.md) · [Core API](API.md) · [Quick start](QUICKSTART.md)

- [Signals and calculations](#signals-and-calculations)
- [Descriptive studies](#descriptive-studies)
- [Daily equity backtest](#fixed-size-daily-equity-backtest)
- [Intraday option backtest](#fixed-size-intraday-option-backtest)
- [General strategy simulator](#general-strategy-simulator)

All functions here run offline. They do not submit broker orders. For a complete
synthetic example of both equity simulation APIs, run:

```sh
python examples/quickstart_offline.py
```

## Signals and calculations

Import from `pyibquant.research`. Inputs are iterables of finite numeric values
in chronological order. Each function returns a tuple with one element per input.
NaN/infinity raise `ValueError`. These functions do not fetch data or align dates.

| Function | Arguments and behavior | Small example |
|---|---|---|
| `simple_returns(closes)` | Close prices; returns fractional change `current / previous - 1`. First value and values after a zero denominator are `None`. | `simple_returns([100, 110, 99])` → approximately `(None, 0.1, -0.1)` |
| `sma(values, window=20)` | Trailing mean including the current observation. Positive integer window measured in bars; first `window-1` results are `None`. | `sma([1, 2, 3], window=2)` → `(None, 1.5, 2.5)` |
| `above_sma(closes, window=20)` | Boolean long/flat target: close strictly above its current trailing mean. Warmup/equality produce False. | `above_sma([1, 2, 3], window=2)` → `(False, True, True)` |
| `sma_crossover(closes, fast=10, slow=20)` | True while fast mean exceeds slow mean; positive integer windows with `fast < slow`. Warmup/equality produce False. This is a persistent target, not just a crossing event. | `sma_crossover([1, 2, 3], fast=1, slow=2)` → `(False, True, True)` |

```python
from pyibquant.research import above_sma, simple_returns, sma, sma_crossover

closes = [100, 110, 99]
print(simple_returns(closes))
print(sma(closes, window=2))
print(above_sma(closes, window=2))
print(sma_crossover(closes, fast=1, slow=2))
```

To calculate from a saved dataset: `closes = [bar.close for bar in dataset.snapshot()]`.
A signal at index i must use only information available by that candle's close.
Passing it to a next-open simulator does not audit the caller's lookahead.

## Descriptive studies

Import from `pyibquant.studies`. Both functions return JSON-compatible dictionaries
with `settings`, `quality` and descriptive outputs; neither writes files.
Inputs must be nonempty, have `download.complete=True` and strictly positive
closes. Do not relabel incomplete provider downloads merely to pass validation.

### `daily_correlations(inputs: BarDatasetCollection) -> dict`

`inputs` contains compatible daily datasets. Calculates log close returns and a
Pearson matrix. Returns are formed between adjacent **union dates** before
listwise selection, so missing rows cannot silently pair returns over different
periods. No filling, currency conversion or adjustment harmonization occurs.

Inspect `report["returns"]` for the dated return panel and
`report["correlation"]` for `samples`, `excluded_rows`, and nested `matrix`.
Constants or fewer than two usable returns yield `None` correlations. Dates absent
from every source remain unknown without an independent calendar.

```python
from pyibquant import BarDatasetCollection
from pyibquant.studies import daily_correlations

# Offline; requires the collection saved by the Market.datasets example in API.md.
inputs = BarDatasetCollection.load("charts/inputs.collection.json")
report = daily_correlations(inputs)
print(report["correlation"]["samples"])
print(report["correlation"]["matrix"])
```

### `intraday_scaling(dataset, *, lags=(1, 2, 4, 8), session_timezone=None) -> dict`

| Argument | Meaning |
|---|---|
| `dataset: BarDataset` | One fixed-interval intraday dataset; daily bars are rejected. |
| `lags: Iterable[int]` | Nonempty, distinct positive integer delays in **bars**, not minutes. On 5min data, lag 2 spans ten minutes. |
| `session_timezone: str \| None` | IANA zone such as `America/New_York` for the within-date filter. Defaults to recorded source timezone; explicitly supply it if unknown. |

Only uninterrupted grids within the same local date contribute. Gaps/date changes
break a segment. Returns `increments` (dated log increments) and `moments` (per-lag
sample/exclusion counts, mean absolute and mean squared increments). Samples can
overlap and are dependent. No fitted exponent, Hurst estimate or multifractality
claim is provided. Local dates do not replace an exchange session calendar.

```python
from pyibquant import BarDataset, Market
from pyibquant.studies import intraday_scaling

with Market.ibkr() as market:  # Acquire once; study itself is offline.
    bars = market.bars("AAPL", interval="5min",
                       start="2026-01-05T09:30:00-05:00",
                       end="2026-01-05T11:00:00-05:00")
    dataset = BarDataset.from_series(bars)
report = intraday_scaling(dataset, lags=(1, 2), session_timezone="America/New_York")
print(report["moments"])
```

## Fixed-size daily equity backtest

Import: `from pyibquant.backtest import backtest_equity`.

```text
backtest_equity(dataset, signals, *, finalized_through, initial_cash=10000,
                shares=1, commission=0, slippage_bps=0, expected_dates=None)
```

| Argument | Meaning |
|---|---|
| `dataset: BarDataset` | At least two daily regular-hours equity bars. Must be a successfully completed fixed range, split-adjusted TRADES, multiplier 1, consistent positive OHLC and nonnegative known volume. |
| `signals: Iterable[bool]` | Exactly one actual boolean per bar. True targets `shares` long, False targets flat. Repeated targets do not rebalance. |
| `finalized_through: date` | Required caller assertion covering the final date. A datetime is rejected. |
| `initial_cash: float` | Positive finite starting cash in the dataset's currency. Default 10000. |
| `shares: int` | Positive whole number held when long, not cash amount or portfolio weight. |
| `commission: float` | Nonnegative flat cash fee **per fill**, not per share. |
| `slippage_bps: float` | Nonnegative adverse basis points, below 10000; 10 bps = 0.1%. Buys increase/sells decrease the next open. |
| `expected_dates: Iterable[date] \| None` | Optional independent calendar of all expected dates; mismatch raises ValueError. Omission leaves coverage unverified. |

Signal i first acts at supplied open i+1. An unchanged target does nothing;
insufficient cash rejects the order and later targets may retry. No borrowing,
shorts, forced final liquidation, dividends, interest or volume/liquidity model.
Prices remain split-adjusted research prices, not reconstructed nominal executions.

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.backtest import backtest_equity
from pyibquant.research import above_sma

# Offline; use the IBKR dataset from the quick start, not the minimal demo file.
dataset = BarDataset.load("charts/aapl.bars.json")
signals = above_sma([bar.close for bar in dataset.snapshot()], window=2)
result = backtest_equity(dataset, signals, finalized_through=date(2026, 1, 9),
                         shares=1, commission=1, slippage_bps=5)
print(result.metrics())
result.save("charts/equity-result.json")
```

## Fixed-size intraday option backtest

Import: `from pyibquant.option_backtest import backtest_option`.

```text
backtest_option(dataset, signals, *, fill_model, finalized_through,
                initial_cash=10000, contracts=1, commission_per_contract=0,
                slippage_bps=0, expected_times=None)
```

| Argument | Meaning |
|---|---|
| `dataset` | Complete fixed-range USD option intraday `BarDataset`; exact resolved contract identity and positive multiplier required. Positive consistent OHLC, nonnegative volume when available, no overlapping bars. All bars must precede expiry day in New York. |
| `signals` | Exactly one boolean long/flat target per bar, acting at the next supplied open. |
| `fill_model` | Required literal `"next_bar_open"`, explicitly acknowledging synthetic fills. |
| `finalized_through` | Required aware datetime; inclusive **bar-start** finality assertion covering every row. |
| `initial_cash` | Positive finite starting USD cash. |
| `contracts` | Positive whole contracts held when long. Premium cash flows multiply by the actual resolved contract multiplier. |
| `commission_per_contract` | Nonnegative USD fee per contract per side (entry and exit separately). |
| `slippage_bps` | Adverse basis points on premium, nonnegative and below 10000. |
| `expected_times` | Optional iterable of aware expected bar starts for a coverage audit. |

Accepts TRADES/MIDPOINT as descriptive synthetic sources. BID/ASK require a
separate spread model and are rejected. No shorts, scaling, forced final sale,
exercise/assignment or expiry settlement. Historical bars do not establish
executable bid/ask prices or historical Greeks.

```python
from datetime import UTC, datetime
from pyibquant import BarDataset
from pyibquant.option_backtest import backtest_option

# Offline; first save a selected option's bounded history using Market.bars().
# This file is not produced by the equity quick start.
dataset = BarDataset.load("charts/selected-option.bars.json")
last_start = dataset.snapshot()[-1].timestamp
assert isinstance(last_start, datetime)
result = backtest_option(
    dataset, [True] * len(dataset), fill_model="next_bar_open",
    finalized_through=last_start.astimezone(UTC),  # Assert only after verifying finality.
    contracts=1, commission_per_contract=0.65, slippage_bps=10,
)
print(result.metrics())
```

For acquisition, see [options](API.md#options-and-quotes) and
[manual option checks](MANUAL_TESTING.md#selected-option-history).

### Backtest result objects

Both `BacktestResult` and `OptionBacktestResult` expose immutable `fills`, `trades`,
`rejections`, `equity_curve`, and `warnings` (plus settings/provenance in exports).
The equity result uses shares/dates; the option result uses contracts/intraday
times and a multiplier. Obtain these from their backtest function.

| Method | Return and use |
|---|---|
| `metrics() -> dict` | Cash/equity, fractional total return and drawdown, realized/unrealized net P&L, fees, slippage, fills and ending position. Undefined statistics such as win rate with no closed trades may be None. `print(result.metrics())`. |
| `to_dict() -> dict` | JSON-compatible full results, inputs/settings and logs. `document = result.to_dict()`. |
| `save(path: str \| Path) -> Path` | Atomically save result JSON, creating parents. `result.save("charts/result.json")`. |

A fill records signal/execution times, side, size, price, commission, slippage and
cash after execution. A trade pairs entry/exit and reports net P&L; open holdings
are not a closed trade. Rejections retain attempted side/time and reason. Equity
curve points contain time, cash, position/mark, equity, period return and drawdown.
A return of `0.02` is 2%; a drawdown of `-0.1` is a 10% loss from the running peak.

## General strategy simulator

Import from `pyibquant.simulation`. Use it for multiple feeds sharing cash,
variable quantities and custom callbacks. The fixed-size functions above are
simpler when all you need is one long/flat target.

### `Feed(dataset, finalized_through, expected_starts=None)`

`dataset` is a completed fixed-range frozen USD input. Equities require
split-adjusted TRADES and multiplier 1; options require exact identity,
intraday TRADES/MIDPOINT and positive multiplier. Supports daily and the fixed
intraday intervals; weekly/yearly feeds are rejected. Inputs must be nonempty
with valid OHLC and no overlapping candles. Option expiry/lifecycle is unsupported.

`finalized_through` is a date for daily feeds and aware datetime for intraday.
Intraday bars must **finish** by that time (start + interval). Optional
`expected_starts` is an iterable frozen to a tuple; exact calendar mismatch fails.
You cannot mix daily/intraday feeds or duplicate instrument identities under aliases.

### `NextOpen(commission=0, commission_per_unit=0, slippage_bps=0)`

Default synthetic execution model. Finite nonnegative fees in USD: flat
`commission` per order **plus** `quantity * commission_per_unit`. Quantity means
shares for equities, contracts for options. Slippage is adverse premium/share
basis points, below 10000; option notional also uses the multiplier.

`settings() -> Mapping` exports model assumptions. The engine calls
`execute(order, instrument, opening, portfolio) -> Execution`; callers normally
pass the model to `simulate()` rather than invoke this method directly.

### `TargetStrategy(instrument, target, *, decision_feed=None)`

`instrument` is a key in the feeds mapping, such as `apple` (not necessarily a
ticker). `target` is a callable receiving `Context` and returning a nonnegative
integer desired total quantity, not a quantity change. `decision_feed` defaults
to instrument; only updates on that feed trigger the target callback. The adapter
cancels its own pending instrument orders before recalculating the quantity delta.
Its `on_bar(context)` implements the strategy protocol.

### `simulate(feeds, strategy, *, initial_cash=10000, execution=None, strategy_settings=None)`

Returns `SimulationResult`. `feeds` is a nonempty mapping of unique labels to
`Feed`s. `strategy` implements `on_bar(context)`. `initial_cash` is positive USD;
`execution=None` means `NextOpen()`. `strategy_settings` is a JSON-serializable
mapping recorded as provenance; it does not configure your callback automatically.

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate

# Offline; requires the IBKR dataset from the quick start.
dataset = BarDataset.load("charts/aapl.bars.json")
result = simulate(
    {"apple": Feed(dataset, finalized_through=date(2026, 1, 9))},
    TargetStrategy("apple", lambda context: 1),
    initial_cash=10000, execution=NextOpen(commission_per_unit=0.01),
    strategy_settings={"name": "hold_one"},
)
print(result.metrics())
result.save("charts/simulation.json")
```

The callback sees completed bars only. Decisions can fill at the next eligible
supplied open, including an open at the same instant that the previous bar
completes. Cash is shared, orders execute in submission order, and there is no
cash reservation or automatic sell-first ordering. Long-only whole quantities,
market orders and full-fill-or-defer execution are supported. Unfilled orders
cancel at the end; filled positions remain marked, without forced exit.

### `Context`: variables available inside `on_bar`

| Attribute | Meaning |
|---|---|
| `timestamp` | Current aware simulator event time. Daily clocks are synthetic UTC days. |
| `updated` | Tuple of feed keys whose completed bars became available now. |
| `data` | Mapping of feed key to `DataView`. `.bars` is completed history; `.latest` is last Bar or None; `.available_at` and `.age` expose staleness. |
| `instruments` | Mapping of keys to resolved `Instrument`: key, symbol, asset_type, currency, multiplier, interval, data_type, instrument_id, optional expiry. |
| `portfolio` | Current cash and positions by key. See properties below. |
| `orders`, `fills` | Immutable order/fill history available so far. |

`context.submit(instrument, side, quantity, *, order_type="market", tag=None) -> int`:
feed-key instrument, lowercase `buy`/`sell`, positive whole quantity,
market-only order type, optional user label. Returns simulator order ID.

`context.cancel(order_id) -> bool`: cancel a pending simulator order by integer
ID; returns whether canceled. Both methods work only during the callback.

```python
# Use this object as the strategy argument to simulate(feeds, BuyOnce()).
class BuyOnce:
    def __init__(self):
        self.sent = False

    def on_bar(self, context):
        if "apple" in context.updated and not self.sent:
            order_id = context.submit("apple", "buy", 1, tag="first-entry")
            print("Submitted simulator order", order_id)
            self.sent = True
```

`portfolio.positions[key]` is a `Position` with `quantity`, `average_price`,
`cost_basis` (includes unallocated entry fees), `realized_pnl`, `mark`, `marked_at`
and `multiplier`. `.market_value` and `.unrealized_pnl` are derived cash values.
`Portfolio.equity`, `.realized_pnl`, `.unrealized_pnl` aggregate positions and cash.
Marks can be stale between feed updates; inspect mark times and DataView age.

### Custom execution models

Implement `execute(order, instrument, opening, portfolio)` and `settings()`.
The engine supplies an `Order` (ID, instrument key, lowercase side, quantity,
submitted_at, status, updated_at, reason, tag), an `Instrument`, an `OpenEvent`
(`timestamp`, `price`, no future candle fields), and current `Portfolio`.
Return `Execution(price, commission=0)` for a full fill, or `None` to defer.
Price must be positive finite, commission nonnegative finite. Invalid output or
model exceptions fail the run. `settings()` must return serializable assumptions.

```python
from pyibquant.simulation import Execution

class NoCostOpen:
    def execute(self, order, instrument, opening, portfolio):
        return Execution(opening.price, commission=0)

    def settings(self):
        return {"model": "no_cost_open"}
```

### `SimulationResult`

Fields: `initial_cash`, `currency`, `orders`, `fills`, `equity_curve`, final
`portfolio`, `warnings`. Methods `metrics()`, `to_dict()` and `save(path)` follow
the result API above. Metrics include rejected orders and filled orders;
equity points distinguish `close` and `open` phases, so do not assume one point
per input candle. Logs retain fingerprints, assertions, strategy/model settings,
order statuses and costs. These results model assumptions, not broker executions.

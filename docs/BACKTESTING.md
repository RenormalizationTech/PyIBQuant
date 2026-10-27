# Backtesting guide

[Documentation home](README.md) · [Research API](RESEARCH.md) ·
[Strategy validation checklist](STRATEGY_LAB.md)

This guide shows how to backtest the built-in strategies, read the results and
write your own rules. All backtests run offline on saved data and never send
orders. For exact argument rules, see the [research reference](RESEARCH.md).

- [Which data can be backtested](#which-data-can-be-backtested)
- [1. Run a first backtest offline](#1-run-a-first-backtest-offline)
- [2. Save real daily data from IBKR](#2-save-real-daily-data-from-ibkr)
- [3. Built-in strategies](#3-built-in-strategies)
- [4. Settings shared by every run](#4-settings-shared-by-every-run)
- [5. Read the results](#5-read-the-results)
- [6. Compare several strategies in Python](#6-compare-several-strategies-in-python)
- [7. Write your own strategy](#7-write-your-own-strategy)
- [8. Worked example: intraday SPY range reversion](#8-worked-example-intraday-spy-range-reversion)
- [9. What a backtest does not model](#9-what-a-backtest-does-not-model)

## Which data can be backtested

| Data | Backtest? | Notes |
|---|---|---|
| Synthetic demo from `examples/quickstart_offline.py` | Yes | Five invented daily bars; good for learning the tools, meaningless as results |
| IBKR historical bars saved as a `BarDataset` | Yes | Requires the official SDK and logged-in TWS/Gateway once, to download |
| Yahoo Finance bars | No | Currently rejected (dividend-adjusted, completeness unknown); see the [Yahoo guide](YAHOO.md#what-yahoo-supports-in-this-package) |

You can calculate moving averages on Yahoo closes, but a real-data backtest
currently needs an IBKR download.

## 1. Run a first backtest offline

**Offline.** Create the synthetic dataset, then backtest it from the command line:

```sh
python examples/quickstart_offline.py
python examples/backtest_equity.py charts/quickstart/demo.bars.json --strategy above-sma --window 2 --finalized-through 2026-01-09 --initial-cash 1000 --output-dir charts/backtest/demo-sma2
```

The run prints metrics and saves CSV logs under `charts/backtest/demo-sma2/`.
Open `fills.csv`: the close on Jan 6 is above its 2-day average, so the strategy
buys at the Jan 7 open (104). The close on Jan 7 is below it, so it sells at the
Jan 8 open (101). Final equity is 997 from 1000. A signal always acts at the
**next** bar's open, never at the close that produced it.

## 2. Save real daily data from IBKR

Set up the SDK and a read-only paper TWS connection as described in the
[quick start](QUICKSTART.md#4-connect-to-ibkr-for-a-small-historical-request).

**IBKR data; no orders.** Download a fixed past period once and save it:

```python
from pyibquant import BarDataset, Market

with Market.ibkr(client_id=72) as market:
    series = market.bars("AAPL", interval="1d", start="2024-01-01", end="2026-10-01")
    if len(series) < 2 or series.download_complete is not True:
        raise RuntimeError("Download incomplete; inspect permissions and bounds")
    dataset = BarDataset.from_series(series)
    dataset.save("charts/aapl-daily.bars.json")
    print(dataset.describe())
```

The `end` date is exclusive, so the last bar is on or before 2026-09-30. Every
command below reuses this file without connecting to IBKR. Change the symbol and
dates as you like; use a period that has fully ended.

## 3. Built-in strategies

Each strategy is long/flat: it holds a fixed size when its rule is true and
nothing otherwise. No built-in strategy shorts.

| Strategy | Rule (at each bar's close) | Command-line script | Options |
|---|---|---|---|
| Above SMA | Long while the close is strictly above its N-bar simple moving average | `backtest_equity.py --strategy above-sma` | `--window N` (default 20) |
| SMA crossover | Long while the fast SMA is above the slow SMA | `backtest_equity.py --strategy sma-cross` | `--fast` (default 10), `--slow` (default 20); fast must be smaller |
| Above SMA, variable size | Same rule as Above SMA, with a chosen quantity and stale-data exit | `backtest_strategy.py` | `--window`, `--quantity` (default 2), `--max-signal-age-minutes` |
| Option, own price | Above SMA or crossover on a selected option's intraday bars | `backtest_option.py` | Same strategy flags, plus `--contracts` and a required `--fill-model next_bar_open` |
| Option, driven by underlying | Above SMA on the stock's bars; trades a selected option | `backtest_strategy.py --option-dataset FILE` | Both files must be intraday |

During warmup (fewer bars than the window) the rule is false, so the strategy
stays flat.

**Above SMA, 20 days:**

```sh
python examples/backtest_equity.py charts/aapl-daily.bars.json --strategy above-sma --window 20 --finalized-through 2026-09-30 --shares 10 --commission 1 --slippage-bps 5 --output-dir charts/backtest/aapl-sma20
```

**SMA crossover, 10/40 days:**

```sh
python examples/backtest_equity.py charts/aapl-daily.bars.json --strategy sma-cross --fast 10 --slow 40 --finalized-through 2026-09-30 --shares 10 --commission 1 --slippage-bps 5 --output-dir charts/backtest/aapl-cross10-40
```

**Above SMA with the general simulator** (per-share instead of per-order fees):

```sh
python examples/backtest_strategy.py charts/aapl-daily.bars.json --window 20 --quantity 10 --finalized-through 2026-09-30 --commission-per-unit 0.01 --slippage-bps 5 --output-dir charts/backtest/aapl-sim-sma20
```

Option backtests need a separately saved option history; follow the
[manual option example](MANUAL_TESTING.md#selected-option-history), then run
`python examples/backtest_option.py --help`. Option results use TRADES/MIDPOINT
bars, not executable bid/ask prices, and expiry day is unsupported.

## 4. Settings shared by every run

| Flag | Meaning | Default |
|---|---|---|
| `--finalized-through` | Required. Your statement that every bar up to this date is final. Use the last bar's date only after that session has closed. Intraday option runs need a timezone-aware timestamp. | none |
| `--initial-cash` | Starting cash in USD | 10000 |
| `--shares` / `--quantity` / `--contracts` | Size held while long: whole shares or contracts, not dollars | 1 / 2 / 1 |
| `--commission` | Flat fee per fill, not per share (`backtest_equity.py`) | 0 |
| `--commission-per-unit` / `--commission-per-contract` | Fee per share or contract | 0 |
| `--slippage-bps` | Adverse price move per fill in basis points; 5 = 0.05% worse | 0 |
| `--calendar` | Optional file of expected trading dates, one per line, to detect missing bars | unchecked |
| `--output-dir` | Folder for the saved results | under `charts/` |

Costs are your assumptions, not IBKR's fees. Run each comparison with the same
cash, size and costs, then repeat your favorite with higher costs.

## 5. Read the results

This section assumes you ran the 20-day above-SMA command from step 3, which saved
its results to `charts/backtest/aapl-sma20/`. Replace that folder with your own
`--output-dir` for other runs.

The examples below show real output from the synthetic demo, so you can reproduce
them exactly. Rerun the step 1 command with `--commission 1 --slippage-bps 5` added.
Your AAPL numbers will differ, but the layout is the same.

### The summary printed at the end of a run

`backtest_equity.py` prints the metrics, the output folder and its assumptions:

```text
{
  "initial_cash": 1000.0,
  "final_cash": 994.8975,
  "final_equity": 994.8975,
  "ending_shares": 0,
  "total_return": -0.00510250000000001,
  "max_drawdown": -0.00510250000000001,
  "realized_net_pnl": -5.102499999999992,
  "unrealized_net_pnl": 0.0,
  "commissions": 2.0,
  "slippage_cost": 0.10249999999999204,
  "completed_trades": 1,
  "rejected_orders": 0,
  "win_rate": 0.0
}
Saved inputs, strategy, results and CSV logs to .../charts/backtest/demo-sma2
Assumption: Synthetic tutorial prices; not historical market data.
...
```

| Metric | Meaning |
|---|---|
| `final_equity` | Cash plus open holdings marked at the last close |
| `total_return` | Fraction of initial cash: `-0.0051` is −0.51%, `0.05` is +5% |
| `max_drawdown` | Worst fall from a previous equity peak: `-0.1` is −10% |
| `realized_net_pnl` / `unrealized_net_pnl` | Profit after costs on closed trades / on the position still open |
| `commissions`, `slippage_cost` | Total costs paid; both are already included in the P&L |
| `completed_trades`, `win_rate` | Closed round trips and the fraction that made money (`None` when there are none) |
| `ending_shares` | Position still held; it is **not** sold automatically at the end |
| `rejected_orders` | Orders skipped, for example because cash ran out |

Two identities always hold, and they make a quick sanity check:
`final_equity = initial_cash + realized_net_pnl + unrealized_net_pnl` and
`total_return = final_equity / initial_cash - 1`.

Numbers are stored unrounded, so values such as `-5.102499999999992` are normal
floating-point output.

### See the summary again later

Everything is saved, so you do not need to rerun the backtest:

```sh
ls charts/backtest/aapl-sma20
python -c "import json; print(json.dumps(json.load(open('charts/backtest/aapl-sma20/results.json'))['metrics'], indent=2))"
cat charts/backtest/aapl-sma20/strategy.json
```

| File | Contents |
|---|---|
| `results.json` | Metrics, settings, signals, all logs below, input fingerprint and assumptions |
| `fills.csv` | One row per buy or sell |
| `trades.csv` | One row per completed entry/exit pair |
| `equity_curve.csv` | One row per bar: cash, shares, close, equity, return and drawdown |
| `rejections.csv` | Orders refused, usually for insufficient cash; only a header means none |
| `strategy.json` | The strategy name and window, or fast/slow |
| `inputs.dataset.json` | An exact copy of the input data, so the run can be reproduced |

### Read the trade logs

The CSV files open in any spreadsheet program (`open charts/backtest/aapl-sma20/trades.csv`
on macOS). To view one in the terminal as aligned columns:

```sh
column -s, -t < charts/backtest/aapl-sma20/fills.csv | less -S
```

The demo's `fills.csv`:

```text
signal_date,execution_date,side,shares,price,commission,slippage_cost,cash_after
2026-01-06,2026-01-07,buy,1,104.05199999999999,1.0,0.0519999999999925,894.948
2026-01-07,2026-01-08,sell,1,100.9495,1.0,0.050499999999999545,994.8975
```

- `signal_date` is the close that produced the decision; `execution_date` is the
  next bar, whose open is used.
- `price` already includes slippage. The Jan 7 open was 104; 5 bps worse for a
  buy is `104 × 1.0005 = 104.052`. The Jan 8 sell is `101 × 0.9995 = 100.9495`.
- `cash_after` subtracts the price and the commission:
  `1000 − 104.052 − 1 = 894.948`.

The demo's `trades.csv` pairs those fills:

```text
entry_date,exit_date,shares,entry_price,exit_price,commissions,net_pnl,return_fraction
2026-01-07,2026-01-08,1,104.05199999999999,100.9495,2.0,-5.102499999999992,-0.04857118379469208
```

`net_pnl` is `(100.9495 − 104.052) × 1 share − 2.0 commissions = −5.1025`.
`return_fraction` divides it by the entry cost including its commission:
`−5.1025 / 105.052 ≈ −4.86%`. A position still open at the end appears in `fills.csv` but not in
`trades.csv`.

`equity_curve.csv` has one row per bar. To see how equity moved over time,
chart its `equity` column against `timestamp` in a spreadsheet.

### Explore the results in Python

**Offline.** The standard library is enough to load and summarize a run:

```python
import json
from pathlib import Path

folder = Path("charts/backtest/aapl-sma20")
results = json.loads((folder / "results.json").read_text())

for name, value in results["metrics"].items():
    print(f"{name:20} {value}")

trades = results["trades"]
wins = [trade for trade in trades if trade["net_pnl"] > 0]
print(f"\n{len(trades)} closed trades, {len(wins)} profitable")
for trade in sorted(trades, key=lambda trade: trade["net_pnl"])[:3]:
    print(f"Worst: {trade['entry_date']} -> {trade['exit_date']} "
          f"net {trade['net_pnl']:.2f} ({trade['return_fraction']:+.2%})")

curve = results["equity_curve"]
low = min(curve, key=lambda point: point["drawdown"])
print(f"Deepest drawdown {low['drawdown']:.2%} on {low['timestamp']}")
print(f"Rejected orders: {len(results['rejections'])}")
for warning in results["warnings"]:
    print("Assumption:", warning)
```

With pandas (`python -m pip install -e '.[pandas]'`) you can slice the CSVs further:

```python
import pandas as pd

folder = "charts/backtest/aapl-sma20"
curve = pd.read_csv(f"{folder}/equity_curve.csv", parse_dates=["timestamp"],
                    index_col="timestamp")
trades = pd.read_csv(f"{folder}/trades.csv", parse_dates=["entry_date", "exit_date"])

monthly = curve["equity"].resample("ME").last()
print(monthly.pct_change().dropna().round(4))                   # Monthly returns
print((trades["exit_date"] - trades["entry_date"]).dt.days.describe())  # Holding days
print(f"Days in the market: {(curve['shares'] > 0).mean():.0%}")
```

### Check before trusting a number

- Verify one buy, one sell and one commission by hand, as above.
- `rejections.csv` should be empty, or you should understand every row.
- If `ending_shares` is not zero, part of the result is an unsold position.
- Read the printed assumptions; `calendar_checked: false` in `results.json`
  means missing bars were not detected.
- Compare against a buy-and-hold baseline (step 6) with the same costs.

`backtest_strategy.py` saves only `results.json` and copies of its inputs. Its
metrics report `filled_orders` instead of `completed_trades`/`win_rate`, and its
file contains `orders`, `fills`, `portfolio` and `equity_curve`.

## 6. Compare several strategies in Python

**Offline; requires `charts/aapl-daily.bars.json` from step 2.**

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.backtest import backtest_equity
from pyibquant.research import above_sma, sma_crossover

dataset = BarDataset.load("charts/aapl-daily.bars.json")
closes = [bar.close for bar in dataset.snapshot()]

candidates = {
    "above_sma_10": above_sma(closes, window=10),
    "above_sma_20": above_sma(closes, window=20),
    "above_sma_50": above_sma(closes, window=50),
    "cross_10_40": sma_crossover(closes, fast=10, slow=40),
    "always_long": [True] * len(closes),  # Buy-and-hold baseline
}
for name, signals in candidates.items():
    result = backtest_equity(dataset, signals, finalized_through=date(2026, 9, 30),
                             shares=10, commission=1, slippage_bps=5)
    m = result.metrics()
    print(f"{name:13} equity={m['final_equity']:10.2f} return={m['total_return']:+.2%} "
          f"drawdown={m['max_drawdown']:.2%} trades={m['completed_trades']}")
```

Always include a simple baseline such as `always_long`. If you tune parameters
on this data, the best number is optimistic. Keep a later period aside and test
your final choice on it once; the [validation checklist](STRATEGY_LAB.md#3-acquire-fixed-training-and-holdout-data)
shows how.

## 7. Write your own strategy

Pick the simplest of three levels that fits your idea. Each example is a complete
script that runs on its own.

Level 1 uses `backtest_equity()`; Levels 2 and 3 use the general simulator,
`simulate()`. Both fill at the next bar's open, are long-only and never sell
automatically at the end. For the same rule and costs they produce the same
equity. They differ in what they let you express:

| | `backtest_equity()` | `simulate()` |
|---|---|---|
| Your rule is | A precomputed list of booleans | A function or class called at each bar |
| Position size | Fixed `shares` or nothing | Any whole quantity, or your own orders |
| Instruments | One daily equity dataset | Several equity/option feeds sharing USD cash, daily or intraday |
| Lookahead | Not checked; your list can accidentally use future closes | Your code only sees completed bars |
| Fees | Flat per fill | Flat per order plus per share/contract, or a custom model |
| Results | `trades`, `win_rate`, `ending_shares` | `orders` with statuses, `fills`, final `portfolio` |

Start with `backtest_equity()` for "hold N shares or nothing" ideas and parameter
sweeps; move to `simulate()` for sizing, stops, several instruments or intraday data.

**Offline; requires `charts/aapl-daily.bars.json` from step 2.** To try them
without IBKR data, use `charts/quickstart/demo.bars.json` with
`date(2026, 1, 9)` and a window of 2 instead.

### Level 1: a list of signals

Build one `True`/`False` per bar and pass it to `backtest_equity`. This example
holds after any down day:

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.backtest import backtest_equity
from pyibquant.research import simple_returns

dataset = BarDataset.load("charts/aapl-daily.bars.json")
closes = [bar.close for bar in dataset.snapshot()]
returns = simple_returns(closes)
signals = [change is not None and change < 0 for change in returns]
result = backtest_equity(dataset, signals, finalized_through=date(2026, 9, 30), shares=10)
print(result.metrics())
```

Signal `i` must use only bars `0..i`. The backtest does not check for lookahead;
a signal built from future closes produces impossible results without an error.

API reference: [`backtest_equity()` arguments and data requirements](RESEARCH.md#fixed-size-daily-equity-backtest)
and [result objects](RESEARCH.md#backtest-result-objects).

### Level 2: a target quantity

`TargetStrategy` calls your function at each bar with only the completed history.
Return the total number of shares you want to hold; the simulator buys or sells
the difference at the next open:

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.research import sma
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate

dataset = BarDataset.load("charts/aapl-daily.bars.json")

def target(context):
    closes = [bar.close for bar in context.data["stock"].bars]
    if len(closes) < 20:
        return 0
    return 10 if closes[-1] > sma(closes, window=20)[-1] else 0

result = simulate(
    {"stock": Feed(dataset, finalized_through=date(2026, 9, 30))},
    TargetStrategy("stock", target),
    initial_cash=10000,
    execution=NextOpen(commission=1, slippage_bps=5),
    strategy_settings={"name": "above_sma", "window": 20, "quantity": 10},
)
print(result.metrics())
result.save("charts/backtest/custom-target.json")
```

`"stock"` is any label you choose for the feed. `strategy_settings` is only
recorded in the results; it does not configure your function.

API reference: [`simulate()`, `TargetStrategy` and the simulator rules](RESEARCH.md#general-strategy-simulator),
[`Feed`](RESEARCH.md#feeddataset-finalized_through-expected_startsnone),
[`NextOpen` costs](RESEARCH.md#nextopencommission0-commission_per_unit0-slippage_bps0)
and [`SimulationResult`](RESEARCH.md#simulationresult).

### Level 3: submit orders yourself

For stops, staged entries or several instruments, write a class with
`on_bar(context)` and call `context.submit()`:

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.simulation import Feed, simulate

dataset = BarDataset.load("charts/aapl-daily.bars.json")

class StopAfterLoss:
    def __init__(self, max_loss):
        self.max_loss = max_loss
        self.stopped = False

    def on_bar(self, context):
        position = context.portfolio.positions.get("stock")
        held = 0 if position is None else position.quantity
        if self.stopped:
            return
        if held == 0 and not context.orders:
            context.submit("stock", "buy", 10, tag="entry")
        elif held and position.unrealized_pnl < -self.max_loss:
            context.submit("stock", "sell", held, tag="stop")
            self.stopped = True

result = simulate({"stock": Feed(dataset, finalized_through=date(2026, 9, 30))},
                  StopAfterLoss(max_loss=200), initial_cash=10000,
                  strategy_settings={"name": "stop_after_loss", "max_loss": 200})
print(result.metrics())
print([(fill.side, fill.price) for fill in result.fills])
```

Pass several feeds to `simulate()` to trade more than one instrument from shared
cash.

API reference: [everything available in `context`](RESEARCH.md#context-variables-available-inside-on_bar),
including `submit()`, `cancel()` and portfolio fields, and
[custom execution models](RESEARCH.md#custom-execution-models).

Custom strategies run offline only. The paper runners currently execute just the
built-in above-SMA rules; a custom rule needs new code before paper trading.

For a complete intraday strategy built from these pieces, see the
[worked example](#8-worked-example-intraday-spy-range-reversion) below.

## 8. Worked example: intraday SPY range reversion

The script [`examples/backtest_spy_range_reversion.py`](https://github.com/RenormalizationTech/PyIBQuant/blob/main/examples/backtest_spy_range_reversion.py)
backtests a one-minute SPY strategy over September 2026. Unlike the daily
examples above, it uses trading-time windows, a stop loss, a strategy that keeps
state between bars and a check for missing bars. It needs IBKR data once; every
backtest after that runs offline.

### The two rules

Both rules share this behavior, in New York time:

- Flat before 12:00; everything is sold by 15:00.
- **Location** is where the latest close sits in today's high-low range so far,
  using completed bars only: 0 is the day's low, 1 its high.
- **Stop loss:** if the close falls $1 per share below the average entry price,
  sell everything and stay flat for the rest of that day.

| | `--rule fixed` (default) | `--rule scaled` |
|---|---|---|
| Position | 5 shares or none | 0–6 shares in steps of 2 |
| Buys | At location 0.2 or lower | More as location falls |
| Sells | At location 0.8 or higher | More as location rises |

The scaled rule's target position by location:

| Location | ≤ 0.2 | 0.4 | 0.6 | ≥ 0.8 |
|---|---|---|---|---|
| Shares | 6 | 4 | 2 | 0 |

It only moves once the target is a full step away from the current position, so
a price hovering at a step boundary does not trade back and forth, paying a
commission each time.

> **Is this market making?** No. The scaled rule's inventory curve resembles a
> market maker's, but every trade is a market order filled at the next bar's open,
> so it pays slippage rather than earning the bid/ask spread. Passive limit-order
> fills cannot be backtested honestly from one-minute bars: they would depend on
> queue position and on the order of prices inside each bar, which the bars do
> not record.

### Run it

```sh
python examples/backtest_spy_range_reversion.py --download   # IBKR data, once
python examples/backtest_spy_range_reversion.py              # Fixed rule, offline
python examples/backtest_spy_range_reversion.py --rule scaled
```

The download needs a logged-in TWS or Gateway with read-only API access (see the
[quick start](QUICKSTART.md#4-connect-to-ibkr-for-a-small-historical-request)),
uses client ID 72 and sends no orders. It saves about 8,000 one-minute bars to
`charts/spy-sep2026-1min.bars.json`. Without `--download`, the script never
connects to IBKR.

Each run saves `results.json` and a copy of its input to
`charts/backtest/spy-range-reversion-sep2026-fixed/` or `...-scaled/`, then prints:

```text
{ ...metrics, as in section 5... }
2026-09-DD HH:MM buy    5 shares @ <price>
2026-09-DD HH:MM sell   5 shares @ <price>
...
Assumption: <one line per modeling assumption>
Saved to: <output folder>
```

To use another month, change the download dates, the trading calendar in
`expected_starts()` and `finalized_through` together; otherwise the missing-bar
check stops the run.

### Compare the two rules

**Offline; run both rules first.**

```python
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

for rule in ("fixed", "scaled"):
    folder = Path(f"charts/backtest/spy-range-reversion-sep2026-{rule}")
    results = json.loads((folder / "results.json").read_text())
    m = results["metrics"]
    costs = m["commissions"] + m["slippage_cost"]
    before_costs = m["final_equity"] - results["initial_cash"] + costs
    days = {datetime.fromisoformat(fill["timestamp"]).astimezone(NY).date()
            for fill in results["fills"]}
    print(f"{rule:6} return={m['total_return']:+.2%} drawdown={m['max_drawdown']:.2%} "
          f"fills={m['filled_orders']:3} days={len(days):2} "
          f"before_costs={before_costs:+8.2f} costs={costs:7.2f}")
```

`before_costs` is the profit the rule would have made with free trading. If it is
negative, the idea itself lost money; if it is positive but smaller than `costs`,
the rule trades too often for its edge. Either way, refining parameters on the
same month will mostly fit noise; test your final choice once on a different
month, as in the [validation checklist](STRATEGY_LAB.md#6-evaluate-the-held-out-period-once).

### Limits of this example

- Fills use the next one-minute open plus 1 basis point of assumed slippage; the
  real bid/ask spread and queue are not modeled.
- A stop sells at the next open, not at the stop price; a fast drop fills lower.
- One month of one symbol is a very small sample.
- Custom rules like these cannot run in the paper runners yet.

## 9. What a backtest does not model

- Fills happen at the next bar's open plus your slippage; spreads, volume and
  liquidity are ignored.
- Prices are split-adjusted; dividends, interest, taxes and borrowing are excluded.
- Long-only, whole shares or contracts; a buy without enough cash is rejected.
- Any open position is valued at the last close, not sold.
- A good historical result does not predict future returns.

When a strategy looks interesting, work through the
[strategy validation checklist](STRATEGY_LAB.md) before any paper run.

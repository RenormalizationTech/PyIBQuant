# Strategy validation checklist: from first experiment to paper trading

[Documentation home](README.md) · [Backtesting guide](BACKTESTING.md) ·
[Research API](RESEARCH.md) · [Paper operating guide](WORKFLOWS.md)

New to backtesting? Start with the [backtesting guide](BACKTESTING.md), which
explains the built-in strategies, result files and custom rules. Use this
checklist once you want to validate an idea carefully, from verified accounting
through a held-out test to a bounded paper run.

Work through these tasks in order. Each has a concrete output and a completion
check. This is a software-testing sequence, not a recommended investment strategy.
Symbols, costs and caps are examples; choose your own experimental assumptions.

The offline simulator accepts custom strategy callbacks. The paper runners
currently implement above-SMA equities and above/below-SMA selected options;
arbitrary backtest callbacks cannot yet be passed directly to a paper runner.
A custom paper strategy needs an implementation change, not just a CLI switch.

## 1. Verify the offline accounting

- [ ] Run `python examples/quickstart_offline.py`.
- [ ] Inspect the synthetic CSV/chart, frozen dataset, fills and simulation result
  under `charts/quickstart/`.
- [ ] Trace why the fixed-size backtest buys at 104, sells at 101 and finishes with
  997 cash from 1000 with zero costs.
- [ ] Confirm the general simulator retains one share rather than automatically
  selling at the final close.

**Done when:** you can explain signal time versus execution time and reconcile
cash + marked holdings to final equity. Do not move straight to paper orders if
these synthetic results are surprising.

## 2. Try real data without a broker

- [ ] Follow the [Yahoo guide](YAHOO.md) to chart one stock/ETF and export CSV/JSON.
- [ ] Calculate 10-, 20- and 40-day moving averages on the same closes.
- [ ] Inspect price adjustment, provider warnings and the latest date.

**Done when:** you can reload the saved data offline and explain why the current
Yahoo preview is suitable for inspection/calculations but rejected by the strict
backtests. Do not relabel Yahoo's provenance to bypass those checks.

## 3. Acquire fixed training and holdout data

Install the official SDK and configure read-only TWS access as described in the
[quick start](QUICKSTART.md#4-connect-to-ibkr-for-a-small-historical-request).
The following downloads historical data and saves it; it sends no orders:

```python
from pyibquant import BarDataset, Market

# Illustrative fixed dates, fully in the past. Change both periods deliberately
# if choosing another experiment; preserve non-overlap and record the choice.
periods = {
    "train": ("2025-01-01", "2026-01-01"),
    "holdout": ("2026-01-01", "2026-10-01"),
}
with Market.ibkr(client_id=191) as market:
    for label, (start, end) in periods.items():
        series = market.bars("AAPL", interval="1d", start=start, end=end)
        if len(series) < 2 or series.download_complete is not True:
            raise RuntimeError(f"{label}: no qualifying completed input")
        dataset = BarDataset.from_series(series)
        dataset.save(f"charts/lab/{label}.bars.json")
        print(label, dataset.fingerprint(), dataset.describe())
```

- [ ] Review source, adjustment, multiplier, requested/observed bounds and quality.
- [ ] Assert finality only after verifying the supplied bars are finished. An
  exclusive request end is not a finality certificate.
- [ ] Supply independent expected trading dates if you want a missing-bar audit.

**Done when:** both datasets are saved and their fingerprints/settings are recorded.
A completed download does not establish complete exchange-calendar coverage.
The two periods deliberately start independently: indicators warm up again in
holdout. Record this choice instead of silently borrowing future observations.

## 4. Establish one baseline

Run a 20-day above-SMA long/flat backtest on training data:

```sh
python examples/backtest_equity.py charts/lab/train.bars.json --strategy above-sma --window 20 --finalized-through 2025-12-31 --initial-cash 10000 --shares 1 --commission 1 --slippage-bps 5 --output-dir charts/lab/train-sma20
```

The finality date matches the illustrative training period. The costs here are
hypothetical USD per fill and adverse basis points, not a broker fee estimate.

- [ ] Inspect `results.json`, `fills.csv`, `trades.csv`, `equity_curve.csv`,
  `rejections.csv`, saved inputs and strategy settings.
- [ ] Manually verify one entry, one exit and one commission calculation.
- [ ] Record final equity, fractional return/drawdown, fees, fills, ending position
  and any rejections. Use the same initial cash/position size across comparisons.

**Done when:** the logs explain the result. A high win rate or positive return
alone is not a software correctness check.

## 5. Compare a small predefined set

Before examining the holdout, choose a small set of comparisons, for example:

| Experiment | Relevant CLI arguments | Separate output directory |
|---|---|---|
| Above SMA 10 | `--strategy above-sma --window 10` | `charts/lab/train-sma10` |
| Above SMA 20 | `--strategy above-sma --window 20` | `charts/lab/train-sma20` |
| Above SMA 40 | `--strategy above-sma --window 40` | `charts/lab/train-sma40` |
| SMA crossover | `--strategy sma-cross --fast 10 --slow 40` | `charts/lab/train-cross10-40` |

Reuse the other arguments from task 4. Compare against a simple hold-one baseline
using `TargetStrategy` from the [simulator reference](RESEARCH.md#general-strategy-simulator).
Record the search space and your selection rule; do not repeatedly tune against
holdout results.

- [ ] Repeat a chosen run with zero costs and higher hypothetical costs.
- [ ] Check that costs, rejected buys, warmup and final open holdings explain any
  differences rather than assuming a ranking implies a reliable strategy.

**Done when:** you have a comparison table and a written choice made using only
training results. Keep all runs, including unfavorable outcomes.

## 6. Evaluate the held-out period once

Use the chosen training configuration without changing its parameters. For the
illustrative SMA20 baseline:

```sh
python examples/backtest_equity.py charts/lab/holdout.bars.json --strategy above-sma --window 20 --finalized-through 2026-09-30 --initial-cash 10000 --shares 1 --commission 1 --slippage-bps 5 --output-dir charts/lab/holdout-sma20
```

- [ ] Record holdout performance separately from training.
- [ ] Inspect behavior during losing periods and cases with no trade/rejected buys.
- [ ] If you revise the idea after seeing holdout, label that as a new experiment;
  the already-inspected data is no longer untouched evaluation data.

**Done when:** you can describe both the strategy rule and the limits of the
historical test. Adjusted next-open fills do not model spreads/liquidity or broker
execution, and do not guarantee future results.

## 7. Write a custom offline target

Save a small program under `charts/lab/` (or a separate research project). This
example combines a trailing average and a one-period return filter:

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.research import sma
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate

prices = BarDataset.load("charts/lab/train.bars.json")

def target(context):
    view = context.data["asset"]
    if len(view.bars) < 20:
        return 0
    closes = [bar.close for bar in view.bars]
    average = sma(closes, window=20)[-1]
    change = closes[-1] / closes[-2] - 1
    return 1 if average is not None and closes[-1] > average and change > 0 else 0

result = simulate(
    {"asset": Feed(prices, finalized_through=date(2025, 12, 31))},
    TargetStrategy("asset", target),
    initial_cash=10000,
    execution=NextOpen(commission=1, slippage_bps=5),
    strategy_settings={"name": "sma_and_positive_return", "window": 20},
)
print(result.metrics())
result.save("charts/lab/custom-target.json")
```

- [ ] Confirm the callback reads `view.bars`, which contains completed history,
  rather than indexing the full saved dataset for future values.
- [ ] Try a quantity of two, then an insufficient positive cash balance, and inspect sizing
  and rejected-order behavior. Target is desired total quantity, not buy size.
- [ ] Repeat tasks 5–6 for a predefined custom experiment.

**Done when:** your custom rule is reproducible, records settings and produces
explainable orders. It remains an offline strategy until separately implemented
and verified for paper execution.

## 8. Optional: explore one option offline

- [ ] Discover chain groups and choose one valid unexpired contract.
- [ ] Download a small fixed intraday range using the [manual option example](MANUAL_TESTING.md#selected-option-history).
- [ ] Inspect exact identity, multiplier, source and missing volume.
- [ ] Run `examples/backtest_option.py --help`, then use explicit
  `--fill-model next_bar_open`, a verified aware finality bound and hypothetical
  per-contract costs.
- [ ] For an underlying-driven option simulation, inspect
  `examples/backtest_strategy.py --help` and use compatible intraday clock kinds.

**Done when:** you can reconcile premium × contracts × multiplier, distinguish
TRADES/MIDPOINT from executable bid/ask, and explain why expiry-day lifecycle is
unsupported. Do not reconstruct expired option history by assuming a chain exists.

## 9. Observe your paper account and a built-in runner

Keep execution disabled. Start with your established journal if you have already
used this package; do not create a fresh journal to bypass old recovery state.
A local lab profile can reuse the shipped example settings and that journal:

```python
import json
from pathlib import Path

profile = json.loads(Path("examples/paper_aapl.json").read_text())
# Use the actual established journal if yours has a different path.
profile["journal"] = str(Path("charts/paper/strategy.sqlite3").resolve())
target_path = Path("charts/lab/paper-profile.json")
target_path.parent.mkdir(parents=True, exist_ok=True)
target_path.write_text(json.dumps(profile, indent=2) + "\n")
```

Review the local profile's clients, account selection, symbol, caps and duration.
The profile alone cannot enable execution.

```sh
python examples/paper_preflight.py --profile charts/lab/paper-profile.json --connect
python examples/paper_strategy.py --profile charts/lab/paper-profile.json --seconds 180
```

- [ ] Observe fresh live quotes/bars during a provider-confirmed regular session.
- [ ] Explain each decision or blocked reason. No decision in a short session is
  possible and does not prove the signal is broken.
- [ ] Compare the built-in rule's warmup/timing to your offline rule. Do not expect
  daily research fills and one-minute paper decisions to match.

**Done when:** the account is synchronized, original orders are resolved, and
observation produces understandable state without placing orders.

## 10. Deliberately run one bounded paper experiment

Only after task 9, choose the built-in strategy and review its quantity, notional,
loss, duration and order caps. Stop other execution workflows. Do not use this
command for an arbitrary custom callback from task 7:

```sh
python examples/paper_strategy.py --profile charts/lab/paper-profile.json --execute
```

This sends eligible paper orders. It may finish without a fill. Preserve the exact
run ID and inspect actual orders/fills rather than changing caps to force action.

- [ ] Compare quote receipts, decision time, order limit, terminal state and fees.
- [ ] Confirm what `cancel_on_stop` did for working orders.
- [ ] Check whether holdings remain; stopping is not an exit.
- [ ] Read [stopping and owned exits](WORKFLOWS.md#pausing-stopping-and-explicit-exits)
  before deliberately closing an eligible run-owned position.

**Done when:** the final account/ledger/orders reconcile and any retained holding
or unresolved outcome has an explicit next action. This is not a live-money test.

## 11. Practice recovery before increasing complexity

- [ ] Inspect a stopped run using its exact ID without `--execute`.
- [ ] Verify identity, consumed order cap and ownership survive restore.
- [ ] Review same-day resume, later-day `--new-session`, and owned-only flatten
  separately in the [operating guide](WORKFLOWS.md#restart-recovery).
- [ ] Study cancellation recovery before deliberately testing uncertain sends;
  disconnect-after-send is not needed for an initial strategy experiment.

**Done when:** you can distinguish a paused runner, terminal order, canceled order,
flat strategy ledger and flat account. They are different states.

## Experiment notebook

Keep a private note for each experiment under `charts/lab/` containing:

- Hypothesis, rule, predefined comparison set and training/holdout dates
- Input paths/fingerprints, source, adjustment, interval, sessions and finality assertions
- Strategy/model settings, quantity, costs and initial cash
- Metrics, fills/rejections, ending position and the reason for your next change
- For paper runs: exact local run/journal identity, reconciled final state and
  outstanding actions; keep these account-specific details out of public source

Start with tasks 1–7 for new strategy ideas. Use 9–11 to learn the supported paper
lifecycle; implement a custom paper strategy interface before attempting to deploy
an arbitrary offline callback.

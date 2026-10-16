# Development handoff

Checkpoint: 2026-10-16. The primary workflow is on-demand IBKR historical data →
Python research → backtesting. Selected-option historical acquisition is implemented;
a first single-contract historical-bar option backtest is also implemented.
Next: broader research/performance reports and improved execution modeling.
Do not require live recording, a large local archive or external historical-data
providers. Research/backtesting comes before broker-connected paper execution.

## Cleanup checkpoint

Removed the superseded recording-based options experiment:

- Sampled quote recording, rotating capture and disk-backed recording replay modules.
- Receipt-based option simulator and its dedicated examples/tests.
- Recording-dependent TWS integration scripts and public package exports.
- Known generated experimental recordings/results under `charts/live-options-validation/`,
  `charts/quote-recovery-check/`, `charts/rotating-options-check/` and
  `charts/options-research-check/` (approximately 4.7 MB of file contents).
- Stale wheel/build output, tool caches and project bytecode.

The removed source is recoverable from Git commit `59da0e5`. Recorded market-data
files were ignored, not committed; those generated experiment files were deleted.
Existing equity research datasets, backtest results, chart assets/caches and the
working `.venv` remain. No broker requests or settings changes were part of cleanup.

Validation: all 261 remaining tests, Ruff, mypy and `git diff --check` pass. A wheel
was built from a clean build directory, checked for absence of removed modules,
installed into a temporary SDK-free environment and passed `tests/wheel_smoke.py`.
The test count decreased because 127 recording/simulation tests were removed with
the obsolete features. Existing retained tests were not weakened; the wheel check
now directly verifies quote streams rather than using a recording round trip.

Inspect `git log -1` and `git status -sb` when resuming or transferring machines.
Changes are saved as local checkpoints; no remote push or release is implied.

## What remains implemented

- Official manually installed IBKR SDK adapter; no order-placement/account-state API.
- US equity/ETF historical bars, fixed start/end ranges, paging/pacing and optional
  exact-query Parquet cache. History is TRADES with split-only adjustment semantics.
- Selected unexpired option intraday history with fixed bounds, exact resolved
  identity/multiplier and TRADES/MIDPOINT/BID/ASK sources. Shared paging/pacing
  and optional query cache; BID/ASK/MIDPOINT volume remains None.
- Immutable bars, CSV/records and optional pandas exports, frozen BarDataset save/
  reload with integrity/fingerprint checks, caller-supplied calendar/finality audits.
- Simple returns, SMA, above-SMA and SMA-crossover research signals.
- Daily single-instrument equity long/flat backtest: prior-close signals execute
  next open, fixed whole shares, configurable commissions/slippage, logs and metrics.
- Explicit option selectors, exact contract resolution/multiplier, grouped option
  discovery, stock/option quote snapshots and available IV/Greeks.
- Independent quote-stream handles/cursors and opt-in reconnect. Recovery clears
  fields/feed confirmation, restores exact resolved contracts and preserves gap
  history. These remain useful for inspection and future strategy feeds.
- Optional native Canvas charts, sessions, history loading, live bar recovery and
  browser controls. Charts remain supporting inspection tools.

Historical option acquisition and a first intraday option backtest are implemented.
Do not describe the removed recorded-quote prototype as implemented functionality.
No recording/rotation/replay API is exported. Do not reintroduce that stack as a
prerequisite for research or automatically download whole option chains.

## Option history checkpoint — 2026-10-16

- `Market.bars(Option(...), interval="5min", start=..., end=..., data_type=...)`
  accepts fixed intraday bounds and TRADES/MIDPOINT/BID/ASK. No lookback/live/session
  mode for options. Stock defaults and current equity backtesting remain intact.
- Exact selector matching, resolved conId, currency, actual multiplier, expiry,
  strike/right, trading class and local symbol are retained with query metadata.
  Adjustment/finality/gap completeness remain unverified. Never assume multiplier 100.
- BID/ASK/MIDPOINT bars preserve missing volume through Python, CSV, pandas,
  frozen datasets, Parquet cache and charts. Served option charts omit stock
  reload/session controls. Fixed-range history cannot load older bars implicitly.
- `examples/research_option_history.py` requests one selected contract, saves CSV,
  metadata, dataset and descriptive returns/SMA signals. Empty/incomplete downloads
  produce no research outputs. `examples/research_saved.py` reuses the dataset
  without IBKR, SDK, pandas or a chart.
- After-hours TWS check: AAPL 2026-11-20 340 C, trading class AAPL, conId 845042071,
  multiplier 100. Completed 2026-10-16 regular session [09:30,16:00) New York,
  five-minute bars: 78 each for TRADES, MIDPOINT, BID and ASK. Verified a MIDPOINT
  cache hit, preserved identity/volume/source and broker-free research reload.
  No live quote subscription, order or settings change was needed.
- Validation: 289 pytest tests, Ruff, mypy, offline Chrome chart regression and
  diff whitespace check. New tests cover all sources, identity mismatch, unsupported
  modes, expiry/future bounds, permissions, empty data, partial/disconnected paging,
  cache separation, missing-volume exports and example behavior.
- Small generated validation inputs/results remain ignored under
  `charts/option-history-check/{TRADES,MIDPOINT,BID,ASK,cache}/`. They are optional
  experiment inputs, not a required market-data archive.

## Option backtest checkpoint — 2026-10-16

- `src/pyibquant/option_backtest.py`: `backtest_option()` and immutable result/logs.
  Single contract long/flat, fixed whole contracts, USD TRADES/MIDPOINT intraday
  inputs. Requires `fill_model="next_bar_open"` and timezone-aware finality assertion.
- Prior-close targets execute at the next supplied open. Overlapping bars are
  rejected. Cash flows and marks use the resolved multiplier; commission is per
  contract per side, slippage adverse in basis points. Insufficient cash rejects
  fills; last-bar signals cannot execute and final positions remain marked.
- Synthetic prices do not establish historical executable fills. BID/ASK-only
  inputs, expiry-day/later bars, shorting, exercise/assignment/settlement and
  adjusted-deliverable modeling are outside this first model. Saved pre-expiry
  data remains usable after expiry. No wall-clock restriction on offline analysis.
- Result retains input fingerprint/metadata, targets, assumptions, optional
  calendar, fills/trades/rejections and cash/position/equity/return/drawdown curve.
  Metrics reconcile realized plus unrealized net P&L with total equity change.
- `examples/backtest_option.py` runs above-SMA or SMA-cross, saving exact frozen
  inputs, strategy settings, JSON results and CSV logs. Both strategies passed on
  the saved 78-bar AAPL MIDPOINT and TRADES inputs with costs; no TWS calls needed.
  Outputs are ignored under `charts/option-backtest-check/{MIDPOINT,TRADES}/`.
- Fixed an existing dataset loader issue: integer OHLCV values used to become
  floats, changing the fingerprint after reload. Numeric representation is now
  preserved; integrity verification still applies and missing volume remains null.
- Validation: 336 tests plus style/typing checks. Tests cover hand-calculated
  nonstandard multiplier/cost accounting, losses/open positions, cash rejection,
  next-bar timing/lookahead isolation, overlapping bars, expiry, invalid inputs,
  source restrictions, calendar/finality, overflow, atomic save and runnable examples.
  A clean SDK-free wheel also passed offline equity/option simulation and dataset
  reload checks without optional dependencies. No chart code changes in this slice;
  previous browser regression remains applicable.

## Next — research and execution-model improvements

Expand research/performance reports and comparisons on frozen inputs. A paired
BID/ASK model could add direction-aware spread pricing using synchronized source
bars, while preserving the limits of OHLC aggregates. Lifecycle and multi-leg
models need separate explicit scope. Paper execution remains later work.

Implementation entry points:

- `src/pyibquant/option_backtest.py`, `examples/backtest_option.py` and
  `tests/test_option_backtest.py`: new option simulation, reports and regressions.
- `src/pyibquant/research.py` / `backtest.py`: shared research and equity simulator.
- `src/pyibquant/bars.py` / `dataset.py`: provenance, nullable volume and audits.
- `src/pyibquant/market.py` / `data/providers/ibkr.py`: bounded option acquisition.

IBKR excludes expired options and option end-of-day data from historical access.
Scope initial work to available intraday history for a resolvable option. Current
chain discovery cannot reconstruct historical option universes. Do not fabricate
historical Greeks, sizes, quote receipts or live feed confirmation from OHLC bars.
MIDPOINT bars do not imply executable bid/ask fills; BID_ASK bars have special
aggregate semantics. See [IBKR limitations](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction)
and [bar definitions](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars).

## Setup and local checks

Use Python 3.11+ and the existing `.venv`, or create a new environment and install
`.[dev]` plus optional `.[cache]`/`.[pandas]` only as needed. Install the official
TWS Python SDK 10.33+ manually into that environment; do not use the old PyPI ibapi.
See README for SDK installation and the complete API examples.

TWS/Gateway must be logged in for acquisition, with API socket access and appropriate
market-data permissions. Keep Read-Only API enabled. Defaults: localhost:7497,
client ID 71; choose a unique ID for concurrent clients. Saved-data research and
equity backtests require no broker or SDK. CI/automatic SDK installation remain
outside scope. No broker-connected paper trading is implemented.

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check src examples tests
.venv/bin/mypy
```

Explicit TWS checks are separate from pytest: `tests/live_ranges_check.py`,
`tests/live_exports_check.py`, `tests/live_quotes_check.py` and
`tests/live_recovery_check.py`. The last reconnect script disconnects only its
own client socket for bar recovery. Do not run these just to work on saved data.

Preserved local equity inputs/results include `charts/research-live-check/`
(AAPL 2025 daily bars, signals and calendar) and `charts/backtest/` (above-SMA and
SMA-cross results). The ignored `charts/` directory is not carried by Git; save
specific research inputs separately when transferring machines. `.venv` is also
machine-local. No credentials, account IDs, SDK downloads or generated datasets
should be committed.

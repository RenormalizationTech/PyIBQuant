# Development handoff

Checkpoint: 2026-10-16. The primary workflow is on-demand IBKR historical data →
Python research → backtesting. Selected-option historical acquisition is implemented;
the historical-bar option backtest is next.
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

There is currently no options backtest. Historical option acquisition is implemented.
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

## Next — historical-bar option backtest

Build a small single-contract model using saved historical inputs, preserving
contract multiplier and price-source semantics. Define prior-bar signals, next-bar
execution, commissions/slippage, sizing and finality requirements explicitly.
MIDPOINT does not establish executable bid/ask fills. Handle unavailable inputs
honestly; do not infer quote sizes, historical Greeks or chain membership from bars.
Then expand financial research/performance analytics and reproducible reports.
Paper execution, exercise/assignment and multi-leg models remain later work.

Implementation entry points:

- `src/pyibquant/research.py` / `backtest.py`: broker-independent calculations and
  equity simulator; add the option model without changing equity assumptions.
- `src/pyibquant/bars.py` / `dataset.py`: saved contract/query provenance, nullable
  volume, explicit caller-supplied calendar/finality audits.
- `src/pyibquant/market.py` / `data/providers/ibkr.py`: completed bounded option
  acquisition, reused `_resolve_option()`, paging/pacing and exact-query cache.
- `examples/research_option_history.py`, `examples/research_saved.py` and
  `tests/test_option_history.py`: runnable acquisition/offline workflow and regressions.

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

# Development handoff

Checkpoint: 2026-10-16. The primary workflow is on-demand IBKR historical data →
Python research → backtesting, including selected options as the next slice.
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

There is currently no options backtest or historical option acquisition API.
Do not describe the removed recorded-quote prototype as implemented functionality.
No recording/rotation/replay API is exported. Do not reintroduce that stack as a
prerequisite for research or automatically download whole option chains.

## Next — On-demand IBKR option history

1. Resolve one explicit unexpired Option selector and request a small, completed
   intraday range, initially five-minute bars. Preserve start-inclusive/end-exclusive
   bounds and explicit TRADES/MIDPOINT/BID/ASK semantics.
2. Reuse historical paging/pacing and query-specific caching without stock-only
   identity, multiplier-one or adjustment assumptions. Preserve exact conId,
   selector, currency, multiplier, data type, range and coverage in metadata.
3. Verify a small request against TWS, including outside exchange hours when broker
   services/permissions are available. Missing history, expired/unavailable contracts
   and permission failures must remain explicit; no fallback to live recording.
4. Add saved-input research and a historical-bar options backtest with explicit
   signal/fill/cost assumptions, then expand research/performance reports.

Implementation entry points:

- `src/pyibquant/market.py`: bars() currently accepts stock symbols.
- `src/pyibquant/data/providers/ibkr.py`: bars()/bars_range() resolve stock contracts,
  cache TRADES queries and set equity identity/multiplier one in _set_identity().
  Existing _resolve_option() and quote identity preserve exact conId/multiplier.
- `src/pyibquant/bars.py`, `dataset.py`, `data/history.py` and `data/providers/_pacing.py`:
  shared normalization, provenance, bounds and pacing to reuse deliberately.
- `src/pyibquant/research.py` and `backtest.py`: broker-independent calculations and
  the existing equity simulator. Preserve their current behavior.

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

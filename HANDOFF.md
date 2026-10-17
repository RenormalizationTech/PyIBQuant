# Development handoff

Checkpoint: 2026-10-16. The primary workflow is on-demand IBKR historical data →
Python research → backtesting. Selected-option historical acquisition is implemented;
a first single-contract historical-bar option backtest is also implemented.
The basic strategy-driven bar simulator is now implemented (see checkpoint below).
Named scientific datasets, quality reports and lightweight study starters are delivered.
The current local development snapshot is 0.1.0.dev1; see docs/API.md and CHANGELOG.md.
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

## Strategy-driven backtesting checkpoint — 2026-10-16

- `src/pyibquant/simulation.py`: `Feed`, `Context`/`Strategy`, `Order`, `ExecutionModel`,
  `NextOpen`, `Portfolio`, `SimulationResult`, `TargetStrategy` and `simulate()`.
- Complete frozen daily/intraday inputs, USD only. Existing equity and option
  fixed-size APIs remain compatible; new strategies use the general simulator.
- Explicit close/open clock: publish all completed bars, invoke one strategy
  callback, then execute eligible market orders at actual supplied opens. Strategy
  histories exclude uncompleted bars; execution inputs exclude future OHLCV.
- Different intraday intervals/gaps, empty/stale histories, data ages and mark times.
  Daily feeds use synthetic UTC days and cannot mix with intraday feeds. Intraday
  finality must cover start + interval, unlike the legacy option start assertion.
- Shared cash, submission-order execution, whole long quantities, cash/holding
  rejection, cancellation and end-of-data cancellation. No cash reservation or
  implicit sell-first ordering. `TargetStrategy(..., decision_feed=...)` lets an
  underlying signal trade an option and replaces its outstanding target orders.
- Scaling/partial exits, multiplier-aware weighted-average cost basis including
  allocated entry fees, realized/unrealized P&L. Equity records separate close/open
  phases at adjacent boundaries so drawdown includes both marks and execution costs.
- Model protocol returns a full fill or defers. `NextOpen` supports a flat fee,
  per-unit fee and adverse bps slippage. Settings and strategy parameters are
  serialized with fingerprints, metadata, finality/calendar assertions and logs.
- `examples/backtest_strategy.py` runs equity or underlying-driven option targets
  from saved inputs, saving exact datasets alongside atomic JSON results. Missing
  or stale signals target zero; tolerated signal age is an explicit argument.
- No broker changes/requests are needed. No shorting/margin, FX, limit/stops,
  partial fills or expiry lifecycle. Option simulation horizons crossing expiry
  are rejected even if that option's own data ends earlier. User code/external
  inputs remain responsible for their own lookahead and reproducibility.
- Tests cover accounting with nonstandard multipliers and partial sales, shared
  cash/order priority, cancellation, asynchronous clocks/stale data, future-bar
  isolation, invalid model outputs, SMA parity, atomic results and runnable examples.
- Validation: 389 tests (53 new), Ruff, mypy and whitespace checks pass. A clean
  wheel built from a temporary source copy passed SDK/pandas/PyArrow-free equity
  and option strategy simulation. The example also ran offline on saved AAPL
  2025 daily inputs and the 78-bar option MIDPOINT input, with costs. Outputs are
  ignored under `charts/strategy-backtest-check/{equity,option}/`. Underlying-driven
  option behavior is verified with controlled multi-feed test fixtures, not a new
  live download. No chart changes; prior browser regression remains applicable.

## Scientific research data checkpoint — 2026-10-16

User direction: scientific research means enabling users to study market structure
(e.g. correlations, scaling/multifractality and random matrices). Keep built-in
analysis small; prioritize solid, useful datasets requested/loaded from IBKR.
Backtest comparisons and out-of-sample reports remain backtesting features.

- `BarDatasetCollection` stores named frozen inputs in one atomic integrity-checked
  JSON document; every input retains its full bars, fingerprint and provenance.
- Explicit inner/outer exact bar-start alignment requires matching interval,
  timestamp kind and session settings. Known incomplete downloads are rejected.
  No filling/resampling or inferred calendar; dropped/absent/null counts and source
  metadata accompany records and optional pandas output. Unknown quality stays unknown.
- `examples/research_collection.py fetch` uses bounded sequential equity/ETF queries
  and existing pacing/cache; no collection is written on empty/incomplete/failing
  inputs. `inspect` loads and aligns offline. Selected-option datasets can also be
  put into collections via Python; no bulk option-chain download is introduced.
- Validation: 423 tests (34 new), Ruff, mypy, whitespace checks and a clean
  SDK/pandas/PyArrow-free wheel smoke pass. Previously saved AAPL option inputs
  for TRADES/MIDPOINT/BID/ASK round-tripped with unchanged source fingerprints;
  both joins retained 78 UTC starts, nullable volume remained absent and offline
  inspection exported 78 rows. Outputs remain ignored under
  `charts/scientific-data-check/`. This is reuse of saved data, not fresh acquisition.
- Fresh TWS AAPL/MSFT/SPY acquisition for [2026-10-12,2026-10-16) passed:
  four daily bars per instrument, both joins retained four dates with no absent
  observations among inputs, and offline inspection/CSV export passed. The initial
  connection failure was sandbox network denial (direct socket errno 1), not a
  disconnected TWS. Retrying with approved network access succeeded. Inputs and
  exports remain ignored under `charts/scientific-data-check/`. No orders or
  account/settings changes were made. Next: follow concrete scientific data needs. Do not build advanced estimators or
  prioritize performance reports as the scientific research milestone.

## Dataset quality and named acquisition checkpoint — 2026-10-16

- `BarDataset.describe()` and collection `describe()` summarize recorded identity,
  sampling/source/adjustment/session semantics, queries, coverage, download progress
  and fingerprints. `quality_report()` adds JSON-compatible observation flags,
  warnings/errors and optional caller calendar/finality checks. No source mutation,
  inferred expected calendar, automatic repairs or overall quality score.
- Finality in reports uses `audit()`'s inclusive BAR-START convention, explicitly
  distinct from the general simulator's intraday end-coverage requirement.
- Collection reports accept calendars/finality keyed by input label. They expose
  source differences and optional alignment losses; incompatible/partial inputs
  still receive individual reports with an unavailable-alignment reason.
- `Market.datasets(mapping, start=..., end=..., interval=...)` requests and freezes
  named inputs sequentially through existing `bars()` paging/pacing/cache. Strings
  and Options default to TRADES; `BarRequest` supports per-input option sources
  and equity primary exchanges. Common hours, refresh and equity-only sessions.
- First error/empty/incomplete input raises `DatasetCollectionError`: `failed_key`,
  read-only `completed` mapping, original `__cause__` (including partial-page
  HistoricalRangeError). No automatic retries, later requests or filesystem writes.
  The example now uses this public API and can export `--quality-report` JSON.
- Fresh TWS checks passed: AAPL/MSFT/SPY, four daily bars each for
  [2026-10-12,2026-10-16); mixed AAPL equity plus 2026-11-20 340 C MIDPOINT,
  six five-minute bars each on 2026-10-16 [09:30,10:00) New York. Option identity
  conId 845042071/multiplier 100 and nullable volume preserved. Explicit calendar/
  finality checks and broker-free reload, reports and CSV export passed.
  Artifacts remain ignored under `charts/scientific-quality-check/`.
- Use approved network access for live checks: the default execution sandbox denies
  local sockets (errno 1) even while TWS is listening. No TWS/account/order changes.
- Validation: 475 tests (52 new), Ruff, mypy and whitespace checks pass. A clean
  wheel passed existing smoke checks plus named request coordination and quality
  reports without SDK/pandas/PyArrow installed. New tests cover anomalies, unknown/partial/empty
  inputs, mismatched calendars, reports on incompatible collections, source
  differences, acquisition ordering/preflight/failures and offline example outputs.
- The agreed scientific-data foundation is delivered. Further transformations,
  sampling/calendar integration or acquisition scope should follow a concrete study;
  advanced statistical estimators remain user-owned. Backtest reports stay separate.

## Lightweight study starters checkpoint — 2026-10-16

- User requested both daily correlations and intraday scaling preparation, provided
  they require no extra packages or complicated construction. `pyibquant.studies`
  uses only the standard library; no dependency/configuration changes.
- `daily_correlations(collection)` constructs log returns on adjacent union dates
  before listwise selection, preserving endpoints/missing values and reporting
  common sample/exclusion counts plus Pearson matrix. Constants/insufficient data
  yield null correlations. No filling or source/currency harmonization.
- `intraday_scaling(dataset, lags=..., session_timezone=...)` exports log-price
  increments and first absolute/second moments. Exact uninterrupted grids and
  same local date required; missing intermediate bars and date changes break
  sequences. Explicit timezone needed if source metadata is unknown. Overlapping
  increments remain dependent; no fitted exponents/Hurst/multifractal claims.
- Both helpers reject empty, nonpositive-close and incomplete/unknown-download
  inputs. Reports retain source fingerprints, quality evidence and assumptions;
  provenance/finality remains unchanged. Calendar completeness is not inferred.
- `examples/research_studies.py` runs either workflow entirely offline against a
  saved collection, writing JSON values/results/provenance. It prevents overwriting
  source inputs. See README for acquisition and analysis commands.
- Fresh TWS validation: AAPL/MSFT/SPY 2025 daily inputs (250 rows each, 249 common
  log-return observations), AAPL five-minute [2026-10-12,2026-10-16) (312 bars;
  308/304/296/280 valid increments at lags 1/2/4/8). Offline examples passed.
  Generated artifacts ignored under `charts/scientific-studies-check/`.
- Validation: 497 tests (22 new), Ruff, mypy and whitespace checks pass. A clean
  wheel ran both helpers without SDK/pandas/PyArrow/NumPy/SciPy dependencies.
  New tests check known inverse correlations, missing-period
  isolation, constants, hand-calculated moments, gaps, timezone/date boundaries,
  input restrictions, empty lags and offline CLI safety.

## Development snapshot checkpoint — 0.1.0.dev1

- Reviewed supported API entry points and added `docs/API.md`, with acquisition,
  quality/alignment, scientific helpers and simulation in one workflow. Updated
  overview/roadmap statements that still described delivered features as next work.
- Added `CHANGELOG.md`, explicit source manifest and version `0.1.0.dev1`.
  Source distributions include docs, examples and validation scripts; generated
  datasets, virtual environments and credentials are excluded by curated copying.
- Fresh `tests/live_workflow_check.py` passed through TWS: AAPL/MSFT/SPY daily
  2025 inputs and AAPL/selected 2026-11-20 340 C MIDPOINT for the completed
  2026-10-16 regular session. All post-download work runs after broker close:
  persistence, quality, correlations, scaling, equity/option/general strategy
  simulation and HTML generation. No account/orders/settings changes.
- Chrome offline regressions passed for native chart interactions, history
  pagination and session/freshness/reconnect rendering. No shared live-chart
  session or TWS settings were changed by these tests.
- Release acceptance: 497 pytest tests, Ruff, mypy, whitespace checks; build source
  archive, then wheel from that archive, inspect contents and run SDK/optional-
  dependency-free wheel smoke and CLI checks. `tests/build_check.py` performs the
  artifact checks using existing tools, without downloads. Artifacts/checksums go
  under ignored `dist/`. Re-run it after changing source or docs.
- Locally tested with Python 3.14 only; Python 3.11+ remains declared compatibility,
  not a validated multi-version matrix. No CI/automatic SDK install introduced.
- This is a local development checkpoint. No remote push, tag or publication is
  implied. Further scope should follow concrete research needs or a separate
  explicit execution/backtesting request.

Implementation entry points:

- `src/pyibquant/dataset.py`, `collection.py`, `requests.py`, `Market.datasets()` and
  `tests/test_dataset_quality.py`/`tests/test_dataset_requests.py`: descriptions,
  quality assertions and named acquisition/error handling.
- `src/pyibquant/collection.py`, `examples/research_collection.py` and
  `tests/test_collection.py`: scientific data collections and alignment.

- `src/pyibquant/simulation.py`, `examples/backtest_strategy.py` and
  `tests/test_simulation.py`: general strategy, execution and portfolio tools.
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

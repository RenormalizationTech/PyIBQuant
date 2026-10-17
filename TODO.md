# PyIBQuant development roadmap

Last reconciled: 2026-10-16. Checkboxes describe implemented behavior, not a release promise.
The full project direction remains in [PROJECT_PLAN.md](PROJECT_PLAN.md).
For machine setup and where to resume, see [HANDOFF.md](HANDOFF.md).

The basic strategy-driven backtesting tools are implemented: time-aware feeds,
strategy callbacks, market-order submission/cancellation, replaceable execution,
shared cash/positions with variable sizing and partial exits, and reproducible
results. Existing fixed-size equity/option APIs retain their behavior. Named
scientific datasets, quality reports and small daily/intraday study starters are
also implemented. The local 0.1.0.dev1 snapshot packages these foundations with
an API guide, source-distribution examples and reusable validation scripts. Strategy comparisons and performance
reports remain part of the backtesting backlog.

Historical acquisition supports all four TRADES/MIDPOINT/BID/ASK sources and was
verified after hours against TWS, including cache reuse. Current validation:
497 tests, typing/style checks and a clean SDK-free wheel smoke check pass. The
previous chart browser regression passed; this slice changes no chart code.
Live recording, bulk collection and external providers are not required. The
obsolete recording/rotation/replay stack and recorded-quote simulator were removed.

## Goal and scope

Make IBKR convenient to use from Python for quantitative research, backtesting
and algorithmic trading. Users manually install `ibapi` and run logged-in
TWS/Gateway with the account and data permissions their requests need.

Charts support data inspection and research/trading results. A standalone charting
application or TradingView replacement is not the current product objective.
Retain the useful native Canvas renderer; prioritize new visualization features
when they serve a concrete research or trading workflow. CI and automatic SDK
installation are outside current scope; keep local unit and integration checks.

This extends the original v0.1 market-data/chart slice. The complete list is not
required before the next useful release. Broker execution remains on the separate
paper-trading roadmap; displaying trade context does not authorize order placement.

## Audience and options direction

Equities/ETFs are the accessible entry point for general users. Options trading
and backtesting are a major use case and the project owner's primary personal
interest. Use the equity slice to validate shared data and backtest foundations;
keep contract identity, multipliers and execution assumptions extensible to options.

Use IBKR historical requests as the source for options research, within IBKR's
contract availability and retention limits. Do not require users to collect a live
archive or subscribe to an external historical-data provider. Keep acquisition
bounded to a selected contract and requested range, with optional cache/save for
repeatability. The recorded-quote experiment was removed; the primary product
data model uses on-demand IBKR historical inputs.

## Scientific research data — current priority

Support scientists studying correlations, scaling/multifractality, random matrices
and other phenomena through dependable IBKR data. Users own advanced analysis;
PyIBQuant supplies acquisition, loading, provenance and small preparation tools.
Research does not require a strategy, backtest, chart or live recorder.

- [x] Bounded per-instrument requests, frozen inputs, provenance and explicit calendar audits
- [x] Named multi-instrument collections with atomic save/reload and per-source integrity checks
- [x] Exact bar-start inner/outer alignment, explicit join choice, no filling or resampling
- [x] Records/optional pandas output plus source fingerprints and dropped/absent/null counts
- [x] Sequential equity/ETF acquisition example and broker-free collection inspection
- [x] Round-trip saved IBKR option inputs and inspect/export aligned values offline
- [x] Verify a fresh AAPL/MSFT/SPY collection against TWS and inspect/export offline
- [x] Dataset/collection describe and quality reports with explicit per-input calendar/finality assertions
- [x] Report volume/price observation flags, provider warnings, source differences and alignment blockers
- [x] Market.datasets named acquisition with per-source BarRequest and explicit first-failure diagnostics
- [x] Fresh mixed equity/selected-option request verification and offline JSON quality exports
- [x] Dependency-free daily log-return panel and descriptive Pearson correlation starter
- [x] Intraday gap/date-aware log increments and first/second moment summaries by lag
- [x] Fresh TWS verification of both starters; offline saved-data examples
- [ ] Extend preparation only for concrete study needs; advanced models stay user-owned

No built-in advanced statistical framework is planned. Unknown coverage/finality,
source semantics and IBKR availability limits must remain visible. Alignment is
not an exchange-calendar audit or a certification of comparable observations.

## Basic backtesting tools

- [x] Bar-driven clock with completed histories and immutable decision snapshots
- [x] Multiple explicit instruments, unequal intraday intervals, missing/stale data ages
- [x] User-owned strategy state and underlying-driven option decisions
- [x] Market orders, cancellation, pending/filled/rejected/canceled states and explicit reasons
- [x] Replaceable execution model with open-only inputs and serialized settings
- [x] Shared USD cash, long-only whole quantities, scaling and partial exits
- [x] Weighted-average ledger, actual multipliers, fee allocation and P&L reconciliation
- [x] Order/fill logs, position snapshots, open/close equity history and basic metrics
- [x] Input fingerprints, finality/calendar assertions, strategy/model settings and atomic results
- [x] Equity SMA parity with existing simulation and underlying-to-option examples
- [ ] Backtest experiment reports, benchmark comparisons and out-of-sample evaluation

Keep the foundation small. Limit/stop orders, partial fills, spread/liquidity models,
shorting/margin, FX and option lifecycle/multi-leg accounting require separate scope.
Daily and intraday feeds cannot mix without an explicit session-time model. Broker
execution remains separate. See README's strategy-driven backtesting section.

## Option history and first backtest delivered

- [x] Resolve one explicit unexpired option selector and retain exact identity/multiplier
- [x] Add intraday historical requests with fixed start/end bounds and explicit TRADES/MIDPOINT/BID/ASK types
- [x] Reuse paging/pacing and query-specific caching without stock-only identity or adjustment assumptions
- [x] Preserve contract selector, source type, requested range and coverage in saved research metadata
- [x] Surface expired/unavailable history and permission failures explicitly; no fallback to live recording or fabricated data
- [x] Verify a small recent historical request against TWS, including when the exchange is closed
- [x] Provide an offline research example from the returned historical input
- [x] Add a historical-bar option backtest with explicit timing/cost assumptions appropriate to the input bars
- [ ] Backtesting: performance comparisons and a reproducible strategy-evaluation report

Acceptance: request a selected option's available intraday history from IBKR on
demand, then inspect/analyze saved inputs without a chart, live recorder or an
ongoing broker connection. The API does not promise expired options, option EOD
history, historical chain reconstruction or historical contract Greeks. Preserve
TRADES/MIDPOINT/BID/ASK semantics; do not treat BID_ASK aggregates as an atomic quote.
The previous recorded-quote simulator was removed; the historical-bar option engine
is implemented separately from equity simulation. The initial model uses TRADES or
MIDPOINT with explicit synthetic next-open fills; BID/ASK execution and expiry-day
lifecycle handling remain unsupported.

## Python research data workflow

- [x] Make session/chart enrichment optional for Python data requests
- [x] Convenient Python exports of bars (records/CSV; optional pandas DataFrame)
- [x] Explicit start/end historical queries with bounded paging, deduplication and pacing (offline and live verified)
- [x] Instrument/query/session/adjustment metadata with explicit unverified gap/finality status
- [x] Reusable simple returns and SMA calculations with local correctness tests
- [x] A runnable IBKR data → research signal example without a chart (synthetic and live workflows verified)
- [x] Run fixed-range checks against TWS/Gateway (passed on port 7497, 2026-10-16)
- [x] Frozen dataset save/reload with atomic writes, integrity checks and preserved provenance
- [x] Explicit calendar comparison and caller-confirmed finality audit (no inferred exchange calendar)
- [x] Offline research example consuming the saved dataset without IBKR/optional dependencies

Acceptance: a Python script obtains a defined historical dataset, computes a
signal, and exports reproducible inputs/results. Optional charts inspect the work.

## First daily equity backtest

- [x] Single-instrument daily long/flat equity backtest with fixed whole-share sizing
- [x] Next-open execution of prior-close targets; configurable commissions/slippage
- [x] Trade/fill/rejection logs, equity curve, returns and drawdown metrics
- [x] Frozen input fingerprint, required finality assertion and optional calendar check
- [x] Validate two strategies (above-SMA and SMA crossover) before generalizing a framework
- [ ] Optional entry/exit and performance visualizations
- [ ] Explicit paper-trading workflow through IBKR (after execution prerequisites)

Equity backtesting remains implemented and verified. The recorded-quote options
experiment was removed during scope cleanup; historical option acquisition is implemented;
a first historical-bar option simulation is also implemented. Keep paper execution separate.

## Stock/option quote foundation

- [x] Separate Level-one snapshot API via reqMktData; no regulatory snapshots
- [x] Immutable bid/ask/last and sizes with contract identity and JSON export
- [x] Explicit requested/reported feed type, delayed tick IDs and local receipt timestamps
- [x] Missing/crossed quotes and permission failures remain visible
- [x] Explicit option selectors resolve one contract and retain actual multiplier
- [x] Preserve available bid/ask/last/model IV/Greeks separately (offline verified)
- [x] Live AAPL stock snapshot verification against TWS
- [x] Resolve user-selected SPY 2026-11-20 770 C identity/multiplier against TWS
- [x] Frozen AAPL 2026-11-20 340 C bid/ask and model IV/Greeks verified via TWS
- [x] Handle SDK-normalized None Greeks and UNSET_DECIMAL sizes
- [x] In-session live option bid/ask, sizes and model IV/Greeks verified (2026-10-16)
- [ ] Optional SPY retry after resolving its 10091 SPY ARCA/TOP/ALL permission message
- [x] Grouped option-chain discovery with explicit, unverified candidate selection
- [x] Independently owned continuous stock/option quote subscriptions and consumer cursors
- [x] Opt-in quote reconnect with exact contract identity, empty replacement generations and gap history
- [x] Frozen quote recovery verified against TWS (independent of the historical research workflow)
- [x] Remove superseded recording/rotation/replay stack, recorded-quote simulator and generated test recordings
- [ ] Chart bid/ask display
- [ ] Richer liquidity models and expiry/exercise/assignment semantics within the supported data scope

## Execution architecture prerequisites

- [x] Quote subscriptions have independent ownership and per-consumer update cursors
- [ ] Independent bar subscription ownership for chart and strategy consumers
- [ ] Completed-bar strategy events independent of browser polling and countdowns
- [x] Fixed-range downloads release the Market control lock; subscription cancellation stays responsive
- [ ] Extend this separation to future broker order/cancel controls and legacy lookback/history operations
- [ ] Separate broker order/fill/position state and reconciliation from data recovery
- [ ] Explicit user start/stop/cancel controls and paper-account integration checks

## Completed prototype

- [x] Official IBKR API adapter, configurable host/port/client ID, readiness and request timeouts
- [x] US stock/ETF contract resolution and historical OHLCV bars
- [x] UTC intraday timestamps and date-only daily bars
- [x] Live historical-bar updates; repeated timestamps replace the current candle
- [x] Independent Canvas candlesticks, synchronized volume, axes and crosshair OHLCV
- [x] Wheel zoom, horizontal drag, touch pinch, keyboard navigation and high-DPI resizing
- [x] Fit data and Latest controls; preserve a panned view during updates
- [x] Browser symbol, interval, history and trading-hours selection with Load chart/Enter
- [x] 2-hour/4-hour and weekly bars; yearly candles aggregated from monthly IBKR bars
- [x] Loading/errors, retain prior chart on failure, cancel prior subscription on success
- [x] Self-contained offline HTML snapshots and localhost live chart server
- [x] Offline provider/session tests and separate browser/integration checks

## Existing chart foundations

Price/time scaling, vertical panning, right space and older-history loading are
implemented, along with optional Parquet query caching, fixed New York time labels
and a browser trading-hours selector. Session shading, session date ticks, an
intraday countdown, receipt-time status and automatic reconnect/backfill are now
implemented. These support the Python data workflow. Further chart features below
are a secondary backlog, not the next delivery milestone.

- [x] Drag the price axis to scale vertically
- [x] Vertical pan with explicit manual/automatic price-scale modes
- [x] Autoscale toggle and reset; preserve manual scaling through live updates
- [x] Drag the time axis to adjust candle spacing
- [x] Configurable space to the right of the latest candle
- [x] Load older historical bars when panning left; deduplicate and preserve viewport
- [x] Local historical cache to reduce repeat requests (optional Parquet; no database server)
- [x] Fixed New York display with daylight-saving-aware labels
- [x] Browser regular/extended-hours selector
- [x] Provider-supplied session shading and New York day separators
- [x] Session date ticks and session-aware intraday bar-boundary countdown
- [x] Show subscribed/disconnected/reconnecting state, callback quiet time and unverified entitlements
- [ ] Confirm delayed versus real-time feed types through an explicit provider signal
- [x] Display last bar receipt time and actionable connection errors
- [x] Reconnect, restore subscriptions and backfill gaps while retaining series/history

Acceptance: scaling, panning, interval changes, history loads and live updates do
not unexpectedly move the trader's view. Price/time coordinates stay consistent
across both panes. Add browser regressions for those behaviors.

## Supporting chart backlog: workspace

- [ ] Symbol/company search with exchange, currency and instrument identification
- [ ] Saved watchlists with sorting and last/change/volume/bid/ask/spread
- [ ] Premarket/after-hours quote context
- [ ] Favorite intervals and quick date ranges
- [ ] Save/restore preferences and named workspaces across restarts
- [ ] Fullscreen, context menus and consistent keyboard shortcuts
- [ ] Appearance settings; line and OHLC bar styles
- [ ] PNG and CSV exports

## Supporting chart backlog: analysis tools

- [ ] Horizontal/vertical lines, trend lines, rectangles, text and measurements
- [ ] Drawing handles, candle snapping, lock/hide/delete and undo/redo
- [ ] Persist drawings by symbol using timestamp/price anchors, with timeframe visibility
- [ ] Drawing templates and object management
- [ ] SMA, EMA, VWAP and Bollinger Bands overlays
- [ ] RSI and MACD in separate resizable panes
- [ ] Indicator parameters, styles, templates and custom Python calculations
- [ ] Multiple resizable charts with optional symbol/time-range/crosshair synchronization
- [ ] Comparison symbols, percentage/indexed and logarithmic scales

## Monitoring and research

- [ ] Price/indicator alerts with crossing and bar-close semantics
- [ ] Python-side alert evaluation, expiration, history, sound and notifications
- [ ] Earnings/dividend/split markers; explicit data-provider requirements
- [ ] Explicit corporate-action adjustment settings and consistent indicator inputs
- [ ] Historical replay with stepping and speed control
- [ ] Research annotations, signal markers and backtest entry/exit overlays
- [ ] Backtest performance views
- [ ] Positions, average entry, orders and fills displayed on charts
- [ ] Later: option chain tables, IV smiles/skew, term structure and surfaces

## Quality and release work

- Local unit, lint, typing and explicit TWS integration checks; CI is outside current scope.
- [x] Verify base wheel assets/import/export and SDK-free tests in an isolated local environment
- [ ] Verify clean installation and wheel assets on another machine
- [ ] Expand renderer tests for large datasets and lengthy live sessions
- [ ] Test data gaps, market holidays, DST, corporate actions and indicator correctness
- [ ] Persistence recovery tests once saved workspaces exist
- [ ] Bound live in-memory history and avoid sorting/repainting all bars on every poll
- [ ] Decide release metadata, supported Python/OS matrix and dependency constraints

Future chart-workspace acceptance: prepare a watchlist, inspect research signals
and results, and retain useful annotations. This follows the Python research and
backtesting milestones.

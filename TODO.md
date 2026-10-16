# PyIBQuant development roadmap

Last reconciled: 2026-10-16. Checkboxes describe implemented behavior, not a release promise.
The full project direction remains in [PROJECT_PLAN.md](PROJECT_PLAN.md).
For machine setup and where to resume, see [HANDOFF.md](HANDOFF.md).

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

After the shared data/first equity-backtest slice, prioritize stock/option quote
access and an options pilot ahead of broad-universe monitoring or chart parity.
The options pilot should identify contracts by underlying/expiry/strike/right,
show bid/ask/spread and available IV/Greeks, and support collecting selected quotes
for later research. Historical option dataset imports and explicit spread/fill
models follow; full options backtesting also needs expiry/exercise/assignment
semantics. Do not assume IBKR can reconstruct expired option histories, or that
recorded sampled quotes form a complete exchange tick archive. Explicit option
snapshots, grouped discovery, continuous selected-contract subscriptions and
sampled recording/replay are implemented. Options backtesting remains planned.

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

Next: choose the historical input source for the first options backtest and
verify live options during their trading session. Discovery and sampled quote
collection are implemented and verified with frozen AAPL option data. Keep
paper execution separate; the simulator does not submit orders or model account
settlement, dividends, taxes, liquidity or historical nominal-share execution.

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
- [ ] In-session live option quote/Greeks verification (overnight live request had no prices)
- [ ] Optional SPY retry after resolving its 10091 SPY ARCA/TOP/ALL permission message
- [x] Grouped option-chain discovery with explicit, unverified candidate selection
- [x] Independently owned continuous stock/option quote subscriptions and consumer cursors
- [x] Sampled JSONL recording, integrity checks, partial-status handling and SDK-free replay
- [x] Frozen AAPL discovery → selected stream → recording → offline replay verified via TWS
- [ ] Choose first options-backtest inputs: newly collected recordings or supplied historical data
- [ ] Quote reconnect with explicit generation/gap recording; file rotation/large-file replay
- [ ] Chart bid/ask display
- [ ] Historical quote imports and options-specific spread/fill/expiry semantics

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

# PyIBQuant development roadmap

Last reconciled: 2026-10-20. Checkboxes describe implemented behavior, not a release promise.
The full project direction remains in [PROJECT_PLAN.md](PROJECT_PLAN.md).
For machine setup and where to resume, see [HANDOFF.md](HANDOFF.md).

The basic strategy-driven backtesting tools are implemented: time-aware feeds,
strategy callbacks, market-order submission/cancellation, replaceable execution,
shared cash/positions with variable sizing and partial exits, and reproducible
results. Existing fixed-size equity/option APIs retain their behavior. Named
scientific datasets, quality reports and small daily/intraday study starters are
also implemented. The local 0.1.0.dev1 snapshot packages these foundations with
an API guide, source-distribution examples and reusable validation scripts.
Release preparation is complete at checkpoint `f0f79a6`. Next: algorithmic paper
trading with persistent account performance and order tracking. Worked scientific
studies follow the paper-trading milestone. Strategy comparisons and performance
reports remain part of the backtesting backlog.

Historical acquisition supports all four TRADES/MIDPOINT/BID/ASK sources and was
verified after hours against TWS, including cache reuse. Recorded validation at
the development checkpoint: 497 tests, typing/style checks, a clean SDK-free build,
the TWS end-to-end workflow and three offline Chrome regressions passed.
Live recording, bulk collection and external providers are not required. The
obsolete recording/rotation/replay stack and recorded-quote simulator were removed.

## Next milestone — algorithmic paper trading and account performance

Priority updated 2026-10-19. Detailed design and acceptance checks are in
[PROJECT_PLAN.md, section 24](PROJECT_PLAN.md#24-phase-6--algorithmic-paper-trading-and-account-performance).
Read-only account tracking is implemented and API-verified. The initial paper-order
and runner code passes offline tests; live-data observation is verified. The owner
reports successful paper sells and an AAPL algorithmic round trip. A ten-minute
bounded run with three filled orders completed on October 20; its explicit
restart/resume then filled the fourth order and preserved the order cap and loss
baseline. The separate acknowledged unfilled cancellation also passed with no
fills, flat holdings and no pending reservation. The bounded equity workflow is
validated; broader recovery, settlement edge cases and multi-session work remain.

Stop checkpoint, 2026-10-20: the owner is pausing work here. Basic algorithmic
AAPL stock paper trading is live-validated; normal strategy orders are automatic.
Selected option execution/cancellation is validated separately, without an option
strategy runner. Restart instructions and final account/process state are at the
top of HANDOFF.md. Unattended recovery across failures/sessions remains future work.

- [x] Shared paper/live execution design with explicit target account/funding policy
- [x] P1: selected paper account; API values, positions and visible order snapshots
- [x] P1: distinct broker funding fields and explicitly estimated unsettled cash
- [x] P1: durable account history and focused cash/value/P&L charts with freshness/gaps
- [x] P2: initial limit submit/cancel, fill/fee callbacks and durable identities (offline tested)
- [ ] P2: settlement-aware spending checks, fees and reconciled order reservations
- [ ] P2: startup/reconnect reconciliation without duplicate submissions
- [x] P2: recorded order/fill history and bounded paper round-trip/cancellation checks
- [x] P3: dedicated market feed and completed-bar above-SMA runner (observation verified)
- [x] P3: initial lifecycle controls, limits and pause-on-disconnect (offline tested)
- [x] Shared terminal order waits and exact-tag cancellation with confirmation
- [x] Read-only reconciliation reporting missing/foreign working orders without resends
- [x] Durable fill-based ownership audit and masked strategy JSON export
- [x] In-memory pause/resume preserving risk limits; explicit strategy-owned flatten
- [x] Versioned process checkpoint restore, paused, with risk/ownership checks and local run lease
- [x] Offline per-run FIFO P&L, fees, exposure and observed dollar drawdown with CSV exports
- [x] Saved bounded AAPL profile, local/read-only API preflight and launch/recovery runbook
- [x] Owner-run ten-minute strategy session completes with filled orders and reconciled ownership
- [x] Owner-run process restart/resume preserves ownership, loss baseline and order budget
- [x] Separate one-share cancellation harness with exact-ID recovery and fill/timeout handling
- [x] Owner-run acknowledged unfilled cancellation and released reservation (2026-10-20)
- [ ] Completed-order recovery, execution corrections and multi-session baseline policy
- [x] P3: validate bounded equity strategy orders and explicit same-day process recovery
  - Owner-run AAPL algorithmic buy/sell round trip reconciles to -2.147077 USD net.
    October 20 bounded run completed with three fills and one AAPL share retained.
    Restart/resume sold that share at 340.01, reconciled flat and stopped at the
    original four-order cap. Total net is -4.854022 USD after 4.014022 USD fees.
    Separate cancellation check c97af579ef034829b3afd3d383c928a9 passed with broker
    acknowledgment, zero fills, flat holdings, clear reconciliation and no pending
    owned-order reservation. Broader automatic reconnect remains a separate item.
- [ ] P4: account/strategy attribution, returns and drawdown with cash-flow evidence
- [x] P4: initial selected long-option execution after the shared equity lifecycle passes
  (one-contract bounded harness; automated option strategies remain separate)

Market-session continuation, 2026-10-20:

- [x] Fresh AAPL stock and selected 2026-11-20 340 C live bid/ask, sizes and option Greeks
- [x] Live stock/option stream reconnect preserves identity/cursors and records closed gaps
- [x] Observation runner produces completed-bar signals before/after data recovery;
  explicit pause/resume and stop suppress decisions; recovery leaves the runner paused
- [x] Data-only bar reconnect/backfill with retained yearly history
- [x] Read-only completed-order coverage probe reaches its barrier (five AAPL records)
- [x] Longer human-run bounded paper session, then account/run performance review:
  run d547a4da804c4e5891518952953d0e4c completed 30 minutes, 30 signals and four
  fills; flat, ledger complete, gross -0.25 USD, fees 4.014050, net -4.264050
- [x] Bounded execution-enabled pause/resume controls and broker disconnect-after-send
  recovery acceptance; broader automatic broker reconnect remains separate
- [x] Integrate exact-identity completed-order recovery; read-only TWS reconciliation
  matched nine records, and reconstructed missing cancellation callbacks recovered
  Submitted to Cancelled with no orders sent and no pending reservation
- [ ] Full historical coverage and execution-correction handling. Filled TWS records
  can report totalQuantity=0; recovery preserves the durable submitted quantity
- [x] Prepare one-send broker disconnect harness and exact-ID recovery; offline tested
- [x] Owner-run disconnect-after-send and exact-ID recovery: check
  417b80ac0fcf47958f2c59a89f79f427, client 297 order 2, one send attempt,
  UnknownSend recovered to broker-observed order, canceled unfilled, flat,
  reconciliation clear and no pending reservation; no replacement submission
- [x] Prepare execution-enabled runner pause/resume check across a live candle;
  offline tests cover frozen baseline, configuration, budget, cursor and no signals
  during pause, explicit resume and a subsequent new signal
- [x] Owner-run execution controls: 77d386816acd417e94d29b1545d9b339, ten minutes,
  paused/resumed/passed; nine signals, unchanged baseline/caps, one BUY fill at
  341.25; one owned share retained at stop (exit remains an explicit action)
- [x] Read-only exact-run flatten plan and restored-checkpoint ordering regression
- [x] Owner-run strategy-owned flatten for 77d386816acd417e94d29b1545d9b339:
  SELL one at 340.03, gross -1.22 USD, fees 2.007011, net -3.227011;
  strategy/account flat, ledger complete and no pending reservation
- [x] Initial selected-option order API: shared durable send/cancel/reconciliation,
  exact contract and broker SMART tick ladder, multiplier-aware premium/funding/P&L,
  one long contract, owned exits and expiry-day refusal (offline tested)
- [x] Read-only option round-trip preflight: AAPL 2026-11-20 365 C, conId 845042384,
  multiplier 100; nickel-grid BUY 2.30 / exit reference 2.15, premium 230 USD,
  quoted spread/fee estimate 19 USD under the configured 25 USD budget
- [x] Owner-run one-contract option BUY/SELL check e7c2452026e5459d845a3214ff0bfc8a:
  AAPL 2026-11-20 365 C, BUY 2.32 / SELL 2.17, gross -15 USD, fees 1.535070,
  net -16.535070; complete ledger, account/strategy flat, no pending reservation.
  Fresh read-only post-option preflight is clear. This is a manual bounded lifecycle
  harness; automated option strategies remain separate.
- [x] Owner-run acknowledged unfilled option cancellation c7a050a5fbad4f7f807738fc3ef9383e:
  client 311 order 3, BUY one at 1.95, Cancelled with zero fills; multiplier-based
  reservation 197 USD (195 premium plus 2 fee allowance) released to zero,
  complete zero-execution ledger, account flat and reconciliation clear.
  Fresh read-only post-option-cancellation preflight passes with zero working,
  missing or foreign orders. Fill-race retention remains offline tested.
- [x] Fix legacy UnknownSend replay across API client IDs: source-session identity
  prevents a false foreign-order duplicate; fresh read-only preflight and offline
  replay confirm no unresolved orders after the recovery check
- SPY live API quotes remain blocked by IBKR 10089 (ARCA/TOP/ALL). Owner chose to
  continue with AAPL and leave SPY blocked; no entitlement change is assumed.

The bounded AAPL live-session acceptance checks above are complete. Remaining
broader milestone items are not certified by these checks: settlement calendars
and next-day cash release, natural partial fills/execution corrections, full
historical recovery coverage, automatic broker reconnect during execution,
multi-session baselines, verified cash-flow-adjusted returns and automated option
strategies. No additional paper orders are needed to repeat completed acceptance.

Reusable read-only checks: `tests/live_session_controls_check.py` and
`tests/live_completed_orders_check.py`. Evidence is under ignored
`charts/paper/live-session-controls-2026-10-20/` and
`charts/paper/completed-order-coverage-2026-10-20/`. These checks never submit or
cancel broker orders and do not validate execution-enabled runner recovery.

Account performance charts are trading observability and remain in scope. General
chart workspace features remain removed. Paper account development/testing is
authorized by the owner; real-money accounts are outside this milestone.

## Subsequent milestone — two reproducible worked studies

The study helpers and terminal examples are implemented. The next deliverables
are documented scientific examples using those tools, rather than new estimators.

- [x] Complete API/documentation review, regression and local `0.1.0.dev1` build
- [ ] Work through the terminal workflows manually and record usability findings
- [ ] Document a daily correlation study: question, explicit instrument universe,
  dates, sampling/source choices, aligned return periods and descriptive results
- [ ] Document an intraday scaling study: question, selected instrument, dates,
  interval/timezone, lag choices, gap/date exclusions and descriptive moments
- [ ] Include exact acquisition/offline commands, frozen-input fingerprints,
  quality evidence and interpretation limits in each study; keep generated data
  outside Git and make clear that fresh IBKR data may differ from frozen inputs
- [ ] Improve calendar inputs, session filtering or exports only if those studies
  demonstrate a concrete need; retain the dependency-free starting workflows
- [ ] Validate Python 3.11–3.13 compatibility before a public release; only Python
  3.14 has been exercised in the local development checks

Acceptance: a reader can acquire bounded inputs, inspect their limitations, save
them, and rerun each analysis offline from the same frozen collection. Neither
example should claim causality, statistical significance or multifractality from
the starter calculations. Advanced estimators remain later work. These studies follow the paper-trading milestone.

## Goal and scope

Make IBKR convenient to use from Python for quantitative research, backtesting
and algorithmic trading. Users manually install `ibapi` and run logged-in
TWS/Gateway with the account and data permissions their requests need.

Charts support data inspection, research/backtest results and account/order performance. A standalone charting
application or TradingView replacement is outside project scope. The chart workspace,
watchlist, drawing, indicator-pane and alert UI backlog has been removed. Maintain
the existing native Canvas viewer; add visualization only for a concrete research
or backtest result, or account/order performance tracking. CI and automatic SDK
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
implemented. These support the Python data workflow. Maintain these delivered
capabilities as an optional inspection tool.

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
- [x] Display last bar receipt time and actionable connection errors
- [x] Reconnect, restore subscriptions and backfill gaps while retaining series/history

Acceptance: scaling, panning, interval changes, history loads and live updates do
not unexpectedly move the viewer's viewport. Price/time coordinates stay consistent
across both panes. Preserve existing browser regression coverage.

## Quality and release work

- Local unit, lint, typing and explicit TWS integration checks; CI is outside current scope.
- [x] Verify base wheel assets/import/export and SDK-free tests in an isolated local environment
- [ ] Verify clean installation and wheel assets on another machine
- [ ] Explicit corporate-action adjustment settings and consistent research inputs
- [ ] Test data gaps, market holidays, DST, corporate actions and research calculation correctness
- [ ] Decide release metadata, supported Python/OS matrix and dependency constraints

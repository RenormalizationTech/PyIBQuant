# PyIBQuant

**A Python-first toolkit for IBKR data access, quantitative research, backtesting and algorithmic trading, with supporting visualization.**

> PyIBQuant is an independent open-source project and is not affiliated with or endorsed by Interactive Brokers LLC.

---

### Paper execution acceptance — 2026-10-21

The owner explicitly requested agent-run bounded paper testing in this chat.
Validation after the quote-refresh fix: 850 tests, Ruff, mypy (43 source files),
source archive/wheel and isolated SDK-free smoke/CLI all pass.
The new execution paths now have TWS paper evidence:

- Cross-session equity recovery: restored `77d386816acd417e94d29b1545d9b339`
  from October 20 with two orders consumed, explicitly rolled its daily baseline,
  and automatically filled one BUY and one SELL on October 21. The original
  four-order lifetime cap is consumed, ownership reconciles flat and fees are
  complete. Today's two fills net -2.207100 USD; the whole run nets -5.434111 USD.
- Selected-option automation: `5ea6f20b6bb647918879d36711dbbfbc`, one AAPL
  2026-11-20 365 C, multiplier 100, two-order cap and six-minute bound. The
  above-SMA runner automatically filled BUY 3.25 and SELL 3.05. Gross -20 USD,
  fees 1.536883, net -21.536883; complete ledger and flat. These are paper results.
- Quiet unchanged option BBOs exposed a caller usability issue. The option example
  now makes one bounded data-subscription refresh at a new decision candle when
  otherwise valid live BBO receipts are stale. It obtains new broker callbacks;
  it never re-dates cached fields or relaxes the 15-second guard. Delayed, crossed,
  missing and disconnected inputs are not retried by this helper. The bounded run
  recorded six live completed-bar signals and six quote refreshes.
- Unknown-send reservation: check `c3eda727ed824cc28fc9e14b8e568b05`, client 297
  order 3, one send attempt. Deliberate own-socket disconnect produced UnknownSend.
  The local 339.02 USD reservation survived restart and the cancellation request.
  Exact-ID recovery canceled that same order unfilled, with no replacement;
  the reservation released to zero and reconciliation is clear.
- Both actual run checkpoints were restored from a consistent journal backup:
  paused, correct option/equity identity, consumed caps preserved, no old balances
  reused as current funds. A fresh read-only TWS preflight passed every check.
  Final account flat, zero pending reservation and no unresolved/foreign orders.

Evidence: ignored `charts/paper/acceptance-2026-10-21/summary.json` and its component
reports; original check artifacts remain under `charts/paper/cancel-checks/` and
run audits under `charts/paper/runs/`. Keep the journal and all recovery identities.
The two exhausted runs are reporting-only for normal strategy execution; do not
increase/reset their budgets to obtain more fills. Explicit owned exits remain
separate from strategy entry/resume.

Both recorded sales are held locally until October 22 under the saved conservative
policy, capped by fresh broker balances. Actual next-date release cannot be observed
on October 21. It and natural partial fills remain pending live observations;
deterministic tests cover both. Automatic broker reconnect, execution corrections
and full historical coverage remain separate backlog. No real-money account was used.

## Earlier implementation checkpoint — 2026-10-21

Historical checkpoint, superseded by the paper acceptance above.

Implemented and offline-tested: durable USD funding baseline and versioned local
settlement policy; immediate buy/fee debits, partial-fill commitments and retained
cancellation/unknown-send reservations; dated sale release capped by fresh broker
funds; replay and local transmission locking. Explicit session rollover preserves
run ownership/configuration/order budgets while recording a fresh daily P&L
baseline. The selected long-option above/below-SMA runner shares those controls,
including checkpoint restore and owned flatten. Observation remains the default.

Validation: 844 tests, Ruff, mypy (43 source files), source archive/wheel, isolated
SDK-free smoke/CLI and the synthetic offline Chrome account-report check pass.

These are code/offline-test results, not additional TWS execution acceptance.
Read-only TWS preflight passed against the existing journal on October 21:
account, order reconciliation, funding, flat starting holdings and P&L checks all
passed with transmission disabled. Evidence: ignored
`charts/paper/funding-preflight-2026-10-21.json`. A read-only selected-option
runner check resolved the contract and started, then paused on a live-quote
validity/freshness check before a completed signal; zero order intents. Summary:
`charts/paper/option-observation-2026-10-21.json`. This is a verified refusal, not
successful automated execution. At that checkpoint, bounded execution acceptance was pending; it subsequently
passed as recorded above. No order was sent during the initial offline validation. Automatic broker reconnect, full historical coverage,
execution-correction normalization and verified external cash flows remain open.
The local cash ceiling does not automatically credit external deposits/interest;
the default conservative closure calendar covers 2026–2027. See docs/API.md.



The initial IBKR-to-chart slice is implemented, with live bar updates and browser
symbol/interval/history and regular/extended-hours controls. Chart foundations now
include price/time scaling, older-history pagination, optional Parquet caching,
2-hour/4-hour/weekly/yearly intervals and New York display with automatic EST/EDT.
The renderer is our own HTML Canvas code, with no TradingView library dependency.
Provider session shading, session date ticks, an intraday countdown, receipt-time
status and automatic reconnect/backfill are also implemented. Research requests
now skip session enrichment by default; records/CSV and optional pandas exports
work independently of a chart. Local automated
and explicit TWS integration checks support development; CI and automatic SDK
installation are outside the current scope.
This remains a development prototype.

Product direction: prioritize convenient Python access to IBKR for quantitative
research, backtesting and algorithmic trading. Interactive visualization supports
those workflows. A standalone charting product or TradingView replacement is
outside project scope. The general chart workspace and charting-feature backlog
has been removed. Users supply the IBKR Python API, logged-in TWS/Gateway and
required account/data permissions; automating that setup is not a milestone.

Fixed-range data queries, basic dataset metadata and a returns/SMA research
example are now implemented with offline and live TWS validation. Frozen dataset
save/reload and explicit calendar/finality comparison are also implemented. A first
daily equity backtest now handles prior-close targets, next-open fills, fixed
whole-share sizing, configurable costs and performance accounting. The options
pilot includes stock/explicit-option Level-one snapshots, with stock
feed verification and frozen AAPL option bid/ask/model IV/Greeks verified against
TWS. Grouped option discovery and independently owned quote streams with opt-in
reconnect are implemented and verified with frozen AAPL data.
The recorded-quote options experiment and its recording/replay infrastructure have
been removed to keep the software focused on on-demand IBKR history. Selected-option
intraday history and saved-input returns/SMA research are now implemented and
verified against TWS after exchange hours. A first single-contract intraday
option backtest now runs offline with explicit synthetic next-open fills, resolved
multiplier and per-contract costs. A general bar-driven simulator now adds user
strategy callbacks, multiple explicit instruments, variable sizing/partial exits,
market-order lifecycle, replaceable execution and a shared USD portfolio ledger.
Named scientific datasets, quality reports and small dependency-free study
starters are implemented. API/documentation review, end-to-end regression and the
local `0.1.0.dev1` development snapshot are complete (checkpoint `f0f79a6`).
Current milestone: algorithmic paper trading with persistent account performance
and order tracking. Account observation, bounded AAPL strategy execution, explicit
same-day restart/recovery, cancellation and selected-option lifecycle checks are
validated. Durable settlement accounting, explicit session rollover and selected-option
automation now have offline and bounded TWS coverage. Actual next-date release,
natural partial fills, execution corrections, automatic broker reconnect and full
historical coverage remain open.
See [the staged paper-trading plan](#24-phase-6--algorithmic-paper-trading-and-account-performance).
The two worked scientific studies remain a subsequent milestone; their helpers
already exist. Advanced analysis remains user-owned.
 [TODO.md](TODO.md) orders the work.
[HANDOFF.md](HANDOFF.md) records setup, limitations, validation and where to resume.
Phase checklists distinguish delivered foundations from remaining scope. Target
API sketches are design examples; docs/API.md describes supported public APIs.

# 1. Vision

PyIBQuant aims to provide a coherent Python environment for people who:

- use Interactive Brokers (IBKR);
- want to explore and visualize market data;
- develop quantitative trading signals;
- perform systematic backtesting;
- conduct statistical and scientific market research;
- research equities, ETFs, and options;
- monitor large stock universes;
- and eventually deploy strategies through IBKR.

The long-term workflow is:

```text
Observe Market
      ↓
Visualize
      ↓
Form Hypothesis
      ↓
Research
      ↓
Develop Signal
      ↓
Backtest
      ↓
Inspect Results
      ↓
Paper Trade
      ↓
Live Trade
      ↓
Refine
```

PyIBQuant should support this entire research-to-trading loop without forcing every
experiment into a trading-strategy abstraction. Users should be able to fetch and
analyze data directly from Python. Plotting is an optional inspection step.

Near-term priority: reliable scientific datasets, multi-instrument acquisition and
loading, transparent alignment and Python exports. Existing research helpers and
backtest engines remain useful. Strategy reports are a separate backtesting
improvement. Paper-account execution and performance tracking are now the next
implementation priority. Maintain the existing chart
viewer and add visualization for concrete research/backtest results and
account/order performance tracking.

---

## Audience and options priority

Equities and ETFs provide the initial general-user workflow. Options trading and
backtesting are a major product use case and the project owner's primary personal
interest. Validate shared acquisition, research and accounting components through
a small equity backtest, while avoiding assumptions that every instrument is a
stock or every contract has a multiplier of one.

Current user direction: options research and backtesting should request available
historical data on demand from IBKR, just as equities do. Do not require live
recording, large-scale collection or an external historical provider. Existing
stock/option snapshots and independent streaming remain supporting capabilities; their further scaling and live checks do not gate research.

Explicit-contract intraday option history now supports bounded queries, all four
TRADES/MIDPOINT/BID/ASK sources, exact identity/multiplier, caching and saved-input
returns/SMA research. After-hours TWS validation passed for one completed AAPL
option session. The first bar-based option backtest is implemented for long/flat
TRADES/MIDPOINT inputs with explicit synthetic next-open execution. The basic
strategy-driven engine now supports underlying signals driving option trades,
shared cash and partial exits. Prioritize the paper-account execution and performance milestone next; keep
built-in scientific analysis small and leave advanced methods to users.
The removed recorded-quote simulator is not the historical backtest model; do not
invent sizes/Greeks/receipt timestamps for historical bars. Current chain discovery is not a historical
point-in-time chain. Expired options and option EOD history are outside IBKR's
available historical scope; unavailable inputs should fail clearly.

Selected experiments may cache or save their exact inputs for repeatability.
This is a convenient IBKR research client, not a market-data warehousing product.
Build paper execution on the delivered research/backtest foundations.

---

# 2. Relationship to `quantIBKR`

`quantIBKR` is the private predecessor and experimental IBKR repository.

Its role remains:

- minimal IBKR API experiments;
- connection tests;
- API exploration;
- personal utilities;
- proof-of-concept implementations.

PyIBQuant is the public, user-facing successor.

```text
quantIBKR
(private)
    │
    │ ideas / experiments / proven code
    ▼
PyIBQuant
(public)
```

Code from `quantIBKR` should NOT be copied blindly.

When migrating functionality:

1. inspect the existing implementation;
2. identify reusable ideas;
3. redesign interfaces where appropriate;
4. remove personal assumptions;
5. remove credentials and account information;
6. add typing;
7. add error handling;
8. add tests;
9. add documentation.

PyIBQuant should be usable by people other than the original author.

---

# 3. Project Philosophy

## 3.1 Python-first

Core functionality should remain Python-native.

Users should be able to:

```python
from pyibquant import Market

market = Market(...)
```

and perform research without needing to write JavaScript.

Browser technologies may be used internally when they provide a substantially better visualization experience.

---

## 3.2 IBKR-first, but not IBKR-locked

IBKR is the primary:

- brokerage;
- live market-data provider;
- account interface;
- paper-trading backend;
- execution backend.

However, research code should not depend directly on IBKR API objects.

The architecture should permit alternative historical-data providers.

```text
                 PyIBQuant
                     │
              Market Data API
                     │
       ┌─────────────┼─────────────┐
       │             │             │
      IBKR        Provider B    Provider C
```

IBKR is therefore the primary integration, but not necessarily the only data source.

---

## 3.3 Research-first

PyIBQuant is not merely a trading bot framework.

Research should be possible independently of strategy execution.

For example:

```python
bars = market.bars("AAPL", interval="1d", start="2025-01-01", end="2026-01-01")
dataset = BarDataset.from_series(bars)
records = dataset.to_records()
# Analyze these inputs with your chosen scientific tools.
```

should not require creating a `Strategy`.

---

## 3.4 Lightweight repository

Market data must NOT be stored in Git.

The repository should contain:

- source code;
- tests;
- examples;
- documentation;
- configuration templates;
- small synthetic/sample datasets when useful.

Large market datasets belong outside the repository.

---

## 3.5 Optional local caching

Historical data may be cached locally to avoid repeated downloads.

Conceptually:

```text
Historical Request
       │
       ▼
    Cache?
    /    \
  YES     NO
   │       │
   │    Provider API
   │       │
   └───┬───┘
       ▼
     Result
```

Caching must be optional.

A default location might be:

```text
~/.cache/pyibquant/
```

Users should be able to configure or disable it.

Live data should normally be processed in memory rather than permanently stored.

---

## 3.6 Build vertical slices

Avoid building large speculative abstractions.

Prefer:

```text
IBKR
 ↓
AAPL data
 ↓
internal representation
 ↓
browser chart
```

over simultaneously implementing:

```text
IBKR + multiple providers
+ scanner
+ options engine
+ backtester
+ ML
+ execution engine
+ cloud system
```

Implement abstractions when real use cases require them.

---

# 4. Initial Market Scope

Initial focus:

- US stocks;
- US ETFs;
- US listed options.

Examples of important underlyings include:

```text
SPY
QQQ
AAPL
MSFT
NVDA
AMZN
META
GOOGL
```

Other asset classes are not initial priorities.

---

# 5. Intended Usage Scale

PyIBQuant should eventually support three levels of market observation.

## 5.1 Broad Market Universe

Approximately the S&P 500 universe.

Typical resolution:

```text
1 minute
```

with optional:

```text
30 seconds
```

Use cases:

- market monitoring;
- market breadth;
- relative volume;
- momentum;
- realized volatility;
- sector behavior;
- cross-sectional ranking;
- correlation analysis;
- anomaly detection;
- candidate selection.

---

## 5.2 Active Trading Universe

Approximately 10 highly liquid stocks/ETFs at a time.

Typical resolution:

```text
30-second bars
```

with potentially more detailed:

- quotes;
- trades;
- spreads;
- volume;
- realized volatility;
- options information.

These instruments receive deeper analysis than the broad market universe.

---

## 5.3 Options Universe

Options research focuses on highly liquid underlyings.

Do NOT attempt to continuously process the entire US options market.

Relevant contracts can be filtered by criteria such as:

```text
DTE
moneyness
delta
liquidity
bid/ask spread
volume
open interest
```

---

# 6. High-Level Architecture

```text
                     External Providers
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
        IBKR          Historical Data    Future Provider
          │              Provider
          └─────────────────┼─────────────────┘
                            │
                       Data Layer
                            │
              ┌─────────────┴─────────────┐
              │                           │
          Live Stream              Historical Query
              │                           │
              │                    Optional Cache
              │                           │
              └─────────────┬─────────────┘
                            │
                       Market Layer
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
       Equities           Options          Universes
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
       Research          Signals        Visualization
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                        Backtesting
                            │
                        Paper Trade
                            │
                         Live Trade
```

---

# 7. Proposed Repository Structure

```text
PyIBQuant/
│
├── README.md
├── PROJECT_PLAN.md
├── LICENSE
├── pyproject.toml
├── .gitignore
│
├── src/
│   └── pyibquant/
│       │
│       ├── data/
│       │   ├── base.py
│       │   ├── cache.py
│       │   │
│       │   └── providers/
│       │       ├── ibkr/
│       │       └── ...
│       │
│       ├── market/
│       │   ├── bars.py
│       │   ├── quotes.py
│       │   ├── trades.py
│       │   ├── universe.py
│       │   ├── option_contract.py
│       │   ├── option_chain.py
│       │   └── option_surface.py
│       │
│       ├── indicators/
│       │
│       ├── signals/
│       │   ├── market/
│       │   ├── equity/
│       │   └── options/
│       │
│       ├── research/
│       │   ├── timeseries/
│       │   ├── cross_sectional/
│       │   ├── volatility/
│       │   └── options/
│       │
│       ├── backtest/
│       │   ├── engine.py
│       │   ├── strategy.py
│       │   ├── portfolio.py
│       │   ├── orders.py
│       │   ├── execution.py
│       │   └── metrics.py
│       │
│       ├── visualization/
│       │   ├── charts/
│       │   └── options/
│       │
│       ├── monitor/
│       │   └── scanner.py
│       │
│       └── trading/
│           └── ibkr/
│
├── examples/
│   ├── data/
│   ├── visualization/
│   ├── research/
│   ├── backtesting/
│   └── options/
│
├── notebooks/
│
└── tests/
```

This structure is a direction, not a requirement.

Do not create empty modules simply to reproduce this tree.

---

# 8. Data Provider Design

Provider-specific APIs should be hidden behind PyIBQuant interfaces.

Avoid exposing code like:

```python
ib.reqHistoricalData(...)
```

throughout the project.

Prefer:

```python
bars = market.bars(
    "AAPL",
    start="2026-10-01",
    end="2026-10-15",
    interval="1min",
)
```

Internally:

```text
market.bars()
     │
     ▼
DataProvider
     │
     ├── IBKR
     ├── cache
     └── other provider
```

The user-facing API should remain stable when the backend changes.

---

# 9. Canonical Market Data

## Bars

Minimum bar fields:

```text
symbol
timestamp
open
high
low
close
volume
interval
```

Useful metadata may include:

```text
provider
timezone
currency
session
adjustment
```

---

## Quotes

Possible representation:

```text
symbol
timestamp
bid
ask
bid_size
ask_size
```

Derived quantities may include:

```text
mid
spread
relative_spread
```

---

## Trades

Possible representation:

```text
symbol
timestamp
price
size
exchange
```

Only implement detailed trade data when required.

---

# 10. Options as First-Class Objects

Options should NOT simply be represented as strange ticker symbols.

Important concepts:

```text
Underlying
OptionContract
OptionChain
OptionQuote
OptionTrade
OptionSurface
```

## OptionContract

Potential fields:

```text
underlying
expiration
strike
right
multiplier
exchange
provider_contract_id
```

## OptionQuote

Potential fields:

```text
timestamp
bid
ask
bid_size
ask_size
last
volume
open_interest
```

## Option Analytics

Potential values:

```text
implied_volatility
delta
gamma
theta
vega
```

Always distinguish:

```text
provider-supplied values
```

from:

```text
PyIBQuant-derived values
```

---

# 11. Option Surface

A major long-term research object should be:

```text
OptionSurface
```

representing approximately:

\[
IV = f(m, T, t)
\]

where:

\[
m = \log(K/S)
\]

and:

- \(K\) = strike;
- \(S\) = underlying price;
- \(T\) = maturity;
- \(t\) = observation time.

Potential API:

```python
surface = market.options.surface(
    "AAPL",
    timestamp=...
)

surface.smile(dte=30)
surface.skew(dte=30)
surface.term_structure(moneyness=0)
```

Potential research topics:

- volatility smile dynamics;
- volatility skew;
- IV term structure;
- IV versus realized volatility;
- option-volume anomalies;
- surface response to underlying movement;
- cross-strike dynamics;
- cross-expiration dynamics.

---

# 12. Visualization

Visualization is an optional tool for inspecting source data, research signals,
backtest entries/exits and equity curves. Maintain the existing native Canvas
viewer and its delivered interactions. Result plots may be added for concrete
research, backtesting or account/order performance needs.

A standalone charting platform is outside project scope. Saved chart workspaces,
watchlist UI, drawing tools, general indicator panes, synchronized multi-chart
layouts, chart alerts and appearance/export feature expansion are not roadmap
items. Account performance and order views are in scope. See [TODO.md](TODO.md)
for current priorities.

---

# 13. Market Monitor

PyIBQuant should eventually monitor approximately the S&P 500 universe.

Conceptually:

```text
Ticker   Return   RelVol   RV      Signal
------------------------------------------------
NVDA     +2.1%     2.4    High     Momentum
AAPL     +0.8%     1.3    Normal   -
META     -1.2%     2.0    High     Watch
...
```

Potential signals include:

- intraday return;
- relative volume;
- realized volatility;
- moving-average distance;
- unusual movement;
- sector-relative strength.

The monitor identifies candidates through Python data and ranking outputs.
A watchlist or chart dashboard UI is outside scope.

It should not initially execute trades automatically.

---

# 14. Scientific Research Data Layer

Scientific research is independent of strategy execution. Users may study
correlations, scaling/multifractality, random-matrix connections and other market
phenomena without producing trading signals. PyIBQuant should provide useful,
well-described IBKR datasets; users supply advanced scientific methods.

Prioritize explicit instruments/ranges, resolved identities, original OHLCV and
missing volume, source/adjustment/session semantics, bounded pacing/cache reuse,
frozen persistence, visible errors and coverage limits, and transparent alignment.
Do not build a large statistical framework or infer missing prices, corporate
history, exchange calendars, historical chain membership or bar finality.

Implemented: `BarDataset` for individual frozen inputs and `BarDatasetCollection`
for named multi-instrument bundles, atomic save/reload, exact bar-start inner/outer
alignment, records/optional pandas export and per-input alignment provenance.
`describe()`/`quality_report()` expose recorded semantics, observation flags,
per-input calendar/finality assertions and alignment blockers. `Market.datasets()`
coordinates named bounded requests; `BarRequest` selects per-input sources/exchanges
and failures retain the named input, completed datasets and original cause.
A small descriptive Pearson starter is now implemented alongside daily return
panels and intraday log-increment/moment preparation. Advanced correlation models,
multifractal methods and random-matrix estimators remain user-owned. Benchmark comparisons, parameter studies and out-of-sample evaluation
belong to the backtesting layer.

---

# 15. Signal Architecture

Signals may eventually exist at three levels.

## Market Signals

Examples:

- breadth;
- correlation regime;
- market volatility;
- sector behavior;
- market regime.

## Equity Signals

Examples:

- momentum;
- mean reversion;
- relative volume;
- realized volatility;
- price/volume anomaly.

## Option Signals

Examples:

- IV-RV spread;
- skew;
- term structure;
- unusual volume;
- volatility-surface movement.

Strategies may combine signals:

```text
Market Context
      +
Equity Signal
      +
Option Signal
      ↓
Trading Decision
```

---

# 16. Backtesting

The backtesting engine should eventually support:

- intraday data;
- stocks;
- ETFs;
- options;
- multiple instruments;
- commissions;
- slippage;
- bid/ask execution;
- portfolio accounting;
- signal logging;
- trade history;
- performance metrics.

Initial versions should focus on equities and ETFs.

Do NOT start by building a sophisticated options backtester.

---

# 17. Strategy API

One long-term goal is to reuse strategy logic across:

```text
Backtest
   ↓
Paper Trading
   ↓
Live Trading
```

Possible future interface:

```python
class Strategy:

    def on_start(self, context):
        ...

    def on_bar(self, context, bar):
        ...

    def on_signal(self, context, signal):
        ...
```

Do NOT finalize the strategy API until at least two real strategies have
been implemented.

Real use cases should drive the abstraction.

---

# 18. Development Roadmap

## Phase 0 — Public Repository Foundation

**Goal:** Establish a clean open-source Python project.

### TODO

- [ ] Create `PyIBQuant` GitHub repository
- [x] Choose license (Apache-2.0)
- [x] Add IBKR non-affiliation disclaimer
- [x] Create `pyproject.toml`
- [x] Use `src/pyibquant/` package layout
- [x] Add `.gitignore`
- [x] Add `README.md`
- [x] Add `PROJECT_PLAN.md`
- [ ] Add `CONTRIBUTING.md` later, when contributor guidance is needed (deferred)
- [x] Configure `pytest`
- [x] Configure `ruff`
- [x] Configure type checking
- CI and automatic SDK installation: outside current scope; run checks locally.
- [x] Establish Python version policy
- [ ] Verify no credentials or private information are committed

---

# 19. Phase 1 — Minimal IBKR Market Data

**Goal:** Establish the first complete vertical slice.

```text
IBKR
 ↓
PyIBQuant
 ↓
Normalized Data
 ↓
Python User
```

### TODO

- [x] IBKR connection manager
- [x] connection configuration
- [x] contract resolution
- [x] historical bar requests
- [x] live bar updates via historical-data subscription; independent Level-one quote streams also implemented
- [x] normalized timestamps
- [x] canonical bar representation
- [x] structured exceptions
- [x] basic reconnect handling and fresh gap backfill for active bar subscriptions
- [x] unit tests without requiring live IBKR
- [x] integration tests clearly separated from unit tests

### Target API

```python
from pyibquant import Market

market = Market.ibkr(...)

bars = market.bars(
    "AAPL",
    interval="1min",
    duration="1D",
)
```

---

# 20. Phase 2 — Interactive Visualization

**Goal:** Inspect market data and research results with supporting charts.

```text
IBKR
 ↓
Market Data
 ↓
PyIBQuant
 ↓
Interactive Browser Chart
```

### TODO

- [x] candlestick chart
- [x] volume
- [x] zoom
- [x] pan
- [x] interval display

The delivered viewer is maintained for inspection. General charting expansion
has been removed from the roadmap; research/backtest result plots and account
performance/order views are scoped with those workflows.

Implemented CLI:

```bash
pyibquant chart AAPL
```

This should open an interactive browser visualization.

---

# 21. Phase 3 — Historical Cache

**Goal:** Avoid unnecessary repeated API requests.

### TODO

- [x] cache interface
- [x] configurable cache directory
- [x] cache enable/disable
- [x] historical-query caching
- [x] cache metadata
- [x] cache invalidation policy
- [x] cache inspection
- [x] cache clearing

Implemented as an optional exact-query Parquet cache. Live subscriptions bypass
it; older pages can reuse entries. Fixed-end queries expire after 24 hours by
default and relative snapshots after at most five minutes. See README for
configuration, refresh, metadata inspection and scoped cache clearing.

Initial storage format:

```text
Parquet
```

Do NOT introduce a database server.

---

# 22. Phase 4 — Scientific Research Datasets

**Goal:** Supply dependable IBKR inputs for user-owned scientific experiments.

- [x] Bounded historical requests and records/CSV/optional pandas exports
- [x] Frozen dataset persistence, provenance and explicit calendar/finality audits
- [x] Named multi-instrument collection persistence with integrity checks
- [x] Explicit inner/outer timestamp alignment, visible missing values and source metadata
- [x] Sequential acquisition and offline collection inspection example
- [x] Verify a small AAPL/MSFT/SPY acquisition against TWS and reload/export offline
- [x] Dataset/collection description and quality reports without implicit repair or certification
- [x] Named collection requests with per-input source/exchange selectors and explicit failures
- [x] Verify mixed equity/selected-option acquisition and offline quality reports against TWS
- [x] Small standard-library daily return/correlation and intraday increment/moment starters
- [x] Fresh IBKR input verification of both workflows without new dependencies
- [ ] Further preparation driven by concrete study requirements; advanced estimators stay user-owned

Small existing returns/SMA helpers remain useful conveniences. Advanced scientific
analysis is not a prerequisite or a planned framework. Resampling and further
transformations require explicit future scope and preserved semantics.

```python
collection = BarDatasetCollection.load("inputs.collection.json")
aligned = collection.align(field="close", join="outer")
records = aligned.to_records()
# Use your chosen scientific tools; missing observations remain explicit.
```

---

# 23. Phase 5 — Backtesting v1

**Goal:** Test equity/ETF signals systematically.

### TODO

- [x] minimal strategy interface
- [x] positions
- [x] orders
- [x] cash
- [x] portfolio accounting
- [x] commissions
- [x] simple slippage
- [x] trade history
- [x] performance metrics
- [ ] visualize trades on existing charts

Do not attempt to simulate an entire exchange.

---

# 24. Phase 6 — Algorithmic Paper Trading and Account Performance

Priority updated 2026-10-19: this is the next implementation milestone, ahead of
worked scientific studies. The owner authorizes development and integration tests
against the current paper account. Real-money trading remains outside this scope.
Implementation checkpoint 2026-10-19: initial account monitoring/reporting, guarded
paper order code and a completed-bar runner are implemented. Account acquisition and
live-data observation are verified; the owner reports successful paper liquidation
and a one-share AAPL entry. Shared order waits, tagged cancellation, reconciliation
reports, persistent fill ownership/export and owned flatten have offline regression
coverage. Versioned process restore now preserves identity, limits and the session
baseline, returns paused and reconciles before explicit resume. Account reports
include fill-derived per-run P&L, costs, exposure and observed dollar drawdown with
offline journal replay and CSV exports. Completed-order recovery, corrections,
broker restart integration and strategy execution across sessions remain acceptance work.
The October 20 checkpoint below supersedes this initial status. Unchecked items
describe remaining scope, including partially implemented requirements.

Bounded-equity acceptance checkpoint 2026-10-20: the owner completed a ten-minute
AAPL run with fills, then restarted/resumed its process while preserving fill
ownership, loss baseline and the four-order cap. The fourth fill closed the held
share; a fifth submission was blocked. A separate resting-order check then passed
broker acknowledgment, unfilled cancellation, flat reconciliation and released
pending reservation. The initial saved-profile/preflight/execution/reporting setup
is validated. Broader multi-session, broker-restart, correction and settlement
edge-case requirements below remain separate from this bounded acceptance. Later
October 20 checks also validated a 30-minute AAPL run, execution pause/resume,
disconnect-after-send exact-ID recovery without replacement, owned flattening,
exact-identity completed-order recovery, and selected long-option buy/sell and
unfilled cancellation. Automated option strategies remain unimplemented.

## Outcome and boundaries

Run a tested Python strategy in an IBKR paper account, track every order and fill,
and inspect persistent cash, net liquidation value and P&L histories. Account and
order performance charts are part of trading observability. The standalone
charting-platform backlog remains removed.

The validated runner uses one selected paper account, USD reporting, one US equity
and whole shares, long/flat. Selected long-option limit orders now reuse the shared
broker lifecycle with resolved identity/multiplier and expiry restrictions; they
now have an initial underlying-driven above/below-SMA runner with offline and
bounded TWS buy/sell evidence. Actual next-date release and natural partial fills
remain live acceptance gaps.
Existing positions in any instrument must remain visible even when the first
runner cannot trade them. Multi-leg options, shorting, margin strategies and live
accounts require later scope. Do not liquidate pre-existing positions implicitly.

## Architecture

Keep `Market` and its data-only adapter separate from a broker connection with a
dedicated client ID. Implemented modules include `broker.py` (public immutable state and
commands), `trading/ibkr.py` (SDK adapter), `trading/journal.py` (durable events),
`trading/runner.py` (strategy orchestration) and `trading/performance.py` (reports).
These modules contain the implementation; see docs/API.md for supported
entry points and experimental execution limitations.

The broker owns account subscriptions, order IDs, order/fill state and recovery.
The runner consumes independently owned market data and emits order intents through
the broker. A serialized event loop processes strategy decisions; network callback
threads enqueue events without running user strategy code. The journal supplies
account reports and a localhost performance viewer. Browser refresh or navigation
must never drive strategy decisions, stop feeds or own broker state.

Reuse pure signal calculations and instrument identity. Do not reuse simulated
fills, cash or order statuses as broker truth, and do not promise the simulator's
`Context` is already suitable for asynchronous execution.

## Shared paper/live execution and funding policy

Requirement clarified 2026-10-19: paper trading is a rehearsal for real trading.
Use the same strategy runner, order lifecycle, reconciliation, funding checks and
performance definitions in both environments. Environment/account selection is
explicit configuration; the first implementation permits paper only. Future live
activation requires separate authorization and validation, not a second strategy
implementation. Paper fills/clearing behavior are not evidence of live fill quality
or exact funding enforcement.

The intended live account type must be recorded separately from the paper account's
reported type. A margin paper account must not silently supply margin capacity to
a strategy intended for a cash account. Start with an explicit settled-cash-only,
no-borrowing policy; support a margin policy separately if requested.

- [x] P1: capture account type, total cash, settled cash, available funds and buying
  power distinctly, including currency, timestamps, source and missing-field status.
  Account value and total cash alone are not an executable spending budget.
- [x] P2: evaluate spendable funds before each supported new limit buy, including
  fee allowance and the submitted limit price; serialize checks/commitments.
  Quantity/price amendments are unsupported and require separate scope.
- [x] Track local commitments against an independent durable cash ceiling, capped
  by fresh broker fields rather than subtracting holds from broker funds again. Partial fills reduce
  remaining reservations; pending cancellations retain the remaining hold until
  confirmed. Unknown send outcomes retain their commitments until resolved.
- [x] For the cash-only policy, exclude recorded unsettled sale proceeds. Maintain dated,
  currency-specific settlement obligations and reconcile with broker settled funds;
  never treat a sell fill or realized profit as immediately spendable by default.
  Any local estimate must not loosen broker restrictions. Unknown/stale funding
  data blocks new exposure, with a visible reason.
- [x] Version local settlement rules by product, market and effective date; default
  conservative US/USD STK/OPT T+1 with bounded 2026–2027 closure coverage. US stock/ETF
  regular-way settlement is generally T+1 business day; account for settlement
  holidays rather than adding 24 hours. Do not hardcode the same rule for options,
  FX or other markets. Formal clearing settlement and IBKR's displayed settled-cash
  availability are distinct: the current TWS guide lists T+0 options availability
  for US/Canadian/Mexican/Indian markets. Verify account/product behavior; a stricter
  local policy is allowed when explicit, not described as the broker's rule.
- [ ] If margin is later enabled, enforce broker available funds, margin requirements,
  excess liquidity and configured exposure/borrowing limits. Unsettled proceeds are
  not universally blocked in a margin account. Broker acceptance remains decisive;
  local checks cannot guarantee acceptance or simulate all house restrictions.
- [x] Show total, settled, unsettled and locally reserved cash plus usable strategy
  budget in the account report; label local estimates and incomplete coverage.
- [x] Offline tests cover same-day sell/rebuy blocking, unused settled-cash
  purchases, next-business-day release, holidays, fees, two simultaneous orders,
  partial fills, cancellation races, restart and missing/stale funding snapshots.
- [ ] Validate the new settlement ledger and explicit session rollover against TWS.

Funding references checked 2026-10-19:

- [SEC T+1 investor bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin)
- [IBKR account balances and settled cash](https://www.ibkrguides.com/traderworkstation/account-balances.htm)
- [IBKR cash and margin account configurations](https://www.interactivebrokers.com/en/accounts/configuring-your-account.php)
- [IBKR paper simulator limitations](https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/)

### Funding distinction and implementation status

A cash account and a margin account whose strategy avoids borrowing are different
funding configurations. Margin may allow reuse of unsettled proceeds; avoiding a
debit balance does not turn it into a cash account. Broker `AccountType` can describe
legal structure rather than cash/margin financing, so it is not sufficient proof.
`BuyingPower` is not universal order-specific approval. The first implementation
uses broker fields and a stricter settled-cash/no-borrowing cap, serializes to one
unresolved owned order, and refreshes funds before each submission. Its durable local
funding ledger now applies a deliberately stricter
versioned T+1 policy to US stock and selected-option sales; it does not claim to
reimplement IBKR settlement availability. It validates the USD
`SettledCashByDate` date:balance entries and selects today's balance from single-
or multi-date schedules, blocking missing, malformed or ambiguous values. A full dated
local settlement ledger is implemented with offline coverage. Advanced margin
policy, verified external cash flows, actual next-date release and natural partial
fills remain open.

## P1 — Account observation and durable performance history

- [x] Discover managed accounts, select one explicitly and establish its paper
  identity from the configured paper session/account mapping. A port number or
  account-name prefix alone is not proof; reject ambiguity and live targets.
- [x] Download initial account values, positions and visible orders with explicit
  completion barriers. Report partial/timeout states rather than an empty portfolio.
- [x] Subscribe to account values and account P&L; retain currency, source, receipt
  timestamps and per-field freshness. Normalize unset values to missing, never zero.
- [x] Capture cash (`TotalCashValue`), net liquidation value, available funds,
  buying power, gross position value, daily/realized/unrealized P&L and positions.
  Keep currencies distinct and use broker base-currency totals for account charts.
- [x] Persist raw normalized events and materialized snapshots transactionally in
  a local standard-library SQLite journal outside Git. Use schema versions,
  session IDs, account IDs, sequence numbers and UTC timestamps; mask account IDs
  in shareable reports. Flush on orderly stop and recover after interrupted writes.
- [x] Show cash and account-value curves, separate P&L curves, current positions,
  visible open orders and connection/freshness status in a focused localhost view;
  provide offline HTML/CSV reporting from the same persisted history.

Acceptance: compare displayed fields to TWS during a market session, restart the
observer without losing history, and show a visible gap during disconnect. A flat
account is a valid result. Account monitoring works before order placement is enabled.

Account history starts when observation starts. TWS callbacks are not a complete
historical account statement service. Account-value callbacks and P&L have different
cadences/reset semantics; faster chart refresh does not create fresher broker data.
Record broker P&L separately from change since the local session baseline. Net
liquidation change is not trading profit when deposits, withdrawals, paper resets,
FX or external trades contribute. Record known external cash flows; publish an
adjusted profit/return only when flows and coverage are verified. Otherwise label
value changes and incomplete return attribution explicitly. P&L resets must not be
summed into a fictitious cumulative curve. Start a new baseline after paper resets.

## P2 — Paper order lifecycle and reconciliation

- [x] Allocate IDs from `nextValidId` and observed order IDs, persist local intent
  before sending, and track account/client/order ID, broker permanent ID, order
  reference, strategy ID and run ID. Market-data request counters are not order IDs.
- [x] Submit/cancel DAY limit orders for the initial equity scope; provide explicit
  holding-only market sells (market buys remain unsupported);
  preserve broker acknowledgement, held/rejected/inactive reasons, partial fills,
  remaining quantity, execution IDs and late commission/fee reports.
- [ ] Deduplicate callbacks and executions; tolerate missing/repeated/out-of-order
  status updates and execution corrections. Submission success is not a fill.
  A cancellation request is not cancellation confirmation; fills may race it.
- [x] Separate account-wide visibility from strategy-owned orders. Report which
  clients/manual orders are visible and which are controllable; never imply a
  snapshot of all open orders grants cancellation rights or continuous coverage.
- [ ] At start/reconnect, reconcile open/completed orders, available executions and
  positions before enabling submissions. Missing historical coverage stays explicit.
  Ambiguous send outcomes enter an unresolved state; never blindly resubmit them.
- [x] Add order/fill tables and timestamped submission/fill/cancel/rejection events
  to performance reports, including fees, strategy/run filters and position changes.

Acceptance: a bounded paper buy/sell round trip reconciles with TWS executions and
positions; a resting limit order is canceled and its final state verified. Repeated
callbacks and a disconnect after send do not cause duplicate orders or counted fills.
Record actual effects and final holdings rather than assuming every test fills.

## P3 — Strategy runner and explicit controls

- [x] Independent bar subscriptions, completed-bar events and caller-visible
  session/calendar/late-update policy; warmup bars must never trigger stale orders.
- [x] Run one already backtested intraday equity strategy with explicit quantity,
  symbol, session hours, parameters and starting holdings policy.
- [ ] Process live partial fills and outstanding orders when converting target
  positions into new orders; prevent duplicate decisions for one completed bar.
- [x] Implement start, pause, stop and cancel-owned-orders separately. Stop blocks
  new decisions; cancellation is explicit; flattening is a separate command.
- [x] Enforce configured order quantity/notional, position/exposure, outstanding
  order and submission-rate limits; evaluate fresh account/data state and reject
  delayed/frozen/stale decision inputs. Daily-loss limits use a defined P&L baseline.
- [x] On disconnect, stale data or reconciliation mismatch, pause new submissions.
  Reconcile before an explicit resume. Journal configuration, code version,
  signals, risk decisions, order intents and resulting broker events.

Acceptance: a bounded market-session run produces traceable decisions and broker
orders, obeys pause/stop/limits, and remains independent of viewer navigation.
A profitable run is not an acceptance condition.

## P4 — Performance attribution and selected options

- [ ] Report account value, cash, gross/net exposure, P&L, verified cash-flow-adjusted
  returns and drawdown; distinguish broker account totals from strategy attribution.
- [x] Attribute owned fills, fees, positions and P&L by strategy/run. Existing and
  manual positions stay in an external/unattributed bucket; do not assign the
  account's entire P&L to one strategy. Broker account totals remain authoritative.
- [x] Selected long-option limit orders: exact contract/multiplier, fresh bid/ask,
  tick-valid limits and expiry-day refusal; bounded buy/sell and cancellation validated.
- [ ] Validate natural option partial fills and implement additional lifecycle handling
  only within explicit scope. The selected-option SMA runner is offline-tested;
  broader option strategies remain separate.
- [ ] Compare paper executions and costs with the same strategy's backtest under
  recorded assumptions; evaluate behavior across multiple sessions.

## Implementation sequence and local validation

Implement P1 first, then P2, then P3; account charts and the order log evolve with
these stages. P4 follows a working equity end-to-end path. Do not delay P1/P2 for
scientific studies or chart workspace work.

Use deterministic fake-callback tests for lifecycle races, partial downloads,
missing values, late fees, restart, reconciliation and P&L baselines; keep existing
research/backtest tests passing. Exercise explicit paper integration checks during
available market hours, with recorded quantities and before/after state. No test
should require a particular profit or market move. SDK compatibility must cover
both the documented minimum and the installed version where signatures differ;
the inspected local SDK is 10.50.2, including its commission-and-fees callback and
`OrderCancel` cancellation object.

Existing market-data-only setup keeps TWS Read-Only API enabled. P1 can remain
read-only. P2 requires disabling that setting in the verified paper session;
account selection and order controls belong in the execution API itself. Reconnect
must not use the data-recovery path to replay order requests.

API references checked for planning:

- [IBKR account updates](https://www.interactivebrokers.com/docs/tws-api/doc/account-portfolio-data/account-updates/requesting-account-updates)
- [IBKR placing orders](https://www.interactivebrokers.com/docs/tws-api/doc/quick-start/placing-orders)
- [IBKR order identity and modification](https://www.interactivebrokers.com/docs/tws-api/doc/orders/modifying-orders)
- [IBKR P&L semantics (legacy reference)](https://interactivebrokers.github.io/tws-api/pnl.html)

---

# 25. Phase 7 — Broad Market Monitor

**Goal:** Monitor approximately the S&P 500 universe.

### TODO

- [ ] universe abstraction
- [ ] S&P 500 universe implementation
- [ ] efficient concurrent data handling
- [ ] market scanner
- [ ] ranking
- [ ] configurable refresh intervals

Initial scanner signals:

```text
return
relative volume
realized volatility
moving-average distance
```

---

# 26. Phase 8 — Options Foundation

**Goal:** Make options a first-class component.

### TODO

- [x] Explicit `Option` selector and resolved `OptionQuote` contract identity
- [x] `OptionChain`
- [x] contract discovery
- [x] Exact expiry/strike candidate selection within discovered chain groups
- [ ] Convenience range filters for expirations and strikes
- [ ] moneyness calculations
- [x] Initial US equity/ETF option snapshots and selected-contract quote streams
- [ ] Full option-chain quote snapshots beyond selected-contract acquisition
- [x] implied volatility representation
- [x] Greeks representation

Future convenience API (current API: `Market.option_chain()` and `OptionChain.select()`):

```python
chain = market.options.chain("AAPL")

selected = chain.filter(
    dte=(7, 60),
    moneyness=(0.8, 1.2),
)
```

---

# 27. Phase 9 — Options Visualization and Research

### TODO

- [ ] IV smile
- [ ] volatility skew
- [ ] term structure
- [ ] option volume
- [ ] open interest
- [ ] Greeks visualization
- [ ] option-surface representation
- [ ] surface snapshots
- [ ] IV versus realized-volatility research

---

# 28. Phase 10 — Options Backtesting

Only begin once historical options representation is understood.

### TODO

- [ ] historical option-chain interface
- [ ] point-in-time contract selection
- [ ] expiration handling
- [x] First single-contract long/flat synthetic next-open execution model (TRADES/MIDPOINT)
- [ ] bid/ask modeling
- [ ] exercise
- [ ] assignment
- [ ] multi-leg positions
- [ ] option-specific P&L attribution

---

# 29. Historical Data Scope — IBKR Only

The current software uses IBKR historical requests on demand for supported
instruments, including selected unexpired options using bounded intraday queries.
Availability, permissions and broker limitations define the scope. Do not add
external providers, mandatory archives or broad option-market ingestion under the
current plan. Keep provider-specific logic inside the existing IBKR boundary.

Optional caching and saved experiment inputs are useful, but users should not need
to operate a continuous recorder. No expired-option history or historical chain
reconstruction is promised. IBKR's option end-of-day limitation also means the
initial option-history workflow should use supported intraday requests.

---

# 30. Non-Goals for Early Releases

Do NOT prioritize:

- high-frequency trading;
- microsecond execution;
- full order-book reconstruction;
- distributed computing;
- custom database infrastructure;
- cloud infrastructure;
- standalone charting platforms and TradingView replication;
- hundreds of technical indicators;
- every brokerage;
- cryptocurrency;
- every asset class;
- entire US options-market ingestion;
- automatic live trading;
- AI trading agents.

Keep the early project focused.

---

# 31. Rules for Coding Agents

Any coding agent working on PyIBQuant should follow these rules.

## Before changing code

1. Read `README.md`.
2. Read `PROJECT_PLAN.md`.
3. Inspect the existing architecture.
4. Search for existing related functionality.
5. Inspect relevant predecessor code in `quantIBKR` when available.
6. Understand the current task before introducing abstractions.

## During implementation

- Make small, reviewable changes.
- Add tests with new functionality.
- Use type hints.
- Prefer simple implementations.
- Avoid unnecessary dependencies.
- Avoid global mutable state.
- Keep provider-specific logic inside provider modules.
- Do not expose IBKR objects through general public APIs.
- Never commit credentials.
- Never commit IBKR account identifiers.
- Never commit private logs.
- Never commit large market datasets.
- Avoid premature optimization.
- Avoid speculative abstractions.

## Architecture rule

Code outside the IBKR integration should depend on:

```text
PyIBQuant abstractions
```

rather than:

```text
IBKR API objects
```

## Architecture readiness for research and execution

The existing provider boundary, immutable `Bar` values, `BarSeries.snapshot()`,
UTC/date normalization and optional chart imports are useful foundations. Keep
those pieces. The prototype now includes research datasets, equity/option backtests, independent
quotes, account monitoring and experimental paper broker/runner APIs. Bounded
AAPL execution, explicit same-day recovery and selected-option lifecycle checks
are validated; broader recovery/accounting remains unfinished.
Preserve the implemented boundaries and address the remaining ones incrementally:

- Implemented: research requests skip session enrichment by default;
  `include_sessions=True` opts in. Charts enable it explicitly. Records/CSV exports
  and optional pandas DataFrames provide independent snapshots. Explicit dataset
  bounds/basic metadata, frozen reload, caller-supplied calendar audits and finality
  assertions are implemented. The equity runner consumes completed bars independently
  of the browser. Automatic data-finality certification remains future work.
- Fixed-range downloads now release the Market control lock and fail with partial
  data if their provider generation disconnects. Subscription cancellation stays
  responsive. Legacy data lookback loads/recovery still serialize operations; broker
  order/cancel controls use a separate connection.
- Chart selection cancels the prior chart subscription. The equity runner owns a
  separate Market connection, so chart navigation cannot stop its feed. Keep
  multi-symbol research independent of the single-chart HTTP session.
- Live candles are replaceable snapshots. The equity runner implements completed-bar
  decisions, warmup exclusion and a persisted decision cursor; preserve those
  semantics when extending user-defined or option strategies. Browser polling/countdowns are
  presentation only and must not drive strategy execution.
- Frozen `BarDataset` files provide independent offline research inputs with
  integrity checks and fingerprints. Keep these inputs
  separate from the exact-query cache, which remains an acquisition optimization
  rather than a merged historical research database.
- The separate broker execution component owns order IDs, acknowledgements,
  partial-fill callbacks, positions, reconciliation and user controls. The current
  data-only reconnect/resubscribe path must not be reused to resubmit orders.

Develop these changes through the next research/backtest/paper-trading slices;
there is no need to rebuild the renderer or introduce a general framework first.
Keep local correctness tests and explicit IBKR integration tests.

## Definition of Done

A task is complete when:

- implementation works;
- tests pass;
- new public behavior is documented;
- reasonable errors are handled;
- typing remains consistent;
- no credentials/private information are introduced;
- unrelated code has not been unnecessarily modified.

---

# 32. v0.1 Foundation — Implemented Prototype

The first slice established IBKR data access, immutable bar snapshots, optional
caching, live updates/recovery and a supporting chart. It is a foundation for the
Python workflow. Continued chart polish is not the next release gate.

Existing API (requires the documented IBKR setup for data acquisition):

```python
from pyibquant import Market

with Market.ibkr() as market:
    series = market.bars("AAPL", interval="1min", duration="1 D")
    bars = series.snapshot()

# Python analysis can consume these immutable values after the connection closes.
closes = [bar.close for bar in bars]
# series.plot() is optional inspection.
```

---

# 33. Implemented — Research Data and First Equity Backtest

Records/CSV and optional pandas exports, opt-in session enrichment, explicit
historical start/end queries with paging/pacing, basic dataset metadata, and
simple-return/SMA research calculations are implemented. The research-range example
is verified with synthetic inputs and live TWS data (2026-10-16).
Frozen datasets now save/reload atomically with integrity checks and preserved
provenance. An offline research example consumes them without the SDK or optional
dependencies. Calendar comparisons require caller-supplied expected bar starts;
finality requires an explicit caller assertion. Exchange calendar generation and
automatic finality certification are not implemented.
The first daily equity backtest is now implemented with long/flat boolean targets,
fixed whole-share sizing, prior-close/next-open timing and configurable flat
commission/adverse slippage. It requires complete fixed-range input and caller
confirmation of finality. An optional expected calendar rejects gaps. Both
above-SMA and SMA-crossover strategies validate the API. Fills/trades/rejections,
cash/positions/equity, returns and drawdown are exported with assumptions and an
exact input fingerprint. The following path now works through performance results;
optional result charts remain on the backlog:

```text
IBKR historical dataset
        ↓
Python research signal
        ↓
Equity backtest with explicit execution timing and costs
        ↓
Trade log, equity curve and performance metrics
        ↓
Optional result chart
```

Validate the API with one or two simple strategies before generalizing it. Research
calculations and backtests consume collected datasets; they must not depend on an
open chart or a continuously connected broker. Data acquisition still requires
the user's IBKR setup and permissions. Data/research APIs above are implemented;
the daily backtest engine and basic performance accounting above are implemented.
The recorded-quote option simulator was removed. The first historical-bar option
engine now consumes complete saved intraday TRADES/MIDPOINT inputs, with resolved
multiplier, next-open synthetic fills and per-contract costs. Expiry-day bars and
BID/ASK-only execution remain outside this model.
The general long-only shared-cash portfolio simulator is also implemented.
Broader option lifecycle models and broker controls remain planned.

---

# 34. Later Target — User-Controlled Paper Trading

The IBKR historical-data research/backtest foundation, including selected options,
is delivered. The next milestone reuses signal calculations with an IBKR paper
broker (see section 24), while keeping historical simulation and broker execution separate. Implement order IDs, order/fill state,
position/cash reconciliation, explicit start/stop/cancel controls, and reconnect
handling before moving toward live execution. Chart navigation must not control
strategy subscriptions or order lifecycle. This target can reuse the first equity
backtest foundation; it does not depend on chart feature parity. The stock/option
quote foundation and historical option research/backtest are implemented (section 35).
The superseded capture experiment was removed. Offline simulation consumes bounded
IBKR historical inputs; broader execution models and broker prerequisites remain.

---

# 35. Options Foundation and Historical Research

Implemented: explicit Option selectors, exact stock/option contract resolution,
immutable quote snapshots with requested/reported feed type and available IV/Greeks,
grouped option-chain discovery, and independently owned quote streams. Stream
reconnect preserves ownership/cursors, clears accumulated fields and retains gap
history. Frozen acquisition and reconnect passed explicit TWS checks. These tools
remain useful for contract selection/inspection and future strategy feeds.

Removed: sampled JSONL recording, rotating capture, disk-backed recording replay,
receipt-based option simulation and their dedicated examples/tests. These were an
experimental branch of the workflow; Git commit `59da0e5` preserves the source.
Their generated recording/test datasets were removed during scope cleanup.

Implemented: selected unexpired option intraday history via `Market.bars(Option(...),
start=..., end=..., data_type=...)`, preserving exact identity/multiplier, source,
range/coverage and query-specific caching. Shared paging/pacing remains bounded.
BID/ASK/MIDPOINT volume stays unavailable rather than becoming zero. Saved datasets
feed broker-independent returns/SMA research. After-hours TWS checks on 2026-10-16
returned 78 five-minute bars per source for AAPL 2026-11-20 340 C; cache reuse and
offline reload passed. Local checks: 289 tests, Ruff, mypy and Chrome regression.

Implemented: first single-contract option long/flat backtest, requiring explicit
synthetic next-open execution and caller-confirmed finality. It preserves multiplier,
source, frozen-input fingerprint and costs in its accounting/reports. Both example
strategies passed offline on saved TRADES/MIDPOINT AAPL inputs. Local validation:
336 tests plus typing/style checks. Integer-valued datasets now retain the same
fingerprint on save/reload. No broker request was needed for this slice.

Named scientific datasets and lightweight study starters are implemented.
Backtest performance reports and improved execution models remain a separate backlog.
No live recorder or huge local collection is required. The option model does not
reconstruct executable bid/ask fills, lifecycle settlement, adjusted deliverables
or historical chain membership. BID/ASK-only and expiry-day inputs are rejected.
IBKR's unavailable expired-option/EOD history and historical Greeks remain outside
scope. Paper execution, exercise/assignment, multi-leg models and broad surfaces
remain later work driven by supported research requirements.

---

# 36. Long-Term Goal

The eventual PyIBQuant experience should look approximately like:

```python
from pyibquant import Market, Research, Backtest

market = Market.ibkr()

# Observe
spy = market.bars("SPY", interval="1min")

# Visualize
spy.plot()

# Research
signal = Research.some_signal(spy)

# Backtest
result = Backtest(
    signal=signal,
    data=spy,
).run()

# Inspect
result.summary()
result.plot()
```

For options:

```python
chain = market.options.chain("SPY")

surface = chain.iv_surface()

surface.plot()

skew = surface.skew(dte=30)
```

And eventually:

```python
strategy.paper_trade()
```

followed, only with explicit user action and appropriate safeguards, by
live IBKR execution.

---

# 37. Core Principle

Every major PyIBQuant feature should contribute to this loop:

```text
          ┌───────────────┐
          │    Observe    │
          └───────┬───────┘
                  ↓
          ┌───────────────┐
          │   Visualize   │
          └───────┬───────┘
                  ↓
          ┌───────────────┐
          │   Research    │
          └───────┬───────┘
                  ↓
          ┌───────────────┐
          │    Signal     │
          └───────┬───────┘
                  ↓
          ┌───────────────┐
          │   Backtest    │
          └───────┬───────┘
                  ↓
          ┌───────────────┐
          │  Paper Trade  │
          └───────┬───────┘
                  ↓
          ┌───────────────┐
          │  Live Trade   │
          └───────┬───────┘
                  │
                  └──────────→ Observe
```

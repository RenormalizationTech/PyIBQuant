# PyIBQuant

**A Python-first toolkit for IBKR data access, quantitative research, backtesting and algorithmic trading, with supporting visualization.**

> PyIBQuant is an independent open-source project and is not affiliated with or endorsed by Interactive Brokers LLC.

---

## Implementation checkpoint — 2026-10-16

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
those workflows. A standalone charting product or TradingView replacement is not
the current objective. Users supply the IBKR Python API, logged-in TWS/Gateway and
required account/data permissions; automating that setup is not a milestone.

Fixed-range data queries, basic dataset metadata and a returns/SMA research
example are now implemented with offline and live TWS validation. Frozen dataset
save/reload and explicit calendar/finality comparison are also implemented. A first
daily equity backtest now handles prior-close targets, next-open fills, fixed
whole-share sizing, configurable costs and performance accounting. The options
pilot includes stock/explicit-option Level-one snapshots, with stock
feed verification and frozen AAPL option bid/ask/model IV/Greeks verified against
TWS. Grouped option discovery, independently owned quote streams and sampled
recording/offline replay are now implemented and verified with frozen AAPL data.
The user chose our collected recordings for the first options backtest. An offline
intraday simulator now uses later observed ask/bid fills, costs, recorded multipliers
and explicit freshness/size checks. In-session live capture and offline simulation
were verified on 2026-10-16, including conservative skipped fills and unknown
valuations when price receipts age despite size/Greek updates.
Broker-connected paper execution
remains planned.
 [TODO.md](TODO.md) orders the work.
[HANDOFF.md](HANDOFF.md) records setup, limitations, validation and where to resume.
Later phases below remain plans, not implemented APIs.

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

Near-term order: reliable historical datasets and Python exports, reusable research
calculations, a small equity backtester, result inspection, then paper-trading
integration. Expand chart/workspace features when a research or trading use case
needs them.

---

## Audience and options priority

Equities and ETFs provide the initial general-user workflow. Options trading and
backtesting are a major product use case and the project owner's primary personal
interest. Validate shared acquisition, research and accounting components through
a small equity backtest, while avoiding assumptions that every instrument is a
stock or every contract has a multiplier of one.

Prioritize a stock/option streaming quote API and a focused options pilot after
the shared data/equity-backtest slice. It need not wait for broad-universe scanners,
advanced chart workspaces or feature parity. Start with option contract identity,
bid/ask/spread, available IV/Greeks and collection of selected quotes. Add historical
option dataset imports, explicit spread/fill models and expiry/exercise/assignment
handling as requirements for an options backtest. Acquisition from IBKR and import
of research datasets remain separate paths; do not promise reconstruction of
expired option histories from IBKR. Sampled quote recordings only represent the
updates the application receives.

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
bars = market.bars(...)

returns = research.log_returns(bars)

correlation = research.correlation(returns)
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
│       │   ├── dashboard/
│       │   └── options/
│       │
│       ├── monitor/
│       │   ├── scanner.py
│       │   └── watchlist.py
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

PyIBQuant should provide browser-based interactive visualization.

Visualization is a supporting tool for inspecting source data, research signals,
backtest entries/exits, equity curves and trading context. Keep the existing native
Canvas renderer useful, but prioritize the Python research/backtesting workflow
over chart parity, saved workspaces or a standalone charting application.
Follow the priorities in [TODO.md](TODO.md).

## Market Chart

Initial features:

- candlesticks;
- volume;
- zoom;
- pan;
- configurable interval;
- indicator overlays;
- signal markers.

Later:

- multiple panels;
- synchronized charts;
- trade markers;
- research annotations;
- live updates.

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

The monitor identifies candidates.

It should not initially execute trades automatically.

---

# 14. Research Layer

Research code must remain independent of trading strategies.

Example:

```python
bars = market.bars(...)

returns = research.log_returns(bars)

rv = research.realized_volatility(returns)
```

Potential future areas include:

```text
time series
statistics
cross-sectional analysis
correlation
volatility
options
spectral analysis
machine learning
```

Do NOT create these modules until concrete research requires them.

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
- [x] live bar updates via historical-data subscription (continuous tick quote subscriptions remain future work)
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
- [ ] indicator overlays
- [ ] signal markers

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

# 22. Phase 4 — Research Primitives

**Goal:** Support serious quantitative experiments.

### TODO

- [ ] arithmetic returns
- [ ] log returns
- [ ] rolling statistics
- [ ] realized volatility
- [ ] resampling
- [ ] multi-symbol alignment
- [ ] trading-session handling
- [ ] missing-data handling
- [ ] basic correlation analysis

Example:

```python
dataset = market.bars(
    symbols=["AAPL", "MSFT", "NVDA"],
    ...
)

returns = dataset.log_returns()
```

---

# 23. Phase 5 — Backtesting v1

**Goal:** Test equity/ETF signals systematically.

### TODO

- [ ] minimal strategy interface
- [ ] positions
- [ ] orders
- [ ] cash
- [ ] portfolio accounting
- [ ] commissions
- [ ] simple slippage
- [ ] trade history
- [ ] performance metrics
- [ ] visualize trades on existing charts

Do not attempt to simulate an entire exchange.

---

# 24. Phase 6 — Paper Trading

Only strategies that have already been tested should reach this stage.

### TODO

- [ ] broker abstraction
- [ ] IBKR broker implementation
- [ ] order state management
- [ ] reconciliation
- [ ] disconnect recovery
- [ ] structured logging
- [ ] risk/safety controls
- [ ] paper-account testing

Live automated trading is explicitly out of scope until paper trading is
robust.

---

# 25. Phase 7 — Broad Market Monitor

**Goal:** Monitor approximately the S&P 500 universe.

### TODO

- [ ] universe abstraction
- [ ] S&P 500 universe implementation
- [ ] watchlist manager
- [ ] efficient concurrent data handling
- [ ] market scanner
- [ ] ranking
- [ ] dashboard
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

- [ ] `OptionContract`
- [ ] `OptionChain`
- [ ] contract discovery
- [ ] expiration filtering
- [ ] strike filtering
- [ ] moneyness calculations
- [x] Initial US equity/ETF option snapshots and selected-contract quote streams
- [ ] Full option-chain quote snapshots beyond selected-contract acquisition
- [ ] implied volatility representation
- [ ] Greeks representation

Target API:

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

- [ ] interactive option-chain table
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
- [ ] option execution model
- [ ] bid/ask modeling
- [ ] exercise
- [ ] assignment
- [ ] multi-leg positions
- [ ] option-specific P&L attribution

---

# 29. Future Historical Data Providers

IBKR should not be assumed to provide every historical research dataset.

Potential future providers may include services specializing in:

- historical equity bars;
- historical quotes/trades;
- historical options;
- point-in-time market data.

Provider implementations should plug into the common data interface.

Do not add providers merely for completeness.

Add them when a real research requirement justifies them.

---

# 30. Non-Goals for Early Releases

Do NOT prioritize:

- high-frequency trading;
- microsecond execution;
- full order-book reconstruction;
- distributed computing;
- custom database infrastructure;
- cloud infrastructure;
- full TradingView replication;
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
those pieces. The prototype now includes research datasets, daily equity backtests
and intraday recorded-option simulations. It has no broker trading-control API.
Preserve the implemented boundaries and address the remaining ones incrementally:

- Implemented: research requests skip session enrichment by default;
  `include_sessions=True` opts in. Charts enable it explicitly. Records/CSV exports
  and optional pandas DataFrames provide independent snapshots. Explicit dataset
  bounds/basic metadata, frozen reload, caller-supplied calendar audits and finality
  assertions are implemented. Automatic finality certification and completed-bar
  strategy events remain future work.
- Fixed-range downloads now release the Market control lock and fail with partial
  data if their provider generation disconnects. Subscription cancellation stays
  responsive. Legacy lookback loads/recovery still serialize operations; future
  broker controls must keep their own responsive path.
- Chart selection currently cancels the prior chart subscription. Give chart and
  strategy consumers independent ownership so navigation cannot stop a strategy's
  feed. Keep multi-symbol research independent of the single-chart HTTP session.
- Live candles are replaceable snapshots. Define bar-update versus completed-bar
  events, event time/order, historical replay and partial-bar policies before
  sharing signals between backtest and live use. Browser polling/countdowns are
  presentation only and must not drive strategy execution.
- Frozen `BarDataset` files and `QuoteRecording` files provide independent offline
  inputs with integrity checks and fingerprints. Keep these research inputs
  separate from the exact-query cache, which remains an acquisition optimization
  rather than a merged historical research database.
- Add a separate broker execution component for order IDs, acknowledgements,
  partial fills, positions, reconciliation and user controls. The current
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
The first intraday recorded-option simulation is also implemented (section 35).
Portfolio simulation, broader option lifecycle models and broker controls remain planned.

---

# 34. Following Target — User-Controlled Paper Trading

Reuse signal calculations with an IBKR paper broker, while keeping historical
simulation and broker execution separate. Implement order IDs, order/fill state,
position/cash reconciliation, explicit start/stop/cancel controls, and reconnect
handling before moving toward live execution. Chart navigation must not control
strategy subscriptions or order lifecycle. This target can reuse the first equity
backtest foundation; it does not depend on chart feature parity. The stock/option
quote and options research pilot has since been implemented (section 35);
live-session capture and offline simulation were verified on 2026-10-16.
Broader live fill/valuation checks and execution prerequisites remain before broker execution.

---

# 35. Options Pilot and Later Expansion

Implemented first step: `Market.quote()` returns an immutable Level-one snapshot
using reqMktData with regulatory snapshots disabled. Stocks and explicit US
equity/ETF option selectors are supported; ambiguous contracts are rejected and
actual multipliers retained. Requested/reported feed type, delayed tick IDs,
local receipt times, missing/crossed quotes and partial entitlements remain
explicit. Available bid/ask/last/model computations are kept separately.
Stock live verification passed. The selected SPY 2026-11-20 770 C contract
resolved but returned error 10091 (SPY ARCA/TOP/ALL) without bid/ask/Greeks. The
user then selected AAPL 2026-11-20 340 C: its frozen snapshot returned bid/ask
and model IV/Greeks with confirmed frozen feed type. The overnight live request
returned no prices; subsequent in-session live streams returned bid/ask, sizes
and model IV/Greeks on 2026-10-16. SDK-normalized None
Greeks and unset Decimal sizes are now handled without disconnecting or inventing
large sizes. No subscription or account settings were changed.
The following foundation is now also implemented:

- `Market.option_chain()` uses reqSecDefOptParams and preserves exchange, trading
  class and multiplier partitions. Expiry/strike sets describe candidates, not
  guaranteed combinations; selected options still resolve exactly before quoting.
- `Market.stream_quote()` provides independent subscription handles, immutable
  observations and per-consumer sequence cursors. No browser polling or user/file
  callback runs on the IBKR reader thread. Mixed requested feed modes on a single
  active connection are rejected. Disconnects end default handles; opt-in
  `reconnect=True` restores exact resolved contracts in empty generations with
  persistent gap history and new feed confirmation. Permission failures stay terminal.
  Local recovery checks pass; live recovery verification is blocked by IBKR 10197.
- `record_quotes()` samples on the caller's thread, preserves field receipt times
  and records unchanged observations. Versioned JSONL includes identity, sampling
  and feed provenance, a completion/error footer and integrity digest.
  `QuoteRecording.load()` replays without SDK/optional dependencies; incomplete
  input requires opt-in and checksum failures are rejected. Quality reports do
  not certify executable quotes or exchange quote age.

AAPL verification returned 41 chain groups and recorded 12 frozen observations,
10 with bid/ask and 9 with model IV/delta. This verifies acquisition/recording,
not an exchange tick archive or live trading-session coverage. Live capture and
simulation were subsequently verified as recorded below. Quote reconnect is now
implemented with local checks; chart bid/ask enrichment and historical imports remain planned.
The user chose our collected recordings for the first backtest.

`pyibquant.option_backtest.backtest_option()` is now a standard-library intraday
long/flat simulator for one resolved option. Boolean targets act only at a later
sample with a new side-price receipt after the signal and configurable latency.
Buys use ask plus slippage, sells bid minus slippage; costs are per contract and
actual recorded multipliers are retained. Local receipt age/skew and displayed
size gate fills; no borrowing or partial fills. Unchanged targets preserve pending
intents. Unpriced open positions remain unknown rather than forward-filled.
Only complete, confirmed-live, same-New-York-date recordings strictly before
expiry qualify; frozen/delayed data, excessive sample gaps and terminal states
are rejected. Initial unknown-feed samples are ineligible. This does not model
exchange quote age, queue priority, market impact or guaranteed liquidity.
`examples/backtest_option.py` runs hold-window or spread-filter demonstrations
and exports exact input bytes, input-fingerprinted results/assumptions, strategy settings
and fill/trade/skip/equity CSV logs without TWS/SDK/optional dependencies.
Live intraday recordings and offline replay were verified on 2026-10-16; frozen
AAPL data remains diagnostic replay input. Continue live fill/valuation checks
and live reconnect verification after the competing-live-session error is resolved.
An explicit `quote_age_basis="side_update"` policy now uses matching live size
receipts at/after each side's price, without rewriting price timestamps. It retains
post-signal causality, size/age/skew checks and the original strict default. Both
live recordings produced a complete simulated round trip under that explicit
policy, with some intermediate valuations/drawdown still unknown. New recording
format version 2 retains gap/generation history and loads legacy version 1 inputs;
the simulator rejects reconnect gaps. Exercise, assignment, overnight carry and
settlement remain outside this initial simulator.


Options trading/backtesting is an explicit product priority. After the shared
research/equity-backtest foundation, introduce a stock/option quote API and an
options pilot with contract discovery, bid/ask/spread, available IV/Greeks and
selected quote collection. This can precede broad-market monitoring; the phase
catalog above does not require implementing scanners before the options pilot.

Full options backtesting follows suitable historical datasets, fill/cost models,
contract multipliers and expiry/exercise/assignment behavior. Broad universes,
advanced surfaces and chart workspaces follow concrete workflow needs.

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

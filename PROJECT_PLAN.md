# PyIBQuant

**A Python quantitative research, visualization, backtesting, and algorithmic trading platform for Interactive Brokers users.**

> PyIBQuant is an independent open-source project and is not affiliated with or endorsed by Interactive Brokers LLC.

---

## Implementation checkpoint — 2026-10-15

The initial IBKR-to-chart slice is implemented, with live bar updates and browser
symbol/interval/history controls. The renderer is our own HTML Canvas code, with
no TradingView library dependency. This remains a development prototype.

The visualization goal has expanded to a daily charting workspace that can replace
TradingView for frequent IBKR US stock/ETF usage. Deliver it incrementally; full
parity is not a v0.1 requirement. [TODO.md](TODO.md) is the detailed visualization
backlog. [HANDOFF.md](HANDOFF.md) records setup, limitations, validation and where
to resume. Later phases below remain plans, not implemented APIs.

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

PyIBQuant should support this entire research-to-trading loop without forcing every experiment into a trading-strategy abstraction.

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

The visualization direction is an independently designed daily charting workspace
for IBKR stock/ETF traders, integrated with quantitative research. It should
eventually replace TradingView for that workflow. Do not attempt full feature
parity before useful releases; follow the milestones in [TODO.md](TODO.md).

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
- [ ] Configure GitHub Actions
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
- [x] live bar updates via historical-data subscription (tick quotes remain future work)
- [x] normalized timestamps
- [x] canonical bar representation
- [x] structured exceptions
- [ ] basic reconnect handling
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

**Goal:** Make PyIBQuant immediately useful.

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

- [ ] cache interface
- [ ] configurable cache directory
- [ ] cache enable/disable
- [ ] historical-query caching
- [ ] cache metadata
- [ ] cache invalidation policy
- [ ] cache inspection
- [ ] cache clearing

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

# 24. Phase 6 — Broad Market Monitor

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

# 25. Phase 7 — Options Foundation

**Goal:** Make options a first-class component.

### TODO

- [ ] `OptionContract`
- [ ] `OptionChain`
- [ ] contract discovery
- [ ] expiration filtering
- [ ] strike filtering
- [ ] moneyness calculations
- [ ] option quotes
- [ ] option-chain snapshots
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

# 26. Phase 8 — Options Visualization and Research

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

# 27. Phase 9 — Options Backtesting

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

# 28. Phase 10 — Paper Trading

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

# 32. v0.1 Target

Do NOT attempt to implement the entire roadmap before releasing something useful.

The first release should do one thing very well:

> Connect to IBKR, obtain market data, and visualize it interactively.

A successful v0.1 should support something conceptually like:

```python
from pyibquant import Market

market = Market.ibkr()

aapl = market.bars(
    "AAPL",
    interval="1min",
    duration="1D",
)

aapl.plot()
```

The result should be an interactive browser chart with:

- candlesticks;
- volume;
- zoom;
- pan.

That is enough for v0.1.

---

# 33. v0.2 Target

Add the first complete research loop:

```text
Get historical data
        ↓
Compute signal
        ↓
Backtest signal
        ↓
Calculate performance
        ↓
Plot trades
```

Use one or two simple strategies to validate the architecture.

The purpose is not to develop profitable strategies.

The purpose is to make sure the research/backtesting abstractions work.

---

# 34. v0.3 Target

Introduce broad-market monitoring:

```text
S&P 500
   ↓
Market scanner
   ↓
Signals / ranking
   ↓
Watchlist
   ↓
Detailed chart
```

---

# 35. v0.4 Target

Introduce options:

```text
Underlying
    ↓
Option Chain
    ↓
Contract Selection
    ↓
IV / Greeks
    ↓
Option Visualization
```

Options should only be introduced after the core equity data model has
proven stable.

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

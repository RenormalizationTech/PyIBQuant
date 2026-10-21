# PyIBQuant documentation

Start with the [quick start](QUICKSTART.md). It runs without an IBKR account,
then shows how to replace synthetic bars with a small historical download.
If you want real daily prices without TWS, use the
[Yahoo Finance guide](YAHOO.md) for installation, charts and Python examples.

These docs describe the implemented `0.1.0.dev1` snapshot, not planned features.

| I want to… | Read |
|---|---|
| Install and run my first example | [Quick start](QUICKSTART.md) |
| Download real daily prices without TWS | [Yahoo Finance data](YAHOO.md) |
| Look up market data, bars, datasets, quotes or caching | [Core API reference](API.md) |
| Start testing a strategy step by step | [Strategy lab](STRATEGY_LAB.md) |
| Calculate signals, run studies or simulate a strategy | [Research and simulation API](RESEARCH.md) |
| Inspect a paper account or understand runner/order arguments | [Paper trading API](PAPER_TRADING.md) |
| Try features one at a time and diagnose failures | [Manual testing guide](MANUAL_TESTING.md) |
| Understand advanced funding, recovery and execution workflows | [Operational workflows](WORKFLOWS.md) |
| Find complete command-line programs | [Examples directory](https://github.com/RenormalizationTech/PyIBQuant/tree/main/examples) |

## How the pieces fit

```text
Market (connected) ──bars()──> BarSeries (mutable, optionally live)
                                  │
                         BarDataset.from_series()
                                  │
                                  v
                         BarDataset (frozen, offline)
                                  │
                     save/load, audit, research, backtest

Market.datasets() ──> BarDatasetCollection ──align()──> AlignedData
Market.quote() / stream_quote() ──> Quote (separate from historical bars)
PaperBroker ──> account snapshots, durable journal, experimental paper orders
```

A **bar** contains open, high, low, close and volume (OHLCV) for one interval.
A **series** can change as callbacks arrive. A **dataset** freezes rows and their
provenance (source, contract, request and download metadata) for reuse.
A **collection** gives datasets your own labels, such as `apple` or `benchmark`.
A **quote** contains independently received bid/ask/last fields; it is not a bar.

Examples marked **offline** need only Python and this package. **IBKR data**
examples need the official SDK and logged-in TWS/Gateway. **Paper execution**
examples can send orders when explicitly enabled. Documentation work and offline
tests do not require running any broker integration checks.

In signatures, `*` means following arguments must be passed by name. `None` means
an absent value, not zero. Paths are relative to your current working directory
unless stated otherwise. Commands assume the repository root and an activated
virtual environment. Generated examples use the Git-ignored `charts/` directory.


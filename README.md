# PyIBQuant

[![Docs](https://github.com/RenormalizationTech/PyIBQuant/actions/workflows/docs.yml/badge.svg?branch=main)](https://renormalizationtech.github.io/PyIBQuant/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

A Python toolkit for Interactive Brokers market data, reproducible research,
backtesting and experimental paper trading. An optional Yahoo Finance preview
provides daily US stock/ETF data without TWS.

PyIBQuant is an independent project and is not affiliated with or endorsed by
Interactive Brokers. This is a development snapshot (`0.1.0.dev1`).

## Get started

Python 3.11+ is required. From this checkout:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python examples/quickstart_offline.py
```

The walkthrough creates synthetic candles, exports a chart/CSV, saves and reloads
datasets, and runs two offline simulations with known results. No account or
broker connection is needed.

For real daily prices without TWS:

```sh
python -m pip install -e '.[yahoo]'
python -m pyibquant chart SPY --provider yahoo --interval 1d --duration '1 Y'
```

Yahoo currently supports adjusted daily previews and simple calculations. The
strict backtest APIs require qualifying IBKR datasets or explicitly synthetic
fixtures; see the [Yahoo guide](docs/YAHOO.md) for the current limitations.

## Documentation

- [Documentation home](docs/README.md): concepts and learning path
- [Quick start](docs/QUICKSTART.md): offline examples and IBKR setup
- [Yahoo Finance without TWS](docs/YAHOO.md): charts, Python downloads and exports
- [Backtesting guide](docs/BACKTESTING.md): built-in strategies, results and custom rules
- [Strategy validation checklist](docs/STRATEGY_LAB.md): tasks from first backtest to bounded paper runs
- [Core API](docs/API.md): arguments and examples for market data, datasets and quotes
- [Research and simulation](docs/RESEARCH.md): indicators, backtests and custom callbacks
- [Paper accounts and runners](docs/PAPER_TRADING.md): observation, execution and recovery APIs
- [Paper operating guide](docs/WORKFLOWS.md): setup, funding, stopping and exact-ID recovery
- [Manual feature checks](docs/MANUAL_TESTING.md): expected behavior and troubleshooting

## What is implemented

| Workflow | Support |
|---|---|
| Historical acquisition | IBKR equity/ETF bars and selected bounded intraday option history |
| Reusable research inputs | Frozen datasets/collections, fingerprints, coverage reports and exact timestamp alignment |
| Calculations | Returns, moving averages, daily descriptive correlations and intraday increment studies |
| Backtesting | Daily fixed-size equities, selected intraday long options and a callback-driven USD portfolio simulator |
| Market observation | Stock/option snapshots, quote streams, live equity bars and optional charts |
| Paper trading | Read-only accounts/reports, bounded experimental equity/selected-option orders and SMA runners |

IBKR access requires the official manually installed TWS Python API SDK and a
logged-in TWS/Gateway with the necessary permissions. Historical downloads do not
require an open trading session. Quotes, live updates and paper execution have
separate freshness/session requirements. See the [quick start](docs/QUICKSTART.md).

Paper brokers and runners default to observation. Orders require explicit
execution settings. Stopping does not liquidate filled holdings. Real-money
execution, shorting, margin strategies, option rolling and exercise/assignment are
outside the implemented scope. Synthetic fills do not establish executable prices
or live execution quality.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for checks, architecture and documentation
preview/publishing instructions. [CHANGELOG.md](CHANGELOG.md) lists development
changes; [TODO.md](TODO.md) tracks remaining work. Generated account journals,
reports, charts, caches and local profiles belong under the ignored `charts/`
directory and must not be committed.

License: [Apache 2.0](LICENSE).

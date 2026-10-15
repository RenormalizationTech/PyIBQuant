# PyIBQuant

A Python quantitative research, visualization, backtesting, and algorithmic trading platform for Interactive Brokers users.

## Project documents

- [Development handoff](HANDOFF.md): setup on another machine, current architecture and limitations
- [Visualization TODO](TODO.md): completed work and ordered next milestones
- [Project plan](PROJECT_PLAN.md): research-to-trading vision and overall phases

## First slice: IBKR → Python → HTML chart

Retrieve US stock/ETF bars through the official TWS API, then display candles and
volume using PyIBQuant's own HTML Canvas renderer, with no third-party chart library.
Charts support zoom, pan, crosshair OHLCV, a synchronized volume pane, and optional
live bar updates. This is the initial market-data slice of [the plan](PROJECT_PLAN.md).

### Setup

Python 3.11+ and a running, logged-in TWS or IB Gateway are required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Install the **official TWS Python API 10.33+** from the
[IBKR API download](https://interactivebrokers.github.io/), following its license
and installation instructions. Install the `source/pythonclient` directory from
that download into the same virtual environment:

```sh
python -m pip install "/path/to/TWS API/source/pythonclient"
python -c 'from ibapi import get_version_string; print(get_version_string())'
```

The old `ibapi` distribution on PyPI is not the supported SDK; it is deliberately
excluded from automatic dependencies. Install the SDK in the new virtual environment;
see [HANDOFF.md](HANDOFF.md) for the versions used during local validation.

In TWS **Global Configuration → API → Settings**, enable **ActiveX and Socket
Clients**, allow localhost, and leave **Read-Only API** enabled. The adapter
requests contract details and market data only.

| Application | Paper port | Live port |
|---|---|---|
| TWS | 7497 | 7496 |
| IB Gateway | 4002 | 4001 |

Use a unique client ID for each concurrent API application. Defaults are
`127.0.0.1:7497`, client ID `71`. Data permissions depend on the instrument and
your IBKR subscriptions; historical bars and live updates can require different
permissions. Delayed data is not substituted automatically.

### HTML snapshot

```sh
pyibquant chart AAPL --interval 1min --duration '1 D'
```

This opens `charts/chart.html` in your browser, then disconnects from IBKR.
Use `--output /path/to/chart.html` to choose a destination or `--no-browser` to
save without opening. Generated charts contain market data; `charts/` is ignored
by Git. The renderer is embedded in each HTML export, so saved charts work offline
and make no external network requests.

Scroll or pinch to zoom, drag to pan, and move the pointer for crosshair OHLCV.
Double-click or choose **Fit data** to show the full history. **Latest** follows
new bars while preserving your zoom. Focus the chart to use arrow keys for pan,
`+`/`-` for zoom, `Home` to fit, and `End` for latest. Both panes share the time
axis; the price scale adjusts to the visible candles.

### Live bar chart

```sh
pyibquant chart AAPL --interval 1min --duration '1 D' --live
```

This serves the chart on a free localhost port and keeps the IBKR subscription
open. The browser checks the in-memory bars every two seconds; IBKR determines
the actual bar-update cadence. Keep the command running and press Ctrl+C to
cancel subscriptions and disconnect. Use `--web-port 8050` for a fixed HTTP port.
The displayed subscription status does not guarantee real-time entitlements;
provider warnings appear above the chart. Disconnects are shown in the chart;
restart the command to reconnect. Automatic reconnect is not implemented yet.

On the connected page, enter a **Symbol**, select an **Interval**, set **History**
(for example `1 D`, `2 W`, or `6 M`), and click **Load chart** or press Enter.
Successful requests replace the chart and cancel the previous live subscription.
Failed requests leave the previous chart available and show the provider error.
Requests retain the initial command's regular/extended-hours setting. Saved HTML
snapshots display disabled controls with instructions for opening a connected chart.

More examples:

```sh
pyibquant chart SPY --interval 1d --duration '6 M'
pyibquant chart MSFT --interval 5min --extended-hours --port 4002 --client-id 72
pyibquant chart AAPL --primary-exchange NASDAQ --no-browser
```

Supported intervals: `30s`, `1min`, `5min`, `15min`, `30min`, `1h`, `1d`.
Duration accepts IBKR units such as `1 D`, `2 W`, `6 M`, and `1 Y`.
IBKR's bar-size/duration limits and pacing rules still apply; requests are not
automatically split into multiple downloads.

### Python

```python
from pyibquant import Market

with Market.ibkr() as market:
    aapl = market.bars("AAPL", interval="1min", duration="1 D")
    aapl.plot()

with Market.ibkr(client_id=72) as market:
    aapl = market.bars("AAPL", interval="1min", duration="1 D", live=True)
    market.serve(aapl)
```

`aapl.snapshot()` returns immutable `Bar` values; repeated timestamps replace
the current candle. Intraday timestamps are UTC-aware datetimes, while daily bars
retain their trading-session dates. The chart shows intraday times in UTC.
`aapl.plot()` always exports a snapshot, including when called on a live series.
The context manager closes subscriptions and the connection on exit.

### Development checks

```sh
python -m pytest
ruff check src tests examples
mypy
```

Offline tests simulate provider callbacks; they do not connect to an account.
The optional browser regression checks offline rendering, interaction, resizing,
and live viewport behavior using generated synthetic bars and installed Google
Chrome. No TWS connection or existing chart export is needed:

```sh
python -m pip install -e '.[browser]'
python tests/browser_chart_check.py
```

With the live chart running on `--web-port 8050`, the separate manual integration
check `python tests/browser_controls_check.py` verifies symbol/interval changes,
invalid input, and recovery against TWS. It leaves the chart on AAPL daily bars.

Install the official SDK before running provider tests. For an explicit manual
integration check with TWS running:

```sh
pyibquant chart AAPL --duration '1 D' --no-browser
```

The implementation draws on `../QuantIBKR/examples/historical_market_data.py`,
`ChartApp.py`, and `backtest/ibdata.py`. The predecessor is not a runtime dependency.

## Disclaimer

PyIBQuant is provided for research and educational purposes only.

It is not financial, investment, or trading advice. Trading financial
instruments involves risk and may result in financial loss.

Users are solely responsible for validating strategies, data, and order
execution before using the software with real capital.

PyIBQuant is an independent open-source project and is not affiliated with,
endorsed by, or sponsored by Interactive Brokers LLC.

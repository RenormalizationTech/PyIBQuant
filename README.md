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
axis. Prices automatically scale to the visible candles by default.

Drag the right-hand **price axis** vertically to stretch/compress prices and enter
manual scaling, or click **Autoscale: on** to freeze the current price range.
With autoscale off, dragging the price pane pans both time and price; dragging
volume pans time only. Manual price bounds survive updates, zooming, **Latest**,
and resizing. Click **Autoscale: off** or double-click the price axis to restore
automatic scaling without changing the time view. **Fit data**, `Home`, or a
double-click inside the chart resets both axes. Loading a new chart also resets
both axes. On a focused chart, `A` toggles autoscale and up/down arrows enter
manual mode and pan prices; left/right arrows pan time.

Drag the bottom **time axis** horizontally to widen/narrow candle spacing.
Double-click that axis to fit the time range while keeping manual price scaling.
Choose **Right space** (0–40%, default 10%) to leave room after the latest candle.
**Latest** follows incoming bars with that space and keeps your candle spacing.
When viewing older bars, updates preserve the time viewport. Right space also
works in saved snapshots and stays selected when loading another symbol or
interval; it is a page setting and resets on reload. Hovering blank space shows
a crosshair without inventing a future trading time or OHLCV values.

On a connected chart, **pan toward the oldest loaded candles** to fetch an earlier
page automatically, or click **Load older**. Candle spacing, the candles in view,
manual prices and right space stay in place when data is prepended. You can still
navigate while a download is running. Overlapping timestamps are deduplicated,
existing live candles retain their newer values, and the live subscription remains
open. Other tabs sharing the server receive the extended history on their next poll.

Downloads are serialized with chart selection, and rapid repeats are throttled.
If a request fails, the current chart stays available; **Retry older history**
starts an explicit retry. When a page returns no earlier data, automatic loading
and the button stop for that chart; this is not a guarantee of IBKR's earliest
available date. Reload the symbol with a wider History if needed. Saved HTML
snapshots contain only the downloaded bars and cannot fetch more.

Older pages use bounded lookbacks rather than repeatedly expanding the initial
query: one week for 30-second/1-minute bars, one month for 5-minute bars, three
months for 15-minute through 4-hour bars, one year for daily bars, five years for
weekly bars and ten years of monthly inputs for yearly candles. IBKR pacing,
permissions and retention limits still apply. Loaded history is kept in memory;
History/`--duration` continues to show the initial lookback.

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
Choose **Trading hours → Include extended hours** to request premarket and
after-hours bars, then click **Load chart**. Regular hours is the default;
`--extended-hours` sets the initial selection. The chart header identifies the
active session setting, and older pages use the same setting. Availability
depends on the instrument and IBKR data permissions. Saved HTML
snapshots display disabled controls with instructions for opening a connected chart.

More examples:

```sh
pyibquant chart SPY --interval 1d --duration '6 M'
pyibquant chart MSFT --interval 5min --extended-hours --port 4002 --client-id 72
pyibquant chart AAPL --primary-exchange NASDAQ --no-browser
```

Supported intervals: `30s`, `1min`, `5min`, `15min`, `30min`, `1h`, `2h`, `4h`,
`1d`, `1w`, `1y`. Interval is the size of each candle; History/`--duration` is
the total lookback. For example:

```sh
pyibquant chart AAPL --interval 2h --duration '1 M'
pyibquant chart AAPL --interval 4h --duration '3 M'
pyibquant chart SPY --interval 1w --duration '2 Y'
pyibquant chart AAPL --interval 1y --duration '10 Y'
```

Yearly candles combine IBKR monthly OHLCV bars by calendar year because the
[TWS API's native bar sizes](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars)
stop at one month. They use the first monthly open, highest high, lowest low,
last close and summed volume. Monthly inputs use calendar-month identities, so
changing provider period-end dates and live replacements never count a month
twice. Weekly/yearly source requests extend beyond the requested lookback when
needed to obtain complete starting periods, then discard earlier unrequested
buckets. History selects the weeks/years that intersect that lookback. The
current year and an instrument's first available year may still be partial;
a notice stays visible on yearly charts. Use multi-year History such as `10 Y`.
Weekly candles use Monday anchors; yearly candles use January 1 and year labels.
These are period identities, not claims that trading occurred on those dates.
Daily/coarser bars are date-only.

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

Within an open `Market` connection, `market.load_older(aapl)` fetches one earlier
page into the same series and returns the number of new candles. For yearly
charts a page can add source months to the oldest year without adding a new
annual candle. `aapl.history_exhausted` indicates that no earlier source data was
returned. Live monthly updates retain the newly loaded yearly inputs.

`aapl.snapshot()` returns immutable `Bar` values; repeated timestamps replace
the current candle. Intraday timestamps are UTC-aware datetimes, while daily bars
retain their trading-session dates. The chart displays intraday times in New York
(`America/New_York`), with automatic EST/EDT changes. Daily, weekly and yearly
labels retain their calendar dates.
`aapl.plot()` always exports a snapshot, including when called on a live series.
The context manager closes subscriptions and the connection on exit.

### Optional historical cache

Caching is off by default and adds no dependency to the base package. Install
the optional Parquet support to enable it:

```sh
python -m pip install -e '.[cache]'
pyibquant chart AAPL --interval 1d --duration '6 M' --cache
pyibquant chart AAPL --live --cache-dir /path/to/local/cache
```

`--cache` uses `~/.cache/pyibquant/`; `--cache-dir` enables a chosen directory.
`--no-cache` disables reads/writes even if a cache directory is also specified.
Cache files contain market data and belong outside tracked source files. The
development preview uses the Git-ignored `charts/cache/` directory.

Only exact historical queries are reused. Keys include the resolved instrument,
bar size, lookback, end boundary, regular/extended hours, exchange, currency and
TRADES data type. Fixed-end older pages expire after 24 hours by default;
`--cache-max-age 3600` shortens that to an hour. Relative snapshots ending now
expire after at most five minutes, even if a longer lifetime is configured.
Cached snapshots show their cache timestamp, and history loads say **from cache**
when reused. IBKR can revise historical data; use `--refresh-cache` to bypass
reads and replace entries during a run, or clear the cache explicitly.

**Live subscriptions always request fresh IBKR history and updates.** Their
initial bars and subsequent live updates are not written to the cache. Explicit
older-history pages can use the cache while retaining the current subscription
and its fresher overlapping candles. Yearly entries retain monthly source bars
so extending a partial year and later monthly updates remain consistent.

Expired entries are misses. Corrupt files and I/O failures fall back to the
provider with a visible warning; successful data remains usable if a write fails.
Empty results and provider failures are not cached. Writes replace complete
files atomically. This is a query cache, not a merged historical database or an
offline `Market`: a normal `Market.ibkr()` connection still requires TWS/Gateway.

Inspect metadata or clear only PyIBQuant's cache files without connecting to IBKR:

```sh
pyibquant cache inspect --cache-dir /path/to/local/cache
pyibquant cache clear --cache-dir /path/to/local/cache
```

The Python API supports the same configuration and per-request refresh:

```python
with Market.ibkr(cache_dir="~/.cache/pyibquant", cache_max_age=86400) as market:
    bars = market.bars("AAPL", interval="1d", duration="6 M")
    fresh = market.bars("AAPL", interval="1d", duration="6 M", refresh=True)
    market.load_older(bars, refresh=True)
    entries = market.cache.inspect()
```

Pass `cache_dir=None` to disable caching, or `refresh_cache=True` to bypass reads
for the whole connection. `HistoricalCache` is also exported for standalone
inspection and clearing. Expiry limits reuse but does not delete files; clear
them explicitly when no longer needed. There is no automatic disk-size limit yet.

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
python tests/browser_history_check.py
```

With the live chart running on `--web-port 8050`, the separate manual integration
check `python tests/browser_controls_check.py` verifies symbol/interval changes,
invalid input, and recovery against TWS. It leaves the chart on AAPL daily bars.
`python tests/browser_live_history_check.py` additionally checks panning-triggered
pagination for intraday, daily, weekly and yearly bars against real IBKR data,
including stable time/price views and the retained live subscription. It also
leaves the shared chart on AAPL daily bars. Run the integration checks sequentially.
`python tests/browser_hours_check.py` verifies regular/extended-hours switching,
actual outside-session bars, older history and invalid-hours rejection, then
restores regular-hours AAPL daily bars.
With caching enabled on that server, `python tests/browser_cache_check.py` checks
reused daily/yearly history pages, fresh live initialization and stable viewports.
Install `.[dev,browser,cache]` to run the complete cache test suite; cache-specific
unit tests skip when the optional Parquet dependency is absent.

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

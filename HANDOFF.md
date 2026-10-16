# Development handoff

Checkpoint: 2026-10-15. This document records the chart-foundations implementation
and local validation. Work is saved in a local checkpoint commit; it has not been
pushed or released. Start with `git status` and `git log -1` after transferring work.

## Where to resume

Read [README.md](README.md), [PROJECT_PLAN.md](PROJECT_PLAN.md), then
[TODO.md](TODO.md). Price-axis dragging, vertical panning, and autoscale toggle/reset
are implemented, along with time-axis dragging for candle spacing and configurable
right space. Older-history loading now supports automatic fetches when panning
left, a Load older button, retries, deduplication and stable viewports. Optional
Parquet caching, fixed New York display with DST-aware labels and a browser
regular/extended-hours selector are implemented. Next: session shading and
separators. Do not start implementing the whole visualization roadmap at once.

The long-term visualization goal is a daily charting workspace replacing
TradingView for IBKR US stock/ETF users, with our own Canvas renderer and Python
research integration. Indicators, drawings, workspaces and options are future work.

## What exists

| File | Responsibility |
|---|---|
| `src/pyibquant/market.py` | Public connection, bar query and chart-serving API |
| `src/pyibquant/data/providers/ibkr.py` | Official SDK callbacks, contracts, requests, normalization, cancellation |
| `src/pyibquant/data/cache.py` | Optional exact-query Parquet cache, expiry, inspection and clearing |
| `src/pyibquant/bars.py` | Immutable Bar values and mutable thread-protected BarSeries snapshots |
| `src/pyibquant/visualization/chart.py` | HTML export, localhost HTTP server, active chart session |
| `src/pyibquant/visualization/chart.html` | Page layout, form, styles and template placeholders |
| `src/pyibquant/visualization/chart.js` | Independent Canvas rendering, interactions and browser requests |
| `src/pyibquant/cli.py` | `pyibquant chart` command |
| `tests/test_market_data.py` | Offline provider, export and chart-session tests |
| `tests/browser_chart_check.py` | Offline Chrome regression using generated synthetic data |
| `tests/browser_controls_check.py` | Explicit manual TWS/browser integration check |
| `tests/test_history.py` | Offline history merge, provider paging and session tests |
| `tests/browser_history_check.py` | Synthetic browser pagination, delayed responses and retry checks |
| `tests/browser_live_history_check.py` | Real TWS pagination and viewport integration check |
| `tests/test_cache.py` | Cache persistence, expiry, corruption, refresh, live bypass and concurrency |
| `tests/browser_cache_check.py` | Real TWS/browser daily/yearly cache reuse check |
| `tests/browser_hours_check.py` | Real TWS regular/extended-hours switching and older-history check |

No npm build or third-party chart library is required. JS is packaged with Python
and embedded into exported HTML. The sibling QuantIBKR repository supplied examples
but is not needed to install or run PyIBQuant.

HTTP API: `GET /` serves the page; `GET /data` returns the active series;
`POST /chart` accepts JSON `symbol`, `interval`, `duration`, and optional boolean
`regular_hours` (omitting it retains the active setting). Selection is serialized;
success replaces the series and cancels the old subscription, failure preserves
it. One server has one shared active chart, including across browser tabs.
`POST /older` accepts the current `selection_id` and earliest bar `before` time.
It shares the selection lock, rejects stale selections, reuses another tab's
already loaded boundary and throttles history requests to at most one per two
seconds. `/data` and the initial page carry the selection ID, so selecting the
same symbol/interval with another duration also resets clients correctly.

The browser polls every two seconds. Epoch seconds represent UTC intraday bars;
daily bars retain ISO session dates. Intraday labels use America/New_York
(EST/EDT automatically);
date-only labels remain unchanged. Canvas x coordinates use bar indices, omitting
closed-market gaps. Prices autoscale from visible candles by default. Manual
price ranges survive incoming bars, time navigation and resizing. Price and volume
are clipped separately; volume always keeps its own automatic scale.
The viewport count includes blank bar slots. Right space defaults to 10% of plot
width (selectable 0–40%). Fit includes all bars plus that space; Latest anchors
the data edge at the chosen margin. Fitted views expand on appends, following
views keep their zoom, and panned views keep their bar-index coordinates. A
time-axis drag zooms around the data edge when following, or around the right
viewport edge when panned. Double-clicking an axis resets only that axis.
Prepending anchors the old first timestamp at its new index, shifts `left` by
the inserted count and keeps candle spacing and tick-grid origin stable. Normal
append/follow behavior remains unchanged. History loading pauses polling, bumps
the browser generation counter to reject older in-flight polls, and leaves
Canvas navigation available. Errors require explicit retry; empty/no-progress
pages stop further loading for the current selection.

Supported intervals now include `2h`, `4h`, `1w` and `1y`. Yearly candles are
aggregated inside the IBKR provider from native monthly callbacks, grouped by
calendar year. A monthly replacement recomputes that year's OHLCV, so repeated
updates never add volume twice and corrected extrema can shrink. Annual date
anchors are January 1, with year-only axis labels. The chart warns that boundary
years can be partial. Weekly/yearly requests fetch enough extra source history
to cover the first requested calendar bucket and filter out unrequested earlier
periods. Weekly anchors are Mondays and source-month anchors are the first day
of each month, so clipped IBKR period-end dates cannot create duplicate periods.
Older pages use a fixed bounded duration per interval rather than the initial
query duration. Daily/coarser end boundaries use New York midnight converted to
UTC, including DST. The original live subscription is retained; overlapping
older downloads never replace live candles. Yearly source months are retained
in a provider-owned weak-key map and merged under a lock before recomputing the
affected years, including any previously partial earliest year.

Caching is off unless a cache directory is configured. Install `.[cache]` and
use `--cache` (default `~/.cache/pyibquant/`) or `--cache-dir`; `--no-cache` disables
it. The current preview uses ignored `charts/cache/`. Parquet is imported only
when a cache is instantiated; the base package still has no runtime dependencies.
The provider resolves contracts before looking up exact query keys, including
conId, native bar size, effective source window, hours, exchange, currency,
TRADES and normalization version. Calendar normalization version 2 prevents
reuse of entries made before period identities and aligned requests were fixed.
Fixed-end entries default to 24-hour expiry; relative snapshots are capped at
five minutes. Live subscriptions never read/write cached initialization or updates.
Older pages may hit cache, including normalized monthly inputs for yearly charts.
Cache hits are labeled; errors fall back to IBKR with warnings. Empty results
and errors are never persisted. Writes use temporary files and atomic replace.
`pyibquant cache inspect/clear` needs no IBKR connection and operates only on
namespaced cache entries. Per-request `refresh=True` or connection/CLI
`refresh_cache=True`/`--refresh-cache` bypasses reads and updates entries.

## Set up on the other machine

Clone/pull the committed work, enter the repository, and create a new environment.
Do not copy `.venv` from the original machine.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,browser,cache]'
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.
Python 3.11+ is declared. Original local checks used Python 3.11.6 on macOS;
the price/time-scaling follow-up used Python 3.14.5 on macOS. Other operating
systems have not yet been validated.

Install TWS/IB Gateway and the official TWS API Python client 10.33+ separately,
following the SDK's installation/license instructions. The project's dependency
list deliberately does not install the old PyPI `ibapi` distribution.

```sh
python -m pip install "/path/to/TWS API/source/pythonclient"
python -c 'from ibapi import get_version_string; print(get_version_string())'
python -m pytest -q
ruff check src tests examples
mypy
```

Local validation used SDK 10.50.2. The original environment reused that existing
SDK using `--system-site-packages`; a fresh machine must install its own SDK.

For manual browser checks, install Google Chrome; Playwright launches the `chrome`
channel. The offline check needs neither an account nor a local market-data file:

```sh
python tests/browser_chart_check.py
python tests/browser_history_check.py
```

For live use, log into TWS, enable socket clients, allow localhost, keep Read-Only
API enabled, and use the matching port and a free client ID (defaults: paper TWS
7497, client ID 71). See README for the port table and subscription requirements.

```sh
pyibquant chart AAPL --live --web-port 8050
```

Open the printed URL (`http://127.0.0.1:8050/` for the command above), rather than a
saved HTML file, to change symbols/intervals. Keep the Python process running.
Browser controls select symbol, interval, history and trading hours. Regular hours
is the default; `--extended-hours` chooses the initial setting. Load chart applies
the selected hours through a fresh data subscription; older pages and cache keys
retain the active setting. Press Ctrl+C to stop.

With that server running, an optional integration check requests SPY 5-minute and
AAPL daily data and leaves the shared chart on AAPL daily:

```sh
python tests/browser_controls_check.py
```

## Validation recorded at this checkpoint

Hours/timezone follow-up: 60 offline tests, Ruff, mypy and the offline browser
regression passed. The real IBKR browser hours check returned 156 regular-hours
versus 384 extended-hours AAPL 5-minute bars over the same 2 D window, confirmed
outside-session bars and older-history retention, rejected invalid hours, and
restored the shared preview to regular-hours AAPL daily 6 M. New York labels were
checked across EST/EDT, the spring transition and overnight calendar rollover.

Cache follow-up: 58 offline tests, Ruff and mypy passed on Python 3.14.5 with
PyArrow 26.0.0. Coverage includes date/datetime Parquet roundtrips, exact keys,
expiry/future clocks, corruption/schema failures, atomic/concurrent writes,
scoped clearing, optional imports, refresh, live bypass and monthly source
restoration. Real IBKR checks proved snapshot hits avoid historical requests,
refresh/live initialization still request IBKR, and a fresh connection reuses
older pages. Browser cache checks passed for daily/yearly charts while retaining
manual views and live subscriptions. Cache metadata inspection exposed varying
IBKR month-end labels: calendar normalization/aligned source requests now keep
current YTD values equal for short/long lookbacks and closed-year OHLCV unchanged
through pagination. Weekly buckets likewise keep stable Monday identities.

History-loading follow-up: 26 offline tests, Ruff and mypy passed. The existing
renderer regression and synthetic pagination regression passed, including slow
responses, navigation during downloads, stable price/time coordinates, stale
poll suppression, explicit retry, exhaustion and same-symbol selection resets.
Real TWS/browser history tests passed for AAPL: 1-minute 390 to 2,340 bars, daily
22 to 273, weekly 105 to 366 and yearly 2 to 12. Live subscriptions and manual
time/price views survived each prepend. The existing live symbol/interval/error
integration checks also passed. Counts are local observations, not fixtures.
Run the two live integration scripts sequentially because they share one chart.

Interval follow-up: 15 offline tests, Ruff, mypy, Chrome offline regression and
live browser integration passed. Real AAPL subscriptions returned 2-hour,
4-hour, weekly and aggregated yearly candles. Unit tests cover calendar-year
boundaries, chronological open/close with out-of-order monthly callbacks,
volume replacement, corrected highs/lows and subscription cancellation. Browser
checks cover date/year labels and all four interval selections.

Price/time-scaling follow-up: validated on macOS with Python 3.14.5 and the locally
installed official SDK 10.50.2. All 11 offline tests, Ruff, mypy and the expanded
Chrome regression passed. Browser checks cover dragging both axes, vertical
panning, right-space settings, blank-area crosshairs, native touch axes/pinch,
manual bounds through updates/resizing/navigation, autoscale and selection resets,
pane clipping and empty/flat data. Desktop/mobile screenshots were reviewed.
Live TWS integration also passed: AAPL 1-minute data, subscribed browser polling
with stable manual/time views, SPY 5-minute selection, invalid-history recovery,
and AAPL daily/6-month selection. The integration check leaves the shared chart
on AAPL daily; it verifies subscriptions/polling, not real-time entitlements or
that prices changed during the test.

Original implementation checks:

- 11 offline tests passed; Ruff and mypy passed.
- Wheel build and isolated import/render smoke check passed; HTML/JS assets and
  typing marker are included, with no source-tree or SDK dependency for chart export.
- Chrome offline renderer check passed with no external requests or JS errors:
  zoom, drag, crosshair, keyboard, DPR, resizing, viewport updates, empty/flat bars.
- Real TWS historical requests and live bar subscriptions succeeded.
- Browser selection succeeded for SPY 5-minute and AAPL daily/6-month history.
- Invalid history retained the active chart; the next valid selection recovered.
- Desktop/mobile layouts and touch pinch were checked in Chrome.

The local chart server only runs while its Python process remains active. Launch
it again on a new machine; a localhost URL is not a hosted service.

These are development checks, not proof of production reliability. Recorded bar
counts and chart screenshots are local artifacts, not fixtures or release data.

## Known limits

- Single active series per server; no saved layouts, drawings, indicators or watchlists.
- No automatic reconnect; session shading and separators remain future work.
- Exact-query cache only; no coverage merging, automatic pruning or disk-size limit.
- US stock/ETF TRADES bars only. No delayed-data fallback or tick-level quotes.
- IBKR pacing, duration/bar-size limits and entitlements apply; requests are not split.
- Live bars remain in memory without a retention limit; full snapshots are polled/redrawn.
- A selection temporarily creates the replacement subscription before releasing the old one.
- No order execution, account credentials or account identifiers are needed by this slice.
- No CI or cross-platform clean-install validation yet.

## Git transfer

Source, tests, docs and package configuration should travel through Git.
`.venv/`, generated `charts/` HTML/screenshots, caches and build outputs are ignored.
Nothing in `/tmp` is needed. No credentials or downloaded SDK should be added.

The chart-foundations checkpoint includes source, regression checks and progress
documentation. Generated market-data artifacts remain ignored. The local preview
uses client ID 173 and `charts/cache/`, with regular-hours AAPL daily bars over 6 M.
To restart it after closing the current process:

```sh
python -m pyibquant chart AAPL --interval 1d --duration '6 M' --live --web-port 8050 --client-id 173 --cache-dir charts/cache --no-browser
```

The HTTP server and TWS connection are local processes, not part of the commit.
Before moving machines, inspect `git status --short` and `git log -1`, then push
the checkpoint to your chosen remote when ready. No push was performed here.

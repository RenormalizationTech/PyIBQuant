# Development handoff

Checkpoint: 2026-10-15. This document records the implementation and local validation
at the end of the initial development session. It does not imply a release or that
changes have been committed/pushed. Start with `git status` after transferring work.

## Where to resume

Read [README.md](README.md), [PROJECT_PLAN.md](PROJECT_PLAN.md), then
[TODO.md](TODO.md). The next agreed slice is draggable price scaling, vertical
panning, and an autoscale toggle/reset. Do not start implementing the whole
visualization roadmap at once.

The long-term visualization goal is a daily charting workspace replacing
TradingView for IBKR US stock/ETF users, with our own Canvas renderer and Python
research integration. Indicators, drawings, workspaces and options are future work.

## What exists

| File | Responsibility |
|---|---|
| `src/pyibquant/market.py` | Public connection, bar query and chart-serving API |
| `src/pyibquant/data/providers/ibkr.py` | Official SDK callbacks, contracts, requests, normalization, cancellation |
| `src/pyibquant/bars.py` | Immutable Bar values and mutable thread-protected BarSeries snapshots |
| `src/pyibquant/visualization/chart.py` | HTML export, localhost HTTP server, active chart session |
| `src/pyibquant/visualization/chart.html` | Page layout, form, styles and template placeholders |
| `src/pyibquant/visualization/chart.js` | Independent Canvas rendering, interactions and browser requests |
| `src/pyibquant/cli.py` | `pyibquant chart` command |
| `tests/test_market_data.py` | Offline provider, export and chart-session tests |
| `tests/browser_chart_check.py` | Offline Chrome regression using generated synthetic data |
| `tests/browser_controls_check.py` | Explicit manual TWS/browser integration check |

No npm build or third-party chart library is required. JS is packaged with Python
and embedded into exported HTML. The sibling QuantIBKR repository supplied examples
but is not needed to install or run PyIBQuant.

HTTP API: `GET /` serves the page; `GET /data` returns the active series;
`POST /chart` accepts JSON `symbol`, `interval`, `duration`. Selection is serialized;
success replaces the series and cancels the old subscription, failure preserves
it. One server has one shared active chart, including across browser tabs.

The browser polls every two seconds. Epoch seconds represent UTC intraday bars;
daily bars retain ISO session dates. Canvas x coordinates use bar indices, omitting
closed-market gaps. Each redraw autoscales prices from the visible candles.

## Set up on the other machine

Clone/pull the committed work, enter the repository, and create a new environment.
Do not copy `.venv` from the original machine.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,browser]'
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.
Python 3.11+ is declared; local checks used Python 3.11.6 on macOS. Other machines
and Python versions have not yet been validated.

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
```

For live use, log into TWS, enable socket clients, allow localhost, keep Read-Only
API enabled, and use the matching port and a free client ID (defaults: paper TWS
7497, client ID 71). See README for the port table and subscription requirements.

```sh
pyibquant chart AAPL --live --web-port 8050
```

Open the printed URL (`http://127.0.0.1:8050/` for the command above), rather than a
saved HTML file, to change symbols/intervals. Keep the Python process running.
Browser controls select symbol, interval and history; hours are currently chosen
at startup with `--extended-hours`. Press Ctrl+C to stop.

With that server running, an optional integration check requests SPY 5-minute and
AAPL daily data and leaves the shared chart on AAPL daily:

```sh
python tests/browser_controls_check.py
```

## Validation recorded at this checkpoint

- 11 offline tests passed; Ruff and mypy passed.
- Wheel build and isolated import/render smoke check passed; HTML/JS assets and
  typing marker are included, with no source-tree or SDK dependency for chart export.
- Chrome offline renderer check passed with no external requests or JS errors:
  zoom, drag, crosshair, keyboard, DPR, resizing, viewport updates, empty/flat bars.
- Real TWS historical requests and live bar subscriptions succeeded.
- Browser selection succeeded for SPY 5-minute and AAPL daily/6-month history.
- Invalid history retained the active chart; the next valid selection recovered.
- Desktop/mobile layouts and touch pinch were checked in Chrome.

The local live chart server was stopped for the handoff. Launch it again on the
new machine; the old localhost URL is not a hosted service.

These are development checks, not proof of production reliability. Recorded bar
counts and chart screenshots are local artifacts, not fixtures or release data.

## Known limits

- Single active series per server; no saved layouts, drawings, indicators or watchlists.
- UTC display only; autoscale only; no older-history loading, cache or automatic reconnect.
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

Review and commit the intended files, then push the current branch to your chosen
remote. No commit or push was performed automatically during this handoff.

```sh
git status --short
git diff --check
git add README.md PROJECT_PLAN.md TODO.md HANDOFF.md .gitignore pyproject.toml src tests examples
git diff --cached --stat
git commit -m "Add IBKR market data and native interactive charts"
git push
```

If the branch has no upstream, use `git push -u <remote> <branch>` with your actual
remote/branch names. Run `git status` afterward to confirm all intended changes
were included before switching machines.

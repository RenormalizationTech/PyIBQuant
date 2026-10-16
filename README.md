# PyIBQuant

A Python-first toolkit for convenient access to Interactive Brokers market data,
quantitative research, backtesting, and algorithmic trading.

The main product is a usable Python API for the research-to-trading workflow.
Charts help inspect data, signals and results. Live IBKR access requires a manually
installed `ibapi`, a running and logged-in TWS or IB Gateway, and the account and
market-data permissions needed for the requested instruments. Backtesting and
algorithmic execution are planned; the implemented foundation currently provides
market data, bar exports, optional enrichment, caching, connection recovery and
interactive charts.

## Project documents

- [Development handoff](HANDOFF.md): setup on another machine, current architecture and limitations
- [Project TODO](TODO.md): research priorities, completed foundations and supporting chart backlog
- [Project plan](PROJECT_PLAN.md): research-to-trading vision and overall phases

## Development direction

Python exports, optional session enrichment, fixed historical ranges, dataset
metadata and a returns/SMA research example are implemented and verified against
TWS. Frozen dataset save/reload and explicit calendar/finality audits also work
without a broker. A first daily equity backtest now simulates next-open execution,
costs and performance from these frozen inputs. Level-one quote snapshots support
stocks and explicit option selectors, with stock snapshots verified against TWS.
Next: live option verification, contract discovery and selected quote collection;
user-controlled paper trading remains on the roadmap. Equities/ETFs are the initial workflow
for general users; options trading/backtesting is a major product direction and
the project owner's primary personal interest. A focused options research pilot
builds on the shared foundation, ahead of broad scanners or
advanced chart-workspace features.
The existing chart is an optional data/results viewer. Order placement, account
state and broker-connected strategy execution are not implemented yet. See the project plan for
the data/strategy/broker boundaries to address before adding them.

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

### Python research exports

Fetch bars once and export/analyze them without opening a chart:

```python
from pyibquant import Market

with Market.ibkr() as market:
    bars = market.bars("AAPL", interval="1min", duration="1 D")
    # No extra session-schedule requests by default.
    # Use include_sessions=True when you need provider session metadata.

records = bars.to_records()
path = bars.to_csv("charts/research/AAPL-1min.csv")
```

Each export captures one sorted snapshot, deduplicated by timestamp. Returned
records and DataFrames are independent copies; changing them does not change the
series. Exports work after the connection closes and make no IBKR requests.
Live exports include the latest available candle, which may still be partial;
exporting does not mark candles as completed.

`to_records()` returns dictionaries with `timestamp`, `open`, `high`, `low`,
`close`, and `volume`. Intraday timestamps are native UTC-aware Python datetimes;
daily/weekly/yearly timestamps remain Python dates. `to_csv(path)` writes those
same columns in that order, with ISO 8601 UTC offsets for intraday timestamps and
`YYYY-MM-DD` for date-only bars. It creates parent directories, expands `~`, and
returns the absolute path. A completed file replaces the destination atomically;
write failures preserve an existing file. Empty series produce a header-only CSV.
Records and CSV need no pandas or Parquet installation.

For an optional pandas DataFrame:

```sh
python -m pip install -e '.[pandas]'
```

```python
frame = bars.to_dataframe()
returns = frame["close"].pct_change()
```

The frame has a `timestamp` index and float64 `open`, `high`, `low`, `close`, and
`volume` columns. Populated intraday frames use a UTC DatetimeIndex; date-only
frames retain Python dates in their index. Empty frames keep the column schema.
Pandas is imported only when `to_dataframe()` is called. CSV contains OHLCV only;
`bars.metadata()` provides separate JSON-compatible instrument/query metadata to
save alongside it. Dataset reload APIs remain future work.
See `examples/research_exports.py` for a runnable local example.

### Fixed historical ranges

```python
from pyibquant import HistoricalRangeError, Market

with Market.ibkr() as market:
    try:
        bars = market.bars(
            "AAPL", interval="5min", start="2025-01-01", end="2026-01-01"
        )
    except HistoricalRangeError as error:
        partial = error.partial  # Only completed pages; download_complete is False.
        print(error.remaining_start, error.remaining_end)
        raise

records = bars.to_records()
metadata = bars.metadata()
```

Both bounds are required and are **start inclusive, end exclusive**, filtering by
bar timestamp. Date strings/Python dates mean New York midnight for intraday bars,
including DST. Alternatively provide timezone-aware whole-second datetimes or ISO
datetimes with offsets; they normalize to UTC. Naive datetimes and fractional
seconds are rejected. Daily/weekly/yearly queries require calendar dates.
Weekly timestamps are Monday anchors and yearly timestamps are January 1: use
aligned bounds to include a whole starting week/year. A final week/year ending
mid-period can still be partial; bar finality is not independently verified.
The exclusive end cannot be in the future. Fixed ranges cannot be combined with
`duration` or `live=True`; existing lookback calls still default to `duration="1 D"`.

The downloader moves backward through fixed time windows, including empty windows,
then sorts/deduplicates and trims the result. Pages use an eight-hour maximum for
30-second bars, one day for 1-minute bars, seven days for 5-minute bars, 28 days for
15-minute through 4-hour bars, 365 days for daily bars, approximately five years
for weekly inputs and ten years for yearly inputs. Internal weekly/yearly page
boundaries align to full periods; yearly pages merge retained source months.
Provider requests can overfetch to cover these bounds; returned rows stay in range.

All history requests on a connection have a 0.25-second minimum spacing. 30-second
requests also wait at least 11 seconds between small-bar requests and 15.1 seconds
before repeating an identical request. Pacing state survives reconnects, waits are
interruptible by `Market.close()`, and cache hits bypass pacing/provider requests.
These controls track this Market connection only; other clients and IBKR's own
throttling still apply. Long ranges may take substantial time. A fixed-range
download does not hold the Market control lock while waiting, so cancelling other
subscriptions remains possible. A disconnect fails that download with its partial
result; it does not silently restart against another connection.

`download_complete=True` means every planned window completed, not that all
expected market bars exist. `download_pages`, `download_cached_pages`, and
`empty_windows` report the work. Empty windows are retained with a warning; they
may represent closures or unavailable data. Provider failures/timeouts raise
`HistoricalRangeError` with the completed `partial` series and the remaining
`[remaining_start, remaining_end)` bounds. Permission errors are never converted
into successful empty pages. Fixed-range series cannot use `load_older()`; request
a different range instead. Chart pagination is disabled for such datasets.

### Dataset metadata and a research example

`bars.metadata()` returns an independent JSON-compatible dictionary with resolved
instrument ID, asset type, currency, exchange, multiplier, interval, TRADES data
type, split-only adjustment setting, session configuration/available schedules,
UTC/date timestamp conventions, query bounds and download/cache progress. Coverage
contains observed first/last timestamps and row count, with gaps and bar finality
explicitly **not verified**. A successful download is not a gap/holiday audit or a
point-in-time corporate-action dataset. Metadata for manually constructed series
leaves unverified identity fields unset.

```python
import json
from pathlib import Path

path = bars.to_csv("charts/research/bars.csv")
Path(path).with_suffix(".metadata.json").write_text(
    json.dumps(bars.metadata(), indent=2), encoding="utf-8"
)
```

Freeze a dataset for later offline research:

```python
from pyibquant import BarDataset

dataset = BarDataset.from_series(bars)
dataset.save("charts/research/bars.dataset.json")
# Later, without TWS, ibapi, pandas or PyArrow:
dataset = BarDataset.load("charts/research/bars.dataset.json")
closes = [bar.close for bar in dataset.snapshot()]
```

The immutable snapshot preserves bars and copied metadata together in one atomic
JSON file. Live updates cannot change it. Loading checks format version, SHA-256
integrity, timestamp ordering/kinds, coverage counts and requested range bounds.
The checksum detects accidental edits; it does not establish authenticity.
Incomplete download status remains incomplete after reload.

`dataset.audit(expected_starts, finalized_through=last_final_start)` compares the
dataset with **caller-supplied** expected bar starts. For daily bars, pass trading
dates from your chosen calendar for the same query and hours. For other intervals,
pass that calendar's bar starts, including early closes and period boundaries.
The result reports `missing`, `unexpected` and `unconfirmed` timestamps, plus
`matches_calendar`. `finalized_through` is an inclusive assertion by the caller,
not a finality inference by the toolkit. Without it, every bar is unconfirmed.
No weekdays, holidays or trading sessions are guessed, and an audit never changes
the original provenance's unverified gap/finality fields. A matching timestamp
calendar does not verify prices, volumes or point-in-time corporate actions.

`pyibquant.research.simple_returns(closes)` computes fractional close-to-close
returns, with `None` for the first observation or a zero denominator.
`pyibquant.research.sma(closes, window=20)` computes a trailing mean, with `None`
until a full window is available. Both accept iterables of finite numbers and
require no broker, pandas or chart. They do not define strategy execution timing.

A complete local example downloads fixed daily inputs, saves their CSV/metadata,
and computes returns plus a descriptive close-above-SMA signal:

```sh
python examples/research_range.py AAPL --start 2025-01-01 --end 2026-01-01
```

It writes `bars.csv`, `bars.metadata.json`, `bars.dataset.json` and `signals.csv` under ignored
`charts/research/`. Download failure exits without analyzing the partial data.
This is a research example; it does not simulate orders, fills or strategy profits.
Verified against local TWS on 2026-10-16: the example exported 250 AAPL daily bars
for 2025, matching signal rows and dataset metadata.

Recompute the research values offline from that frozen input:

```sh
python examples/research_saved.py charts/research/bars.dataset.json
```

Optionally pass `--calendar trading-dates.txt` (one ISO expected bar start per
line), and `--finalized-through YYYY-MM-DD` for daily bars. The example rejects
explicitly incomplete downloads and calendar mismatches before calculations.
Without a calendar it computes descriptive values with coverage still unverified.

### First daily equity backtest

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.backtest import backtest_equity
from pyibquant.research import above_sma

dataset = BarDataset.load("charts/research/bars.dataset.json")
signals = above_sma([bar.close for bar in dataset.snapshot()], window=20)
result = backtest_equity(
    dataset, signals, finalized_through=date(2025, 12, 31),
    initial_cash=10_000, shares=1, commission=1, slippage_bps=5,
)
print(result.metrics())
result.save("charts/backtest/results.json")
```

This initial simulator requires complete fixed-range daily regular-hours equity
TRADES bars, split-only adjustment and multiplier one. Supply exactly one boolean
long/flat target per bar. Each signal acts at the **next supplied bar's open**;
unchanged targets do not rebalance. Built-in `above_sma` and `sma_crossover` use
only trailing closes, with flat targets during warmup/equality. Caller-provided
signals must obey the same information timing; execution delay cannot detect
look-ahead inside a supplied signal.

`shares` is a fixed positive whole-share quantity in the adjusted price basis.
No borrowing or shorting is modeled. A buy that cannot afford price plus fees is
rejected; the next target may retry at the next open. Slippage is adverse in basis
points, commission is a flat amount in the instrument's currency **per fill**,
and both are included once in P&L. These are configurable simulation assumptions,
not an IBKR commission schedule. Final positions remain valued at the last close;
there is no invented final fill or estimated final exit cost. The last signal has
no following open and cannot execute.

`finalized_through` is the caller's confirmation that all supplied bars are final.
Pass optional `expected_dates` from an independent calendar to reject missing or
unexpected trading dates. Without it, results explicitly report unchecked calendar
coverage and may execute across gaps. No total-return/dividend, settlement, tax,
interest, volume/liquidity or broker account model is included. Split-adjusted
prices are research units; historical nominal-share execution and corporate-action
cash flows are not reconstructed. Intraday, options and portfolio simulation are
outside this initial engine.

The frozen result includes fills, rejected orders, completed trades, a daily
cash/position/equity/return/drawdown curve, assumptions, the optional expected
calendar and an exact input fingerprint matching the saved dataset. Metrics
include fractional total return, negative fractional maximum drawdown, realized
and unrealized P&L, commissions, modeled slippage and completed-trade win rate
(`None` with no completed trades). Ending open positions contribute to equity
and unrealized P&L, not completed-trade statistics. No annualization is inferred.

Run either strategy offline and export reproducible inputs plus JSON/CSV results:

```sh
python examples/backtest_equity.py charts/research/bars.dataset.json --finalized-through 2025-12-31 --commission 1 --slippage-bps 5
python examples/backtest_equity.py charts/research/bars.dataset.json --finalized-through 2025-12-31 --strategy sma-cross --fast 10 --slow 20 --output-dir charts/backtest/crossover
```

Optional `--calendar trading-dates.txt` uses one expected ISO date per line.
The example writes `inputs.dataset.json`, `strategy.json`, `results.json` and
CSV logs for fills, trades, equity and rejections under ignored `charts/backtest/`.
No broker connection or optional dependency is needed.

### Stock and option quote snapshots

```python
from datetime import date
from pyibquant import Market, Option

with Market.ibkr(timeout=30) as market:
    stock = market.quote("AAPL")
    option = market.quote(Option("AAPL", date(2026, 11, 20), 340, "C"))

print(stock.bid, stock.ask, stock.spread, stock.market_data_type)
print(option.instrument, option.greeks)
record = option.to_dict()  # Independent JSON-compatible record after disconnect.
```

Choose a contract appropriate to your research and data permissions; the option
above illustrates selector syntax. The option path has offline callback tests.
The user-selected SPY 2026-11-20 770 C resolved successfully, but TWS returned
error 10091 (additional API data permissions, SPY ARCA/TOP/ALL) and no bid/ask
or Greeks. Live option BBO/Greeks verification remains pending. AAPL stock
snapshot acquisition and feed-type confirmation passed against TWS on 2026-10-16.

`Market.quote()` calls **`reqMktData(snapshot=True, regulatorySnapshot=False)`**,
separately from historical bars. It returns one immutable `Quote` after
`tickSnapshotEnd`; it is not a continuous subscription or an order-book request.
Standard snapshots normally complete in about 11 seconds and return only fields
available during the request, so use a longer connection timeout. See IBKR's
[snapshot documentation](https://interactivebrokers.github.io/tws-api/md_request.html).
Regulatory snapshots are never requested.

Quotes contain resolved contract identity, bid/ask/last and sizes, requested and
reported market-data type, per-field tick IDs and local UTC callback receipt
times. Missing/nonpositive prices and unset values remain `None`; zero sizes
remain zero. Receipt time is **not exchange quote time or proof of freshness**.
Bid/ask callbacks arrive independently. Crossed values are preserved and flagged,
with `spread`/`midpoint` left `None`; other incomplete pairs also have no spread.
These fields do not certify an executable price or a consolidated order book.

`market_data_type` accepts `live` (default), `frozen`, `delayed`, or
`delayed_frozen`. Requested type is not a promise of the delivered feed: IBKR's
callback reports the actual type, or it remains unknown. Delayed tick IDs are
tracked separately, and `is_delayed` stays true even if they conflict with a live
callback. Feed mismatches and partial entitlement messages appear in `warnings`;
terminal permission errors/timeouts raise data errors. No mode change, subscription
purchase or automatic retry is performed in response to a permission failure.
See IBKR's [data-type definitions](https://www.interactivebrokers.com/docs/tws-api/doc/md/delayed-data).

An `Option` requires underlying symbol, expiry date, strike and `C`/`P`. Optional
`trading_class` and `multiplier` help disambiguate adjusted contracts. Exactly one
IBKR contract must resolve; its conId, local symbol, trading class and actual
multiplier are preserved. No multiplier of 100 is assumed. This initial path is
US equity/ETF options routed via SMART in USD, not futures/index option coverage.

Available option computations are preserved separately by `source` (`bid`, `ask`,
`last`, `model`), with IV, delta, gamma, vega, theta, option/underlying prices and
provider dividend estimate. Unavailable values stay `None`, delayed computations
are marked, and missing computations are not manufactured. Availability depends
on the broker's inputs and permissions; see IBKR's
[option computations](https://interactivebrokers.github.io/tws-api/option_computations.html).
Model values are not substituted for a missing bid/ask or a historical fill.

```sh
python examples/quote_snapshot.py AAPL --output charts/quotes/aapl.json
python tests/live_quotes_check.py --symbol AAPL
```

Pass `--expiry YYYY-MM-DD --strike NUMBER --right C` (or P) to inspect an explicit
option. Continuous quote subscriptions, chain discovery, chart bid/ask display,
quote recording and historical quote imports remain future work. Snapshot calls
serialize on a connection because IBKR's requested feed type is connection-wide;
they do not hold the Market control lock while waiting. Disconnects fail the
snapshot instead of silently repeating it. Historical bar recovery is unchanged.

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

### Sessions and data freshness

**Sessions: on/off** controls shading outside regular sessions and dashed New York
calendar-day separators on intraday charts. Session boundaries come from IBKR's
regular and extended `SCHEDULE` responses, including provider-reported early
closes and daylight-saving offsets. Shading spans price and volume and never adds
closed-market slots or moves the view. Date ticks identify new sessions; labels
are spaced to avoid overlap. Missing or invalid schedules leave bars usable with
a visible explanation and no guessed standard-hours shading. Saved snapshots
include whatever session metadata was downloaded.

`Market.bars()` skips schedule enrichment by default. Use `include_sessions=True`
to request regular and extended `SCHEDULE` metadata separately from OHLCV, including
when bars come from the optional cache. This flag controls metadata requests;
`regular_hours` independently controls which trading hours the OHLCV query includes.

The chart CLI explicitly enables enrichment. `market.serve(bars)` also enables it
by default and retains the setting when selecting another chart; pass
`market.serve(bars, include_sessions=False)` to skip it. For a shaded HTML snapshot,
request `market.bars(..., include_sessions=True)` before calling `bars.plot()`;
`plot()` only exports downloaded data and makes no provider requests.

For enriched series, intraday history loads extend the schedule; daily/coarser
charts request only a recent schedule for connection context. These extra requests
do not read or write OHLCV cache entries. Only enriched live series request
schedules after reconnect or at the five-minute refresh. Unenriched live series
still recover and backfill OHLCV normally. Disabling enrichment leaves any
previously downloaded metadata available without requesting more.

The chart reports the last bar receipt time, subscription/reconnect state, quiet
callbacks during a known active session, and time outside the requested session.
A 90-second callback warning describes missing callbacks; it does not establish
a lost connection or a market-data entitlement. Unknown schedules are labelled
unverified. Historical bar subscriptions do not confirm a real-time/delayed feed
type, so receiving updates is explicitly labelled **Entitlements unverified**;
provider permission/delay warnings remain visible.

Connected intraday charts show a bar-boundary countdown only while the newest bar
covers the current time within a known requested session. The countdown respects
IBKR's clock-aligned hourly candles (including shortened opening candles) and the
provider's session close. It disappears when disconnected, outside session hours,
on an old bar, or for daily/coarser charts and saved snapshots. The timer is a
clock estimate, not confirmation that IBKR has finalized a candle.

### Live bar chart

```sh
pyibquant chart AAPL --interval 1min --duration '1 D' --live
```

This serves the chart on a free localhost port and keeps the IBKR subscription
open. The browser checks the in-memory bars every two seconds; IBKR determines
the actual bar-update cadence. Keep the command running and press Ctrl+C to
cancel subscriptions and disconnect. Use `--web-port 8050` for a fixed HTTP port.
The displayed subscription status does not guarantee real-time entitlements;
provider warnings appear above the chart. Disconnects and automatic recovery are shown in the chart. Live `Market.ibkr()`
connections retry failed connections with a bounded backoff (up to 30 seconds
between attempts), restore active subscriptions and download fresh gap history.
Downloaded older bars, chart zoom and manual price bounds are retained. TWS must
still be running, logged in and configured for the same host/port/client ID;
recovery cannot log in or repair API settings. Use `--no-reconnect` or
`Market.ibkr(reconnect=False)` to disable recovery. `market.cancel(series)` removes
a subscription from recovery as well as cancelling it at IBKR. Initial connection
failures still raise an error rather than retrying indefinitely.

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
IBKR's bar-size/duration limits and pacing rules still apply. Lookback requests
are not automatically split; use explicit `start`/`end` ranges for paged downloads.

### Python

```python
from pyibquant import Market

with Market.ibkr() as market:
    aapl = market.bars("AAPL", interval="1min", duration="1 D", include_sessions=True)
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
The SDK-free subset runs without `ibapi`:

```sh
python -m pytest tests/test_core.py tests/test_cache_core.py tests/test_exports.py tests/test_pacing.py tests/test_research.py
```

Development checks run locally with the manually installed IBKR Python API.
GitHub CI and automatic SDK installation are outside the current scope. Synthetic
unit/browser checks remain useful for development, while explicit TWS integration
checks verify the connected workflow. The smaller subset above is only a way to
check independent components; it does not make the full IBKR workflow standalone.

The optional browser regression checks offline rendering, interaction, resizing,
and live viewport behavior using generated synthetic bars and installed Google
Chrome. No TWS connection or existing chart export is needed:

```sh
python -m pip install -e '.[browser]'
python tests/browser_chart_check.py
python tests/browser_history_check.py
python tests/browser_sessions_check.py
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

`python tests/live_exports_check.py --client-id 188` additionally verifies that
plain research queries send no `SCHEDULE` requests, opt-in queries do, and records,
CSV and pandas exports work after disconnecting. Install `.[pandas]` for that check.

`python tests/live_ranges_check.py --client-id 189` is the explicit range check
for intraday/daily/weekly/yearly bounds, page-cache reuse and yearly OHLCV
consistency. It requires `.[cache]` and a running TWS/Gateway. It passed against
local TWS on 2026-10-16; it does not connect during normal pytest runs.

The separate recovery integration check uses its own data-only client and
disconnects only that client's socket. It verifies automatic reconnect, intraday
gap recovery, retained yearly source history and cancellation:

```sh
python tests/live_recovery_check.py --client-id 187
```

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

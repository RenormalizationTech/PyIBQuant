# PyIBQuant

A Python-first toolkit for convenient access to Interactive Brokers market data,
quantitative research, backtesting, and algorithmic trading.

The main product is a usable Python API for the research-to-trading workflow.
Charts help inspect data, signals and results. Live IBKR access requires a manually
installed `ibapi`, a running and logged-in TWS or IB Gateway, and the account and
market-data permissions needed for the requested instruments. Implemented features
include market data, frozen datasets, research calculations, daily equity
backtests, a strategy-driven portfolio simulator, stock/option quotes and interactive charts.
Read-only paper-account monitoring and an experimental paper broker/strategy runner
are implemented. Bounded AAPL strategy execution, same-day restart, cancellation
and disconnect-after-send recovery have owner-run paper validation. Selected-option
buy/sell and cancellation are also validated; automated option strategies remain open.

## Project documents

- [Python API guide](docs/API.md): supported entry points and an end-to-end workflow
- [Development changes](CHANGELOG.md): local development snapshot contents

- [Development handoff](HANDOFF.md): setup on another machine, current architecture and limitations
- [Project TODO](TODO.md): research priorities, completed foundations and release work
- [Project plan](PROJECT_PLAN.md): research-to-trading vision and overall phases

## Development direction

The primary workflow is **on-demand IBKR historical data → Python research →
backtesting**, for equities/ETFs and selected options. The software should not
require users to record live markets or build a large local options archive.
Request only the contracts/date ranges needed for an experiment. Optional caching
and saved experiment inputs support repeatability. Continuous collection and
external historical research providers are outside the current scope, except for
the optional daily Yahoo chart preview described below. IBKR remains the intended
data provider for the package.

Equity/ETF historical queries, paging/pacing, exports, frozen datasets and simple
returns/SMA research are implemented, together with a first daily equity backtest.
Option discovery, snapshots, independent quote streams/reconnect and bounded
intraday option history are implemented. `Market.bars(Option(...), start=..., end=...,
data_type=...)` reuses historical paging, pacing and optional exact-query caching.
The superseded recording/replay stack and recorded-quote simulator were removed.

A first historical-bar option backtest now supports single-contract long/flat
TRADES/MIDPOINT research with explicit synthetic next-open fills and costs.
The bar-driven simulator also supports user strategy callbacks, multiple explicit
instruments sharing cash, variable sizing/partial exits, cancellable market orders
and replaceable execution models. Named multi-instrument datasets, quality reports
and two lightweight scientific study starters are also implemented.
Paper account monitoring and persistent performance/order history are implemented.
Paper execution and its runner remain experimental beyond the validated bounded
checks: automatic broker reconnect, multi-session recovery, settlement accounting
and execution corrections remain open; see [the staged plan](PROJECT_PLAN.md#24-phase-6--algorithmic-paper-trading-and-account-performance).
Historical bars do not supply quote receipt times,
quote sizes or historical Greeks.

The scope follows IBKR's available history. IBKR lists expired-option history and
option end-of-day data as unavailable in its historical API; see
[IBKR data limitations](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction).
Start with available intraday history for a currently resolvable, unexpired contract,
not reconstruction of a past option-chain universe. TRADES, MIDPOINT, BID and ASK
have different meanings; IBKR's BID_ASK candle also uses special aggregates rather
than ordinary trade OHLC. See [bar definitions](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars).
Missing history and permission failures must remain explicit. Historical requests
use a logged-in TWS/Gateway and appropriate permissions; live recording and an
open trading session are not requirements for historical acquisition.

Charts are optional data/results viewers. General charting features such as saved
workspaces, watchlist UI, drawing tools and indicator panes are outside project
scope. Visualization work serves concrete research/backtest results and account
performance/order tracking.
Read-only paper-account state and performance tracking work through the API.
The owner has validated bounded AAPL strategy runs, explicit same-day recovery,
strategy-owned flattening and selected-option order/cancellation checks. Options research/backtesting
is a major product direction and the owner's primary interest; prioritize a usable
historical research workflow, now followed by paper execution and account performance.

## Paper account performance and algorithmic trading

Use the API to observe the paper account and open a focused localhost account view:

```sh
.venv/bin/python examples/paper_account.py
```

This records account value, cash, buying power, positions, orders, executions and
available broker P&L in a local SQLite journal. It starts read-only. Reports and
CSV history remain under ignored `charts/paper/`. No past account history is invented.

Run the one-minute above-SMA example without submitting orders:

```sh
.venv/bin/python examples/paper_strategy.py AAPL --seconds 180
```

See [the paper API and funding policy](docs/API.md#paper-account-observation-and-experimental-execution)
for the cash-account/margin-account distinction, settled funds, order limits and
experimental execution status. Live accounts remain disabled. Recovery reports,
terminal order waits, tagged cancellation, fill-based strategy audits, checkpointed
resume and owned-only flattening are documented there.

After hours, rebuild account and per-run performance reports directly from the
saved journal, without TWS:

```sh
.venv/bin/python examples/paper_report.py --output charts/paper/strategy-review.html
```

New strategy runs save recovery checkpoints. Restore returns paused and preserves
identity, risk limits and order counts; explicit resume requires fresh reconciliation.
Earlier runs without complete checkpoints remain available for reporting.

The saved AAPL paper profile and read-only setup check are ready:

```sh
.venv/bin/python examples/paper_preflight.py --profile examples/paper_aapl.json --connect
```

During the regular session, the human operator can launch the bounded test with
`python examples/paper_strategy.py --profile examples/paper_aapl.json --execute`.
The profile alone never enables orders. See [setup and operating sequence](docs/API.md#paper-setup-and-operating-sequence)
for observation, explicit recovery, reports and the remaining broader recovery work.

The separate resting-order cancellation check also defaults to read-only:

```sh
.venv/bin/python examples/paper_cancel_check.py --profile examples/paper_aapl.json
```

The human-run `--execute` check submits one AAPL limit buy below bid, then cancels
only that order and confirms the result. Any fill is reported and retained.
See [cancellation check and recovery](docs/API.md#paper-cancellation-check-and-recovery)
before execution or recovery; uncertain outcomes must not be blindly resubmitted.

## First slice: IBKR → Python → HTML chart

Retrieve US stock/ETF bars through the official TWS API, then display candles and
volume using PyIBQuant's own HTML Canvas renderer, with no third-party chart library.
Charts support zoom, pan, crosshair OHLCV, a synchronized volume pane, and optional
live bar updates. This is the initial market-data slice of [the plan](PROJECT_PLAN.md).

### Setup

Python 3.11+ is required. Live IBKR access additionally requires a running,
logged-in TWS or IB Gateway and the manually installed SDK described below.
Saved-dataset research and equity backtests run offline without that setup.

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

### Optional Yahoo chart preview without TWS

IBKR is the default data source. If TWS/Gateway is unavailable, the chart command
reports the connection error and suggests an explicit Yahoo preview; it never
switches providers automatically. The preview is a temporary convenience for
exploring the chart, not an alternative IBKR research/backtesting workflow.

Install the optional dependency and request a daily US stock/ETF snapshot:

```sh
python -m pip install -e '.[yahoo]'
pyibquant chart AAPL --provider yahoo --interval 1d --duration '1 Y'
```

The preview needs internet access but no TWS, IBKR SDK, subscription or API key.
The chart identifies **Yahoo Finance · Preview** and displays its limitations.
`--output` and `--no-browser` work as usual. Only `--interval 1d` is supported;
duration accepts positive `D`, `W`, `M` or `Y` calendar lookbacks. The current
session date is included when available and may be incomplete. There are no live
updates, interactive symbol switching/older-page downloads, session schedules,
extended-hours bars, options or IBKR cache integration in this preview.

The adapter uses single-symbol `yfinance.Ticker.history()` OHLCV, converts daily
index values to session dates, and explicitly enables split/dividend adjustment.
These prices differ from IBKR's split-only research inputs. Coverage and accuracy
are unverified; missing/nonfinite price rows are skipped with a warning, missing
volume remains null, and empty results fail visibly. Download completeness is
left unknown. The existing backtest adjustment requirements are unchanged.

`yfinance` is unofficial and uses Yahoo's public endpoints for personal research;
access may fail or be rate limited. See its
[documentation and usage terms](https://ranaroussi.github.io/yfinance/).
It is imported only when explicitly selecting the preview. Installing the base
package does not install `yfinance`, pandas or NumPy.

To explicitly validate live downloads and the preview UI (requires `.[yahoo,browser]`
and installed Google Chrome):

```sh
.venv/bin/python tests/live_yahoo_check.py --browser
```

This checks three live symbols, OHLCV conversion, CSV/dataset persistence, invalid
inputs, CLI errors and chart interactions. Reports and screenshots are saved under
ignored `charts/yahoo-validation/`; normal unit tests never contact Yahoo.

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
save alongside it. `BarDataset` saves/reloads both bars and metadata (see below).
See `examples/research_exports.py` for a runnable local example.

## Scientific research: dependable data, user-owned analysis

Scientific research is a separate use case from trading-strategy evaluation.
Users may study correlations, scaling/multifractality, random matrices or other
market phenomena without defining a strategy. PyIBQuant's role is to request and
load useful, well-described IBKR datasets, not implement a large scientific
analysis framework. Users bring their own methods and scientific Python tools.

Priorities are explicit instruments and bounded queries, original OHLCV and
nullable volume, resolved identity, source/adjustment/session semantics, visible
errors and coverage limits, frozen save/reload, and transparent multi-instrument
alignment. No implicit filling, resampling, currency conversion or claims that
IBKR data is point-in-time, survivorship-free, gap-free or independently finalized.
Advanced correlation, multifractal and random-matrix estimators remain user-owned.
Strategy comparisons, benchmarks and out-of-sample reports belong to backtesting.

`BarDatasetCollection` stores named frozen inputs together, retaining each source's
metadata and fingerprint. `align(field="close", join="outer")` returns the union
of observed bar starts with `None` for absent values; `join="inner"` keeps their
intersection. The join must be chosen explicitly. Both require matching intervals,
timestamp kinds and session settings and reject known incomplete downloads. They
compare observed timestamps only: gaps shared by all sources remain undetected.
Different price sources, currencies and adjustments remain visible in per-input
metadata; users decide whether those series are scientifically comparable.
Bar starts are alignment keys, not a claim of simultaneous price observations.
Daily dates retain source session labels; intraday starts normalize to UTC.

```python
from pyibquant import BarDatasetCollection, Market

with Market.ibkr() as market:
    collection = market.datasets(
        {"apple": "AAPL", "microsoft": "MSFT", "benchmark": "SPY"},
        interval="1d", start="2025-01-01", end="2026-01-01",
    )
collection.save("charts/scientific/inputs.collection.json")

# Later, offline, without the SDK:
collection = BarDatasetCollection.load("charts/scientific/inputs.collection.json")
aligned = collection.align(field="close", join="outer")
records = aligned.to_records()  # date/datetime values; absent observations are None
report = aligned.metadata()    # source metadata/digests, dropped/absent/null counts
# frame = aligned.to_dataframe()  # optional pandas; missing values become NaN
```

The collection keeps all original bars even when an inner join drops rows from a
view. Each source still supports `audit()` with an explicit expected calendar and
caller-supplied finality. Integrity digests detect edits, not authenticity or data
quality. Empty inputs are retained by the API; alignment can return zero rows.
Unknown download completeness remains unknown. Collections also accept saved
selected-option datasets; they do not reconstruct historical option universes.

Runnable equity/ETF acquisition and offline inspection:

```sh
python examples/research_collection.py fetch AAPL MSFT SPY \
  --start 2025-01-01 --end 2026-01-01 \
  --output charts/scientific/inputs.collection.json
python examples/research_collection.py inspect charts/scientific/inputs.collection.json \
  --join outer --csv charts/scientific/closes.csv \
  --quality-report charts/scientific/quality.json
```

Fetch uses sequential bounded requests and existing pacing/optional `--cache-dir`.
It writes the collection only after every requested input is nonempty and its
download completed; errors propagate without publishing a partial collection.
Completed downloads still do not certify expected-market-bar coverage. The saved
collection and inspection metadata are the provenance; CSV alone is only values.

### Inspect dataset quality

`describe()` on a `BarDataset` or collection summarizes recorded identities,
sampling/source/session/adjustment semantics, requested and observed coverage,
download status/empty windows and fingerprints. `quality_report()` adds
JSON-compatible evidence, without modifying inputs or issuing broker requests:

```python
from datetime import date

summary = collection.describe()
quality = collection.quality_report(join="outer")
# quality["datasets"]["apple"]["calendar"] is None: no expected calendar was supplied.
# quality["alignment"] contains row losses, missing values and per-source metadata.

# Optional additional acquisition for a small calendar-assertion example:
with Market.ibkr() as market:
    short = market.datasets({"apple": "AAPL"}, start="2026-10-12", end="2026-10-16")
expected = [date(2026, 10, day) for day in (12, 13, 14, 15)]
quality = short.quality_report(
    {key: expected for key in short},
    finalized_through={key: date(2026, 10, 15) for key in short},
    join="outer",
)
```

Supply expected starts from your chosen calendar for each input's query and
sampling; PyIBQuant does not generate a calendar. A single input also supports
`dataset.quality_report(expected, finalized_through=...)`. Calendar mismatches
report missing/unexpected starts; no calendar means these remain unknown.
**Finality here uses the existing `audit()` convention: the caller confirms bars
starting at or before the supplied bound. It does not infer bar completion from
that instant.** The general simulator's intraday finality convention additionally
requires coverage through bar end; use that API's documented assertions.

Observation flags count bars with null/zero/negative volume, nonpositive OHLC prices
or inconsistent OHLC bounds. These are descriptive, not universal validity rules
or automatic repairs. Missing option volume is expected for non-TRADES sources.
Original provider warnings/errors remain visible. Reports carry no overall quality
score or guarantee; matching timestamps does not verify prices or corporate history.

Collection reports accept calendars/finality per label, reject unknown labels,
and list differences in price source, currency, adjustment, multiplier and sampling.
Without `join`, alignment is not attempted. With a join, incompatible or incomplete
inputs produce `alignment.status="unavailable"` with a reason, while individual
reports remain available. Alignment never converts currencies or harmonizes sources.

### Fetch named collections from Python

`Market.datasets()` accepts a nonempty mapping of labels to equity/ETF symbols,
explicit `Option` selectors, or `BarRequest` values. Inputs share fixed start/end,
interval and `regular_hours`; the method reuses `Market.bars()` sequentially with
its existing paging, pacing and optional cache. `refresh` and equity-only
`include_sessions` are supported. No live mode, bulk discovery or file writes.

```python
from datetime import date
from pyibquant import BarRequest, DatasetCollectionError, Market, Option

option = Option("AAPL", date(2026, 11, 20), 340, "C",
                trading_class="AAPL", multiplier=100)
with Market.ibkr() as market:
    try:
        inputs = market.datasets(
            {"underlying": BarRequest("AAPL", primary_exchange="NASDAQ"),
             "call_midpoint": BarRequest(option, data_type="MIDPOINT")},
            interval="5min", start="2026-10-16T09:30:00-04:00",
            end="2026-10-16T10:00:00-04:00",
        )
    except DatasetCollectionError as error:
        print(error.failed_key, list(error.completed), error.__cause__)
        raise
inputs.save("charts/scientific/mixed.collection.json")
```

Choose an available unexpired option/completed range when running. Bare strings
and Options use TRADES; `BarRequest` selects an option's MIDPOINT/BID/ASK source or
an equity primary exchange. Options still require intraday bars without session
enrichment. Mixed option/equity inputs retain their distinct source semantics.

The first failed, empty or incomplete input raises `DatasetCollectionError`.
`failed_key` identifies it, `completed` is a read-only mapping of earlier frozen
inputs, and `__cause__` preserves the original error. A nested `HistoricalRangeError`
still contains that input's completed pages and remaining range. Later inputs are
not requested. No retry or partial save occurs automatically. Local selector/mode
errors raise `ValueError` before requesting data; broker availability is checked
by the existing acquisition path. Successful planned windows still do not establish
expected-market-bar completeness. The example script saves only a successful collection.

Verified with local TWS: AAPL/MSFT/SPY, four daily bars each for
[2026-10-12,2026-10-16), plus AAPL equity and the selected call MIDPOINT, six
five-minute bars each for 2026-10-16 [09:30,10:00) New York. Offline quality reports,
explicit calendar assertions, nullable option volume and exports passed. These
checks establish those requests only, not universal IBKR availability.

### Two lightweight scientific study starters

Both workflows use only Python's standard library and saved collections. There
are no NumPy/SciPy/pandas requirements and no new installation step. Existing
IBKR acquisition still requires the manually installed SDK and logged-in TWS;
subsequent analysis is offline. These helpers are small, inspectable starting
points; users retain responsibility for deeper analysis and interpretation.

**Daily correlations:** `pyibquant.studies.daily_correlations(collection)` exports
close-to-close log returns and a descriptive Pearson matrix. Returns are computed
on adjacent dates in the union of observed starts, then rows missing any instrument
are excluded from the matrix (listwise selection). This avoids pairing an
instrument's multi-day return across a missing date with another's one-day return.
The full return table retains missing values and endpoints; sample/exclusion counts
and source quality reports accompany the matrix. Constant or insufficient samples
produce null correlations, including on the diagonal. No prices are filled and
no currency or adjustment conversion is performed. Common gaps absent from all
inputs remain unknown without an external expected calendar.

```sh
python examples/research_collection.py fetch AAPL MSFT SPY \
  --start 2025-01-01 --end 2026-01-01 \
  --output charts/studies/daily.collection.json
python examples/research_studies.py correlations charts/studies/daily.collection.json \
  --output charts/studies/correlations.json
```

**Intraday scaling preparation:** `pyibquant.studies.intraday_scaling(dataset,
lags=(1, 2, 4, 8), session_timezone="America/New_York")` exports log-price increments
and mean absolute/squared increments by lag. Lags count input bars; five-minute
inputs with lags 1/2/4/8 represent 5/10/20/40 minutes. Every intermediate bar must
exist on the exact grid, and sequences break at local date changes. There is no
interpolation, gap bridging or overnight mixing. Supply the timezone explicitly
when it is not recorded; ordinary requests without session enrichment may leave it
unknown. The stated timezone and filtering rule are saved in the result.

```sh
python examples/research_collection.py fetch AAPL --interval 5min \
  --start 2026-10-12 --end 2026-10-16 \
  --output charts/studies/intraday.collection.json
python examples/research_studies.py scaling charts/studies/intraday.collection.json \
  --instrument AAPL --session-timezone America/New_York --lags 1 2 4 8 \
  --output charts/studies/scaling.json
```

The increment is `log(close_at_end) - log(close_at_start)`; timestamps identify
source bar starts, and the elapsed lag matches the separation of those starts.
Increments overlap, so samples are dependent. Local date filtering is not an
exchange-session calendar: it does not detect every session break or certify
bar finality. Moments are descriptive; no exponent fitting, Hurst estimation,
statistical significance or multifractality conclusion is supplied. These choices
remain user-owned. Empty lag samples have null moments. Both starters reject
nonpositive closes and empty/incomplete/unknown-download inputs; source quality
unknowns remain visible and unchanged.

Verified against fresh TWS history: 250 daily bars each for AAPL/MSFT/SPY in 2025
produced 249 shared return observations; four completed AAPL sessions of five-minute
bars produced 312 input bars and 308/304/296/280 increments at lags 1/2/4/8.
Generated datasets/reports remain ignored; acquire your own bounded inputs with
the commands above. No price history or computed matrix is bundled with the package.

### Selected-option historical research

```python
from datetime import date
from pyibquant import Market, Option, BarDataset

option = Option("AAPL", date(2026, 11, 20), 340, "C", trading_class="AAPL", multiplier=100)
with Market.ibkr() as market:
    bars = market.bars(
        option, interval="5min", data_type="MIDPOINT",
        start="2026-10-16T09:30:00-04:00", end="2026-10-16T16:00:00-04:00",
    )
BarDataset.from_series(bars).save("charts/option-history/bars.dataset.json")
```

Choose a currently unexpired contract and completed range when running this
example. Options require fixed start/end bounds and an intraday interval (`30s`,
`1min`, `5min`, `15min`, `30min`, `1h`, `2h`, `4h`). `data_type` is `TRADES` (the
API default), `MIDPOINT`, `BID` or `ASK`. `live`, `duration`, `include_sessions`
and `primary_exchange` are unsupported for option history. Use the selector's
trading class/multiplier to disambiguate adjusted contracts; no multiplier is assumed.

BID/ASK/MIDPOINT volume is unavailable: Python records contain `None`, CSV leaves
it blank, datasets preserve JSON null and pandas represents it as NaN. These bars
are descriptive price aggregates; a midpoint close is not an executable fill.
Metadata retains resolved conId, expiry/strike/right, trading class, actual
multiplier, requested selector, price source and range/coverage. Option adjustment
and bar finality remain explicitly unverified. Completed paging does not certify
absence of gaps. Empty windows and broker errors remain visible; the research
example refuses empty or incomplete downloads. `market.serve()` shows option
history without stock reload/session controls; `bars.plot()` also works offline.

```sh
python examples/research_option_history.py AAPL \
  --expiry 2026-11-20 --strike 340 --right C --trading-class AAPL --multiplier 100 \
  --start 2026-10-16T09:30:00-04:00 --end 2026-10-16T16:00:00-04:00 \
  --data-type MIDPOINT --output-dir charts/option-history
python examples/research_saved.py charts/option-history/bars.dataset.json
```

The first command downloads and saves bars, metadata and returns/SMA signals. The
second recomputes research offline without TWS or the SDK. The example defaults
to MIDPOINT; pass `--data-type` explicitly for other sources. `--cache-dir` enables
the optional Parquet cache. No continuous collection is required.

After-hours TWS validation on 2026-10-16 returned 78 five-minute bars per source
for the completed regular session of AAPL 2026-11-20 340 C (conId 845042071,
multiplier 100). All four sources, a MIDPOINT cache hit and saved-data research
passed. This verifies that contract/session, not universal historical availability.

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

### First intraday option backtest

```python
from datetime import datetime
from pyibquant import BarDataset
from pyibquant.option_backtest import backtest_option
from pyibquant.research import above_sma

inputs = BarDataset.load("charts/option-history/bars.dataset.json")
result = backtest_option(
    inputs, above_sma([bar.close for bar in inputs.snapshot()], window=20),
    fill_model="next_bar_open",
    finalized_through=datetime.fromisoformat("2026-10-16T16:00:00-04:00"),
    contracts=1, commission_per_contract=0.65, slippage_bps=10,
)
print(result.metrics())
result.save("charts/option-backtest/results.json")
```

This is a single-contract **long/flat premium-price simulation** on complete,
fixed-range intraday USD option TRADES or MIDPOINT inputs. `fill_model` is required
to explicitly select synthetic next-supplied-open execution. A signal computed
using one bar's close acts no earlier than the following supplied bar's open;
overlapping bars are rejected. The last target cannot execute. Signals supplied
by callers remain their responsibility; the built-in strategies use trailing closes.

`contracts` is a fixed positive integer, with no scaling, shorting or borrowing.
Premium cash flows and position values use the **resolved multiplier**, including
nonstandard multipliers, rather than assuming 100. Commission is cash **per contract
per side**; slippage adversely shifts the premium in basis points. Costs are
configurable model inputs, not an IBKR fee schedule. Insufficient cash rejects the
fill and subsequent targets may retry. Existing positions remain marked at the last
source close with no forced sale or estimated exit fees.

`finalized_through` must be timezone-aware: it asserts that all bars whose starts
are at/before that timestamp are complete. `expected_times` optionally supplies
expected timezone-aware bar starts from an independent calendar; otherwise gap
coverage remains unverified and execution may cross a gap. Result fill/rejection
logs identify `signal_bar_start` and `execution_time` explicitly.

Neither TRADES nor MIDPOINT bars establishes an executable price. This model has
no spread, volume/liquidity, size or partial-fill constraints. BID/ASK-only inputs
are rejected because direction-aware spread execution needs another model. All
bars must precede the contract's expiry date in New York: expiry-day/later inputs
are rejected. Exercise, assignment, expiry settlement, adjusted deliverables,
interest, taxes, settlement restrictions and account-specific rules are excluded.
Saved pre-expiry history remains usable offline after the contract expires.

```sh
python examples/backtest_option.py charts/option-history/bars.dataset.json \
  --fill-model next_bar_open --finalized-through 2026-10-16T16:00:00-04:00 \
  --commission-per-contract 0.65 --slippage-bps 10
```

The example supports `--strategy above-sma` or `--strategy sma-cross`, the same
window/fast/slow controls as the equity example, and optional `--calendar` with one
ISO timestamp per line. It saves frozen inputs, strategy settings, results and
CSV fill/trade/rejection/equity logs under `charts/option-backtest/`. Results retain
source/contract metadata, input fingerprint, assumptions, realized/unrealized P&L,
fees, slippage, returns and drawdowns; no intraday annualization is inferred.

Both strategies were run offline on the saved 78-bar AAPL option datasets from
TWS, using TRADES and MIDPOINT independently. Accounting reconciliation and input
fingerprint preservation passed. This validates the workflow, not strategy quality
or historical executability. No new broker request is required for backtesting.

### Strategy-driven backtesting tools

Use `pyibquant.simulation` for custom strategies. The existing `backtest_equity()`
and `backtest_option()` interfaces retain their fixed-size signal-array behavior.
The general engine supports explicit equity/option feeds, shared USD cash,
variable whole quantities, scaling in/out and partial exits. It runs offline from
frozen datasets, without TWS, the SDK, pandas or a chart.

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.research import above_sma
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate

dataset = BarDataset.load("charts/research/bars.dataset.json")

def target(context):
    closes = [bar.close for bar in context.data["equity"].bars]
    return 2 if above_sma(closes, window=20)[-1] else 0

result = simulate(
    {"equity": Feed(dataset, finalized_through=date(2025, 12, 31))},
    TargetStrategy("equity", target),
    execution=NextOpen(commission=1, slippage_bps=5),
    strategy_settings={"name": "above_sma", "window": 20, "quantity": 2},
)
result.save("charts/strategy-backtest/results.json")
```

The extension points are deliberately small:

- **Strategy:** implement `on_bar(context)` and keep state on your strategy object.
  The callback receives only completed histories, immutable portfolio/order/fill
  snapshots, instrument identities, `timestamp` and the keys in `updated`.
  `context.data[key].latest`, `.available_at` and `.age` expose unavailable/stale
  data. Several instruments completing together trigger one callback. Their keys
  are sorted, independent of input mapping order.
- **Orders:** `context.submit(key, "buy" | "sell", quantity, tag=...)` returns an ID;
  `context.cancel(id)` cancels a pending order. Orders move through pending,
  filled, rejected or canceled states. Only market orders/full fills are currently
  supported; unsupported instructions fail explicitly. Orders compete in submission
  order with no implicit cash/position reservation. Insufficient cash or holdings
  rejects that order; strategies decide whether to retry. Remaining pending orders
  are canceled at the end with `reason="end_of_data"`.
- **Execution:** implement `execute(order, instrument, opening, portfolio)` and
  `settings()`. Return `Execution(price, commission)` for a full fill or `None` to
  defer until a later supplied open. `opening` exposes only the opening timestamp
  and price, excluding that bar's future high/low/close/volume. Invalid prices and
  fees fail the run. `NextOpen` provides adverse bps slippage, a flat fee and a
  per-share/contract fee. Costs are assumptions, not an IBKR commission schedule.
  Reported slippage is signed against the supplied open; price improvement from
  a custom model produces negative slippage cost.
- **Ledger/results:** the engine owns cash, positions and weighted-average cost
  basis, including entry fees. Partial sales allocate basis proportionally. Resolved
  multipliers scale option premiums and marks. Immutable snapshots expose average
  price, cost basis, realized/unrealized P&L and mark timestamps. Results include
  orders, fills, position/equity/return/drawdown history, basic metrics, exact input
  fingerprints/metadata and supplied strategy/model settings. Save exact datasets
  alongside results for reproducibility; strategy code/external inputs remain yours.

At each timestamp the engine publishes completed bars and invokes the strategy,
then processes opens at that timestamp. A decision may fill at an adjacent next
open, never at the earlier open of its own signal bar. Intraday bar completion is
`start + interval`; the finality assertion must cover that completion time. Unequal
intraday intervals and gaps are supported; only actual supplied opens can fill
orders. Histories retain stale closes with explicit ages. Portfolio marks update
on observed opens/closes and retain their last value when a feed goes quiet.
Equity history records separate `close` and `open` phases so boundary jumps and
costs contribute to drawdown. Dates alone do not establish exchange session times:
daily feeds use synthetic UTC calendar-day events and cannot mix with intraday
feeds. The engine does not infer holidays, shortened sessions or gap completeness.

`Feed(..., expected_starts=tuple(...))` optionally audits exact starts against an
independently supplied calendar; finality and coverage assertions are saved.
Inputs require complete fixed-range USD datasets, positive consistent OHLC, and
supported daily/intraday intervals. Equities use split-adjusted TRADES, multiplier
one. Options require exact identity/multiplier and intraday TRADES/MIDPOINT.
Duplicate instrument aliases, overlapping bars and simulation horizons crossing
an option's New York expiry date are rejected. Pre-expiry saved data works after
expiry; current wall-clock time does not restrict offline analysis.

`TargetStrategy(traded_key, target, decision_feed="underlying")` evaluates a target
quantity whenever the underlying completes a bar, even if the traded option has
a different interval. It owns pending orders for the traded instrument, cancels
them before recalculating, and submits the quantity difference. To combine several
independent order rules, implement `on_bar` directly instead. User strategies and
custom execution models remain responsible for lookahead in their own code or
external inputs; this is an interface boundary, not a Python security sandbox.

Run the saved-input example for equity, or add a selected option and use the
underlying's completed closes as its signal:

```sh
python examples/backtest_strategy.py charts/research/bars.dataset.json \
  --finalized-through 2025-12-31 --quantity 2 --commission-per-unit 0.5
python examples/backtest_strategy.py charts/underlying/bars.dataset.json \
  --option-dataset charts/option-history/bars.dataset.json \
  --finalized-through 2026-10-16T16:00:00-04:00 --commission-per-unit 0.65
```

The second example needs intraday underlying inputs covering the option experiment.
The example defaults to requiring a signal updated at the decision timestamp;
`--max-signal-age-minutes` permits an explicit age tolerance. Missing/stale signals
target zero, requesting an exit at the next supplied traded open. It saves both
inputs and JSON results/settings/logs under ignored `charts/strategy-backtest/`.

This foundation is long-only, cash-funded and single-currency. Default fills are
synthetic; spread, liquidity, partial fills, limit/stops, margin, shorting, FX,
dividends, settlement and option expiry/exercise/assignment remain outside the
supported model. There is no forced final liquidation. Intricate decision logic
can use the interfaces; new instrument/accounting semantics require engine support.

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
or Greeks. The alternative AAPL 2026-11-20 340 C returned frozen bid/ask and
model IV/Greeks on 2026-10-16, with reported feed type frozen. Its live request
returned no prices during the overnight check; in-session live option streams subsequently returned bid/ask, sizes and
model IV/Greeks on 2026-10-16. Live AAPL stock snapshots also passed. Missing SDK-normalized
Greeks and unset Decimal sizes are preserved as None.

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
option. Discovery and independent quote streaming are described below. Historical
quote imports remain future work. Snapshot calls serialize on a connection because IBKR's requested feed type is connection-wide;
they do not hold the Market control lock while waiting. Disconnects fail the
snapshot instead of silently repeating it. Historical bar recovery is unchanged.

### Option discovery and independent quote streams

`Market.option_chain()` discovers grouped expiry/strike candidates. Groups preserve
exchange, trading class and multiplier; candidate sets do not guarantee that every
expiry/strike pair exists. Selected contracts still resolve exactly before quoting.

```python
from datetime import date
from pyibquant import Market

with Market.ibkr() as market:
    chain = market.option_chain("AAPL")
    option = chain.select(date(2026, 11, 20), 340, "C",
                          trading_class="AAPL", multiplier=100)
    with market.stream_quote(option) as stream:
        quote = stream.latest()
        newer = stream.wait_for_update(quote.sequence, timeout=5)
        print(newer.status, newer.market_data_type, newer.bid, newer.ask)
```

`stream_quote()` returns before fields are available and uses standard reqMktData,
never a regulatory snapshot. Close the handle explicitly or use its context
manager; cancellation affects only that subscription. Chart navigation does not
own these streams. Consumers keep independent monotonic sequence cursors; callbacks
may coalesce, so this is not a tick archive. Quotes are immutable accumulated
observations, with local callback receipts rather than exchange timestamps.
An active stream does not certify a complete, live or executable bid/ask.

Default handles end on disconnect. Opt-in `reconnect=True` on the stream requires
the default Market recovery supervisor. It restores the exact resolved contract,
clears prices/sizes/Greeks/feed confirmation and increments the generation. Gap
history remains visible even if a consumer misses the disconnected state. New
callbacks and feed confirmation are required after replacement; gap end means the
request was issued, not that data continuity or availability has been established.
Terminal data/permission errors are not retried. Closing prevents resurrection.
All active quote streams on a connection must request the same data mode.

Option discovery/snapshots and frozen quote recovery passed explicit TWS checks.
These supporting tools do not gate historical research. The recording-specific
JSONL APIs, rotation/replay examples and recorded-quote options simulator were
removed during scope cleanup; their implementation history is recoverable from
Git commit `59da0e5`. Selected-option history now requests IBKR directly; the
intraday option backtest above consumes its saved inputs without a broker.

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
python -m pytest \
  tests/test_core.py tests/test_cache_core.py tests/test_exports.py \
  tests/test_pacing.py tests/test_research.py tests/test_dataset.py \
  tests/test_backtest.py tests/test_quote_core.py tests/test_option_core.py
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

## Local development snapshot

The current development version is `0.1.0.dev1`; see [changes](CHANGELOG.md) and
[the Python API guide](docs/API.md). This is a local development build, without
publication or a stable API guarantee.

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check src examples tests
.venv/bin/mypy
.venv/bin/python tests/build_check.py
```

The build check uses existing setuptools/pip with no network downloads. It builds
a source archive, builds the wheel from that archive, verifies documented examples
and assets, and runs `tests/wheel_smoke.py` plus CLI checks in an isolated environment
without the SDK or optional packages. Validated `.tar.gz`, `.whl` and SHA-256
checksums go under ignored `dist/`. Source archives include guides, examples and
validation scripts; generated datasets and virtual environments remain excluded.
Browser regressions additionally require installed Chrome and the `[browser]` tools.
This checkpoint is locally validated on Python 3.14; other declared Python 3.11+
versions have not been exercised as a release matrix.

For an explicit data-only broker regression (choose an available unexpired option
and completed, aligned bounds):

```sh
.venv/bin/python tests/live_workflow_check.py \
  --option-expiry 2026-11-20 --option-strike 340 --trading-class AAPL --multiplier 100 \
  --intraday-start 2026-10-16T09:30:00-04:00 --intraday-end 2026-10-16T16:00:00-04:00
```

It uses a separate client, closes its connection after bounded acquisition, then
checks offline save/reload, quality reports, both study starters, equity/option/
strategy simulation and HTML generation. Generated results stay under ignored
`charts/release-workflow-check/`. Running it does not place orders or change TWS
settings. Restricted execution environments may need local socket permission even
when TWS is already connected and listening.

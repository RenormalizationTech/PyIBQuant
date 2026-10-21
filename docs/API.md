# Core Python API reference

[Documentation home](README.md) · [Quick start](QUICKSTART.md) ·
[Research API](RESEARCH.md) · [Paper API](PAPER_TRADING.md)

For daily US stock/ETF prices without TWS, see the
[Yahoo Finance API and examples](YAHOO.md#use-the-downloaded-bars-in-python).
Yahoo uses `preview_bars()` rather than a `Market` connection.

This reference covers the supported user-facing entry points in `0.1.0.dev1`.
Provider adapters, callback plumbing, journal internals and names beginning with
`_` are implementation details. Construct connections with `Market.ibkr()` and
`PaperBroker.ibkr()`, streams with `stream_quote()`, and frozen datasets with
`BarDataset.from_series()` or `.load()` rather than their internal constructors.

Examples in each section state what objects they reuse. Start with the
[self-contained quick start](QUICKSTART.md) if you do not yet have data.

- [Connections and historical requests](#connections-and-historical-requests)
- [Bars and mutable series](#bars-and-mutable-series)
- [Frozen datasets and coverage](#frozen-datasets-and-coverage)
- [Collections and alignment](#collections-and-alignment)
- [Options and quotes](#options-and-quotes)
- [Historical cache](#historical-cache)
- [Exceptions](#exceptions)

## Connections and historical requests

Import: `from pyibquant import Market, BarRequest`.

### `Market.ibkr(...) -> Market`

```text
Market.ibkr(host="127.0.0.1", port=7497, client_id=71, timeout=30, *,
            cache_dir=None, cache_max_age=86400, refresh_cache=False, reconnect=True)
```

| Argument | Meaning |
|---|---|
| `host: str` | TWS/Gateway socket host. Localhost is the default. |
| `port: int` | Configured API port, 1–65535; default is paper TWS 7497. |
| `client_id: int` | Nonnegative ID; use a different ID for each simultaneous connection. |
| `timeout: float` | Positive request/connection timeout in seconds. Snapshot quotes normally need about 11 seconds, so retain adequate headroom. |
| `cache_dir: str \| Path \| None` | Enable historical cache in this directory; `None` disables caching. Requires the `cache` extra. |
| `cache_max_age: float` | Positive cache lifetime in seconds (86400 = 24 hours); now-ending queries have a shorter cap. |
| `refresh_cache: bool` | Bypass cache reads and refresh entries on requests. |
| `reconnect: bool` | Run background recovery for managed live subscriptions. This does not retry failed fixed-range downloads or snapshots. |

Opens the connection immediately. Prefer a `with` block to release sockets and
subscriptions even if code raises. Missing SDK raises `ImportError`; connection
failure raises `pyibquant.errors.ConnectionError`.

```python
from pyibquant import Market

with Market.ibkr(client_id=71) as market:  # IBKR data
    print(len(market.bars("AAPL", interval="1d", duration="1 M")))
```

### `market.bars(...) -> BarSeries`

```text
market.bars(symbol, *, interval="1min", duration=None, start=None, end=None,
            live=False, regular_hours=True, primary_exchange="", refresh=False,
            include_sessions=False, data_type="TRADES")
```

| Argument | Meaning and accepted values |
|---|---|
| `symbol: str \| Option` | US equity/ETF ticker, or one explicit option selector. Resolution must be unambiguous. |
| `interval: str` | Candle size: `30s`, `1min`, `5min`, `15min`, `30min`, `1h`, `2h`, `4h`, `1d`, `1w`, `1y`. Yearly equity candles aggregate monthly provider bars. |
| `duration: str \| None` | Lookback such as `"1 D"`, `"1 W"`, `"1 M"`, `"1 Y"`. Omission means `"1 D"` in lookback mode. |
| `start`, `end` | Both required for a fixed range. ISO strings, `date`, or aware `datetime`; start inclusive, end exclusive. Cannot combine with duration or live mode. |
| `live: bool` | Keep equity bars updated after initial history. May revise the current candle; keep `Market` open. |
| `regular_hours: bool` | Restrict to regular sessions if true; request extended hours if false. |
| `primary_exchange: str` | Equity contract disambiguation such as `"NASDAQ"`; empty lets resolution choose. Unsupported for options. |
| `refresh: bool` | Bypass historical cache reads for this request. |
| `include_sessions: bool` | Enrich equity metadata with provider session schedules; extra requests may be needed. Unsupported for options. |
| `data_type: str` | Equities: `TRADES` only. Options: `TRADES`, `MIDPOINT`, `BID`, `ASK`; only TRADES supplies volume. |

Daily/weekly/yearly bounds must be dates. Intraday datetimes must include a
timezone and use whole seconds. Intraday date-only bounds mean New York midnight.
Rows export intraday times in UTC; calendar bars retain dates. Options require
fixed intraday bounds and disallow live mode, duration and session enrichment.

Fixed ranges are paged sequentially. `HistoricalRangeError` retains completed
pages on failure. Returned rows can be empty; inspect `len(series)`, `error`,
`warnings` and download metadata. Completion is not proof of calendar coverage.

```python
from pyibquant import Market

with Market.ibkr() as market:  # IBKR data
    recent = market.bars("AAPL", interval="1min", duration="1 D")
    fixed = market.bars("AAPL", interval="1d", start="2026-01-05", end="2026-01-10")
    print(fixed.to_records()[:1])
```

### `BarRequest(instrument, data_type="TRADES", primary_exchange="")`

An offline selector for one entry in `datasets()`. `instrument` is a ticker or
`Option`; `data_type` and `primary_exchange` mean the same as in `bars()`.
Rejects non-TRADES equity requests and primary exchanges on option requests.

### `market.datasets(...) -> BarDatasetCollection`

```text
market.datasets(instruments, *, start, end, interval="1d", regular_hours=True,
                refresh=False, include_sessions=False)
```

`instruments` is a nonempty mapping of your labels to tickers, `Option` or
`BarRequest`. Labels must be nonblank and cannot be `timestamp`. The remaining
arguments have the same meanings as in `bars()` and apply to every entry.
Downloads run sequentially and return frozen datasets only when each input is
nonempty and its download completed. This method does not save files.

```python
from pyibquant import BarRequest, Market

with Market.ibkr() as market:  # IBKR data
    inputs = market.datasets(
        {"apple": BarRequest("AAPL", primary_exchange="NASDAQ"), "benchmark": "SPY"},
        start="2026-01-05", end="2026-01-10", interval="1d",
    )
inputs.save("charts/inputs.collection.json")
print(inputs["apple"].describe())
```

Failure raises `DatasetCollectionError`: `.failed_key` identifies the input,
`.completed` holds earlier frozen datasets, and `.__cause__` is the original
error. Invalid local selectors/modes raise `ValueError` before acquisition.

### Other `Market` methods and properties

| API | Arguments, result and behavior | Example (inside an open `Market`) |
|---|---|---|
| `load_older(bars, *, refresh=False) -> int` | `bars` is a lookback series from this connection; fetch one older page. Returns number added, retaining current/live rows. `refresh` bypasses cache. Fixed ranges are rejected. | `added = market.load_older(recent)` |
| `cancel(series) -> None` | Stop updates and reconnection restoration for that `BarSeries`; existing rows remain. | `market.cancel(recent)` |
| `serve(bars, *, port=0, open_browser=True, include_sessions=True) -> None` | Blocking localhost chart until Ctrl+C. `port=0` chooses a free port; optional browser launch and equity session enrichment. Supports interactive equity reload/history; fixed option charts retain their identity. | `market.serve(recent, open_browser=False)` |
| `cache` | Property: configured `HistoricalCache`, or `None`. | `print(market.cache)` |
| `close() -> None` | Close the provider and managed subscriptions. Context exit calls it. | `market.close()` |

`serve()` needs the connection to stay open while it runs. For a saved chart,
use `series.plot()` instead. Quotes and chains are documented below.

## Bars and mutable series

Import: `from pyibquant import Bar, BarSeries`.

### `Bar(timestamp, open, high, low, close, volume)`

Immutable candle. `timestamp` is a daily `date` or timezone-aware intraday
`datetime`. `open/high/low/close` are finite prices in the instrument's price
units; `volume` is finite or `None` when unavailable. Option premiums are quoted
per unit; contract cash exposure also uses the resolved multiplier.
The constructor checks finiteness and timezone awareness; use quality reports
for OHLC consistency/negative-volume flags.

`bar.chart_data() -> dict` returns chart keys `time`, OHLC and volume. `time` is
an ISO date for calendar bars or epoch seconds for intraday candles.

```python
from datetime import date
from pyibquant import Bar, BarSeries

bar = Bar(date(2026, 1, 5), 100, 103, 99, 102, 1000)
print(bar.close, bar.chart_data()["time"])  # 102, '2026-01-05'
series = BarSeries("DEMO", "1d")
series.provider = "synthetic"
series.update(bar)
```

### `BarSeries(symbol, interval, *, live=False)`

Mutable, thread-safe container. `symbol` is its display ticker; `interval` uses
the strings above. `live` marks intended use; constructing a series does not
subscribe to anything. Usually obtain it from `market.bars()`.

The examples in this table continue the synthetic block above.

| Method | Arguments and return | Example |
|---|---|---|
| `update(bar, *, live=False) -> None` | Insert/replace a `Bar` at its timestamp. `live=True` also records local live receipt time; does not open a subscription. | `series.update(bar)` |
| `prepend(bars) -> int` | Iterable of older `Bar`s. Add only timestamps older than the existing first row; never replace existing rows. Returns count added. | `series.prepend([Bar(date(2026, 1, 2), 99, 101, 98, 100, 500)])` |
| `merge_sessions(sessions) -> None` | Merge iterable of schedule dictionaries identified by `start`, `end`, `regular`. Normally populated by the provider. | `series.merge_sessions([])` |
| `snapshot() -> tuple[Bar, ...]` | Ordered immutable row snapshot; no arguments. Use this for consistent iteration. | `closes = [b.close for b in series.snapshot()]` |
| `to_records() -> list[dict]` | Independent OHLCV rows; native date/UTC datetime timestamps. | `print(series.to_records()[0])` |
| `to_csv(path) -> Path` | Atomically write OHLCV CSV, creating parent directories. ISO timestamps; missing volume exports blank. | `series.to_csv("charts/demo.csv")` |
| `to_dataframe() -> DataFrame` | Independent pandas OHLCV frame indexed by timestamp; requires `pandas` extra. | `frame = series.to_dataframe()` |
| `metadata() -> dict` | Copy provenance, query, coverage, download progress, schedules and warnings. | `print(series.metadata()["coverage"])` |
| `payload() -> dict` | Chart-oriented state and serialized candles; use dataset save for reusable research inputs. | `print(series.payload()["bars"])` |
| `plot(path="charts/chart.html", *, open_browser=True) -> Path` | Export a static HTML snapshot and optionally launch a browser. Does not keep updating. | `series.plot("charts/demo.html", open_browser=False)` |
| `len(series) -> int` | Number of currently observed candles. | `print(len(series))` |

Useful attributes: `symbol`, `interval`, `live`; resolved `instrument_id`,
`asset_type`, `currency`, `exchange`, `primary_exchange`, `multiplier`;
`data_type`, `adjustment`, `session_timezone`, `regular_hours`; `status`, `error`,
`warnings`, `connection_state`, `last_update`, `last_live_update`;
`requested_start/end`, `download_complete/pages/cached_pages`, `empty_windows`,
`history_exhausted`, `cache_hit` and `sessions`. Unknown identity fields can be
`None`. Receipt times do not independently prove freshness or finality.

## Frozen datasets and coverage

Import: `from pyibquant import BarDataset, CoverageAudit`.

### Creation, inspection and persistence

| API | Arguments, return and behavior | Example (reuse `series` above) |
|---|---|---|
| `BarDataset.from_series(series) -> BarDataset` | Copy one consistent snapshot of rows and provenance. Future series updates cannot change it. | `dataset = BarDataset.from_series(series)` |
| `BarDataset.load(path) -> BarDataset` | Read local JSON and validate format, SHA-256 and consistency. No SDK/connection required. | `loaded = BarDataset.load("charts/demo.bars.json")` |
| `save(path) -> Path` | Atomically replace file with rows, metadata and integrity digest; creates parents. | `dataset.save("charts/demo.bars.json")` |
| `snapshot() -> tuple[Bar, ...]` | Frozen ordered rows. | `print(dataset.snapshot()[0].close)` |
| `to_records() -> list[dict]` | Fresh OHLCV dictionaries with native date/UTC datetime stamps. | `print(dataset.to_records())` |
| `metadata() -> dict` | Independent copy of original provenance. | `print(dataset.metadata()["query"])` |
| `describe() -> dict` | Summary of identity, sampling, requested/observed coverage, download progress and fingerprint. | `print(dataset.describe())` |
| `fingerprint() -> str` | SHA-256 of rows **and provenance**; detects accidental changes, not authenticity. | `print(dataset.fingerprint())` |
| `len(dataset) -> int` | Number of frozen bars. | `print(len(dataset))` |

`BarDataset` has no `plot()`, `to_csv()` or `to_dataframe()` method. Use series
exports before freezing, or work with `dataset.to_records()` yourself.

### `dataset.audit(expected, *, finalized_through=None) -> CoverageAudit`

`expected` is an iterable of exact expected bar starts from **your calendar**;
use dates for calendar bars and aware datetimes for intraday bars. Duplicate or
wrong-kind timestamps raise `ValueError`. No exchange calendar is inferred.
`finalized_through` is an optional inclusive **bar-start** finality assertion.
Without it all observed bars are unconfirmed.

Returned fields: `expected_count`, `observed_count`, `missing` (expected but absent),
`unexpected` (observed but not expected), `unconfirmed` (starts beyond the assertion,
or all starts when absent), and `finality_checked`. `matches_calendar` is true
when neither missing nor unexpected starts exist; it does not check finality.

### `dataset.quality_report(expected=None, *, finalized_through=None) -> dict`

Same arguments as `audit()`, except `expected` may be omitted. Adds null/zero/
negative-volume, nonpositive-price and inconsistent-OHLC counts, provenance and
warnings. Without an expected calendar, missing-bar counts remain unknown.
Neither method repairs data or changes its fingerprint.

```python
from datetime import date
from pyibquant import BarDataset

# Offline; file created in the quick start.
dataset = BarDataset.load("charts/demo.bars.json")
expected = [date(2026, 1, day) for day in (5, 6, 7)]  # Toy calendar for toy data.
audit = dataset.audit(expected, finalized_through=date(2026, 1, 7))
print(audit.matches_calendar, audit.missing)  # True, ()
report = dataset.quality_report(expected, finalized_through=date(2026, 1, 7))
print(report["observations"])
```

**Finality distinction:** this audit and the legacy option backtest use inclusive
bar starts. The general simulator's `Feed` requires intraday confirmation through
**start + interval**. A 09:30 one-minute candle needs a 09:31 assertion there.
All assertions come from the caller; completed downloads do not establish them.

## Collections and alignment

Import: `from pyibquant import BarDatasetCollection, AlignedData`.

### `BarDatasetCollection(datasets)`

`datasets` is a nonempty mapping of nonblank labels to `BarDataset`s; `timestamp`
is reserved. A collection implements a read-only mapping: `inputs["apple"]`,
`list(inputs)`, `.items()` and `len(inputs)` work normally. Labels do not replace
resolved contract identities. Different kinds of inputs can be stored together,
but may not align.

| Method | Arguments and result | Example (reuse `dataset` above) |
|---|---|---|
| `save(path) -> Path` | Atomically save all original inputs and integrity digests. | `inputs.save("charts/demo.collection.json")` |
| `BarDatasetCollection.load(path)` | Verify and reload the collection and each dataset offline. | `inputs = BarDatasetCollection.load("charts/demo.collection.json")` |
| `describe() -> dict` | Per-source descriptions and collection fingerprint. | `print(inputs.describe())` |
| `fingerprint() -> str` | Digest of labelled inputs and their order/content/provenance. | `print(inputs.fingerprint())` |
| `align(*, field="close", join) -> AlignedData` | `field`: open/high/low/close/volume. Required `join`: `inner` keeps shared starts, `outer` keeps all observed starts with `None` for absent values. | `aligned = inputs.align(field="close", join="outer")` |
| `quality_report(expected=None, *, finalized_through=None, join=None, field="close") -> dict` | `expected` maps labels to expected starts; `finalized_through` maps labels to assertions. Optional join adds alignment losses/blocking reasons; field chooses OHLCV. Unknown assertion labels raise `ValueError`. | `print(inputs.quality_report(join="outer"))` |

Alignment requires equal interval, timestamp kind, regular-hours setting and
session timezone; known incomplete downloads are rejected. It never fills,
resamples, converts currencies or harmonizes adjustment/price sources. It compares
observed timestamps; a date absent from every source needs an external calendar
to be detected. Quality reporting remains available for incompatible inputs.

`AlignedData.timestamps` is the ordered tuple of starts; `.columns` maps labels
to equal-length value tuples. Normally obtain it from `.align()`. Its methods:

| Method | Return | Example |
|---|---|---|
| `metadata()` | Independent alignment report, source metadata, dropped/absent/null row counts. | `print(aligned.metadata()["sources"])` |
| `to_records()` | Rows shaped `{"timestamp": ..., "label": value, ...}`. | `print(aligned.to_records())` |
| `to_dataframe()` | Optional pandas frame with timestamp index; missing values become NaN. | `frame = aligned.to_dataframe()` |

```python
from pyibquant import BarDataset, BarDatasetCollection

# Offline; quick-start output.
dataset = BarDataset.load("charts/demo.bars.json")
inputs = BarDatasetCollection({"demo": dataset})
inputs.save("charts/demo.collection.json")
aligned = inputs.align(join="outer")
print(aligned.to_records()[0])
```

## Options and quotes

Import: `from pyibquant import Option, OptionChain, Quote, QuoteStream`.

### `Option(symbol, expiry, strike, right, trading_class="", multiplier=None)`

Offline selector for exactly one US equity/ETF option. `symbol` is the underlying
symbol; `expiry` must be a `date` (not datetime); `strike` is positive and finite;
`right` is `C` (call) or `P` (put). Symbol/right/trading class normalize to uppercase.
Optional `trading_class` and positive `multiplier` disambiguate adjusted series.
No multiplier is assumed; IBKR resolves the selector before acquiring data.

```python
from datetime import date
from pyibquant import Option

selector = Option("AAPL", date(2026, 11, 20), 365, "C")
print(selector.right)  # C; constructing it makes no network request.
```

This dated selector demonstrates syntax; choose a currently valid contract for
connected checks. There is no expired-chain reconstruction, automatic contract
selection or guarantee that an expiry/strike/right combination exists.

### `market.option_chain(symbol, *, primary_exchange="") -> OptionChain`

Underlying equity ticker and optional primary-exchange disambiguation. Returns
metadata partitions without subscribing to option prices. `OptionChain` fields:
`symbol`, `underlying_instrument_id`, `currency`, `groups`, `received_at`.
Each `OptionChainGroup` has `exchange`, `trading_class`, `multiplier`, `expirations`
(tuple of dates) and `strikes` (tuple of numbers).

`chain.select(expiry, strike, right, *, trading_class="", multiplier=None) -> Option`
uses the selector meanings above and requires exactly one matching SMART group;
otherwise raises `ValueError`. Expirations and strikes are separate sets, so the
result is still a candidate that must resolve, not a verified contract.
`chain.to_dict()` exports JSON-compatible discovery metadata.

```python
from pyibquant import Market

with Market.ibkr() as market:  # IBKR data
    chain = market.option_chain("AAPL")
    print(chain.to_dict())
    for group in chain.groups:
        print(group.exchange, group.trading_class, group.expirations[:3], group.strikes[:3])
# After inspecting a group, chain.select(expiry, strike, "C", trading_class=...)
# creates your chosen candidate; do not assume every pair is listed.
```

### `market.quote(symbol, *, primary_exchange="", market_data_type="live") -> Quote`

`symbol` is an equity ticker or `Option`; `primary_exchange` disambiguates equities.
`market_data_type` is `live`, `frozen`, `delayed` or `delayed_frozen`. Uses standard
Level-one snapshots (not regulatory snapshots). Normally completes in about 11
seconds. A disconnect raises instead of silently retrying. Requested mode does not
prove actual feed mode or permission; inspect the returned fields.

```python
from pyibquant import Market

with Market.ibkr(timeout=30) as market:  # IBKR data
    quote = market.quote("AAPL", market_data_type="delayed")
    print(quote.bid, quote.ask, quote.midpoint, quote.market_data_type)
    print(quote.to_dict()["warnings"])
```

### `market.stream_quote(..., reconnect=False) -> QuoteStream`

Same symbol/exchange/mode arguments as `quote()`, plus `reconnect` to opt into
handle-preserving recovery. Requires `Market.ibkr(reconnect=True)` for that option.
All active streams on one provider must request the same data mode. Default
streams end on disconnect. Recovered streams clear fields, record gaps and require
new feed confirmation; they do not provide uninterrupted tick history.

| Method/property | Meaning | Example (with open `stream`) |
|---|---|---|
| `latest() -> Quote` | Copy currently accumulated fields without waiting. | `current = stream.latest()` |
| `wait_for_update(after=0, *, timeout=None) -> Quote` | Wait for sequence newer than nonnegative integer `after`, or stream termination. Timeout is seconds, nonnegative, or `None` to wait indefinitely. Timeout returns current state, not an exception. | `next_quote = stream.wait_for_update(current.sequence, timeout=5)` |
| `closed -> bool` | Whether subscription ended. | `print(stream.closed)` |
| `close() -> None` | End this subscription and wake waiters; context exit calls it. | `stream.close()` |

```python
from pyibquant import Market

with Market.ibkr() as market:  # IBKR data, bounded observation
    with market.stream_quote("AAPL", market_data_type="delayed") as stream:
        previous = stream.latest()
        current = stream.wait_for_update(previous.sequence, timeout=5)
        print("New callback:", current.sequence > previous.sequence)
        print(current.status, current.bid, current.ask)
```

Each consumer keeps its own sequence cursor. Updates can coalesce; the stream is
an accumulated quote, not a callback-by-callback archive.

### `Quote` fields and helpers

Obtain immutable `Quote` objects from `quote()` or a stream, not by filling all
constructor fields yourself.

| Fields | Meaning |
|---|---|
| `instrument` | Resolved `QuoteInstrument`: symbol, instrument_id, asset_type, currency, exchange, primary_exchange, local_symbol, trading_class, multiplier, expiry, strike, right. |
| `bid`, `ask`, `last`, `bid_size`, `ask_size`, `last_size` | Independently received values; any may be `None`. Missing is not zero. |
| `requested_data_type`, `market_data_type`, `delayed_ticks` | Requested and actual confirmed feed evidence. Actual type may be unknown. |
| `requested_at`, `completed_at`, `observed_at`, `field_received_at`, `field_tick_types` | Local request/callback times and tick provenance; not exchange timestamps. Per-field tuples can be converted with `dict(...)`. |
| `greeks` | Tuple of `OptionGreeks` observations with source, delayed flag, receipt time, implied_volatility, delta, option_price, pv_dividend, gamma, vega, theta, underlying_price. Missing values remain `None`. |
| `streaming`, `sequence`, `status`, `error`, `warnings` | Subscription/snapshot lifecycle and observation cursor. |
| `generation`, `gaps` | Reconnection generation and `QuoteGap` records (started_at, ended_at, reason, previous_generation, next_generation). |

`quote.crossed` reports ask below bid. `quote.spread` is ask minus bid and
`quote.midpoint` is their average; both are `None` for absent/crossed prices.
`quote.is_delayed` uses confirmed mode/delayed ticks. `quote.to_dict()` produces
JSON-compatible data with these derived fields. No helper proves a price is
currently executable. Frozen data is not live even if `is_delayed` is false.

For example, on any acquired quote: `print(quote.spread, quote.crossed)` and
`print(dict(quote.field_received_at).get("bid"))`.

## Historical cache

Import: `from pyibquant import HistoricalCache`.

`HistoricalCache(directory=None, *, max_age=86400)` requires the `cache` extra.
`directory` is a string/Path; omission uses `default_cache_dir()` from
`pyibquant.data.cache`. `max_age` is positive finite seconds. Directory creation
is deferred until writing. This is an exact-query Parquet cache, not a substitute
for a frozen experiment dataset. Now-ending history expires after at most five
minutes; fixed-end history uses `max_age`. Live subscriptions bypass it.

| API | Meaning | Example |
|---|---|---|
| `inspect() -> list[dict]` | Entry metadata, size, expiration and corrupt-entry errors without broker access. | `print(cache.inspect())` |
| `clear() -> int` | Delete only this cache's namespaced Parquet files, including corrupt ones; return removed count. | `removed = cache.clear()` |
| `get(query) -> CacheEntry \| None` | Low-level exact query-dictionary lookup; missing/expired returns None. Usually let Market construct provider query keys. | `entry = cache.get(query)` |
| `put(query, bars) -> None` | Low-level cache write: provider query dictionary and sequence of `Bar`s. Usually managed by Market. | `cache.put(query, bars)` |

`CacheEntry.bars` contains cached candles; `.created_at` is the recorded creation
time. Query keys are provider metadata, not arbitrary ticker strings. For manual
use, prefer these public workflows instead of constructing cache keys:

```python
from pyibquant import HistoricalCache, Market

cache = HistoricalCache("charts/history-cache", max_age=3600)
print(cache.inspect())  # Offline; [] in a new directory.
with Market.ibkr(cache_dir="charts/history-cache", cache_max_age=3600) as market:
    bars = market.bars("AAPL", interval="1d", start="2026-01-05", end="2026-01-10")
    print(bars.metadata()["download"])
```

For an isolated **offline** exercise of the low-level cache methods (requires
`cache` extra), use a separate synthetic directory and an explicit query key:

```python
from datetime import date
from pyibquant import Bar, HistoricalCache
from pyibquant.data.cache import default_cache_dir

print("Default directory:", default_cache_dir())
cache = HistoricalCache("charts/synthetic-cache", max_age=3600)
query = {"provider": "synthetic", "symbol": "DEMO", "interval": "1d", "end": "2026-01-06"}
cache.put(query, [Bar(date(2026, 1, 5), 100, 103, 99, 102, 1000)])
entry = cache.get(query)
assert entry is not None
print(entry.bars[0].close, entry.created_at)  # 102.0 and UTC cache creation time
print(cache.inspect())
print("Removed:", cache.clear())  # Removes this exercise's cache entries.
```

`query` values must be strings, integers or booleans. Keys identify the exact
request; `end` being absent/empty applies the short now-ending TTL. `bars` must
be ordered, unique and use one timestamp kind; an empty sequence is not cached.
Do not write synthetic entries into a real provider cache.

Cache hits still require a Market connection/contract resolution. For a completely
offline workflow use `BarDataset.load()`.

## Exceptions

Import market errors from `pyibquant.errors`; broker errors are also exported
from `pyibquant`.

| Exception | What to inspect/do |
|---|---|
| `PyIBQuantError` | Common package-error base. |
| `ConnectionError` | TWS connection failed/lost. This is the package class, distinct from Python's builtin. Check host/port/login/client ID. |
| `DataError` | Failed market-data request; inspect message and permissions. |
| `RequestTimeout` | Data request did not complete within the timeout. |
| `HistoricalRangeError` | `.partial` is a `BarSeries`; `.remaining_start/end` bound unfinished history. Do not treat partial data as a completed dataset. |
| `DatasetCollectionError` | `.failed_key`, `.completed`, `.__cause__` preserve failed label and earlier results. |
| `CacheError` | Local cache read/write problem. |
| `BrokerError`, `OrderWaitError` | Paper lifecycle failure; wait errors include `.last_order`. See [paper API](PAPER_TRADING.md). |
| `ValueError` | Invalid arguments, incompatible inputs or rejected saved-file integrity. |
| `ImportError` | Missing optional dependency or unsupported/missing official SDK. |
| `OSError` | File/path/permission failure during local I/O. |

```python
from pyibquant import Market
from pyibquant.errors import DatasetCollectionError, HistoricalRangeError

try:  # IBKR data; never silently consume incomplete results.
    with Market.ibkr() as market:
        inputs = market.datasets({"apple": "AAPL"}, interval="1d",
                                 start="2026-01-05", end="2026-01-10")
except DatasetCollectionError as exc:
    print("Failed:", exc.failed_key, "Completed:", list(exc.completed))
    if isinstance(exc.__cause__, HistoricalRangeError):
        print("Partial rows:", len(exc.__cause__.partial))
    raise
```

# Try features one at a time

[Documentation home](README.md) · [Quick start/setup](QUICKSTART.md) · [Core API](API.md)

Run commands from the repository root with your virtual environment active.
Use separate, unique client IDs for simultaneous IBKR connections. The checks
below distinguish **offline**, **IBKR data**, and **paper observation**. No order
execution is needed to learn the data/research APIs.

## Suggested checklist

| Check | Prerequisite | What to verify |
|---|---|---|
| Offline walkthrough | Base install | Five synthetic rows, saved/reloaded fingerprints match, known backtest results. |
| Fixed daily history | SDK + TWS/Gateway + permissions | Nonempty rows within bounds; inspect download metadata and warnings. |
| CSV/HTML exports | A BarSeries | CSV has timestamp/OHLCV; HTML shows matching candles. |
| Frozen data reuse | Saved dataset | Reload after closing TWS; fingerprint/rows unchanged. |
| Quality/calendar audit | Independent expected starts | Missing/unexpected bars are explicit; unknown finality stays unknown. |
| Collections | Two compatible datasets | Named columns; inspect inner/outer row counts and absence reports. |
| Signal/backtest | Completed qualifying dataset | Warmup values and next-open timing; final signal cannot execute. |
| Quote snapshot | Quote permissions | Inspect actual data mode, missing fields and per-field receipt times. |
| Quote stream | Streaming permissions | Sequence advances, bounded wait can time out, close ends subscription. |
| Historical cache | `cache` extra | Repeating identical query uses cached pages; frozen load remains independent. |
| Account report | Paper account + SDK | Read-only snapshot and HTML; missing P&L remains explicit. |

## Offline walkthrough

```sh
python examples/quickstart_offline.py
```

Expected terminal checks:

```text
Rows: 5; dataset/collection round trips and toy-calendar audit passed
SMA: (None, 102.0, 102.5, 101.0, 101.0)
Targets: (False, True, False, False, True)
...
Equity backtest: 2 fills; final equity 997.0 (zero costs)
General simulator: 1 fill; 1 share retained; final equity 1000.0
```

Under `charts/quickstart/`, inspect `demo.csv`, `demo.html`, `demo.bars.json`,
`demo.collection.json`, `backtest.json`, and `simulation.json`. Open the HTML in a
browser. Re-run with `--output-dir /tmp/pyibquant-demo` to use a separate destination.
The toy fixture has five invented prices and explicitly synthetic provenance;
it does not validate a real provider or trading strategy.

## Historical bars, exports and reuse

Run steps 4–5 of the [quick start](QUICKSTART.md). Then close the market connection
and reload `charts/aapl.bars.json`. Verify you can inspect `describe()` and calculate
signals with no SDK/network calls during reload.

For a read-only chart through the CLI:

```sh
python -m pyibquant --help
python -m pyibquant chart AAPL --interval 1d --duration '1 M' --no-browser --output charts/manual-aapl.html
```

For updates, add `--live` with an intraday interval. It serves a localhost chart
until Ctrl+C; the connection must remain open. During closed markets there may be
no updates. A saved HTML snapshot does not continue updating.

With no TWS, an optional external-provider daily preview is available:

```sh
python -m pip install -e '.[yahoo]'
python -m pyibquant chart AAPL --provider yahoo --interval 1d --duration '1 Y' --no-browser
```

See the [Yahoo Finance guide](YAHOO.md) for Python downloads, exports and limits.
This requires internet and uses Yahoo, with different provenance; it does not
validate IBKR permissions, intraday data, live mode or the IBKR cache.

## Collections and study checks

Run the `Market.datasets()` example in [API.md](API.md#connections-and-historical-requests)
to create `charts/inputs.collection.json`. Then, offline:

```python
from pyibquant import BarDatasetCollection
from pyibquant.studies import daily_correlations

inputs = BarDatasetCollection.load("charts/inputs.collection.json")
outer = inputs.align(join="outer")
inner = inputs.align(join="inner")
print("outer/inner:", len(outer.timestamps), len(inner.timestamps))
print(outer.metadata()["sources"])
print(inputs.quality_report(join="outer")["differences"])
print(daily_correlations(inputs)["correlation"])
```

Inner count cannot exceed outer count. Equal counts do not establish a complete
market calendar. A short range may yield too few nonconstant returns for a defined
correlation; None is expected in that case.

## Quote checks

Run the snapshot and bounded stream examples in [API.md](API.md#options-and-quotes).
Inspect `market_data_type`, `status`, `warnings`, `field_received_at` and `gaps`,
not only bid/ask. Missing prices can be a permission/session/provider outcome.
A timed wait returning the same sequence is not a new observation.

## Selected option history

First inspect `market.option_chain("AAPL")` and choose an actual available,
unexpired contract. Replace the illustrative expiry/strike below with that choice
and use a recent range before expiry that the provider can supply.
This example needs option historical permissions and makes no orders.

```python
from datetime import date
from pyibquant import BarDataset, Market, Option

# Illustrative selection; verify/replace before running.
selector = Option("AAPL", date(2026, 11, 20), 365, "C")
with Market.ibkr() as market:
    bars = market.bars(selector, interval="5min", data_type="MIDPOINT",
                       start="2026-10-19T09:30:00-04:00",
                       end="2026-10-19T10:30:00-04:00")
    print(len(bars), bars.metadata())
    if not len(bars):
        raise RuntimeError("No option observations returned")
    BarDataset.from_series(bars).save("charts/selected-option.bars.json")
```

Verify exact option identity/multiplier in metadata. MIDPOINT volume should remain
None. Option history requires fixed intraday bounds; duration, live, session
enrichment and daily option bars are rejected. Expired-option reconstruction is
outside this package. The [option backtest](RESEARCH.md) is explicitly synthetic.

## Cache checks

```sh
python -m pip install -e '.[cache]'
```

Run the same fixed range twice within one `Market.ibkr(cache_dir="charts/manual-cache")`
context. Inspect each result's `metadata()["download"]["cached_pages"]` and
`cache_hit` evidence; repeat with `refresh=True` to bypass reads.
Inspect without TWS:

```sh
python -m pyibquant cache inspect --cache-dir charts/manual-cache
```

To deliberately remove that test cache's namespaced files:
`python -m pyibquant cache clear --cache-dir charts/manual-cache`.
A query cache accelerates downloads; it is not a broker-free replacement for
`BarDataset.load()`.

## Read-only paper account checks

```sh
python examples/paper_preflight.py --help
python examples/paper_preflight.py --profile examples/paper_aapl.json
python examples/paper_account.py --snapshot
```

Preflight defaults to local checks; consult `--help` for an optional connected
check. Account snapshot connects to paper TWS, saves observations/reports, and
sends no orders. Use [PaperBroker's API](PAPER_TRADING.md) for explicit host, port,
account, journal and client settings.

Order methods and runner checks have stronger ownership/funding prerequisites.
Read [paper API](PAPER_TRADING.md) and [recovery procedures](WORKFLOWS.md) before
intentionally using `--execute`. Preserve the exact run/check ID for recovery.

## Troubleshooting

| Symptom | First things to inspect |
|---|---|
| `ModuleNotFoundError: pyibquant` | Activate the venv used for editable installation; run commands from this checkout. |
| SDK ImportError/version error | Install official 10.33+ client in the same interpreter; check `get_version_string()`. |
| Connection refused/timeout | Logged-in TWS/Gateway, socket API enabled, localhost trusted, actual configured port and distinct client ID. |
| History/quotes denied | Provider error/warnings and instrument-specific permissions; delayed quote mode is explicit, not an automatic fallback. |
| Empty history | Bounds, interval, sessions, instrument identity and provider availability. Do not manufacture rows. |
| Invalid bounds | Supply both start/end, start < end, no duration/live conflict; date-only daily or aware intraday times. |
| Study/backtest rejects a dataset | Inspect metadata for completed fixed range, source, asset type, adjustment, multiplier and finality requirements. A minimal synthetic series lacks these assertions. |
| `None` prices, volume, fees or P&L | Missing provider observations; do not substitute zero or stale values as current evidence. |
| No live updates | Closed/quiet session, permissions, `live=True`, connection still open and stream status. |
| Cannot load edited JSON | Integrity digest protects frozen content. Recreate through the API rather than hand-editing a saved document. |
| Optional export/cache ImportError | Install `.[pandas]` or `.[cache]` in the active venv. |
| Paper order wait times out | Inspect OrderWaitError.last_order; reconcile original journal/order. A timeout does not prove rejection or cancellation. |

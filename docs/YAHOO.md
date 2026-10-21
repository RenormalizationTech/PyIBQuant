# Yahoo Finance data without TWS

[Documentation home](README.md) · [Quick start](QUICKSTART.md) · [Core API](API.md)

You can download daily US stock/ETF prices and try charts, exports and simple
calculations without TWS, IB Gateway or the IBKR SDK. The implemented Yahoo
Finance preview uses the optional `yfinance` dependency and needs internet access.
It does not require an IBKR account or an API key in this package's interface.

## Install and try a chart

From this checkout, with your virtual environment active:

```sh
python -m pip install -e '.[yahoo]'
python -m pyibquant chart AAPL --provider yahoo --interval 1d --duration '1 Y'
```

The command downloads daily bars, prints the received count and preview warning,
writes `charts/chart.html`, and opens that saved chart in your browser. To choose
the output and skip automatic browser launch:

```sh
python -m pyibquant chart SPY --provider yahoo --interval 1d --duration '6 M' --output charts/yahoo-spy.html --no-browser
```

Open the printed file afterward. Counts depend on provider availability and the
requested lookback. The latest daily candle may still be forming.

| CLI argument | Meaning |
|---|---|
| `AAPL` / `SPY` | US stock or ETF ticker; responses must identify USD, a New York exchange timezone and equity/ETF instrument type. |
| `--provider yahoo` | Explicitly choose Yahoo. Omission selects IBKR; the package never silently switches sources. |
| `--interval 1d` | Required daily interval for this preview. The general chart command defaults to `1min`, so supply `1d` explicitly. |
| `--duration '1 Y'` | Positive lookback, using D/W/M/Y for days/weeks/months/years, such as `10 D`, `2 W`, `6 M`, `1 Y`. |
| `--timeout 30` | Positive download timeout in seconds. Default 30. |
| `--output charts/yahoo-spy.html` | Saved HTML destination; default `charts/chart.html`. Parent directories are created. |
| `--no-browser` | Save without launching a browser. |

There is no live, intraday, extended-hours, primary-exchange selection or IBKR-cache
mode for Yahoo. Those combinations are rejected rather than ignored. Socket
host/port/client-ID settings do not configure a Yahoo download.

## Use the downloaded bars in Python

The preview helper is implemented in `pyibquant.data.providers.yahoo`, separate
from the IBKR `Market` interface:

```text
preview_bars(symbol, *, duration="1 Y", timeout=30) -> BarSeries
```

| Argument | Meaning |
|---|---|
| `symbol: str` | Nonempty US equity/ETF ticker; whitespace is stripped and letters uppercased. |
| `duration: str` | Positive D/W/M/Y lookback, default one year. Bounds are computed relative to the current New York date, including today if data is returned. |
| `timeout: float` | Positive timeout in seconds passed to the historical download. |

Returns a daily `BarSeries`, with calendar-date timestamps, source warnings and
Yahoo provenance. This helper exposes no fixed `start/end` arguments. It does not
open a broker connection. There is no `Market.yahoo()` factory.

Run this complete example after installing `.[yahoo]`:

```python
from pyibquant import BarDataset
from pyibquant.data.providers.yahoo import preview_bars
from pyibquant.research import simple_returns, sma

series = preview_bars("SPY", duration="1 Y", timeout=30)
print("Rows:", len(series))
print("First row:", series.to_records()[0])
print("Warnings:", series.warnings)
print("Source:", series.metadata()["provider"])

series.to_csv("charts/yahoo-spy.csv")
series.plot("charts/yahoo-spy.html", open_browser=False)
# yfinance supplies pandas, so DataFrame export is available with this extra.
frame = series.to_dataframe()
print(frame.tail())

closes = [bar.close for bar in series.snapshot()]
print("Last five returns:", simple_returns(closes)[-5:])
print("Last five 20-day averages:", sma(closes, window=20)[-5:])

# Freeze and reload the original source metadata without needing internet again.
dataset = BarDataset.from_series(series)
dataset.save("charts/yahoo-spy.bars.json")
loaded = BarDataset.load("charts/yahoo-spy.bars.json")
assert loaded.fingerprint() == dataset.fingerprint()
print(loaded.quality_report()["warnings"])
```

The saved JSON is an ordinary `BarDataset`; CSV and HTML are separate exports.
Reloading it later needs only the base package, not Yahoo, TWS or a network
connection. The [BarSeries and dataset reference](API.md#bars-and-mutable-series)
explains the shared container methods.

## What Yahoo supports in this package

| Feature | Yahoo preview | IBKR interface |
|---|---|---|
| Connection | Internet via yfinance | Official SDK and logged-in TWS/Gateway |
| Instruments | US stocks/ETFs in USD | US equities/ETFs and selected options within documented scope |
| Sampling | Daily snapshots | Supported intraday and calendar intervals, subject to instrument restrictions |
| Request selection | Relative lookback duration | Lookback or fixed start/end ranges |
| Exports and simple returns/SMA | Yes | Yes |
| Price adjustment | Splits and dividends | Equity TRADES research uses splits-only adjustment |
| Download completeness | Unknown (`None`) | Fixed-range request completion recorded separately from market coverage |
| Quotes, live bars, schedules, option history | Unsupported | Separate documented methods and permissions |
| Historical query cache | Unsupported | Optional exact-query Parquet cache |
| Strict study/backtest/simulation inputs | Currently rejected | Supported when each API's data/finality requirements are met |

`backtest_equity()` and the general simulator require qualifying completed
fixed-range inputs with splits-only equity adjustment. Yahoo records
`adjustment="splits_and_dividends"` and `download.complete=None`, so its output
currently fails those contracts. `daily_correlations()` also requires completed
downloads; `intraday_scaling()` requires intraday data. You can still inspect,
export, save/reload and use `pyibquant.research` calculations on Yahoo closes.
Do not change provenance/completeness flags merely to bypass validation.

These limitations describe the current adapter, rather than everything Yahoo or
yfinance might offer. Source changes, missing observations and price adjustments
matter when comparing results between providers.

## Errors and troubleshooting

- Missing dependency: `ImportError` includes the optional installation command.
- Invalid symbol, timeout or lookback: `ValueError` for local argument validation.
- Empty responses, missing OHLCV columns, rejected instrument metadata or network
  failures: `pyibquant.errors.DataError` with the provider/request reason.
- Nonfinite OHLC rows are skipped with a warning; unavailable/nonfinite volume
  remains `None`. No usable rows is an error.
- Access/rate-limit failures remain errors. Check the message and try again later;
  the adapter does not silently substitute another source or certify coverage.

If an IBKR chart attempt fails because TWS/SDK is unavailable, the CLI suggests an
explicit Yahoo command. You still choose whether to run it. Yahoo access does not
validate IBKR connectivity or permissions.

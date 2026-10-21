# Quick start

[Documentation home](README.md) · [API reference](API.md) · [Manual checks](MANUAL_TESTING.md)

## 1. Install from this checkout

Python 3.11+ is required. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -c 'from pyibquant import Bar; print("PyIBQuant import OK")'
```

`-e` installs the local source in editable mode. The base package has no mandatory
third-party dependencies. Install extras only for the features you want:

| Command | Enables |
|---|---|
| `python -m pip install -e '.[pandas]'` | DataFrame exports |
| `python -m pip install -e '.[cache]'` | Parquet historical query cache (PyArrow) |
| `python -m pip install -e '.[yahoo]'` | Optional daily Yahoo chart preview |

The IBKR SDK is installed separately in step 4.

## 2. Run a complete offline example

Save this as `charts/first_steps.py`, creating `charts/` if needed, and run
`python charts/first_steps.py`. You can also paste the entire block into Python.
It creates three **synthetic** daily candles, exports them, freezes/reloads them,
and calculates a two-bar average. It never connects to a broker.

```python
from datetime import date
from pyibquant import Bar, BarDataset, BarDatasetCollection, BarSeries
from pyibquant.research import above_sma, simple_returns, sma

series = BarSeries("DEMO", "1d")
series.provider = "synthetic"  # Label invented data honestly.
for day, opening, closing in [(5, 100, 101), (6, 102, 103), (7, 104, 102)]:
    series.update(Bar(
        timestamp=date(2026, 1, day),
        open=opening, high=max(opening, closing) + 1,
        low=min(opening, closing) - 1, close=closing, volume=1000,
    ))

print("Bars:", len(series))                         # 3
print("First close:", series.snapshot()[0].close)   # 101
print("CSV:", series.to_csv("charts/demo.csv"))
print("Chart:", series.plot("charts/demo.html", open_browser=False))

dataset = BarDataset.from_series(series)
dataset.save("charts/demo.bars.json")
loaded = BarDataset.load("charts/demo.bars.json")
assert loaded.fingerprint() == dataset.fingerprint()

closes = [bar.close for bar in loaded.snapshot()]
print("SMA:", sma(closes, window=2))                # (None, 102.0, 102.5)
print("Targets:", above_sma(closes, window=2))      # (False, True, False)
print("Returns:", simple_returns(closes))          # fractions, not percentages

inputs = BarDatasetCollection({"demo": loaded})
print(inputs.align(join="outer").to_records()[0])  # timestamp and demo=101
print(loaded.quality_report()["warnings"])
```

Open `charts/demo.html` in a browser. It embeds the package's Canvas renderer
and candle data, so this saved chart can be viewed offline.
The quality warnings are expected: invented candles have no verified download,
exchange calendar or finality assertion. Saving a dataset does not certify it.
This minimal fixture demonstrates containers; the strict backtest APIs require
additional acquisition metadata and intentionally reject it.

For the same workflow as a ready-to-run script:

```sh
python examples/quickstart_offline.py
```

That script also creates an explicitly labelled synthetic research fixture and
runs both simulation APIs. Its printed checks make results easy to compare.

## 3. Know what the arguments mean

`Bar.timestamp` is the candle's **start**, not its receipt time. Daily bars use
`datetime.date`; intraday bars use timezone-aware `datetime` values (UTC in exports).
`volume=None` means unavailable; zero means an observed zero.

`interval="1min"` means one minute per candle. `duration="1 D"` means a lookback
of one day; it is not an interval. For reproducible history, use `start` and `end`
instead of duration. Ranges include `start` and exclude `end`.

`regular_hours=True` requests regular-session bars. `live=True` keeps an equity
series receiving updates while the connection is open. Its latest candle may still
be forming. `BarDataset.from_series()` freezes what is present at that instant;
it does not wait for a candle to finish.

## No TWS? Try Yahoo Finance daily prices

For real daily US stock/ETF prices without an IBKR account, TWS or the SDK:

```sh
python -m pip install -e '.[yahoo]'
python -m pyibquant chart SPY --provider yahoo --interval 1d --duration '1 Y' --output charts/yahoo-spy.html
```

This downloads Yahoo data over the internet and opens a saved chart. For Python
acquisition, exports and saved datasets, see the dedicated
[Yahoo Finance guide](YAHOO.md). It also explains the current scope: daily adjusted
previews, with no live/intraday/option data or strict backtest support. The base
IBKR command does not automatically switch to Yahoo.

Continue below when you want to set up IBKR; Yahoo preview users can follow its
own guide without installing the IBKR SDK.

## 4. Connect to IBKR for a small historical request

Install the official TWS Python API SDK (the adapter requires 10.33+) from the
[IBKR download site](https://interactivebrokers.github.io/). Install its downloaded
Python client into the same virtual environment; replace the placeholder path:

```sh
python -m pip install "/path/to/TWS API/source/pythonclient"
python -c 'from ibapi import get_version_string; print(get_version_string())'
```

The old PyPI `ibapi` distribution is not the SDK supported by this repository.
In your logged-in **paper** TWS, open **Global Configuration → API → Settings**,
enable **ActiveX and Socket Clients**, permit localhost, and keep **Read-Only API**
enabled for data checks. Match the configured socket port: this package defaults
to paper TWS `7497`; paper Gateway commonly uses `4002`. Give each simultaneous
connection a distinct client ID. Data requires instrument-specific permissions.

**IBKR data; no orders.** Run this separately from the offline block:

```python
from pyibquant import BarDataset, Market

with Market.ibkr(port=7497, client_id=71, timeout=30) as market:
    series = market.bars(
        "AAPL", interval="1d", start="2026-01-05", end="2026-01-10",
    )
    print("Rows received:", len(series))
    print(series.metadata()["download"])
    if not len(series):
        raise RuntimeError("No bars returned; inspect permissions and request bounds")
    dataset = BarDataset.from_series(series)
    dataset.save("charts/aapl.bars.json")
    series.to_csv("charts/aapl.csv")
    series.plot("charts/aapl.html", open_browser=False)

# Connection closed; these rows remain usable.
print(dataset.describe())
```

Counts depend on the actual provider response. `download.complete=True` means the
planned request finished; it does not prove every market candle exists. Historical
requests do not require the market to be open. No file loads connect to IBKR.

For intraday bounds, make the timezone explicit:

```python
from pyibquant import Market

with Market.ibkr() as market:
    series = market.bars(
        "AAPL", interval="5min",
        start="2026-01-05T09:30:00-05:00", end="2026-01-05T10:00:00-05:00",
    )
    print(series.to_records())
```

Supported intervals are `30s`, `1min`, `5min`, `15min`, `30min`, `1h`, `2h`, `4h`,
`1d`, `1w`, `1y`. Calendar intervals require date-only bounds. Intraday date-only
bounds mean midnight in America/New_York, then normalize to UTC.

## 5. Research the saved data offline

**Offline; requires `charts/aapl.bars.json` from step 4.**

```python
from datetime import date
from pyibquant import BarDataset
from pyibquant.backtest import backtest_equity
from pyibquant.research import above_sma

prices = BarDataset.load("charts/aapl.bars.json")
signals = above_sma([bar.close for bar in prices.snapshot()], window=2)
result = backtest_equity(
    prices, signals, finalized_through=date(2026, 1, 9),
    initial_cash=10000, shares=1, commission=1, slippage_bps=5,
)
print(result.metrics())
print(result.fills)
result.save("charts/aapl.backtest.json")
```

Here `finalized_through` is **your assertion** that all supplied daily candles
are finished. Each boolean signal targets long/flat after that close and can first
fill at the next supplied open. Commission is USD per fill; 5 basis points is
0.05% adverse slippage. The final signal cannot fill without a later open, and
an ending position is not automatically sold. See the
[research reference](RESEARCH.md) for required metadata and all cost arguments.

Continue with the [manual checklist](MANUAL_TESTING.md) for quotes, collections,
caching and read-only account checks, or the [API reference](API.md) to look up a
particular method.

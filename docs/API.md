# Python API guide

This describes implemented APIs in the `0.1.0.dev1` development snapshot.
`PROJECT_PLAN.md` also contains future concepts; those are not API promises.

## Choose the entry point

| Task | Import / API | Broker connection? |
|---|---|---|
| Acquire one instrument | `from pyibquant import Market`; `market.bars(...)` | Yes |
| Acquire named inputs | `market.datasets(...)`; optional `BarRequest` selectors | Yes |
| Freeze, save and reload bars | `BarDataset.from_series(series)`, `.save()`, `.load()` | No |
| Save/reload named inputs | `BarDatasetCollection`, `.save()`, `.load()` | No |
| Inspect quality | Dataset/collection `.describe()`, `.quality_report()` | No |
| Align observed starts | Collection `.align(join="outer" or "inner")` | No |
| Export aligned data | `.to_records()`; optional `.to_dataframe()` | No |
| Daily descriptive correlations | `from pyibquant.studies import daily_correlations` | No |
| Intraday increments/moments | `from pyibquant.studies import intraday_scaling` | No |
| Fixed-size daily equity backtest | `from pyibquant.backtest import backtest_equity` | No |
| Fixed-size intraday option backtest | `from pyibquant.option_backtest import backtest_option` | No |
| Strategy/portfolio simulation | `from pyibquant.simulation import Feed, TargetStrategy, NextOpen, simulate` | No |
| Stock/option snapshots or streams | `market.quote(...)`, `market.stream_quote(...)` | Yes |
| Optional chart | `series.plot(...)` offline; `market.serve(...)` for connected inspection | Depends |

Core offline workflows have no mandatory third-party dependencies. Broker access
requires the official manually installed IBKR SDK and logged-in TWS/Gateway.
`[pandas]` enables DataFrames, `[cache]` enables the Parquet query cache, `[dev]`
provides tests/lint/typing, and `[browser]` provides browser regression tools.

## Acquire once, inspect and reuse

```python
from pyibquant import BarDatasetCollection, Market
from pyibquant.studies import daily_correlations

with Market.ibkr() as market:
    inputs = market.datasets(
        {"apple": "AAPL", "microsoft": "MSFT", "benchmark": "SPY"},
        interval="1d", start="2025-01-01", end="2026-01-01",
    )
inputs.save("charts/research/inputs.collection.json")

# Independent of the connection, SDK and optional dependencies:
inputs = BarDatasetCollection.load("charts/research/inputs.collection.json")
quality = inputs.quality_report(join="outer")
rows = inputs.align(join="outer").to_records()
study = daily_correlations(inputs)
```

Bounds are start-inclusive/end-exclusive. Intraday timestamps normalize to UTC;
daily timestamps are calendar dates. Requests use fixed bounds, sequential
paging/pacing and optional exact-query caching. Collection labels are user names;
resolved contract identity remains in each dataset's metadata.

`Market.datasets()` returns only after every input is nonempty and its planned
download completed. `DatasetCollectionError.failed_key` names the first failed
input; `.completed` exposes earlier frozen inputs and `.__cause__` retains the
original error, including a `HistoricalRangeError`'s partial pages/bounds. Local
selector/mode errors raise `ValueError`. No files or retries are automatic.

For selected options, use `Option` or `BarRequest(option, data_type="MIDPOINT")`.
Only fixed intraday ranges are supported. No bulk chain history or expired-option
reconstruction is supplied. MIDPOINT/BID/ASK volume stays null and these bar sources
do not establish executable quote prices. Source, multiplier and exact identity
remain separate from user labels.

## Evidence and missing observations

`describe()` summarizes recorded identity, sampling, requested/observed coverage,
download progress and fingerprints. `quality_report()` adds observation flags,
provider warnings and optional caller calendar/finality assertions. Unknown
completeness stays unknown; completed request windows do not prove full market
coverage. Reports never repair prices or alter stored provenance.

`collection.quality_report(expected={label: expected_starts},
finalized_through={label: bound}, join="outer")` accepts assertions per input.
A dataset accepts the expected starts directly. Calendar checks compare exactly
those starts; no exchange calendar is inferred. Without a calendar, shared gaps
can remain invisible. Unknown assertion labels raise `ValueError`.

An outer join preserves all observed starts and represents absent values as
`None`; an inner join keeps the intersection. Both require compatible intervals,
timestamp kinds and session settings. Neither fills/resamples or harmonizes
currencies, adjustments or price sources. Reports expose differing semantics and
row losses. Incompatible or incomplete inputs still have quality reports, with an
unavailable-alignment reason when alignment is requested.

Daily study returns are formed on adjacent union dates before listwise selection;
missing inputs cannot silently create mismatched return periods. Pearson values
are descriptive; constants/insufficient samples produce null values.
Intraday study lags count bars and require uninterrupted grids within a stated
local date. Supply `session_timezone` when source metadata is unknown. These are
dependent overlapping increments and descriptive moments, without fitted scaling
exponents, Hurst estimates or multifractal conclusions.

## Simulation assertions and execution

The simple equity/option backtests consume frozen datasets and prior-close targets.
The general simulator consumes named `Feed` objects and a strategy callback:

```python
from datetime import date
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate

result = simulate(
    {"apple": Feed(inputs["apple"], finalized_through=date(2025, 12, 31))},
    TargetStrategy("apple", lambda context: 1),
    initial_cash=10000, execution=NextOpen(commission_per_unit=0.01),
    strategy_settings={"name": "hold_one"},
)
metrics = result.metrics()
result.save("charts/research/simulation.json")
```

Feed histories publish only completed bars; orders fill at subsequent supplied
opens. The initial portfolio ledger is long-only, USD, whole quantities, with
shared cash, market orders, cancellation and full-fill-or-defer execution models.
Costs, logs, fingerprints and settings are preserved. Synthetic fills do not
reconstruct spread/liquidity. Daily and intraday feeds cannot mix, and option
expiry/lifecycle, shorting, margin, FX and broker order placement are unsupported.

**Finality conventions:** `audit()`, quality reports and legacy option backtests
use an inclusive bar-start assertion. The general simulator requires intraday
finality through `start + interval`; a bar's start alone is insufficient. Daily
assertions use dates. None of these assertions independently verify finality.

## Runnable workflows and checks

- `examples/research_collection.py fetch` acquires bounded equity/ETF collections;
  `inspect` exports quality JSON and optionally aligned CSV offline.
- `examples/research_studies.py correlations` / `scaling` consume saved collections.
- `examples/backtest_equity.py`, `backtest_option.py`, `backtest_strategy.py` consume
  saved individual datasets. See each script's `--help` and README examples.
- `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check src examples tests`,
  `.venv/bin/mypy` run local automated checks.
- `tests/browser_chart_check.py`, `browser_history_check.py` and
  `browser_sessions_check.py` use synthetic data in installed Chrome.
- `tests/live_workflow_check.py --help` describes a small explicit TWS-to-offline
  workflow check. It uses a separate client and writes only ignored generated data.
- `.venv/bin/python tests/build_check.py` builds a wheel/source archive from a
  temporary source copy, installs the wheel in an isolated SDK-free environment,
  runs the wheel smoke check and writes checksums under ignored `dist/`.

Generated data and `.venv` are machine-local and excluded from Git and source
archives. Development builds are local; no publication, remote push or tag is
implied. Only Python 3.14 has been exercised in this local release check; the
package declares Python 3.11+, without claiming a tested multi-version matrix.

"""Try containers, exports, signals and simulations without an SDK or broker.

Run from the repository root after installing with `python -m pip install -e .`:
    python examples/quickstart_offline.py
    python examples/quickstart_offline.py --output-dir /tmp/pyibquant-demo

All prices and provenance are explicitly synthetic. No orders or network calls.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from pyibquant import Bar, BarDataset, BarDatasetCollection, BarSeries
from pyibquant.backtest import backtest_equity
from pyibquant.research import above_sma, simple_returns, sma
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("charts/quickstart"))
    args = parser.parse_args()
    output = args.output_dir

    series = BarSeries("DEMO", "1d")
    series.provider = "synthetic"
    # These assertions describe ONLY this invented fixture. Real downloads must
    # retain their actual provider metadata, including any incomplete status.
    series.asset_type = "equity"
    series.currency = "USD"
    series.multiplier = 1
    series.data_type = "TRADES"
    series.adjustment = "splits_only"
    series.session_timezone = "America/New_York"
    series.requested_start = date(2026, 1, 5)
    series.requested_end = date(2026, 1, 10)
    series.download_complete = True
    series.warnings.append("Synthetic tutorial prices; not historical market data.")
    prices = [(100, 101), (102, 103), (104, 102), (101, 100), (99, 102)]
    for day, (opening, closing) in enumerate(prices, start=5):
        series.update(Bar(date(2026, 1, day), opening, max(opening, closing) + 1,
                          min(opening, closing) - 1, closing, 1000))

    series.to_csv(output / "demo.csv")
    series.plot(output / "demo.html", open_browser=False)
    dataset = BarDataset.from_series(series)
    dataset.save(output / "demo.bars.json")
    loaded = BarDataset.load(output / "demo.bars.json")
    assert loaded.fingerprint() == dataset.fingerprint()
    expected = tuple(date(2026, 1, day) for day in range(5, 10))
    audit = loaded.audit(expected, finalized_through=expected[-1])
    assert audit.matches_calendar and not audit.unconfirmed

    inputs = BarDatasetCollection({"demo": loaded})
    inputs.save(output / "demo.collection.json")
    restored = BarDatasetCollection.load(output / "demo.collection.json")
    assert restored.fingerprint() == inputs.fingerprint()
    assert len(restored.align(join="outer").to_records()) == 5
    print("Rows: 5; dataset/collection round trips and toy-calendar audit passed")

    closes = [bar.close for bar in loaded.snapshot()]
    signals = above_sma(closes, window=2)
    print("SMA:", sma(closes, window=2))
    print("Targets:", signals)
    print("Returns:", simple_returns(closes))
    result = backtest_equity(loaded, signals, finalized_through=expected[-1],
                             initial_cash=1000, shares=1, expected_dates=expected)
    result.save(output / "backtest.json")
    # True at Jan 6 close buys Jan 7 open (104); False at Jan 7 close
    # sells Jan 8 open (101). The Jan 9 target has no later supplied open.
    assert [fill.price for fill in result.fills] == [104, 101]
    assert result.metrics()["final_equity"] == 997
    print("Equity backtest: 2 fills; final equity 997.0 (zero costs)")

    simulation = simulate(
        {"demo": Feed(loaded, finalized_through=expected[-1], expected_starts=expected)},
        TargetStrategy("demo", lambda context: 1), initial_cash=1000,
        execution=NextOpen(), strategy_settings={"name": "synthetic_hold_one"},
    )
    simulation.save(output / "simulation.json")
    assert len(simulation.fills) == 1
    assert simulation.portfolio.positions["demo"].quantity == 1
    assert simulation.metrics()["final_equity"] == 1000
    print("General simulator: 1 fill; 1 share retained; final equity 1000.0")
    print("Artifacts:", output.resolve())


if __name__ == "__main__":
    main()

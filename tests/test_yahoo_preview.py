"""Daily preview format and explicit source selection, without network access."""

import json
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import cli
from pyibquant.data.providers.yahoo import _start_date, preview_bars
from pyibquant.errors import ConnectionError, DataError


@pytest.fixture
def yahoo(monkeypatch):
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(
        {"Open": [100, float("nan"), 102], "High": [103, 104, 105],
         "Low": [99, 100, 101], "Close": [102, 103, 104], "Volume": [50, 60, float("nan")]},
        index=pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-07"],
                               tz="America/New_York"),
    )
    ticker = Mock()
    ticker.history.return_value = frame
    ticker.get_history_metadata.return_value = dict(
        currency="USD", exchangeTimezoneName="America/New_York", instrumentType="ETF",
    )
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=Mock(return_value=ticker)))
    return ticker


def test_daily_format_and_preview_provenance(yahoo):
    series = preview_bars(" spy ", duration="10 Y")
    rows = series.snapshot()
    assert [row.timestamp for row in rows] == [date(2026, 1, 5), date(2026, 1, 7)]
    assert rows[0].close == 102
    assert rows[1].volume is None
    metadata = series.metadata()
    assert series.symbol == "SPY"
    assert metadata["provider"] == "Yahoo Finance · Preview"
    assert metadata["adjustment"] == "splits_and_dividends"
    assert metadata["timestamp_kind"] == "date"
    assert metadata["download"]["complete"] is None
    assert "Skipped 1" in series.warnings[-1]
    assert yahoo.history.call_args.kwargs["auto_adjust"] is True
    assert yahoo.history.call_args.kwargs["repair"] is False


def test_empty_response_is_an_error(yahoo):
    yahoo.history.return_value = yahoo.history.return_value.iloc[:0]
    with pytest.raises(DataError, match="no preview data"):
        preview_bars("SPY")


def test_reject_non_us_instrument(yahoo):
    yahoo.get_history_metadata.return_value["currency"] = "EUR"
    with pytest.raises(DataError, match="USD only"):
        preview_bars("SAP.DE")


def test_missing_columns_are_an_error(yahoo):
    yahoo.history.return_value = yahoo.history.return_value.drop(columns="Close")
    with pytest.raises(DataError, match="missing OHLCV"):
        preview_bars("SPY")


def test_missing_optional_install_has_instructions(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", None)
    with pytest.raises(ImportError, match="optional dependency"):
        preview_bars("SPY")


def test_calendar_lookbacks():
    assert _start_date(date(2024, 3, 31), "1 M") == date(2024, 2, 29)
    assert _start_date(date(2024, 2, 29), "1 Y") == date(2023, 2, 28)
    assert _start_date(date(2026, 1, 8), "1 W") == date(2026, 1, 1)
    with pytest.raises(ValueError, match="positive"):
        _start_date(date(2026, 1, 8), "0 D")


def test_cli_explicit_preview_never_opens_ibkr(yahoo, monkeypatch, tmp_path, capsys):
    output = tmp_path / "preview.html"
    monkeypatch.setattr(sys, "argv", [
        "pyibquant", "chart", "SPY", "--provider", "yahoo", "--interval", "1d",
        "--duration", "10 Y", "--output", str(output), "--no-browser",
    ])
    ibkr = Mock(side_effect=AssertionError("Preview must not open TWS"))
    monkeypatch.setattr(cli.Market, "ibkr", ibkr)
    assert cli.main() == 0
    ibkr.assert_not_called()
    html = output.read_text()
    assert json.dumps("Yahoo Finance · Preview") in html
    assert "split/dividend adjusted" in html
    assert '"time": "2026-01-05"' in html
    assert "preview only" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--live"], ["--cache"], ["--interval", "1min"]])
def test_cli_rejects_unsupported_preview_modes(monkeypatch, capsys, extra):
    monkeypatch.setattr(sys, "argv", [
        "pyibquant", "chart", "SPY", "--provider", "yahoo", "--interval", "1d", *extra,
    ])
    assert cli.main() == 1
    assert "Yahoo preview" in capsys.readouterr().err


def test_default_connection_failure_suggests_explicit_preview(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pyibquant", "chart", "SPY"])
    monkeypatch.setattr(cli.Market, "ibkr", Mock(side_effect=ConnectionError("TWS unavailable")))
    assert cli.main() == 1
    error = capsys.readouterr().err
    assert "TWS unavailable" in error
    assert "pip install -e '.[yahoo]'" in error
    assert "--provider yahoo --interval 1d" in error


def test_yahoo_error_does_not_suggest_ibkr_fallback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "pyibquant", "chart", "SPY", "--provider", "yahoo", "--interval", "1d",
    ])
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(
        Ticker=Mock(side_effect=RuntimeError("Rate limited")),
    ))
    assert cli.main() == 1
    error = capsys.readouterr().err
    assert "Rate limited" in error
    assert "For an optional" not in error

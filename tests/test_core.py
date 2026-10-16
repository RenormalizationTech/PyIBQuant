"""Provider-independent regressions, runnable without the IBKR SDK."""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from pyibquant import Bar, BarSeries
from pyibquant.errors import DataError
from pyibquant.visualization.chart import ChartSession, render_chart


def test_chart_export_is_safe_and_snapshot_is_not_labelled_live(tmp_path):
    series = BarSeries('</script><script>alert("x")</script>', "1d", live=True)
    series.update(Bar(date(2026, 10, 15), 100, 102, 99, 101, 50))
    series.error = "<untrusted provider message>"
    path = series.plot(tmp_path / "chart.html", open_browser=False)
    html = path.read_text()
    assert '</script><script>alert("x")</script>' not in html
    assert "\\u003c" in html
    assert '"live": false' in html
    assert '"time": "2026-10-15"' in html
    assert "const liveEndpoint = false;" in html
    assert "const liveEndpoint = true;" in render_chart(series, live_endpoint=True)
    assert '<canvas id="market-canvas"' in html
    assert "class MarketChart" in html
    assert "<script src=" not in html
    assert "__CHART_SCRIPT__" not in html
    assert "TradingView" not in html
    assert "const controlsEnabled = false;" in html
    assert "const controlsEnabled = true;" in render_chart(series, controls=True)



def test_selection_releases_previous_subscription_after_success():
    original = BarSeries("AAPL", "1min", live=True)
    replacement = BarSeries("SPY", "5min", live=True)
    loader, cancel = Mock(return_value=replacement), Mock()
    session = ChartSession(original, loader, cancel)
    assert session.select("SPY", "5min", "1 D")["symbol"] == "SPY"
    loader.assert_called_once_with("SPY", "5min", "1 D", True)
    cancel.assert_called_once_with(original)
    assert session.series is replacement



def test_failed_selection_keeps_previous_chart_and_serializes_requests():
    original = BarSeries("AAPL", "1min", live=True)
    loader, cancel = Mock(side_effect=DataError("Unknown symbol")), Mock()
    session = ChartSession(original, loader, cancel)
    with pytest.raises(DataError, match="Unknown symbol"):
        session.select("MISSING", "5min", "1 D")
    assert session.series is original
    cancel.assert_not_called()
    with session._selection_lock, pytest.raises(BlockingIOError):
        session.select("SPY", "5min", "1 D")
    loader.assert_called_once()



def test_trading_hours_switch_persists_and_failure_keeps_active_hours():
    original = BarSeries("AAPL", "1min", live=True)
    extended = BarSeries("AAPL", "1min", live=True)
    extended.regular_hours = False
    loader = Mock(return_value=extended)
    cancel = Mock()
    session = ChartSession(original, loader, cancel)
    first_id = session.selection_id
    assert session.select("AAPL", "1min", "1 D", False)["regular_hours"] is False
    assert session.selection_id != first_id
    loader.assert_called_once_with("AAPL", "1min", "1 D", False)
    session.select("SPY", "5min", "1 D")
    loader.assert_called_with("SPY", "5min", "1 D", False)
    loader.side_effect = DataError("Unavailable")
    with pytest.raises(DataError):
        session.select("AAPL", "1min", "1 D", True)
    assert session.series is extended
    assert session.payload()["regular_hours"] is False
    assert cancel.call_count == 2
    for invalid in ["false", 0, 1]:
        with pytest.raises(ValueError, match="boolean"):
            session.select("AAPL", "1min", "1 D", invalid)



def test_market_browser_selection_passes_hours_to_provider(monkeypatch):
    from pyibquant import Market

    provider = Mock()
    initial = BarSeries("AAPL", "1min", live=True)
    initial.primary_exchange = "NASDAQ"
    server = Mock()
    monkeypatch.setattr("pyibquant.visualization.chart.serve_chart", server)
    Market(provider).serve(initial, open_browser=False)
    load = server.call_args.kwargs["loader"]
    load("AAPL", "5min", "2 D", False)
    provider.bars.assert_called_once_with(
        "AAPL", interval="5min", duration="2 D", live=True,
        regular_hours=False, primary_exchange="NASDAQ", refresh=False,
    )



def test_prepend_deduplicates_and_keeps_existing_live_values():
    series = BarSeries("AAPL", "1d", live=True)
    latest = Bar(date(2026, 10, 15), 100, 105, 99, 104, 50)
    older = Bar(date(2026, 10, 14), 100, 102, 99, 101, 20)
    series.update(latest)
    assert series.prepend([older, older, Bar(latest.timestamp, 1, 1, 1, 1, 1)]) == 1
    assert series.snapshot() == (older, latest)
    assert series.prepend([older]) == 0



def test_session_stale_duplicate_and_busy_history_requests_do_not_download():
    series = BarSeries("AAPL", "1d")
    series.update(Bar(date(2026, 10, 15), 100, 102, 99, 101, 50))
    loader = Mock(
        side_effect=lambda current: current.prepend(
            [Bar(date(2026, 10, 14), 100, 102, 99, 101, 50)]
        )
    )
    session = ChartSession(series, Mock(return_value=series), None, loader)
    selection = session.selection_id
    with session._selection_lock, pytest.raises(BlockingIOError):
        session.older(selection, "2026-10-15")
    session.older(selection, "2026-10-15")
    duplicate = session.older(selection, "2026-10-15")
    assert len(duplicate["bars"]) == 2
    assert loader.call_count == 1
    with pytest.raises(BlockingIOError, match="two seconds"):
        session.older(selection, "2026-10-14")
    session.select("AAPL", "1d", "6 M")
    with pytest.raises(BlockingIOError, match="changed"):
        session.older(selection, "2026-10-14")
    assert loader.call_count == 1
    assert session.payload()["selection_id"] != selection



def test_session_history_failure_releases_lock_for_retry():
    series = BarSeries("AAPL", "1d")
    series.update(Bar(date(2026, 10, 15), 100, 102, 99, 101, 50))
    loader = Mock(side_effect=DataError("pacing violation"))
    session = ChartSession(series, None, None, loader)
    with patch("pyibquant.visualization.chart.monotonic", return_value=10):
        with pytest.raises(DataError):
            session.older(session.selection_id, "2026-10-15")
    loader.side_effect = None
    with patch("pyibquant.visualization.chart.monotonic", return_value=13):
        assert len(session.older(session.selection_id, "2026-10-15")["bars"]) == 1
    assert loader.call_count == 2



def test_cli_can_disable_automatic_recovery(monkeypatch):
    from unittest.mock import MagicMock

    from pyibquant.cli import main

    market = MagicMock()
    market.__enter__.return_value = market
    connect = Mock(return_value=market)
    monkeypatch.setattr('pyibquant.cli.Market.ibkr', connect)
    monkeypatch.setattr(
        'sys.argv', ['pyibquant', 'chart', 'AAPL', '--no-reconnect', '--no-browser']
    )
    assert main() == 0
    assert connect.call_args.kwargs['reconnect'] is False

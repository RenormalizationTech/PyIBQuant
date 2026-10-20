"""A saved profile cannot silently enable trading or weaken resumed configuration."""

import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_broker import broker as broker

from pyibquant import BrokerError
from pyibquant.trading.preflight import check_profile
from pyibquant.trading.profile import PaperProfile


def write_profile(tmp_path, **values):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(values))
    return path


def test_profile_journal_is_relative_to_its_file_not_the_launch_directory(tmp_path, monkeypatch):
    path = write_profile(tmp_path, journal="records/paper.sqlite3", symbol="AAPL")
    monkeypatch.chdir(tmp_path.parent)
    profile = PaperProfile.load(path)
    assert profile.journal == tmp_path / "records/paper.sqlite3"
    assert profile.runner_config().dry_run
    assert profile.broker_options()["readonly"]
    assert not profile.broker_options()["paper_confirmed"]
    assert not profile.broker_options(preflight=True)["paper_confirmed"]
    assert profile.broker_options(preflight=True)["client_id"] != profile.broker_client_id
    with pytest.raises(ValueError, match="Preflight"):
        profile.broker_options(preflight=True, execute=True)


@pytest.mark.parametrize(
    "values",
    [
        {"execute": True},
        {"readonly": False},
        {"paper_confirmed": True},
        {"account": "U123"},
        {"version": True},
        {"symbol": 123},
        {"symbol": "aapl"},
        {"broker_client_id": 277},
        {"market_client_id": True},
        {"port": 70000},
        {"window": 0},
        {"quantity": 0},
        {"max_orders": True},
        {"max_order_value": -1},
        {"max_order_value": "500"},
        {"max_session_loss": 0},
        {"seconds": float("nan")},
        {"seconds": 3601},
        {"cancel_on_stop": "true"},
        {"journal": []},
    ],
)
def test_invalid_profiles_fail_before_any_api_connection(tmp_path, values):
    with pytest.raises((ValueError, TypeError)):
        PaperProfile.load(write_profile(tmp_path, **values))


def test_shipped_profile_uses_the_selected_bounded_strategy():
    path = Path(__file__).resolve().parents[1] / "examples/paper_aapl.json"
    profile = PaperProfile.load(path)
    assert (profile.symbol, profile.window, profile.quantity) == ("AAPL", 20, 1)
    assert profile.max_order_value == 500 and profile.max_session_loss == 25
    assert profile.seconds == 600 and profile.cancel_on_stop
    assert profile.account is None and profile.runner_config().dry_run


def mock_sdk(monkeypatch):
    monkeypatch.setattr(
        "pyibquant.trading.preflight.import_module",
        lambda name: SimpleNamespace(get_version_string=lambda: "10.50.2"),
    )


def test_local_preflight_never_connects_or_marks_the_profile_ready_to_trade(tmp_path, monkeypatch):
    mock_sdk(monkeypatch)
    connect = Mock(side_effect=AssertionError("No API access"))
    monkeypatch.setattr("pyibquant.trading.preflight.PaperBroker.ibkr", connect)
    report = check_profile(replace(PaperProfile(), journal=tmp_path / "paper.sqlite3"))
    assert report["local_ready"] and not report["connected"]
    assert not report["order_transmission"] and not report["ready_to_trade"]
    assert report["deferred"]
    connect.assert_not_called()
    assert not (tmp_path / "paper.sqlite3").exists()


def test_readonly_preflight_reconciles_without_order_submission(broker, monkeypatch):
    mock_sdk(monkeypatch)
    broker.refresh_pnl = Mock(return_value=SimpleNamespace(pnl={"validated": True}))
    broker._adapter.resolve.return_value = SimpleNamespace(conId=100)
    connect = Mock(return_value=nullcontext(broker))
    monkeypatch.setattr("pyibquant.trading.preflight.PaperBroker.ibkr", connect)
    report = check_profile(replace(PaperProfile(), journal=broker.journal.path), connect=True)
    assert report["local_ready"] and report["connected"]
    assert connect.call_args.kwargs["readonly"] and not connect.call_args.kwargs["paper_confirmed"]
    assert report["contract_id"] == 100 and not report["ready_to_trade"]
    broker._adapter.send_order.assert_not_called()
    broker._adapter.cancel_order.assert_not_called()


def test_preflight_reports_api_failure_and_masks_configured_account(tmp_path, monkeypatch):
    mock_sdk(monkeypatch)
    monkeypatch.setattr(
        "pyibquant.trading.preflight.PaperBroker.ibkr",
        Mock(side_effect=BrokerError("Cannot connect DUABC123")),
    )
    profile = replace(PaperProfile(), journal=tmp_path / "test.sqlite3", account="DUABC123")
    report = check_profile(profile, connect=True)
    assert not report["local_ready"] and not report["ready_to_trade"]
    assert "DUABC123" not in json.dumps(report)
    assert any(c["status"] == "fail" for c in report["checks"])

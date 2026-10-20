"""Fill/fee attribution, timestamped marks and offline report provenance."""

import csv
import sqlite3
from unittest.mock import Mock

import pytest
from test_broker import broker as broker

from pyibquant.trading.journal import Journal
from pyibquant.trading.offline import load_account
from pyibquant.trading.performance import payload
from pyibquant.trading.run_performance import run_reports, valuation


def order(oid, side, quantity, filled=None, tag="strategy"):
    return dict(
        order_id=oid,
        client_id=272,
        tag=tag,
        order_ref=f"pyibquant:{oid}",
        con_id=100,
        symbol="AAPL",
        currency="USD",
        side=side,
        quantity=str(quantity),
        filled=str(quantity if filled is None else filled),
        status="Filled",
    )


def fill(oid, side, quantity, price, fee, eid=None):
    return dict(
        exec_id=eid or str(oid),
        order_id=oid,
        client_id=272,
        con_id=100,
        symbol="AAPL",
        currency="USD",
        side=side,
        quantity=str(quantity),
        price=str(price),
        cumulative_quantity=str(quantity),
        commission=str(fee) if fee is not None else None,
        fee_currency="USD",
    )


def test_partial_exit_fifo_and_allocated_fees():
    result = valuation(
        "strategy",
        (order(1, "BUY", 2), order(2, "SELL", 1)),
        (fill(1, "BOT", 2, 100, 2), fill(2, "SLD", 1, 110, 1)),
        {100: dict(price="105", time="2026-10-19T20:00:00+00:00")},
    )
    assert result["complete"]
    assert result["gross_realized"] == "10"
    assert result["realized_pnl"] == "8"
    assert result["unrealized_pnl"] == "4"
    assert result["net_pnl"] == "12" and result["gross_exposure"] == "105"


def test_fifo_does_not_use_average_cost_from_external_account_positions():
    result = valuation(
        "strategy",
        (order(1, "BUY", 1), order(2, "BUY", 1), order(3, "SELL", 1)),
        (fill(1, "BOT", 1, 100, 1), fill(2, "BOT", 1, 120, 1), fill(3, "SLD", 1, 130, 1)),
        {100: dict(price="125", time="2026-10-19T20:00:00+00:00")},
    )
    assert result["realized_pnl"] == "28" and result["unrealized_pnl"] == "4"
    assert result["net_pnl"] == "32"


def test_missing_fee_or_mark_is_unknown_not_zero():
    orders = (order(1, "BUY", 1),)
    result = valuation("strategy", orders, (fill(1, "BOT", 1, 100, None),), {})
    assert result["net_pnl"] is None and result["commissions"] is None
    assert result["gross_exposure"] is None and result["unrealized_pnl"] is None
    assert result["positions"][0]["mark_time"] is None
    result = valuation("strategy", orders, (fill(1, "BOT", 1, 100, 1),), {})
    assert result["commissions"] == "1" and result["net_pnl"] is None


def test_flat_round_trip_needs_no_mark_and_ignores_other_strategies():
    result = valuation(
        "strategy",
        (order(1, "BUY", 1), order(2, "SELL", 1), order(3, "BUY", 100, tag="manual")),
        (fill(1, "BOT", 1, 100, 1), fill(2, "SLD", 1, 110, 1), fill(3, "BOT", 100, 999, 500)),
        {},
    )
    assert result["positions"] == [] and result["gross_exposure"] == "0"
    assert result["realized_pnl"] == result["net_pnl"] == "8"
    assert result["execution_count"] == 2 and result["commissions"] == "2"


def test_corrections_and_short_inventory_do_not_produce_complete_profit():
    result = valuation(
        "strategy",
        (order(1, "BUY", 1),),
        (fill(1, "BOT", 1, 100, 1, "a"), fill(1, "BOT", 1, 101, 1, "b")),
        {},
    )
    assert not result["complete"] and result["net_pnl"] is None
    result = valuation("strategy", (order(1, "SELL", 1),), (fill(1, "SLD", 1, 100, 1),), {})
    assert not result["complete"] and result["realized_pnl"] is None


def test_history_deduplicates_replay_and_does_not_backfill_late_fees(broker):
    broker._record("runner_start", dict(run_id="strategy", symbol="AAPL", dry_run=False))
    broker._record(
        "portfolio",
        dict(con_id=100, symbol="AAPL", currency="USD", quantity="0", market_price="100"),
    )
    broker._record("intent", order(1, "BUY", 1, filled=0))
    execution = fill(1, "BOT", 1, 100, None)
    execution.pop("commission")
    execution.pop("fee_currency")
    broker._record("execution", execution)
    first = run_reports(broker.journal.events(), broker.snapshot())[0]
    assert first["points"][-1]["net"] is None
    broker._record("fee", dict(exec_id="1", commission="1", fee_currency="USD"))
    second = run_reports(broker.journal.events(), broker.snapshot())[0]
    assert second["net_pnl"] == "-1"
    assert second["points"][0]["net"] is None
    count = len(second["points"])
    broker._record("execution", execution)
    third = run_reports(broker.journal.events(), broker.snapshot())[0]
    assert len(third["points"]) == count and third["execution_count"] == 1


def test_observed_dollar_drawdown_uses_only_recorded_marks(broker):
    broker._record("runner_start", dict(run_id="strategy", symbol="AAPL"))
    broker._record("intent", order(1, "BUY", 1, filled=0))
    broker._record("execution", fill(1, "BOT", 1, 100, 1))
    for price in (100, 120, 110):
        broker._record(
            "portfolio",
            dict(con_id=100, symbol="AAPL", currency="USD", quantity="1", market_price=str(price)),
        )
    row = run_reports(broker.journal.events(), broker.snapshot())[0]
    assert row["net_pnl"] == "9" and row["observed_drawdown"] == "10"


def test_position_callback_does_not_refresh_the_mark_timestamp(broker):
    broker._record(
        "portfolio",
        dict(con_id=100, quantity="1", market_price="100", currency="USD"),
        "2026-10-19T14:00:00+00:00",
    )
    broker._record("position", dict(con_id=100, quantity="1"), "2026-10-19T15:00:00+00:00")
    assert broker.snapshot().positions[0]["mark_received_at"] == "2026-10-19T14:00:00+00:00"


def test_offline_replay_preserves_source_and_marks_state_offline(broker, tmp_path, monkeypatch):
    broker._record("runner_start", dict(run_id="strategy", symbol="AAPL"))
    broker._record("intent", order(1, "BUY", 1, filled=0))
    broker._record("execution", fill(1, "BOT", 1, 100, 1))
    path = broker.journal.path
    count = len(broker.journal.events())
    monkeypatch.setattr(
        "pyibquant.PaperBroker.ibkr", Mock(side_effect=AssertionError("No network"))
    )
    events, snapshot = load_account(path)
    assert len(broker.journal.events()) == count
    assert snapshot.status == "offline" and not snapshot.complete
    assert snapshot.orders[0]["tag"] == "strategy"
    from pyibquant.trading.performance import write_report

    report = write_report(events, snapshot, tmp_path / "report.html")
    assert "DUABC123" not in report.read_text()
    with (tmp_path / "report-runs.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["status"] == "interrupted/unverified"
    assert (tmp_path / "report-run-points.csv").is_file()


def test_offline_missing_or_ambiguous_journal_is_not_created(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        load_account(missing)
    assert not missing.exists()
    path = tmp_path / "multi.sqlite3"
    journal = Journal(path)
    for account in ("DU123", "DU456"):
        journal.append("s", account, "2026-10-19T14:00:00+00:00", "session", {})
    journal.close()
    from pyibquant import BrokerError

    with pytest.raises(BrokerError, match="Select one account"):
        load_account(path)
    assert load_account(path, account="DU123")[1].account == "DU123"
    source = Journal(path, readonly=True)
    with pytest.raises(ValueError, match="read-only"):
        source.append("s", "DU123", "now", "session", {})
    source.close()


def test_transient_zero_pnl_does_not_create_a_validated_chart_spike(broker):
    for value in ("0", "1281"):
        broker._record("pnl", dict(request_id=10, daily=value, unrealized="0", realized="7251"))
    broker._record("pnl_validated", dict(request_id=10, daily="1281"))
    points = payload(broker.journal.events(), broker.snapshot())["points"]
    assert [p["daily"] for p in points if p["daily"] is not None] == ["1281"]


def test_export_masks_account_codes_inside_metadata_and_run_messages(broker, tmp_path):
    for tag in ("AccountCode", "AccountOrGroup"):
        broker._record("value", dict(tag=tag, currency="USD", value=broker.account))
    broker._record("runner_start", dict(run_id="strategy", symbol="AAPL"))
    broker._record("runner_pause", dict(run_id="strategy", reason="Check " + broker.account))
    assert broker.snapshot().value("AccountCode", "USD").value == broker.account
    assert broker.account not in str(broker.snapshot().to_dict())
    assert broker.account in str(broker.snapshot().to_dict(mask_account=False))
    report = broker.report(tmp_path / "masked.html")
    assert broker.account not in report.read_text()
    audit = broker.export_strategy("strategy", tmp_path / "audit.json")
    assert broker.account not in audit.read_text()

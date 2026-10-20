"""Broker state, funding, persistence and order races without SDK or network access."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from pyibquant import BrokerError, PaperBroker
from pyibquant.broker import money
from pyibquant.trading.journal import Journal
from pyibquant.trading.performance import payload, render


class Adapter:
    client_id = 272
    timeout = 0.1

    def __init__(self):
        self.send_order = Mock()
        self.cancel_order = Mock()
        self.close = Mock()
        self.isConnected = Mock(return_value=True)
        self.resolve = Mock(return_value=SimpleNamespace(conId=100))
        self.allocate_id = Mock(return_value=10)
        self.calls = 0
        self.provide_settled = True

    def refresh(self, account):
        self.prepare()
        self.calls += 1
        fields = [
            ("NetLiquidation", "USD", "1000"),
            ("CashBalance", "USD", "1000"),
            ("TotalCashValue", "USD", "1000"),
            ("BuyingPower", "USD", "4000"),
            ("AvailableFunds", "USD", "1000"),
            ("AccountType", "", "INDIVIDUAL"),
        ]
        if self.provide_settled:
            fields.append(("SettledCash", "USD", "500"))
        for tag, currency, value in fields:
            self.sink(
                "value", dict(tag=tag, currency=currency, value=value, source="account_summary")
            )
        for name in ("account", "summary", "positions", "orders", "executions"):
            self.sink("barrier", dict(name=name))


@pytest.fixture
def broker(tmp_path):
    adapter = Adapter()
    with PaperBroker(
        adapter,
        tmp_path / "paper.sqlite3",
        account="DUABC123",
        readonly=False,
        paper_confirmed=True,
    ) as b:
        adapter.refresh(b.account)
        b.wait_ready(0.5)
        yield b


def drain(b):
    b._queue.join()


def status(b, state, filled="0", remaining="1"):
    b.enqueue(
        "order_status",
        dict(order_id=10, client_id=272, status=state, filled=filled, remaining=remaining),
    )
    drain(b)


def test_initial_download_and_immutable_snapshot(broker):
    snap = broker.snapshot()
    assert snap.complete and snap.status == "ready"
    assert snap.value("SettledCash", "USD").number == 500
    assert broker.funding()["usable"] == "500"
    assert broker.funding()["BuyingPower"] == "4000"
    assert "DUABC123" not in str(snap.to_dict())
    broker.enqueue("position", dict(con_id=100, quantity="2"))
    drain(broker)
    with pytest.raises(TypeError):
        broker.snapshot().positions[0]["quantity"] = "100"


def test_initial_download_cannot_be_mistaken_for_flat_account(broker):
    broker._begin_refresh()
    with pytest.raises(BrokerError, match="incomplete"):
        broker.wait_ready(0.001)
    assert broker.funding()["usable"] is None


def test_no_margin_and_missing_settled_cash_never_falls_back_to_buying_power(broker):
    broker._adapter.provide_settled = False
    broker.refresh()
    assert broker.funding()["usable"] is None
    with pytest.raises(BrokerError, match="funds"):
        broker.submit_limit("AAPL", "BUY", 1, 100)
    broker._adapter.send_order.assert_not_called()


def test_dated_settlement_schedule_is_currency_specific_and_today_only(broker):
    broker._adapter.provide_settled = False
    broker.refresh()
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    broker.enqueue("value", dict(tag="SettledCashByDate", currency="USD", value=today + ":700"))
    drain(broker)
    assert broker.funding()["usable"] == "700"
    broker.enqueue("value", dict(tag="SettledCashByDate", currency="USD", value="20991231:700"))
    drain(broker)
    assert broker.funding()["usable"] is None


@pytest.mark.parametrize(
    "value", [None, "", "NaN", "Infinity", float("inf"), 1.7976931348623157e308]
)
def test_unset_values_never_become_funds(value):
    assert money(value) is None


def test_buy_is_journaled_before_send_and_pending_order_blocks_second(broker):
    def send(*args):
        events = broker.journal.events(broker.account)
        assert events[-1]["kind"] == "intent"
        assert events[-1]["payload"]["order_id"] == 10

    broker._adapter.send_order.side_effect = send
    assert broker.submit_limit("AAPL", "BUY", 1, 100, key="decision-1") == 10
    assert broker.funding()["usable"] is None
    with pytest.raises(BrokerError, match="outstanding"):
        broker.submit_limit("AAPL", "BUY", 1, 100)
    assert broker._adapter.send_order.call_count == 1


def test_duplicate_idempotency_key_survives_terminal_order_and_restart(broker, tmp_path):
    broker.submit_limit("AAPL", "BUY", 1, 100, key="decision-1")
    status(broker, "Cancelled")
    with pytest.raises(BrokerError, match="idempotency"):
        broker.submit_limit("AAPL", "BUY", 1, 100, key="decision-1")
    path = broker.journal.path
    broker.close()
    with PaperBroker(
        Adapter(), path, account="DUABC123", readonly=False, paper_confirmed=True
    ) as replacement:
        assert replacement.snapshot().orders[0]["status"] == "Cancelled"
        assert not replacement.snapshot().values
        assert replacement.funding()["usable"] is None


def test_send_failure_is_unknown_and_never_retried(broker):
    broker._adapter.send_order.side_effect = OSError("socket write")
    with pytest.raises(BrokerError, match="unknown"):
        broker.submit_limit("AAPL", "BUY", 1, 100)
    assert broker.snapshot().orders[0]["status"] == "UnknownSend"
    assert broker.funding()["usable"] is None
    assert broker._adapter.send_order.call_count == 1


def test_cancel_request_retains_hold_and_fill_wins_cancel_race(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100)
    broker.cancel(10)
    assert broker.funding()["usable"] is None
    status(broker, "Filled", "1", "0")
    status(broker, "Submitted", "0", "1")
    status(broker, "Cancelled", "1", "0")
    order = broker.snapshot().orders[0]
    assert order["status"] == "Filled" and order["filled"] == "1"
    broker._adapter.cancel_order.assert_called_once_with(10)


def test_partial_executions_and_late_fees_are_deduplicated(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100)
    execution = dict(
        exec_id="fill.01",
        client_id=272,
        order_id=10,
        cumulative_quantity="1",
        quantity="1",
        price="99",
    )
    broker.enqueue("execution", execution)
    broker.enqueue("execution", execution)
    broker.enqueue("fee", dict(exec_id="fill.01", commission=".35"))
    drain(broker)
    snap = broker.snapshot()
    assert len(snap.executions) == 1 and snap.executions[0]["commission"] == ".35"
    assert snap.orders[0]["status"] == "Filled"


def test_disconnect_cannot_be_cleared_by_late_download_end(broker):
    broker.enqueue("disconnected", dict(message="socket closed"))
    for name in ("account", "summary", "positions", "orders", "executions"):
        broker.enqueue("barrier", dict(name=name))
    drain(broker)
    assert not broker.snapshot().complete and broker.funding()["usable"] is None
    with pytest.raises(BrokerError):
        broker.submit_limit("AAPL", "BUY", 1, 100)
    broker._adapter.send_order.assert_not_called()


def test_refresh_removes_positions_that_disappeared(broker):
    broker.enqueue("position", dict(con_id=100, quantity="2"))
    drain(broker)
    assert len(broker.snapshot().positions) == 1
    broker.refresh()
    assert not broker.snapshot().positions


def test_cannot_short_or_cancel_someone_elses_orders(broker):
    with pytest.raises(BrokerError, match="shorting"):
        broker.submit_limit("AAPL", "SELL", 1, 100)
    broker.enqueue("order", dict(order_id=99, client_id=777, order_ref="external"))
    drain(broker)
    with pytest.raises(BrokerError, match="owned"):
        broker.cancel(99)


def test_readonly_and_live_account_guards(tmp_path):
    with pytest.raises(BrokerError, match="paper account"):
        PaperBroker(Adapter(), tmp_path / "x.db", account="U123")
    with pytest.raises(BrokerError, match="confirmation"):
        PaperBroker(Adapter(), tmp_path / "x.db", account="DU123", readonly=False)
    with PaperBroker(Adapter(), tmp_path / "x.db", account="DU123") as b:
        with pytest.raises(BrokerError, match="read-only"):
            b.submit_limit("AAPL", "BUY", 1, 100)


def test_size_limits_and_fee_reserve(broker):
    for quantity, price in ((2, 100), (1, 501)):
        with pytest.raises(BrokerError, match="limit exceeded"):
            broker.submit_limit("AAPL", "BUY", quantity, price)
    with pytest.raises(BrokerError, match="funds"):
        broker.submit_limit("AAPL", "BUY", 1, 499)


def test_report_escapes_provider_text_and_breaks_session_gaps(broker, tmp_path):
    broker.enqueue("error", dict(message="</script><script>alert(1)</script>"))
    broker.enqueue("pnl", dict(daily="5", unrealized="3", realized="2"))
    drain(broker)
    p = broker.report(tmp_path / "account.html")
    assert "</script><script>alert" not in p.read_text()
    assert "\\u003c/script" in p.read_text()
    assert p.with_suffix(".csv").exists()
    data = payload(broker.journal.events(broker.account), broker.snapshot())
    assert data["currency"] == "USD" and data["points"][0]["gap"]
    assert data["latest"]["daily"] == "5"
    assert "__DATA__" not in render(data)


def test_journal_version_and_atomic_reopen(tmp_path):
    path = tmp_path / "account.sqlite3"
    j = Journal(path)
    j.append("s", "a", "2026-10-19T12:00:00+00:00", "pnl", dict(daily="1"))
    j.close()
    j = Journal(path)
    assert len(j.events("a")) == 1
    assert j.events("other") == []
    j.db.execute("PRAGMA user_version=99")
    j.close()
    with pytest.raises(ValueError, match="version"):
        Journal(path)


def test_status_without_selected_account_identity_is_not_attributed(broker):
    broker.enqueue(
        "order_status",
        dict(order_id=88, client_id=999, status="Submitted", filled="0", remaining="1"),
    )
    drain(broker)
    assert not broker.snapshot().orders


def test_market_close_cannot_open_short_and_records_no_assumed_price(broker):
    from types import SimpleNamespace

    with pytest.raises(BrokerError, match="shorting"):
        broker.close_position_market("AAPL", 1)

    def resolve(symbol):
        broker._record("position", dict(con_id=100, quantity="1", symbol=symbol))
        return SimpleNamespace(conId=100)

    broker._adapter.resolve.side_effect = resolve
    assert broker.close_position_market("AAPL", 1, key="explicit-close") == 10
    assert broker._adapter.send_order.call_args.args[4] is None
    order = broker.snapshot().orders[0]
    assert order["order_type"] == "MKT" and order["limit_price"] is None
    assert order["side"] == "SELL" and order["quantity"] == "1"


def test_market_buys_are_not_supported(broker):
    with pytest.raises(BrokerError, match="closing existing"):
        broker._submit_equity("AAPL", "BUY", 1, None)
    broker._adapter.send_order.assert_not_called()


def test_refresh_retains_summary_readiness_but_requires_new_balances_and_positions(broker):
    broker._begin_refresh()
    assert broker.base_currency() == "USD"
    assert broker.snapshot().value("BuyingPower", "USD") is None
    assert broker.funding()["usable"] is None
    assert broker._barriers == {"summary"}
    for tag, value in [
        ("NetLiquidation", "900"),
        ("TotalCashValue", "800"),
        ("SettledCash", "700"),
        ("AvailableFunds", "800"),
        ("BuyingPower", "3200"),
    ]:
        broker.enqueue(
            "value", dict(tag=tag, value=value, currency="USD", source="account_updates")
        )
    for name in ("account", "orders", "executions"):
        broker.enqueue("barrier", dict(name=name))
    drain(broker)
    with pytest.raises(BrokerError, match="missing: positions"):
        broker.wait_ready(0.001)
    broker.enqueue("barrier", dict(name="positions"))
    assert broker.wait_ready(0.5).complete
    assert broker.base_currency() == "USD"
    assert broker.funding()["usable"] == "700"


def test_timeout_names_missing_download_and_broker_error(broker):
    broker._begin_refresh()
    broker.enqueue("error", dict(message="IBKR 322: summary request rejected"))
    drain(broker)
    with pytest.raises(
        BrokerError, match="incomplete.*missing: account, executions, orders, positions"
    ) as error:
        broker.wait_ready(0.001)
    assert "IBKR 322" in str(error.value)
    broker._adapter.send_order.assert_not_called()


def test_settlement_schedule_uses_current_balance_not_future_proceeds():
    from datetime import date
    from decimal import Decimal

    from pyibquant.broker import settled_schedule

    schedule = "20261019:1000.25;20261020:9000.75"
    assert settled_schedule(schedule, on_date=date(2026, 10, 19)) == Decimal("1000.25")
    assert settled_schedule(schedule, on_date=date(2026, 10, 20)) == Decimal("9000.75")
    assert settled_schedule(schedule, on_date=date(2026, 10, 21)) is None
    assert settled_schedule("20261020:9000.75", on_date=date(2026, 10, 19)) is None


@pytest.mark.parametrize(
    "schedule",
    [
        "20261019:1;20261019:2",
        "20261019:1;",
        "20261019:1;bad",
        "20261019:1;20261020:NaN",
        "20261019:1;20261320:2",
    ],
)
def test_malformed_multi_date_schedule_does_not_unlock_funds(schedule):
    from datetime import date

    from pyibquant.broker import settled_schedule

    assert settled_schedule(schedule, on_date=date(2026, 10, 19)) is None


def test_funding_remains_available_after_sale_adds_future_settlement_date(broker):
    from datetime import timedelta

    today = datetime.now(ZoneInfo("America/New_York")).date()
    broker._adapter.provide_settled = False
    broker.refresh()
    schedule = f"{today:%Y%m%d}:600;{today + timedelta(days=1):%Y%m%d}:900"
    broker.enqueue("value", dict(tag="SettledCashByDate", currency="USD", value=schedule))
    drain(broker)
    assert broker.funding()["usable"] == "600"
    assert broker.funding()["blocked_reasons"] == []


def test_execution_prices_repair_zero_status_and_deduplicate_partial_fills(broker):
    broker.max_quantity = 2
    broker.submit_limit("AAPL", "BUY", 2, 100)
    status(broker, "Submitted", "0", "2")
    broker.enqueue(
        "order_status",
        dict(
            client_id=272,
            order_id=10,
            status="Submitted",
            average_fill_price="0",
            filled="0",
            remaining="2",
        ),
    )
    one = dict(
        exec_id="one", client_id=272, order_id=10, quantity="1", price="99", cumulative_quantity="1"
    )
    two = dict(
        exec_id="two",
        client_id=272,
        order_id=10,
        quantity="1",
        price="101",
        cumulative_quantity="2",
    )
    broker.enqueue("execution", one)
    broker.enqueue("execution", one)
    broker.enqueue("execution", two)
    drain(broker)
    order = broker.snapshot().orders[0]
    assert order["status"] == "Filled" and order["average_fill_price"] == "100"
    broker.enqueue(
        "order_status",
        dict(
            client_id=272,
            order_id=10,
            status="Filled",
            average_fill_price="0",
            filled="2",
            remaining="0",
        ),
    )
    drain(broker)
    assert broker.snapshot().orders[0]["average_fill_price"] == "100"


def test_broker_execution_cumulative_average_is_used_when_status_has_no_price(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100)
    broker.enqueue(
        "execution",
        dict(
            exec_id="fill",
            client_id=272,
            order_id=10,
            quantity="1",
            price="99.5",
            average_fill_price="99.5",
            cumulative_quantity="1",
        ),
    )
    drain(broker)
    assert broker.snapshot().orders[0]["average_fill_price"] == "99.5"

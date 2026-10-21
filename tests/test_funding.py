"""Cash ceilings survive broker lag, partial fills, cancellations and restarts."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from test_broker import Adapter, drain
from test_broker import broker as broker

from pyibquant import BrokerError, PaperBroker
from pyibquant.trading.funding import SettlementPolicy, baseline_payload, cash_ledger, execution_day

T = datetime(2026, 10, 9, 15, tzinfo=UTC)


def order(side="BUY", **changes):
    return dict(client_id=272, order_id=10, order_ref="pyibquant:one", con_id=100,
                asset_type="STK", currency="USD", quantity="2", filled="2",
                remaining="0", status="Filled", limit_price="100", side=side, **changes)


def fill(side="BOT", **changes):
    return dict(exec_id="fill1", client_id=272, order_id=10, con_id=100, asset_type="STK",
                currency="USD", side=side, quantity="2", price="99", commission="1",
                fee_currency="USD", first_received_at=T.isoformat(), **changes)


def ledger(orders, fills, at=T):
    return cash_ledger(baseline_payload(Decimal(500), (), SettlementPolicy(), at=T),
                       tuple(orders), tuple(fills), at=at)


def test_buy_and_late_fees_reduce_cash_immediately_without_broker_updates():
    o, f = order(), fill()
    assert ledger([o], [f])["cash_ceiling"] == "301"
    f["commission"] = None
    assert ledger([o], [f])["cash_ceiling"] == "300"
    f["commission"] = "5"
    assert ledger([o], [f])["cash_ceiling"] == "297"


def test_partial_buy_hold_and_cancel_release_only_unfilled_commitment():
    o, f = order(), fill()
    o.update(status="Submitted", filled="1", remaining="1")
    f.update(quantity="1")
    result = ledger([o], [f])
    assert result["cash_ceiling"] == "399"
    assert result["pending_buy_estimate"] == "101"
    o.update(status="Cancelled", remaining="0")
    result = ledger([o], [f])
    assert result["cash_ceiling"] == "400" and result["pending_buy_estimate"] == "0"
    assert not result["funding_issues"]


def test_sale_waits_through_weekend_and_bank_holiday():
    o, f = order("SELL"), fill("SLD")
    result = ledger([o], [f])
    assert result["cash_ceiling"] == "499" and result["local_unsettled"] == "198"
    assert result["settlement_obligations"][0]["settlement_date"] == "2026-10-13"
    assert ledger([o], [f], T + timedelta(days=3))["cash_ceiling"] == "499"
    assert ledger([o], [f], T + timedelta(days=4))["cash_ceiling"] == "697"


def test_options_use_multiplier_and_explicit_stricter_local_t1():
    o, f = order("SELL"), fill("SLD")
    for row in (o, f):
        row.update(asset_type="OPT", multiplier="100", quantity="1")
    o["filled"] = "1"
    result = ledger([o], [f])
    assert result["local_unsettled"] == "9900"
    assert result["cash_ceiling"] == "499"


@pytest.mark.parametrize("day,expected", [
    (date(2026, 11, 10), date(2026, 11, 12)),
    (date(2026, 4, 2), date(2026, 4, 6)),
    (date(2026, 7, 2), date(2026, 7, 6)),
    (date(2026, 12, 31), date(2027, 1, 4)),
])
def test_versioned_calendar_does_not_use_twenty_four_hours(day, expected):
    assert SettlementPolicy().settlement_date(day, "STK", "USD") == expected


def test_calendar_roundtrip_and_unknown_scope_fail_closed():
    policy = SettlementPolicy()
    assert SettlementPolicy.from_dict(policy.to_dict()) == policy
    for day, asset, currency in [(date(2028, 1, 1), "STK", "USD"),
                                 (T.date(), "FUT", "USD"), (T.date(), "STK", "EUR")]:
        with pytest.raises(ValueError):
            policy.settlement_date(day, asset, currency)
    with pytest.raises(ValueError):
        replace(policy, equity_days=0)


def test_execution_date_uses_broker_time_not_redownload_receipt():
    f = fill()
    f["broker_time"] = "20261009  23:59:00 US/Eastern"
    f["first_received_at"] = "2026-10-14T14:00:00+00:00"
    assert execution_day(f) == date(2026, 10, 9)
    f["broker_time"] = "2026-10-10T00:30:00+00:00"
    assert execution_day(f) == date(2026, 10, 9)


def test_missing_execution_or_foreign_fee_blocks_instead_of_releasing_cash():
    assert ledger([order()], [])["funding_issues"]
    f = fill()
    f["fee_currency"] = "EUR"
    assert ledger([order()], [f])["funding_issues"]


def test_no_double_deduction_when_broker_cash_catches_up(broker):
    broker.max_quantity = 2
    broker.submit_limit("AAPL", "BUY", 2, 100)
    broker._record("execution", {**fill(), "cumulative_quantity": "2"})
    broker._record("fee", dict(exec_id="fill1", commission="1", fee_currency="USD"))
    assert broker.funding()["usable"] == "301"
    broker._record("value", dict(tag="SettledCash", currency="USD", value="301"))
    assert broker.funding()["usable"] == "301"
    broker._record("value", dict(tag="SettledCash", currency="USD", value="250"))
    assert broker.funding()["usable"] == "250"
    with pytest.raises(BrokerError, match="funds"):
        broker.submit_limit("AAPL", "BUY", 1, 302)
    assert broker._adapter.send_order.call_count == 1


def test_partial_cancel_and_unknown_send_reservations_survive_restart(broker):
    broker.max_quantity = 2
    broker.submit_limit("AAPL", "BUY", 2, 100)
    broker._record("execution", {**fill(), "quantity": "1", "cumulative_quantity": "1"})
    broker.cancel(10)
    assert broker.funding()["pending_buy_estimate"] == "101"
    path = broker.journal.path
    broker.close()
    adapter = Adapter()
    adapter.seed_order_id = Mock()
    with PaperBroker(adapter, path, account="DUABC123", readonly=False,
                     paper_confirmed=True, max_quantity=2) as b:
        assert b.funding()["usable"] is None
        adapter.refresh(b.account)
        b.wait_ready(.5)
        assert b.funding()["pending_buy_estimate"] == "101"
        b._record("order_status", dict(client_id=272, order_id=10, status="Cancelled",
                                       filled="1", remaining="0"))
        assert b.funding()["usable"] == "400"
        adapter.send_order.assert_not_called()
        adapter.cancel_order.assert_not_called()


def test_unknown_send_retains_entire_reservation(broker):
    broker._adapter.send_order.side_effect = OSError("lost after send")
    with pytest.raises(BrokerError, match="unknown"):
        broker.submit_limit("AAPL", "BUY", 1, 100)
    assert broker.funding()["pending_buy_estimate"] == "102"
    assert broker.funding()["usable"] is None
    broker.cancel(10)
    assert broker.funding()["pending_buy_estimate"] == "102"


def test_duplicate_redownload_does_not_change_first_receipt_or_charge_twice(broker):
    broker.max_quantity = 2
    broker.submit_limit("AAPL", "BUY", 2, 100)
    f = {**fill(), "cumulative_quantity": "2"}
    broker._record("execution", f)
    receipt = broker.snapshot().executions[0]["first_received_at"]
    broker._record("execution", f)
    assert broker.snapshot().executions[0]["first_received_at"] == receipt
    assert broker.funding()["usable"] == "301"
    broker._record("execution", {**f, "price": "98"})
    assert broker.funding()["usable"] is None


def test_stale_balance_blocks_new_exposure(broker):
    result = broker.funding(at=datetime.now(UTC) + timedelta(seconds=61))
    assert result["usable"] is None
    assert any("Stale" in reason for reason in result["blocked_reasons"])
    drain(broker)


def test_restart_keeps_sale_hold_and_releases_only_with_fresh_broker_cap(broker):
    # An existing holding is sold from an anchored 500 USD cash budget.
    original = broker._adapter.resolve.return_value
    def resolve(symbol):
        broker._record("position", dict(con_id=100, quantity="1", symbol=symbol))
        return original
    broker._adapter.resolve.side_effect = resolve
    broker.submit_limit("AAPL", "SELL", 1, 100)
    today = datetime.now(UTC)
    broker._record("execution", {**fill("SLD"), "quantity": "1",
        "price": "100", "broker_time": today.isoformat(), "cumulative_quantity": "1"})
    assert broker.funding()["usable"] == "499"
    path = broker.journal.path
    broker.close()
    adapter = Adapter()
    with PaperBroker(adapter, path, account="DUABC123") as b:
        adapter.refresh(b.account)
        b.wait_ready(.5)
        assert b.funding()["usable"] == "499"
        result = b.funding()
        release = datetime.fromisoformat(
            result["settlement_obligations"][0]["settlement_date"] + "T15:00:00+00:00")
        # A wall-clock change alone cannot release spendable funds.
        assert b.funding(at=release)["usable"] is None
        for tag, value in [("SettledCash", "550"), ("CashBalance", "1000"),
                           ("TotalCashValue", "1000"), ("AvailableFunds", "1000"),
                           ("BuyingPower", "4000")]:
            b._record("value", dict(tag=tag, currency="USD", value=value), release.isoformat())
        result = b.funding(at=release)
        assert result["cash_ceiling"] == "599" and result["usable"] == "550"
        adapter.send_order.assert_not_called()


def test_stale_second_broker_cannot_spend_same_cash(broker):
    adapter = Adapter()
    with PaperBroker(adapter, broker.journal.path, account="DUABC123", readonly=False,
                     paper_confirmed=True) as second:
        adapter.refresh(second.account)
        second.wait_ready(.5)
        broker.submit_limit("AAPL", "BUY", 1, 100)
        with pytest.raises(BrokerError, match="journal changed"):
            second.submit_limit("AAPL", "BUY", 1, 100)
        adapter.send_order.assert_not_called()


def test_baseline_rejects_policy_change_on_restart(broker):
    broker.submit_limit("AAPL", "BUY", 1, 100)
    with pytest.raises(BrokerError, match="Settlement policy differs"):
        PaperBroker(Adapter(), broker.journal.path, account="DUABC123",
                    settlement_policy=replace(SettlementPolicy(), option_days=2))


def test_missing_fees_block_new_exposure_until_confirmed_and_revise_after_restart(broker):
    broker.max_quantity = 2
    broker.submit_limit("AAPL", "BUY", 2, 100)
    f = {**fill(), "commission": None, "cumulative_quantity": "2"}
    broker._record("execution", f)
    assert broker.funding()["usable"] is None
    broker._record("fee", dict(exec_id="fill1", commission="3", fee_currency="USD"))
    assert broker.funding()["usable"] == "299"
    path = broker.journal.path
    broker.close()
    adapter = Adapter()
    with PaperBroker(adapter, path, account="DUABC123") as b:
        adapter.refresh(b.account)
        b.wait_ready(.5)
        assert b.funding()["usable"] == "299"
        b._record("fee", dict(exec_id="fill1", commission="4", fee_currency="USD"))
        assert b.funding()["usable"] == "298"


def test_stale_second_broker_detects_unreplayed_fee_even_without_new_intent(broker):
    broker.max_quantity = 2
    broker.submit_limit("AAPL", "BUY", 2, 100)
    broker._record("execution", {**fill(), "cumulative_quantity": "2"})
    adapter = Adapter()
    with PaperBroker(adapter, broker.journal.path, account="DUABC123", readonly=False,
                     paper_confirmed=True) as second:
        adapter.refresh(second.account)
        second.wait_ready(.5)
        broker._record("fee", dict(exec_id="fill1", commission="50", fee_currency="USD"))
        with pytest.raises(BrokerError, match="journal changed"):
            second.submit_limit("AAPL", "BUY", 1, 270)
        adapter.send_order.assert_not_called()


def test_known_holding_exit_does_not_require_spendable_cash(broker):
    broker._adapter.provide_settled = False
    contract = broker._adapter.resolve.return_value
    def resolve(symbol):
        broker._record("position", dict(con_id=100, quantity="1", symbol=symbol))
        return contract
    broker._adapter.resolve.side_effect = resolve
    assert broker.submit_limit("AAPL", "SELL", 1, 100) == 10
    assert broker._funding_baseline is None


def test_legacy_incomplete_fills_cannot_be_forgiven_by_creating_a_baseline(broker):
    broker._record("intent", order())
    with pytest.raises(BrokerError, match="Legacy fills"):
        broker.submit_limit("AAPL", "BUY", 1, 100)
    assert broker._funding_baseline is None
    broker._adapter.send_order.assert_not_called()


def test_sell_cannot_fund_rebuy_same_day_but_unused_settled_cash_is_available(broker):
    broker.submit_limit("AAPL", "BUY", 1, 450)
    broker._record("execution", {**fill(), "quantity": "1", "price": "450",
                                 "cumulative_quantity": "1"})
    assert broker.funding()["usable"] == "49"
    contract = broker._adapter.resolve.return_value
    def resolve(symbol):
        broker._record("position", dict(con_id=100, quantity="1", symbol=symbol))
        return contract
    broker._adapter.resolve.side_effect = resolve
    broker._adapter.allocate_id.return_value = 11
    broker.submit_limit("AAPL", "SELL", 1, 445)
    broker._record("execution", {**fill("SLD"), "exec_id": "sell", "order_id": 11,
        "quantity": "1", "price": "445", "cumulative_quantity": "1",
        "broker_time": datetime.now(UTC).isoformat()})
    assert broker.funding()["usable"] == "48"
    with pytest.raises(BrokerError, match="funds"):
        broker.submit_limit("AAPL", "BUY", 1, 445)
    broker._adapter.allocate_id.return_value = 12
    assert broker.submit_limit("AAPL", "BUY", 1, 40) == 12
    assert broker._adapter.send_order.call_count == 3


def test_simultaneous_local_sends_cannot_commit_same_account_cash(broker):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    def send(*args):
        entered.set()
        assert release.wait(2)
    broker._adapter.send_order.side_effect = send
    adapter = Adapter()
    with PaperBroker(adapter, broker.journal.path, account="DUABC123", readonly=False,
                     paper_confirmed=True) as second:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(broker.submit_limit, "AAPL", "BUY", 1, 300)
            try:
                assert entered.wait(2)
                with pytest.raises(BrokerError):
                    second.submit_limit("AAPL", "BUY", 1, 300)
            finally:
                release.set()
            assert future.result(timeout=2) == 10
        adapter.send_order.assert_not_called()


def test_timezone_ambiguous_sale_never_releases_proceeds():
    f = fill("SLD")
    f["broker_time"] = "20261009 23:59:00"
    result = ledger([order("SELL")], [f], at=T + timedelta(days=5))
    assert result["cash_ceiling"] == "499"
    assert any("timezone" in issue for issue in result["funding_issues"])

"""SDK callback translation and cancellation compatibility, with no network."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyibquant import BrokerError, Option
from pyibquant.trading.ibkr import BrokerAdapter


def adapter():
    a = BrokerAdapter("127.0.0.1", 7497, 272, 0.1)
    a.sink = Mock()
    a.isConnected = Mock(return_value=True)
    return a


def contract():
    return SimpleNamespace(
        conId=100, symbol="AAPL", secType="STK", currency="USD", multiplier="", localSymbol="AAPL"
    )


def test_order_ids_never_share_data_request_counter():
    a = adapter()
    a.nextValidId(40)
    a._request = 99999
    assert a.allocate_id() == 40 and a.allocate_id() == 41
    a.orderStatus(70, "Submitted", Decimal(0), Decimal(1), 0, 8, 0, 0, 272, "", 0)
    assert a.allocate_id() == 71


def test_actual_sdk_cancellation_signature():
    a = adapter()
    a.cancelOrder = Mock()
    a.cancel_order(4)
    args = a.cancelOrder.call_args.args
    assert args[0] == 4 and len(args) == 2


def test_order_transport_binds_account_and_disables_extended_hours():
    a = adapter()
    a.placeOrder = Mock()
    a.send_order(4, contract(), "BUY", 1, Decimal("123.45"), "DU123", "pyibquant:test")
    oid, c, o = a.placeOrder.call_args.args
    assert oid == 4 and o.account == "DU123" and o.orderRef == "pyibquant:test"
    assert o.orderType == "LMT" and o.lmtPrice == 123.45
    assert o.tif == "DAY" and o.transmit and not o.outsideRth


def test_unset_values_and_old_and_new_fee_callbacks():
    a = adapter()
    a._pnl_id = 1
    a.pnl(1, 1.7976931348623157e308, 2, 3)
    assert a.sink.call_args.args[1]["daily"] is None
    a.commissionAndFeesReport(
        SimpleNamespace(execId="x", commissionAndFees=0.35, currency="USD", realizedPNL=0)
    )
    assert a.sink.call_args.args[1]["commission"] == "0.35"
    a.commissionReport(SimpleNamespace(execId="y", commission=0.50, currency="USD", realizedPNL=0))
    assert a.sink.call_args.args[1]["commission"] == "0.5"


def test_pnl_renewal_filters_old_generation_and_cancels_only_previous_subscription():
    a = adapter()
    a.reqPnL, a.cancelPnL = Mock(), Mock()
    first = a.request_pnl("DU123")
    second = a.request_pnl("DU123")
    assert first != second
    a.cancelPnL.assert_called_once_with(first)
    a.pnl(first, 10, 0, 10)
    a.sink.assert_not_called()
    a.pnl(second, 10, 0, 10)
    assert a.sink.call_args.args[1]["request_id"] == second


def test_error_signatures_and_masking():
    a = adapter()
    a.account = "DU123"
    for args in ((10, 201, "DU123 reject"), (10, 0, 201, "DU123 reject", "")):
        a.error(*args)
        assert a.sink.call_args.args[1]["code"] == 201
        assert "DU123" not in a.sink.call_args.args[1]["message"]
    a.error(-1, 0, 1100, "lost")
    assert a.sink.call_args.args[0] == "disconnected"


def test_summary_generation_filters_late_callbacks():
    a = adapter()
    a._summary_id = 5
    a.accountSummary(4, "DU123", "BuyingPower", "1000", "USD")
    a.accountSummaryEnd(4)
    a.sink.assert_not_called()
    a.accountSummary(5, "DU123", "BuyingPower", "1000", "USD")
    assert a.sink.call_count == 1


def test_market_close_transport_preserves_unset_limit_price():
    a = adapter()
    a.placeOrder = Mock()
    a.send_order(4, contract(), "SELL", 1, None, "DU123", "pyibquant:close")
    order = a.placeOrder.call_args.args[2]
    assert order.orderType == "MKT" and order.action == "SELL"
    assert order.lmtPrice > 1e100 and not order.outsideRth


def test_repeated_refresh_reuses_one_persistent_account_summary():
    a = adapter()
    a.prepare = Mock()
    methods = (
        "reqAccountUpdates",
        "reqAccountSummary",
        "cancelAccountSummary",
        "cancelPositions",
        "reqPositions",
        "reqAllOpenOrders",
        "reqExecutions",
    )
    for name in methods:
        setattr(a, name, Mock())
    for _ in range(5):
        a.refresh("DU123")
    a.reqAccountSummary.assert_called_once()
    a.cancelAccountSummary.assert_not_called()
    assert a._summary_id == a.reqAccountSummary.call_args.args[0]
    assert len({c.args[0] for c in a.reqExecutions.call_args_list}) == 5
    assert a.reqPositions.call_count == 5


def test_summary_subscription_rejection_fails_sync_immediately():
    a = adapter()
    a._summary_id = 9030
    a.error(9030, 0, 322, "ReqAccountSummary: Maximum number of requests exceeded")
    assert a.sink.call_args.args[1]["fatal"]


def test_completed_download_filters_accounts_and_requires_end_barrier():
    a = adapter()
    order = SimpleNamespace(
        account="DU123", orderId=10, clientId=272, permId=50,
        orderRef="pyibquant:test", action="BUY", totalQuantity=Decimal(0),
        filledQuantity=Decimal(1),
    )
    state = SimpleNamespace(status="Filled", completedTime="today", completedStatus="Filled")

    def download(api_only):
        assert api_only is False
        a.completedOrder(contract(), order, state)
        a.completedOrdersEnd()
        a.completedOrder(contract(), order, state)  # Late callback cannot enter the batch.

    a.reqCompletedOrders = Mock(side_effect=download)
    rows = a.completed_orders("DU123")
    assert len(rows) == 1 and rows[0]["quantity"] == "0" and rows[0]["filled"] == "1"
    assert a.completed_orders("DUOTHER") == []


def test_completed_download_timeout_cannot_be_retried_or_completed_by_late_barrier():
    a = adapter()
    a.timeout = .001
    a.reqCompletedOrders = Mock()
    with pytest.raises(BrokerError, match="incomplete"):
        a.completed_orders("DU123")
    a.completedOrdersEnd()
    with pytest.raises(BrokerError, match="new broker session"):
        a.completed_orders("DU123")
    a.reqCompletedOrders.assert_called_once_with(False)


def test_option_resolution_downloads_smart_price_ladder_and_preserves_identity():
    a = adapter()
    selector = Option("AAPL", date(2026, 11, 20), 360, "C", "AAPL", 100)

    def resolve(req_id, c):
        c.conId = 200
        c.localSymbol = "AAPL option"
        a.contractDetails(req_id, SimpleNamespace(
            contract=c, validExchanges="SMART,CBOE", marketRuleIds="26,27"
        ))
        a.contractDetailsEnd(req_id)

    a.reqContractDetails = Mock(side_effect=resolve)
    a.reqMarketRule = Mock(side_effect=lambda rid: a.marketRule(rid, [
        SimpleNamespace(lowEdge=0, increment=.01), SimpleNamespace(lowEdge=3, increment=.05)
    ]))
    c, rules = a.resolve_option(selector)
    assert c.conId == 200 and c.secType == "OPT" and c.exchange == "SMART"
    assert rules == ((Decimal(0), Decimal(".01")), (Decimal(3), Decimal(".05")))
    a.resolve_option(selector)
    a.reqMarketRule.assert_called_once_with(26)


def test_option_resolution_refuses_missing_smart_rule():
    a = adapter()

    def resolve(req_id, c):
        c.conId = 200
        a.contractDetails(req_id, SimpleNamespace(
            contract=c, validExchanges="CBOE", marketRuleIds="27"
        ))
        a.contractDetailsEnd(req_id)

    a.reqContractDetails = Mock(side_effect=resolve)
    with pytest.raises(BrokerError, match="SMART"):
        a.resolve_option(Option("AAPL", date(2026, 11, 20), 360, "C", "AAPL", 100))

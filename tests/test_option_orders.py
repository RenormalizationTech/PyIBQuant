"""Selected-option execution uses real multipliers, exact quotes and owned exits."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from test_broker import broker as broker
from test_broker import drain

from pyibquant import BrokerError, Option
from pyibquant.quotes import Quote, QuoteInstrument
from pyibquant.trading.option_order import round_limit
from pyibquant.trading.run_performance import valuation


@pytest.fixture
def option_setup(broker):
    at = datetime.now(UTC)
    selector = Option("AAPL", (at + timedelta(days=30)).date(), 360, "C", "AAPL", 100)
    contract = SimpleNamespace(conId=200, multiplier="100", localSymbol="AAPL option")
    rules = ((Decimal(0), Decimal(".01")),)
    broker._adapter.resolve_option = Mock(return_value=(contract, rules))
    instrument = QuoteInstrument(
        "AAPL", 200, "option", "USD", "SMART", "", "AAPL option", "AAPL", 100,
        selector.expiry.strftime("%Y%m%d"), 360, "C",
    )
    q = Quote(
        instrument, "live", "live", False, at, None, 3.2, 3.45, None, 1, 1, None,
        (("bid", at), ("ask", at)), (), (), (), streaming=True, status="active",
    )
    return selector, q


def submit(broker, setup, *, side="BUY", price=3.45, **kwargs):
    selector, q = setup
    return broker.submit_option_limit(selector, side, 1, price,
                                      quote=q, tag="option-test", **kwargs)


def execute_buy(broker, setup):
    submit(broker, setup)
    broker._record("execution", dict(
        exec_id="option-buy", order_id=10, client_id=272, con_id=200,
        currency="USD", asset_type="OPT", multiplier="100", side="BOT",
        quantity="1", price="3.45", cumulative_quantity="1",
    ))
    broker._record("fee", dict(exec_id="option-buy", commission="1", fee_currency="USD"))
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue("position", dict(con_id=200, quantity="1", asset_type="OPT"))
        drain(broker)

    broker._adapter.refresh = refresh
    broker._adapter.allocate_id.return_value = 11


def test_premium_reservation_and_cash_flow_use_multiplier(broker, option_setup):
    assert submit(broker, option_setup, key="one-option") == 10
    order = broker.snapshot().orders[0]
    assert order["asset_type"] == "OPT" and order["multiplier"] == "100"
    assert broker.funding()["pending_buy_estimate"] == "347.00"
    with pytest.raises(BrokerError, match="working or uncertain"):
        submit(broker, option_setup)
    broker._adapter.send_order.assert_called_once()


@pytest.mark.parametrize("price,message", [(5.01, "cap"), (3.451, "increment")])
def test_cap_and_tick_fail_before_order_intent(broker, option_setup, price, message):
    with pytest.raises(BrokerError, match=message):
        submit(broker, option_setup, price=price)
    broker._adapter.send_order.assert_not_called()
    assert broker.snapshot().orders == ()


@pytest.mark.parametrize("change", ["stale", "delayed", "wrong_contract", "wrong_multiplier"])
def test_invalid_quote_never_sends(broker, option_setup, change):
    selector, q = option_setup
    if change == "stale":
        q = replace(q, field_received_at=(("bid", datetime.now(UTC) - timedelta(seconds=30)),))
    elif change == "delayed":
        q = replace(q, market_data_type="delayed")
    elif change == "wrong_contract":
        q = replace(q, instrument=replace(q.instrument, instrument_id=201))
    else:
        q = replace(q, instrument=replace(q.instrument, multiplier=10))
    with pytest.raises(BrokerError, match="exact-contract"):
        submit(broker, (selector, q))
    broker._adapter.send_order.assert_not_called()


def test_expiry_day_and_readonly_refuse_orders(broker, option_setup):
    selector, q = option_setup
    selector = replace(selector, expiry=datetime.now(ZoneInfo("America/New_York")).date())
    with pytest.raises(BrokerError, match="Expiry-day"):
        submit(broker, (selector, q))
    broker.readonly = True
    with pytest.raises(BrokerError, match="read-only"):
        submit(broker, option_setup)
    broker._adapter.send_order.assert_not_called()


def test_option_owned_sell_and_pnl_are_contract_scaled(broker, option_setup):
    execute_buy(broker, option_setup)
    value = valuation("option-test", broker.snapshot().orders, broker.snapshot().executions,
                      {200: dict(price="3.60", time="now")})
    assert value["net_pnl"] == "14.00" and value["gross_exposure"] == "360.00"
    assert submit(broker, option_setup, side="SELL", price=3.2) == 11
    broker._record("execution", dict(
        exec_id="option-sell", order_id=11, client_id=272, con_id=200,
        currency="USD", asset_type="OPT", multiplier="100", side="SLD",
        quantity="1", price="3.2", cumulative_quantity="1",
    ))
    broker._record("fee", dict(exec_id="option-sell", commission="1", fee_currency="USD"))
    ledger = broker.strategy_ledger("option-test")
    assert ledger.complete and ledger.cash_flow == -25 and ledger.commissions == 2
    assert ledger.to_dict()["realized_pnl"] == "-27.00"
    value = valuation("option-test", broker.snapshot().orders, broker.snapshot().executions, {})
    assert value["net_pnl"] == "-27.00" and value["gross_realized"] == "-25.00"


def test_external_option_holding_is_not_sellable_under_a_new_tag(broker, option_setup):
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue("position", dict(con_id=200, quantity="1"))
        drain(broker)

    broker._adapter.refresh = refresh
    with pytest.raises(BrokerError, match="this tag"):
        submit(broker, option_setup, side="SELL", price=3.2)
    broker._adapter.send_order.assert_not_called()


def test_option_send_failure_is_durable_and_never_retried(broker, option_setup):
    broker._adapter.send_order.side_effect = OSError("uncertain")
    with pytest.raises(BrokerError, match="never blindly retry"):
        submit(broker, option_setup)
    with pytest.raises(BrokerError, match="working or uncertain"):
        submit(broker, option_setup)
    assert broker.snapshot().orders[0]["status"] == "UnknownSend"
    broker._adapter.send_order.assert_called_once()


def test_option_missing_execution_multiplier_is_incomplete(broker, option_setup):
    execute_buy(broker, option_setup)
    executions = tuple({k: v for k, v in e.items() if k != "multiplier"}
                       for e in broker.snapshot().executions)
    value = valuation("option-test", broker.snapshot().orders, executions, {})
    assert not value["complete"] and value["net_pnl"] is None


def test_tiered_limit_rounding_crosses_increment_boundary():
    rules = ((Decimal(0), Decimal(".01")), (Decimal(3), Decimal(".05")))
    assert round_limit(Decimal("3.021"), "BUY", rules) == Decimal("3.05")
    assert round_limit(Decimal("3.021"), "SELL", rules) == Decimal("3.00")

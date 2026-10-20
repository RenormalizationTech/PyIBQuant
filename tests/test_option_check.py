"""Bounded option harness recovery cannot repeat an entry or an attempted exit."""

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_broker import broker as broker
from test_broker import drain
from test_option_orders import execute_buy
from test_option_orders import option_setup as option_setup

from pyibquant import BrokerError

spec = importlib.util.spec_from_file_location(
    "paper_option_example", Path(__file__).resolve().parents[1] / "examples/paper_option_check.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)
CHECK = "a" * 32
TAG = "option-check-" + CHECK


def retag(broker):
    broker._record("order", dict(order_id=10, client_id=272, tag=TAG))


def test_plan_refuses_spread_exceeding_loss_budget(broker, option_setup):
    selector, q = option_setup
    at = datetime.now(UTC).timestamp()
    series = SimpleNamespace(sessions=[dict(regular=True, start=at - 60, end=at + 60)])
    with pytest.raises(BrokerError, match="spread"):
        example.create_plan(broker, selector, series, q, 25)
    plan = example.create_plan(broker, selector, series, replace(q, ask=3.3), 25)
    assert Decimal(plan["max_entry_premium"]) == 330
    assert Decimal(plan["estimated_spread_and_fees"]) == 14
    broker._adapter.send_order.assert_not_called()


def test_missing_entry_does_not_cancel_or_replace_it(broker, option_setup):
    selector, q = option_setup
    broker.submit_option_limit(selector, "BUY", 1, 3.45, quote=q, tag=TAG)
    with pytest.raises(BrokerError, match="missing"):
        example.finish_check(broker, selector, lambda: q, CHECK)
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_not_called()


def test_recovery_closes_once_and_repeat_cannot_create_an_order(broker, option_setup):
    selector, q = option_setup
    execute_buy(broker, option_setup)
    retag(broker)
    held = ["1"]
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue("position", dict(con_id=200, quantity=held[0]))
        drain(broker)

    def sell(oid, contract, side, quantity, price, account, ref):
        assert side == "SELL" and quantity == 1
        held[0] = "0"
        broker._record("execution", dict(
            exec_id="exit", order_id=oid, client_id=272, con_id=200, currency="USD",
            asset_type="OPT", multiplier="100", side="SLD", quantity="1",
            price=str(price), cumulative_quantity="1",
        ))
        broker._record("fee", dict(exec_id="exit", commission="1", fee_currency="USD"))

    broker._adapter.refresh = refresh
    broker._adapter.send_order.side_effect = sell
    result = example.finish_check(broker, selector, lambda: q, CHECK)
    assert result["passed"] and result["account_flat"] and result["round_trip_filled"]
    assert broker._adapter.send_order.call_count == 2  # Original buy and one close.
    assert example.finish_check(broker, selector, lambda: q, CHECK)["passed"]
    assert broker._adapter.send_order.call_count == 2


def test_prior_canceled_exit_is_not_blindly_repeated(broker, option_setup):
    selector, q = option_setup
    execute_buy(broker, option_setup)
    retag(broker)
    broker._record("intent", dict(
        order_id=11, client_id=272, tag=TAG, order_ref="pyibquant:attempted-exit",
        con_id=200, side="SELL", quantity="1", filled="0", status="Cancelled",
        asset_type="OPT", multiplier="100",
    ))
    with pytest.raises(BrokerError, match="sell was already attempted"):
        example.finish_check(broker, selector, lambda: q, CHECK)
    broker._adapter.send_order.assert_called_once()


def test_paper_nickel_limits_still_follow_the_broker_rule():
    rules = ((Decimal(0), Decimal(".01")),)
    assert example.execution_limit(2.29, "BUY", rules) == Decimal("2.30")
    assert example.execution_limit(2.16, "SELL", rules) == Decimal("2.15")


def test_option_cancel_releases_multiplier_reservation_without_a_sell(
    broker, option_setup, monkeypatch
):
    selector, q = option_setup
    broker.submit_option_limit(selector, "BUY", 1, 2.8, quote=q, tag=TAG)
    broker._record("order_status", dict(
        order_id=10, client_id=272, status="Submitted", filled="0", remaining="1"
    ))
    ticks = count()
    monkeypatch.setattr(example, "monotonic", lambda: next(ticks))
    broker.wait_for_update = Mock(side_effect=lambda *args, **kwargs: broker.snapshot())
    broker._adapter.cancel_order.side_effect = lambda oid: broker.enqueue(
        "order_status", dict(
            order_id=oid, client_id=272, status="Cancelled", filled="0", remaining="0"
        )
    )
    result = example.finish_cancellation(broker, CHECK)
    assert result["passed"] and result["acknowledged"] and result["account_flat"]
    assert Decimal(result["reservation_before_cancel"]) == 282
    assert Decimal(result["reservation_after_cancel"]) == 0
    assert result["ledger"]["execution_count"] == 0
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_called_once_with(10)


def test_option_cancel_recovery_missing_order_blocks_without_replacement(broker, option_setup):
    selector, q = option_setup
    broker.submit_option_limit(selector, "BUY", 1, 2.8, quote=q, tag=TAG)
    with pytest.raises(BrokerError, match="Missing/foreign"):
        example.finish_cancellation(broker, CHECK, wait_ack=False)
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_not_called()


def test_option_cancel_fill_race_retains_and_reports_contract(broker, option_setup):
    execute_buy(broker, option_setup)
    retag(broker)
    result = example.finish_cancellation(broker, CHECK)
    assert not result["passed"] and result["outcome"] == "fill_observed"
    assert not result["flat"] and result["ledger"]["execution_count"] == 1
    broker._adapter.send_order.assert_called_once()
    broker._adapter.cancel_order.assert_not_called()

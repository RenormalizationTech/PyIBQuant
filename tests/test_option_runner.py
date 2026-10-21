"""Automated selected-option decisions share the guarded runner lifecycle."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from test_broker import broker as broker
from test_broker import drain
from test_option_orders import option_setup as option_setup
from test_paper_runner import T, advance, feed

from pyibquant import Bar, BrokerError
from pyibquant.trading.option_runner import OptionRunner
from pyibquant.trading.runner import EquityRunner, RunnerConfig


def q_at(setup, at):
    return replace(setup[1], field_received_at=(("bid", at), ("ask", at)))


def ready(broker, setup, *, dry=False, entry_when="above_sma"):
    broker._record("pnl", dict(daily="0", unrealized="0", realized="0"), T.isoformat())
    broker._record("pnl_validated", dict(request_id=None))
    broker.refresh_pnl = Mock(side_effect=lambda **kw: broker.snapshot())
    broker.refresh_risk = Mock(side_effect=lambda: broker.snapshot())
    series = feed()
    runner = OptionRunner(broker, RunnerConfig("AAPL", window=2, dry_run=dry),
                          setup[0], entry_when=entry_when)
    runner.start(series, at=T)
    return runner, series


def test_warmup_does_not_trade_and_new_bar_buys_exact_option_once(broker, option_setup):
    runner, series = ready(broker, option_setup)
    runner.step(series, q_at(option_setup, T), at=T)
    broker._adapter.send_order.assert_not_called()
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    with patch("pyibquant.trading.option_order.datetime") as clock:
        clock.now.return_value = at
        assert runner.step(series, q_at(option_setup, at), at=at) == 10
    assert runner.step(series, q_at(option_setup, at), at=at) is None
    o = broker.snapshot().orders[0]
    assert o["con_id"] == 200 and o["asset_type"] == "OPT" and o["quantity"] == "1"
    assert o["limit_price"] == "3.45" and o["multiplier"] == "100"
    assert broker.funding()["pending_buy_estimate"] == "347.00"
    runner.stop()


def test_observation_never_calls_order_transport(broker, option_setup):
    runner, series = ready(broker, option_setup, dry=True)
    at = advance(series)
    runner.step(series, q_at(option_setup, at), at=at)
    broker._adapter.send_order.assert_not_called()
    runner.stop()


@pytest.mark.parametrize("failure", ["stale", "wrong_contract", "wrong_strike", "delayed", "cap"])
def test_invalid_option_quote_or_premium_cannot_submit(broker, option_setup, failure):
    runner, series = ready(broker, option_setup)
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    q = q_at(option_setup, at)
    if failure == "stale":
        q = q_at(option_setup, T - timedelta(minutes=1))
    elif failure == "wrong_contract":
        q = replace(q, instrument=replace(q.instrument, instrument_id=201))
    elif failure == "wrong_strike":
        q = replace(q, instrument=replace(q.instrument, strike=999))
    elif failure == "delayed":
        q = replace(q, market_data_type="delayed")
    else:
        runner._order_cap = Decimal(300)
    runner.step(series, q, at=at)
    assert runner.status == "paused"
    broker._adapter.send_order.assert_not_called()
    runner.stop()


def test_restore_preserves_selected_contract_and_refuses_changed_resolution(broker, option_setup):
    runner, series = ready(broker, option_setup)
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    assert isinstance(restored, OptionRunner) and restored.selector == runner.selector
    assert restored.trade_instrument_id == 200 and restored._multiplier == 100
    contract, rules = broker._adapter.resolve_option.return_value
    contract.conId = 201
    with pytest.raises(BrokerError, match="persisted trading contract"):
        restored.resume(series, at=T)
    broker._adapter.send_order.assert_not_called()


def test_expiry_day_pauses_before_any_order_or_signal(broker, option_setup):
    runner, series = ready(broker, option_setup)
    runner.selector = replace(runner.selector, expiry=T.date())
    q = q_at(option_setup, T)
    q = replace(q, instrument=replace(q.instrument, expiry=T.strftime("%Y%m%d")))
    runner.step(series, q, at=T)
    assert runner.status == "paused" and "Expiry-day" in runner.reason
    broker._adapter.send_order.assert_not_called()
    runner.stop()


def test_below_sma_and_owned_exit_use_option_not_underlying(broker, option_setup):
    runner, series = ready(broker, option_setup, entry_when="below_sma")
    assert runner._target([100, 99]) == 1 and runner._target([99, 100]) == 0
    assert runner._target([100, 100]) == 0
    # Seed an actual shared broker entry, not a synthetic runner position.
    with patch("pyibquant.trading.option_order.datetime") as clock:
        clock.now.return_value = T
        broker.submit_option_limit(option_setup[0], "BUY", 1, 3.45,
                                   quote=q_at(option_setup, T), tag=runner.run_id)
    broker._record("execution", dict(exec_id="buy", client_id=272, order_id=10,
        con_id=200, asset_type="OPT", currency="USD", multiplier="100", side="BOT",
        quantity="1", cumulative_quantity="1", price="3.45"))
    broker._record("fee", dict(exec_id="buy", commission="1", fee_currency="USD"))
    original = broker._adapter.refresh
    def refresh(account):
        original(account)
        broker.enqueue("position", dict(con_id=200, symbol="AAPL", quantity="1"))
        drain(broker)
    broker._adapter.refresh = refresh
    broker.refresh()
    broker._adapter.allocate_id.return_value = 11
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    with patch("pyibquant.trading.option_order.datetime") as clock:
        clock.now.return_value = at
        assert runner.step(series, q_at(option_setup, at), at=at) == 11
    assert broker.snapshot().orders[-1]["side"] == "SELL"
    assert broker.snapshot().orders[-1]["con_id"] == 200
    runner.stop()


def test_option_partial_fill_prevents_repeated_target_order(broker, option_setup):
    runner, series = ready(broker, option_setup)
    at = advance(series)
    broker._record("pnl", dict(daily="0"), at.isoformat())
    with patch("pyibquant.trading.option_order.datetime") as clock:
        clock.now.return_value = at
        runner.step(series, q_at(option_setup, at), at=at)
    broker._record("order_status", dict(client_id=272, order_id=10, status="Submitted",
                                       filled=".5", remaining=".5"))
    at += timedelta(minutes=1)
    series.update(Bar(T + timedelta(minutes=2), 102, 102, 102, 102, 1))
    series.last_live_update = at
    broker._record("pnl", dict(daily="0"), at.isoformat())
    runner.step(series, q_at(option_setup, at), at=at)
    broker._adapter.send_order.assert_called_once()
    runner.stop()


def test_owned_flatten_uses_option_premium_and_exact_contract(broker, option_setup):
    runner, series = ready(broker, option_setup)
    with patch("pyibquant.trading.option_order.datetime") as clock:
        clock.now.return_value = T
        broker.submit_option_limit(option_setup[0], "BUY", 1, 3.45,
                                   quote=q_at(option_setup, T), tag=runner.run_id)
    broker._record("execution", dict(exec_id="buy", client_id=272, order_id=10,
        con_id=200, asset_type="OPT", currency="USD", multiplier="100", side="BOT",
        quantity="1", cumulative_quantity="1", price="3.45"))
    broker._record("fee", dict(exec_id="buy", commission="1", fee_currency="USD"))
    original = broker._adapter.refresh
    def refresh(account):
        original(account)
        broker.enqueue("position", dict(con_id=200, symbol="AAPL", quantity="1"))
        drain(broker)
    broker._adapter.refresh = refresh
    broker._adapter.allocate_id.return_value = 11
    with patch("pyibquant.trading.option_order.datetime") as clock:
        clock.now.return_value = T
        oid = runner.flatten(series, q_at(option_setup, T), at=T)
    assert oid == 11 and runner.status == "paused"
    assert broker.snapshot().orders[-1]["con_id"] == 200
    assert broker.snapshot().orders[-1]["side"] == "SELL"
    runner.stop()


@pytest.mark.parametrize("field,value", [("multiplier", None), ("instrument_id", True),
                                         ("rules", [["0", "NaN"]])])
def test_corrupt_option_checkpoint_cannot_restore_execution(broker, option_setup, field, value):
    runner, _ = ready(broker, option_setup)
    runner.stop()
    checkpoint = [e["payload"] for e in broker.journal.events()
                  if e["kind"] == "runner_checkpoint"][-1]
    checkpoint["execution"][field] = value
    broker._record("runner_checkpoint", checkpoint)
    with pytest.raises(BrokerError):
        EquityRunner.restore(broker, runner.run_id)


def test_paper_option_grid_is_persisted_and_respects_broker_ticks(broker, option_setup):
    runner, _ = ready(broker, option_setup)
    q = replace(q_at(option_setup, T), ask=3.42, bid=3.39)
    assert runner._limit_price(q, "BUY") == Decimal("3.45")
    assert runner._limit_price(q, "SELL") == Decimal("3.35")
    runner.stop()
    restored = EquityRunner.restore(broker, runner.run_id)
    assert restored.premium_grid == Decimal(".05")


def test_tiny_option_exit_price_cannot_send_zero(broker, option_setup):
    runner, _ = ready(broker, option_setup)
    with pytest.raises(BrokerError, match="execution grid"):
        runner._limit_price(replace(q_at(option_setup, T), bid=.02), "SELL")
    broker._adapter.send_order.assert_not_called()
    runner.stop()

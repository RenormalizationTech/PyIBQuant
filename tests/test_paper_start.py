"""The owner's starting-position close is separate from algorithmic ownership."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_broker import broker as broker
from test_paper_runner import T, feed, preserve_position_refresh, quote

from pyibquant import BrokerError

spec = importlib.util.spec_from_file_location(
    "paper_strategy_example", Path(__file__).resolve().parents[1] / "examples/paper_strategy.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def test_starting_close_preflight_never_submits(broker):
    preserve_position_refresh(broker, "1")
    # Add identity metadata to the adapter's position download.
    original = broker._adapter.refresh

    def refresh(account):
        original(account)
        broker.enqueue(
            "position",
            dict(con_id=100, symbol="AAPL", quantity="1", asset_type="STK", currency="USD"),
        )
        broker._queue.join()

    broker._adapter.refresh = refresh
    plan = example.close_starting_share(broker, feed(), quote(), at=T)
    assert plan["mode"] == "read-only preflight" and plan["quantity"] == 1
    broker._adapter.send_order.assert_not_called()


@pytest.mark.parametrize("quantity", ["2", "-1", None])
def test_starting_close_refuses_unexpected_position_size(broker, quantity):
    preserve_position_refresh(broker, quantity)
    with pytest.raises(BrokerError, match="exactly one"):
        example.close_starting_share(broker, feed(), quote(), execute=True, at=T)
    broker._adapter.send_order.assert_not_called()


def test_starting_close_requires_confirmed_fill_and_flat_account(broker):
    snapshot = broker.snapshot()
    from dataclasses import replace
    from types import MappingProxyType

    position = MappingProxyType(
        dict(con_id=100, symbol="AAPL", quantity="1", asset_type="STK", currency="USD")
    )
    broker.reconcile = Mock(
        return_value=type(
            "Recovery", (), {"clear": True, "snapshot": replace(snapshot, positions=(position,))}
        )()
    )
    broker.submit_limit = Mock(return_value=55)
    broker.wait_order = Mock(return_value=dict(status="Cancelled", filled="0"))
    broker.refresh = Mock(return_value=snapshot)
    with pytest.raises(BrokerError, match="fully fill"):
        example.close_starting_share(broker, feed(), quote(), execute=True, at=T)
    broker.refresh.assert_not_called()
    broker.wait_order.return_value = dict(status="Filled", filled="1")
    result = example.close_starting_share(broker, feed(), quote(), execute=True, at=T)
    assert result["status"] == "Filled"
    assert broker.submit_limit.call_args.kwargs["tag"] == "owner-authorized-starting-close"
    broker.refresh.return_value = replace(snapshot, positions=(position,))
    with pytest.raises(BrokerError, match="not flat"):
        example.close_starting_share(broker, feed(), quote(), execute=True, at=T)

"""Read-only regression for quiet zero-P&L accounts; no order methods are usable."""

from datetime import UTC, datetime
from time import monotonic
from unittest.mock import Mock

from pyibquant import PaperBroker


def main():
    with PaperBroker.ibkr(client_id=289, journal="charts/paper/flat-risk-check.sqlite3") as broker:
        adapter = broker._adapter
        for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
            setattr(adapter, name, Mock(side_effect=AssertionError("Read-only risk check")))
        baseline = broker.refresh_pnl(renew=False)
        assert broker._pnl_reference is not None, "This regression requires a flat USD account"
        adapter.request_pnl = Mock(wraps=adapter.request_pnl)
        for cycle in range(2):
            deadline = monotonic() + 20
            while monotonic() < deadline:
                snapshot = broker.snapshot()
                broker.wait_for_update(
                    snapshot.sequence, timeout=max(0, min(0.5, deadline - monotonic()))
                )
            result = broker.refresh_risk()
            assert result.complete and result.pnl["daily"] == baseline.pnl["daily"]
            if result.pnl.get("risk_source") == "flat_account_reconciliation":
                assert result.pnl["received_at"] == baseline.pnl["received_at"]
                stamp = result.pnl["risk_confirmed_at"]
            else:
                stamp = result.pnl["received_at"]
            assert 0 <= (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds() < 15
            print(
                f"Cycle {cycle + 1}: fresh flat-account risk confirmation; baseline unchanged",
                flush=True,
            )
        adapter.request_pnl.assert_not_called()
        for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
            getattr(adapter, name).assert_not_called()
        print(
            "PASS: quiet-account risk checks, no P&L renewal loop, zero broker orders", flush=True
        )


if __name__ == "__main__":
    main()

"""Read-only quiet-account P&L renewal check; every order method is disabled."""

from datetime import UTC, datetime
from time import monotonic
from unittest.mock import Mock

from pyibquant import PaperBroker


def main():
    with PaperBroker.ibkr(
        client_id=287, journal="charts/paper/pnl-refresh-check.sqlite3"
    ) as broker:
        adapter = broker._adapter
        for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
            setattr(adapter, name, Mock(side_effect=AssertionError("Read-only P&L check")))
        for cycle in range(2):
            deadline = monotonic() + 20
            while monotonic() < deadline:
                snapshot = broker.snapshot()
                broker.wait_for_update(snapshot.sequence, timeout=min(0.5, deadline - monotonic()))
            old = broker.snapshot().pnl
            snapshot = broker.refresh_pnl(timeout=5)
            assert snapshot.complete
            assert snapshot.pnl["validated"] is True
            assert snapshot.pnl["request_id"] != old.get("request_id")
            stamp = datetime.fromisoformat(snapshot.pnl["received_at"])
            assert 0 <= (datetime.now(UTC) - stamp).total_seconds() < 5
            print(
                f"Cycle {cycle + 1}: renewed P&L after 20 seconds, new generation, fresh value",
                flush=True,
            )
        for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
            getattr(adapter, name).assert_not_called()
        print("PASS: quiet-account P&L renewal, zero order submissions/cancellations", flush=True)


if __name__ == "__main__":
    main()

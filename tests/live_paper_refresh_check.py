"""Read-only regression for rapid account refreshes; order transmission is disabled."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import Mock

from pyibquant import PaperBroker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account")
    parser.add_argument("--client-id", type=int, default=283)
    parser.add_argument("--journal", type=Path, default=Path("charts/paper/refresh-check.sqlite3"))
    args = parser.parse_args()
    with PaperBroker.ibkr(
        account=args.account, readonly=True, client_id=args.client_id, journal=args.journal
    ) as broker:
        adapter = broker._adapter
        adapter.send_order = Mock(side_effect=AssertionError("Read-only check cannot send orders"))
        adapter.placeOrder = Mock(side_effect=AssertionError("Read-only check cannot send orders"))
        adapter.reqAccountSummary = Mock(wraps=adapter.reqAccountSummary)
        adapter.cancelAccountSummary = Mock(wraps=adapter.cancelAccountSummary)
        summary_id = adapter._summary_id
        for index in range(5):
            snapshot = broker.refresh()
            assert snapshot.complete
            assert adapter._summary_id == summary_id
            assert snapshot.value("NetLiquidation", "USD") is not None
            assert broker.funding()["usable"] is not None
            print(
                f"Refresh {index + 1}: ready, {len(snapshot.positions)} positions, "
                "USD cash budget available",
                flush=True,
            )
        adapter.reqAccountSummary.assert_not_called()
        adapter.cancelAccountSummary.assert_not_called()
        adapter.send_order.assert_not_called()
        adapter.placeOrder.assert_not_called()
        recovery = broker.reconcile()
        assert recovery.snapshot.complete
        print(
            f"Reconciliation: {len(recovery.working_orders)} tracked working orders, "
            f"{len(recovery.missing_orders)} missing, {len(recovery.foreign_orders)} foreign"
        )
        adapter.send_order.assert_not_called()
        adapter.placeOrder.assert_not_called()
        broker.report("charts/paper/refresh-check.html")
        print("PASS: five rapid read-only refreshes, one persistent summary, zero orders")


if __name__ == "__main__":
    main()

"""Read-only completed-order coverage probe; never resolves journal intents.

Captures the selected account's broker-returned completed orders and completion
barrier. Availability is limited to TWS coverage, not a full historical statement.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock

from pyibquant import PaperBroker
from pyibquant.trading.ibkr import instrument, number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = dict(
        started_at=datetime.now(UTC).isoformat(),
        passed=False,
        order_transmission=False,
        coverage="Only records returned by this TWS session; absence proves no terminal state",
        orders=[],
    )
    done, lock = Event(), Lock()
    try:
        with PaperBroker.ibkr(
            client_id=307, readonly=True, journal=args.output / "account.sqlite3"
        ) as broker:
            adapter = broker._adapter
            names = ("send_order", "placeOrder", "cancel_order", "cancelOrder")
            for name in names:
                setattr(adapter, name, Mock(side_effect=AssertionError("Read-only coverage probe")))

            def completed(contract, order, state):
                if order.account != broker.account:
                    return
                row = dict(
                    **instrument(contract),
                    order_id=order.orderId,
                    client_id=order.clientId,
                    perm_id=order.permId,
                    order_ref=order.orderRef,
                    side=order.action,
                    quantity=number(order.totalQuantity),
                    filled=number(order.filledQuantity),
                    order_type=order.orderType,
                    status=state.status,
                    completed_time=state.completedTime,
                    completed_status=state.completedStatus,
                )
                with lock:
                    result["orders"].append(row)

            adapter.completedOrder = completed
            adapter.completedOrdersEnd = done.set
            adapter.reqCompletedOrders(False)
            assert done.wait(20), "Completed-order download did not reach completion barrier"
            for name in names:
                getattr(adapter, name).assert_not_called()
            with lock:
                result["passed"] = True
                result["completion_barrier"] = True
                print(
                    f"PASS: completed-order barrier, {len(result['orders'])} selected-account "
                    "records, zero submissions/cancellations; historical coverage remains limited",
                    flush=True,
                )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        with lock:
            result["finished_at"] = datetime.now(UTC).isoformat()
            target = args.output / "completed-orders.json"
            target.write_text(json.dumps(result, indent=2), encoding="utf-8")
            target.chmod(0o600)


if __name__ == "__main__":
    main()

"""Read-only recovery from a reconstructed lost cancellation callback.

Copies journal events into a new evidence directory, omitting only terminal
callbacks for one already canceled, unfilled order. Never edits the source journal,
submits an order or cancels an order. This tests real completed-order downloads,
not an actual broker disconnect while an order is working.
"""

import argparse
import json
from pathlib import Path
from unittest.mock import Mock

from pyibquant import PaperBroker
from pyibquant.broker import money
from pyibquant.trading.ibkr import BrokerAdapter
from pyibquant.trading.journal import Journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("charts/paper/strategy.sqlite3"))
    parser.add_argument("--client-id", type=int, default=297)
    parser.add_argument("--order-id", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = Journal(args.source, readonly=True)
    try:
        events = source.events()
    finally:
        source.close()
    accounts = {e["account"] for e in events}
    assert len(accounts) == 1, "Source must contain exactly one selected account"
    account = next(iter(accounts))

    def selected(p):
        return p.get("client_id") == args.client_id and p.get("order_id") == args.order_id

    order_events = [
        e for e in events
        if e["kind"] in {"intent", "order", "order_status"} and selected(e["payload"])
    ]
    assert order_events, "Exact source order not found"
    assert any(
        e["payload"].get("status") in {"Cancelled", "ApiCancelled"}
        and money(e["payload"].get("filled")) == 0 for e in order_events
    ), "Source must prove an unfilled canceled order"
    assert not any(
        e["kind"] == "execution" and selected(e["payload"]) for e in events
    ), "This check requires an order with no executions"
    target = Journal(args.output / "reconstructed.sqlite3")
    removed = 0
    try:
        for e in events:
            if selected(e["payload"]) and e["kind"] in {"order", "order_status"} and (
                e["payload"].get("status") in {"Cancelled", "ApiCancelled", "Filled"}
            ):
                removed += 1
                continue
            target.append(e["session"], account, e["received_at"], e["kind"], e["payload"])
    finally:
        target.close()
    adapter = BrokerAdapter("127.0.0.1", 7497, args.client_id, 20)
    names = ("send_order", "placeOrder", "cancel_order", "cancelOrder")
    for name in names:
        setattr(adapter, name, Mock(side_effect=AssertionError("Read-only reconstructed recovery")))
    try:
        assert account in adapter.open(), "Source account is not managed by this paper session"
        with PaperBroker(adapter, args.output / "reconstructed.sqlite3", account=account) as broker:
            before = next(o for o in broker.snapshot().orders if selected(o))
            assert before["status"] not in {"Cancelled", "ApiCancelled", "Filled"}
            adapter.subscribe(account)
            broker.wait_ready(20)
            report = broker.reconcile()
            after = next(o for o in report.snapshot.orders if selected(o))
            assert report.completed_orders_checked and report.clear
            assert after["status"] in {"Cancelled", "ApiCancelled"}
            assert after["recovery_source"] == "completed_orders" and money(after["filled"]) == 0
            assert not broker.funding()["pending_owned_order"]
            for name in names:
                getattr(adapter, name).assert_not_called()
            result = dict(
                passed=True, scenario="Reconstructed missing terminal callbacks; real API download",
                source_last_sequence=events[-1]["sequence"], removed_terminal_events=removed,
                before_status=before["status"], after_status=after["status"],
                completed_orders_checked=True, pending_owned_order=False,
                order_submissions=0, order_cancellations=0,
            )
            (args.output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result), flush=True)
    finally:
        adapter.close()


if __name__ == "__main__":
    main()

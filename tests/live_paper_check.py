"""Read-only paper-account acquisition check; no execution switch is provided.

Use examples/paper_strategy.py and examples/paper_cancel_check.py for the separate
human-run execution workflows. The former combined cancellation/round-trip path
was superseded; --orders is deliberately no longer accepted here.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import Mock

from pyibquant import PaperBroker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=Path("charts/paper/integration.sqlite3"))
    args = parser.parse_args()
    with PaperBroker.ibkr(journal=args.journal, readonly=True, client_id=274) as broker:
        for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
            setattr(broker._adapter, name, Mock(side_effect=AssertionError("Read-only check")))
        report = broker.reconcile()
        assert report.snapshot.complete
        broker.report("charts/paper/integration.html")
        for name in ("send_order", "placeOrder", "cancel_order", "cancelOrder"):
            getattr(broker._adapter, name).assert_not_called()
        print(
            f"PASS: read-only account download; {len(report.working_orders)} tracked working, "
            f"{len(report.missing_orders)} missing, {len(report.foreign_orders)} foreign orders; "
            "zero broker submissions/cancellations"
        )


if __name__ == "__main__":
    main()

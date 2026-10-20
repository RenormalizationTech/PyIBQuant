"""Read-only API account observer with persistent history and a local performance view."""

from __future__ import annotations

import argparse
from pathlib import Path
from time import monotonic

from pyibquant import PaperBroker
from pyibquant.trading.performance import serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="Select explicitly when multiple accounts are visible")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=272)
    parser.add_argument("--journal", type=Path, default=Path("charts/paper/account.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("charts/paper/account.html"))
    parser.add_argument("--web-port", type=int, default=0)
    parser.add_argument("--snapshot", action="store_true", help="Write a report and exit")
    args = parser.parse_args()
    with PaperBroker.ibkr(
        account=args.account,
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        journal=args.journal,
    ) as broker:
        print(f"Account {broker.snapshot().to_dict()['account']}: synchronized (read-only)")
        # P&L arrives independently of initial account-download completion.
        deadline = monotonic() + 5
        snapshot = broker.snapshot()
        while not snapshot.pnl and monotonic() < deadline:
            snapshot = broker.wait_for_update(snapshot.sequence, timeout=0.25)
        print(broker.report(args.report))
        if args.snapshot:
            return
        server = serve(broker, args.web_port)
        print(f"Performance view: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            broker.report(args.report)


if __name__ == "__main__":
    main()

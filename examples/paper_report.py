"""Build account and per-run HTML/CSV reports offline from an existing journal."""

import argparse
from pathlib import Path

from pyibquant.trading.offline import load_account
from pyibquant.trading.performance import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=Path("charts/paper/strategy.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("charts/paper/strategy.html"))
    parser.add_argument("--account")
    args = parser.parse_args()
    events, snapshot = load_account(args.journal, account=args.account)
    print(write_report(events, snapshot, args.output))


if __name__ == "__main__":
    main()

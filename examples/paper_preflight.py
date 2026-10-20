"""Validate a saved paper profile, optionally checking the read-only account API."""

import argparse
import json
from pathlib import Path

from pyibquant.trading.preflight import check_profile
from pyibquant.trading.profile import PaperProfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("paper_aapl.json"))
    parser.add_argument(
        "--connect", action="store_true", help="Read-only API checks; never places/cancels orders"
    )
    parser.add_argument("--output", type=Path, default=Path("charts/paper/preflight.json"))
    args = parser.parse_args()
    try:
        report = check_profile(PaperProfile.load(args.profile), connect=args.connect)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.output.chmod(0o600)
    for check in report["checks"]:
        print(f"{check['status'].upper()}: {check['name']} — {check['detail']}")
    print(f"Saved {args.output}. Order transmission disabled; runtime checks remain required.")
    raise SystemExit(0 if report["local_ready"] else 1)


if __name__ == "__main__":
    main()

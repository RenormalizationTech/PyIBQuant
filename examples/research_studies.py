"""Dependency-free study starters on saved IBKR collections; never connects itself.

Acquire daily/intraday inputs with research_collection.py fetch first. Reports
retain source fingerprints/quality evidence. No fitted scaling model is supplied.
"""

import argparse
import json
from pathlib import Path

from pyibquant import BarDatasetCollection
from pyibquant.studies import daily_correlations, intraday_scaling


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', choices=['correlations', 'scaling'])
    parser.add_argument('collection', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--instrument', help='Required collection label for scaling')
    parser.add_argument('--lags', nargs='+', type=int, default=[1, 2, 4, 8])
    parser.add_argument('--session-timezone', help='Override the recorded timezone explicitly')
    args = parser.parse_args()
    if args.output.expanduser().resolve() == args.collection.expanduser().resolve():
        parser.error('--output must differ from the input collection')
    inputs = BarDatasetCollection.load(args.collection)
    if args.study == 'correlations':
        if args.instrument or args.session_timezone or args.lags != [1, 2, 4, 8]:
            parser.error('--instrument, --lags and --session-timezone apply to scaling only')
        report = daily_correlations(inputs)
    else:
        if args.instrument not in inputs:
            parser.error('--instrument must name a label in the saved collection')
        report = intraday_scaling(inputs[args.instrument], lags=args.lags,
                                  session_timezone=args.session_timezone)
        report['collection_fingerprint'] = inputs.fingerprint()
        report['instrument_label'] = args.instrument
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Saved {args.study} inputs and descriptive results to {target}')


if __name__ == '__main__':
    main()

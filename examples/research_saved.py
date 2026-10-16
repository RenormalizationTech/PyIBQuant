"""Recompute research signals from a frozen dataset without IBKR/pandas/a chart.

Optional --calendar supplies one expected ISO bar-start timestamp per line, for
exactly this dataset's query and hours. Obtain these from your chosen exchange
calendar; weekends/holidays and early closes are never guessed. --finalized-through
is your assertion that bars starting at/before that timestamp are complete.
"""

import argparse
from datetime import date, datetime
from pathlib import Path

from pyibquant import BarDataset
from pyibquant.research import simple_returns, sma


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--calendar', type=Path)
    parser.add_argument('--finalized-through')
    args = parser.parse_args()
    if args.window <= 0:
        parser.error('--window must be positive')
    if args.finalized_through and not args.calendar:
        parser.error('--finalized-through requires --calendar')
    dataset = BarDataset.load(args.dataset)
    if dataset.metadata()['download']['complete'] is False:
        raise SystemExit('Dataset download is incomplete; refusing to analyze partial inputs.')
    if args.calendar:
        parse = date.fromisoformat if dataset.metadata()['timestamp_kind'] == 'date' \
            else datetime.fromisoformat
        expected = [parse(line.strip()) for line in args.calendar.read_text().splitlines()
                    if line.strip()]
        audit = dataset.audit(expected, finalized_through=(parse(args.finalized_through)
                              if args.finalized_through else None))
        print(f'Calendar: {len(audit.missing)} missing, {len(audit.unexpected)} unexpected; '
              f'{len(audit.unconfirmed)} bars without caller confirmation of finality')
        if not audit.matches_calendar:
            raise SystemExit('Calendar mismatch; inspect the dataset before research.')
    closes = [bar.close for bar in dataset.snapshot()]
    returns, averages = simple_returns(closes), sma(closes, args.window)
    print(f'Loaded {len(dataset)} bars for {dataset.metadata()["symbol"]} without a broker')
    print(f'Last simple return: {returns[-1] if returns else None}; '
          f'last SMA({args.window}): {averages[-1] if averages else None}')


if __name__ == '__main__':
    main()

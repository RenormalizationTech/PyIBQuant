"""Export IBKR bars for Python research; no browser is needed.

Run after the manual IBKR setup. Install .[pandas] for the optional DataFrame step.
Exports go under the Git-ignored charts/ directory for this example.
"""

from pyibquant import Market


def main() -> None:
    with Market.ibkr() as market:
        # Research queries skip session-schedule requests by default.
        bars = market.bars('AAPL', interval='1d', duration='6 M')

    records = bars.to_records()
    target = bars.to_csv('charts/research/AAPL-1d.csv')
    print(f'Exported {len(records)} bars to {target}')

    # Optional pandas analysis; neither a chart nor an open connection is required.
    # frame = bars.to_dataframe()  # python -m pip install -e '.[pandas]'
    # returns = frame['close'].pct_change()
    # print(returns.tail())


if __name__ == '__main__':
    main()

"""Run after installing PyIBQuant and enabling the TWS API socket."""

from pyibquant import Market


def main() -> None:
    with Market.ibkr() as market:
        aapl = market.bars("AAPL", interval="1min", duration="1 D", include_sessions=True)
        aapl.plot()

    # For continuous bar updates instead:
    # with Market.ibkr() as market:
    #     aapl = market.bars("AAPL", interval="1min", duration="1 D", live=True)
    #     market.serve(aapl)


if __name__ == "__main__":
    main()

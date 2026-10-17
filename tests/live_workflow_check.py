"""Explicit data-only TWS -> saved inputs -> offline research/backtest regression.

Requires logged-in TWS and the manually installed SDK. Supply an available selected
option and a completed aligned range before expiry. No live subscriptions, orders,
account queries or settings changes. Generated data defaults to ignored charts/.
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from pyibquant import BarDatasetCollection, BarRequest, Market, Option
from pyibquant.backtest import backtest_equity
from pyibquant.option_backtest import backtest_option
from pyibquant.research import above_sma
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate
from pyibquant.studies import daily_correlations, intraday_scaling


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--client-id', type=int, default=196)
    parser.add_argument('--daily-symbols', nargs='+', default=['AAPL', 'MSFT', 'SPY'])
    parser.add_argument('--daily-start', default='2025-01-01')
    parser.add_argument('--daily-end', default='2026-01-01')
    parser.add_argument('--symbol', default='AAPL')
    parser.add_argument('--option-expiry', type=date.fromisoformat, required=True)
    parser.add_argument('--option-strike', type=float, required=True)
    parser.add_argument('--option-right', choices=['C', 'P'], default='C')
    parser.add_argument('--trading-class', required=True)
    parser.add_argument('--multiplier', type=float, required=True)
    parser.add_argument('--intraday-start', required=True)
    parser.add_argument('--intraday-end', required=True)
    parser.add_argument('--output-dir', type=Path, default=Path('charts/release-workflow-check'))
    args = parser.parse_args()
    option = Option(args.symbol, args.option_expiry, args.option_strike, args.option_right,
                    trading_class=args.trading_class, multiplier=args.multiplier)
    with Market.ibkr(args.host, args.port, args.client_id, reconnect=False) as market:
        daily = market.datasets({symbol: symbol for symbol in args.daily_symbols}, interval='1d',
                                start=args.daily_start, end=args.daily_end)
        mixed = market.datasets(
            {'underlying': args.symbol, 'option': BarRequest(option, 'MIDPOINT')},
                                interval='5min', start=args.intraday_start, end=args.intraday_end)
    root = args.output_dir.expanduser().resolve()
    # All remaining operations are offline, after the broker client has closed.
    daily = BarDatasetCollection.load(daily.save(root / 'daily.collection.json'))
    mixed = BarDatasetCollection.load(mixed.save(root / 'mixed.collection.json'))
    reports = dict(daily_quality=daily.quality_report(join='outer'),
                   mixed_quality=mixed.quality_report(join='outer'),
                   correlations=daily_correlations(daily),
                   scaling=intraday_scaling(mixed['underlying'], lags=(1, 2, 4),
                                            session_timezone='America/New_York'))
    assert reports['correlations']['correlation']['samples'] >= 2
    assert reports['scaling']['moments'][0]['samples'] >= 1
    assert all(bar.volume is None for bar in mixed['option'].snapshot())
    equity = next(iter(daily.values()))
    equity_signals = above_sma([bar.close for bar in equity.snapshot()], window=3)
    option_signals = above_sma([bar.close for bar in mixed['option'].snapshot()], window=3)
    equity_result = backtest_equity(equity, equity_signals,
                                    finalized_through=equity.snapshot()[-1].timestamp,
                                    commission=.1, slippage_bps=1)
    option_result = backtest_option(mixed['option'], option_signals,
                                    finalized_through=mixed['option'].snapshot()[-1].timestamp,
                                    fill_model='next_bar_open', commission_per_contract=.1,
                                    slippage_bps=1)
    finality = datetime.fromisoformat(args.intraday_end)
    strategy_result = simulate(
        {key: Feed(dataset, finality) for key, dataset in mixed.items()},
        TargetStrategy('option', lambda context: int(
            len(context.data['underlying'].bars) >= 3 and
            context.data['underlying'].bars[-1].close >
            context.data['underlying'].bars[-3].close), decision_feed='underlying'),
        execution=NextOpen(commission_per_unit=.1, slippage_bps=1),
        strategy_settings=dict(name='underlying_three_bar_direction'),
    )
    equity_result.save(root / 'equity-backtest.json')
    option_result.save(root / 'option-backtest.json')
    strategy_result.save(root / 'strategy-backtest.json')
    for name, report in reports.items():
        (root / f'{name}.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    # Exercise both equity and nullable-volume option HTML rendering offline.
    from pyibquant.bars import BarSeries
    for key, dataset in mixed.items():
        viewer = BarSeries(dataset.metadata()['symbol'], dataset.metadata()['interval'])
        for bar in dataset.snapshot():
            viewer.update(bar)
        viewer.plot(root / f'{key}.html', open_browser=False)
    print('PASS: fresh named equity/option acquisition; broker-free save/reload, quality, '
          'correlations, scaling, equity/option/strategy backtests and HTML generation')
    print(f'Artifacts: {root}')


if __name__ == '__main__':
    main()

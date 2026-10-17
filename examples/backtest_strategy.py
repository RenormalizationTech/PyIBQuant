"""Run an equity or underlying-driven option strategy from frozen inputs, offline.

The signal uses the first dataset's completed closes. Optionally trade a selected
option dataset instead. Both inputs must use the same daily/intraday clock kind;
intraday feeds may have different intervals and gaps. No broker requests occur.
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from pyibquant import BarDataset
from pyibquant.research import sma
from pyibquant.simulation import Context, Feed, NextOpen, TargetStrategy, simulate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('signal_dataset', type=Path)
    parser.add_argument('--option-dataset', type=Path)
    parser.add_argument('--finalized-through', required=True,
                        help='Daily ISO date or intraday aware ISO time covering bar completion')
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--quantity', type=int, default=2)
    parser.add_argument('--max-signal-age-minutes', type=float, default=0)
    parser.add_argument('--initial-cash', type=float, default=10000)
    parser.add_argument('--commission-per-unit', type=float, default=0)
    parser.add_argument('--slippage-bps', type=float, default=0)
    parser.add_argument('--output-dir', type=Path, default=Path('charts/strategy-backtest'))
    args = parser.parse_args()
    if args.window < 1 or args.quantity < 1:
        parser.error('window and quantity must be positive')
    try:
        max_age = timedelta(minutes=args.max_signal_age_minutes)
        if max_age < timedelta(0):
            raise ValueError('max-signal-age-minutes must be nonnegative')
        signal = BarDataset.load(args.signal_dataset)
        daily = signal.metadata()['timestamp_kind'] == 'date'
        final = (date.fromisoformat(args.finalized_through) if daily
                 else datetime.fromisoformat(args.finalized_through))
        inputs = {'signal': signal}
        traded = 'signal'
        if args.option_dataset is not None:
            option = BarDataset.load(args.option_dataset)
            if option.metadata().get('asset_type') != 'option':
                raise ValueError('--option-dataset must contain an option')
            inputs['option'] = option
            traded = 'option'

        def target(context: Context) -> int:
            view = context.data['signal']
            # Missing/stale signal data exits at the next supplied traded open.
            if view.age is None or view.age > max_age or len(view.bars) < args.window:
                return 0
            closes = [bar.close for bar in view.bars]
            average = sma(closes, args.window)[-1]
            assert average is not None
            return args.quantity if closes[-1] > average else 0

        settings = dict(name='underlying_above_sma' if traded == 'option' else 'above_sma',
                        window=args.window, quantity=args.quantity,
                        max_signal_age_minutes=args.max_signal_age_minutes)
        result = simulate(
            {key: Feed(dataset, final) for key, dataset in inputs.items()},
            TargetStrategy(traded, target, decision_feed='signal'), initial_cash=args.initial_cash,
            execution=NextOpen(commission_per_unit=args.commission_per_unit,
                               slippage_bps=args.slippage_bps), strategy_settings=settings,
        )
        target_path = result.save(args.output_dir/'results.json')
        for key, dataset in inputs.items():
            dataset.save(target_path.with_name(f'{key}.dataset.json'))
    except (ValueError, OSError, OverflowError) as exc:
        parser.error(str(exc))
    print(json.dumps(result.metrics(), indent=2))
    print(f'Saved frozen inputs, settings, order/fill logs and positions to {target_path.parent}')


if __name__ == '__main__':
    main()

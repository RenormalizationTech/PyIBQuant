"""SDK-free quote model/serialization checks for the optional broker boundary."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pyibquant import Option
from pyibquant.quotes import QuoteInstrument, _QuoteState


def state():
    instrument = QuoteInstrument('DEMO', 123, 'equity', 'USD', 'SMART', 'NASDAQ',
                                 'DEMO', 'DEMO', 1, None, None, None)
    return _QuoteState(instrument, 'live')


def test_snapshot_is_independent_of_mutable_callback_state_and_preserves_zero_size():
    pending = state()
    pending.tick(1, 100)
    pending.tick(2, 102)
    pending.tick(0, Decimal(0), size=True)
    pending.tick(3, Decimal('NaN'), size=True)
    pending.completed_at = datetime.now(UTC)
    quote = pending.snapshot()
    assert quote.bid_size == 0 and quote.ask_size is None
    pending.values['bid'] = 10
    pending.warnings.append('later')
    assert quote.bid == 100 and not any('later' in text for text in quote.warnings)
    assert quote.to_dict()['field_tick_types']['bid'] == 1
    assert quote.to_dict()['field_received_at']['bid'].endswith('+00:00')


def test_conflicting_delayed_ticks_are_flagged_even_with_reported_live_type():
    pending = state()
    pending.actual_type = 'live'
    pending.tick(66, 100)
    pending.tick(67, 102)
    pending.completed_at = datetime.now(UTC)
    quote = pending.snapshot()
    assert quote.is_delayed
    assert any('do not treat this snapshot as live' in warning for warning in quote.warnings)


@pytest.mark.parametrize('config', [
    {'symbol': ''}, {'expiry': datetime(2026, 11, 20)}, {'strike': 0}, {'strike': float('nan')},
    {'right': 'call'}, {'multiplier': 0},
])
def test_invalid_option_selectors_rejected(config):
    values = dict(symbol='AAPL', expiry=date(2026, 11, 20), strike=100, right='C')
    with pytest.raises(ValueError):
        Option(**(values | config))


@pytest.mark.parametrize('option', [False, True])
def test_quote_example_keeps_snapshot_available_after_context_exit(tmp_path, monkeypatch, option):
    import json
    import runpy
    from pathlib import Path
    from unittest.mock import MagicMock, Mock

    pending = state()
    pending.actual_type = 'live'
    pending.tick(1, 100)
    pending.tick(2, 102)
    pending.completed_at = datetime.now(UTC)
    market = MagicMock()
    market.__enter__.return_value = market
    market.quote.return_value = pending.snapshot()
    monkeypatch.setattr('pyibquant.Market.ibkr', Mock(return_value=market))
    target = tmp_path / 'quote.json'
    args = ['quote_snapshot', 'DEMO', '--output', str(target)]
    if option:
        args.extend(['--expiry', '2026-11-20', '--strike', '100', '--right', 'C'])
    monkeypatch.setattr('sys.argv', args)
    script = Path(__file__).resolve().parents[1] / 'examples' / 'quote_snapshot.py'
    runpy.run_path(str(script), run_name='__main__')
    selector = market.quote.call_args.args[0]
    assert isinstance(selector, Option) if option else selector == 'DEMO'
    saved = json.loads(target.read_text())
    assert saved['bid'] == 100 and saved['spread'] == 2
    market.__exit__.assert_called_once()


@pytest.mark.parametrize('value', [Decimal(2**127 - 1), float(2**127 - 1)])
def test_sdk_unset_decimal_size_is_missing_not_an_enormous_bid_size(value):
    pending = state()
    pending.tick(0, value, size=True)
    pending.tick(3, value, size=True)
    pending.completed_at = datetime.now(UTC)
    quote = pending.snapshot()
    assert quote.bid_size is None and quote.ask_size is None
    assert quote.to_dict()['bid_size'] is None

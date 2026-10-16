import csv
import json
import runpy
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from pyibquant import Bar, BarSeries, HistoricalRangeError
from pyibquant.research import simple_returns, sma


def test_returns_preserve_alignment_and_zero_denominators_are_explicit():
    result = simple_returns([100, 110, 99, 0, 100])
    assert result[0] is None and result[-1] is None
    assert result[1:4] == pytest.approx((0.1, -0.1, -1.0))
    assert simple_returns([]) == ()


def test_sma_has_full_window_warmup_and_uses_only_trailing_values():
    assert sma([1, 2, 3, 4, 5], 3) == (None, None, 2, 3, 4)
    assert sma([1, 2, 3], 1) == (1, 2, 3)
    assert sma([1, 2], 3) == (None, None)
    assert sma([], 2) == ()
    assert sma(iter([1, 2, 3]), 2) == (None, 1.5, 2.5)


@pytest.mark.parametrize('window', [0, -1, 1.5, True])
def test_invalid_window_rejected(window):
    with pytest.raises(ValueError, match='positive integer'):
        sma([1, 2, 3], window)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_research_inputs_rejected(value):
    with pytest.raises(ValueError, match='finite'):
        simple_returns([1, value])
    with pytest.raises(ValueError, match='finite'):
        sma([1, value])


@pytest.mark.parametrize('failed', [False, True])
def test_research_example_exports_complete_inputs_and_does_not_analyze_failure(
    monkeypatch, tmp_path, failed
):
    series = BarSeries('DEMO', '1d')
    series.provider = 'synthetic'
    series.requested_start, series.requested_end = date(2026, 1, 1), date(2026, 1, 4)
    series.download_complete = not failed
    for day, close in [(1, 100), (2, 110), (3, 120)]:
        series.update(Bar(date(2026, 1, day), 100, 120, 90, close, 50))
    market = MagicMock()
    market.__enter__.return_value = market
    market.bars.return_value = series
    if failed:
        market.bars.side_effect = HistoricalRangeError(
            'failed page', series, remaining_start=date(2026, 1, 1),
            remaining_end=date(2026, 1, 2))
    monkeypatch.setattr('pyibquant.Market.ibkr', Mock(return_value=market))
    monkeypatch.setattr('sys.argv', ['research_range', 'DEMO', '--start', '2026-01-01',
        '--end', '2026-01-04', '--window', '2', '--output-dir', str(tmp_path)])
    script = Path(__file__).resolve().parents[1] / 'examples' / 'research_range.py'
    if failed:
        with pytest.raises(SystemExit, match='No research outputs written'):
            runpy.run_path(str(script), run_name='__main__')
        assert not list(tmp_path.iterdir())
        return
    runpy.run_path(str(script), run_name='__main__')
    with (tmp_path / 'signals.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]['sma'] == '' and rows[0]['above_sma'] == ''
    assert rows[1]['sma'] == '105.0' and rows[1]['above_sma'] == '1'
    assert len(rows) == 3 and (tmp_path / 'bars.csv').is_file()
    meta = json.loads((tmp_path / 'bars.metadata.json').read_text())
    assert meta['download']['complete'] is True
    assert meta['query']['start'] == '2026-01-01'


def test_return_overflow_is_reported_instead_of_emitting_infinity():
    with pytest.raises(ValueError, match='overflowed'):
        simple_returns([1e-308, 1e308])

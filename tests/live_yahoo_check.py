"""Explicit Yahoo integration check; needs .[yahoo] and internet, never uses TWS.

Run: .venv/bin/python tests/live_yahoo_check.py --browser
Browser verification additionally requires .[browser] and installed Google Chrome.
Generated charts, normalized inputs, screenshots and a report stay under charts/.
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from math import isclose
from pathlib import Path

import yfinance as yf

from pyibquant import BarDataset
from pyibquant.data.providers.yahoo import preview_bars
from pyibquant.errors import DataError


def command(*arguments):
    return subprocess.run(
        [sys.executable, '-m', 'pyibquant', *arguments],
        capture_output=True, text=True, timeout=90,
    )


def check_browser(path, rows, output):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 960})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', lambda route: route.abort()
                       if route.request.url.startswith(('http:', 'https:')) else route.continue_())
            page.goto(path.as_uri())
            page.wait_for_function('chart.bars.length > 0 && chart.frame === null')
            assert page.evaluate('chart.bars.length') == rows
            assert 'Yahoo Finance · Preview' in page.locator('#meta').inner_text()
            assert 'split/dividend adjusted' in page.locator('#error').inner_text()
            assert page.locator('#symbol-input').is_disabled()
            assert page.evaluate('controlsEnabled === false && historyEnabled === false')
            page.locator('#fit').click()
            page.wait_for_function('chart.frame === null')
            page.locator('canvas').focus()
            before = page.evaluate('chart.count')
            page.keyboard.press('+')
            page.wait_for_function('chart.frame === null')
            assert page.evaluate('chart.count') < before
            page.locator('#autoscale').click()
            assert page.locator('#autoscale').get_attribute('aria-pressed') == 'false'
            page.locator('#autoscale').click()
            page.set_viewport_size({'width': 1000, 'height': 800})
            page.wait_for_function('chart.width === 1000 && chart.frame === null')
            page.set_viewport_size({'width': 1440, 'height': 960})
            page.wait_for_function('chart.width === 1440 && chart.frame === null')
            page.locator('#fit').click()
            page.wait_for_function('chart.frame === null')
            page.screenshot(path=str(output / 'SPY-preview.png'), full_page=True)
            assert not errors, errors
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=Path('charts/yahoo-validation'))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'yfinance': yf.__version__, 'datasets': [], 'checks': []}
    spy_rows = 0
    for symbol, duration, minimum in [('AAPL', '1 Y', 150), ('SPY', '6 M', 60), ('MSFT', '2 W', 5)]:
        series = preview_bars(symbol, duration=duration, timeout=20)
        bars = series.snapshot()
        assert len(bars) >= minimum, (symbol, len(bars))
        dates = [bar.timestamp for bar in bars]
        assert all(type(stamp) is date for stamp in dates)
        assert dates == sorted(set(dates))
        assert all(series.requested_start <= stamp < series.requested_end for stamp in dates)
        assert all(bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
                   for bar in bars)
        assert all(bar.volume is None or bar.volume >= 0 for bar in bars)
        dataset = BarDataset.from_series(series)
        path = dataset.save(output / f'{symbol}.dataset.json')
        assert BarDataset.load(path).fingerprint() == dataset.fingerprint()
        series.to_csv(output / f'{symbol}.csv')
        series.plot(output / f'{symbol}.html', open_browser=False)
        metadata = series.metadata()
        assert metadata['adjustment'] == 'splits_and_dividends'
        assert metadata['download']['complete'] is None
        report['datasets'].append(dict(symbol=symbol, rows=len(bars), first=str(dates[0]),
                                       last=str(dates[-1]), duration=duration))
        if symbol == 'SPY':
            spy_rows = len(bars)
            raw = yf.Ticker(symbol).history(
                start=series.requested_start.isoformat(), end=series.requested_end.isoformat(),
                interval='1d', auto_adjust=True, actions=False, repair=False, timeout=20,
            )
            expected = {stamp.date(): row for stamp, row in raw.iterrows()}
            assert set(expected) == set(dates)
            # Exclude today's mutable session from numerical equality assertions.
            for bar in bars[:-1]:
                for field in ('open', 'high', 'low', 'close', 'volume'):
                    value = float(expected[bar.timestamp][field.title()])
                    assert isclose(getattr(bar, field), value, rel_tol=1e-9), (bar.timestamp, field)
    report['checks'].append('three live symbols, OHLCV mapping, dates, CSV and dataset roundtrip')

    for symbol, expected_error in [('SAP.DE', 'USD only'), ('PYIBQUANT_INVALID_SYMBOL_123', None)]:
        try:
            preview_bars(symbol, duration='1 M', timeout=20)
        except DataError as exc:
            if expected_error:
                assert expected_error in str(exc), str(exc)
            report['checks'].append(f'{symbol}: visible rejection: {exc}')
        else:
            raise AssertionError(f'Unexpected successful preview for {symbol}')

    cli_output = output / 'CLI-AAPL.html'
    result = command('chart', 'AAPL', '--provider', 'yahoo', '--interval', '1d',
                     '--duration', '1 Y', '--output', str(cli_output), '--no-browser')
    assert result.returncode == 0, result.stderr
    assert cli_output.exists() and 'preview only' in result.stderr
    before = cli_output.read_bytes()
    for flags in (['--live'], ['--extended-hours'], ['--cache'], ['--cache-dir', str(output)],
                  ['--refresh-cache'], ['--primary-exchange', 'NASDAQ'], ['--interval', '1min'],
                  ['--duration', '0 D']):
        result = command('chart', 'AAPL', '--provider', 'yahoo', '--interval', '1d',
                         '--output', str(cli_output), '--no-browser', *flags)
        assert result.returncode == 1, (flags, result)
        assert result.stderr.startswith('pyibquant:') and 'Traceback' not in result.stderr
        assert cli_output.read_bytes() == before
    report['checks'].append('live CLI, eight unsupported modes, preserved existing output')

    if args.browser:
        check_browser(output / 'SPY.html', spy_rows, output)
        report['checks'].append(
            'Chrome rendering, warning/label, disabled loading, zoom, scale, resize'
        )
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print(f'PASS: Yahoo integration; artifacts at {output}')


if __name__ == '__main__':
    main()

"""Offline session shading, clock, freshness and reconnect viewport regression."""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from pyibquant import Bar, BarSeries
from pyibquant.visualization.chart import render_chart


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


def main():
    series = BarSeries('DEMO', '1h', live=True)
    series.regular_hours = False
    series.connection_state = 'subscribed'
    series.status = 'Subscribed to bar updates'
    for day, offset, close in [('2026-07-06', '-04:00', '16:00'),
                               ('2026-11-27', '-05:00', '13:00')]:
        series.merge_sessions([
            dict(start=epoch(f'{day}T09:30:00{offset}'), end=epoch(f'{day}T{close}:00{offset}'),
                 date=day, regular=True),
            dict(start=epoch(f'{day}T04:00:00{offset}'), end=epoch(f'{day}T20:00:00{offset}'),
                 date=day, regular=False),
        ])
        for hour in range(4, 20):
            series.update(Bar(datetime.fromtimestamp(epoch(f'{day}T{hour:02}:00:00{offset}'), UTC),
                              100, 102, 99, 101, 1000))
    payload = {**series.payload(), 'selection_id': 'sessions'}
    html = render_chart(series, live_endpoint=True, selection_id='sessions')
    Path('charts').mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1050})
        context.set_offline(True)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == '/':
                route.fulfill(content_type='text/html', body=html)
            elif path == '/data':
                route.fulfill(json=payload)
            else:
                raise AssertionError(route.request.url)

        context.route('**/*', route_request)
        page.goto('http://sessions.test/')
        page.wait_for_function('chart.plot && chart.frame === null')
        # Real IBKR 1h/2h/4h RTH openers are shorter than the nominal interval.
        for interval, end in [('1h', '10:00'), ('2h', '10:00'), ('4h', '12:00')]:
            for day, offset in [('2026-07-06', '-04:00'), ('2026-11-27', '-05:00')]:
                result = page.evaluate('''([interval, time]) => {
                  chart.setInterval(interval); return chart.barBoundary(time);
                }''', [interval, epoch(f'{day}T09:30:00{offset}')])
                assert result == epoch(f'{day}T{end}:00{offset}')
        page.evaluate('chart.setInterval("1h")')
        # Compare actual canvas pixels with shading on/off in both panes, away from candles.
        page.evaluate('''() => {
          window.sample = index => {
            const ratio = devicePixelRatio;
            const x = chart.plot.x + (index - chart.left + 0.1) * chart.plot.w / chart.count;
            return [chart.plot.y + 3, chart.plot.y + chart.plot.h - 3].map(y =>
              Array.from(chart.ctx.getImageData(
                Math.floor(x * ratio), Math.floor(y * ratio), 1, 1).data));
          };
          chart.draw();
          window.shaded = [0, 6, 25].map(sample);
        }''')
        page.locator('#sessions').click()
        page.wait_for_function('chart.frame === null')
        plain = page.evaluate('[0, 6, 25].map(sample)')
        shaded = page.evaluate('shaded')
        assert shaded[0] != plain[0]  # Premarket, both panes.
        assert shaded[1] == plain[1]  # Regular 10:00 candle.
        assert shaded[2] != plain[2]  # 13:00 on the early-close day.
        assert all(a != b for a, b in zip(shaded[0], plain[0], strict=True))
        page.locator('#sessions').click()
        page.wait_for_function('chart.frame === null')
        page.screenshot(path='charts/native-sessions.png', full_page=True)

        # Fresh callbacks and a connected socket do not establish real-time entitlements.
        now = epoch('2026-11-27T12:30:00-05:00')
        recent = datetime.fromtimestamp(now - 5, UTC).isoformat()
        base = {**payload, 'last_update': recent, 'last_live_update': recent}
        assert 'Entitlements unverified' in page.evaluate(
            '([p, now]) => freshness(p, now)', [base, now])
        stale = {**base, 'last_live_update': datetime.fromtimestamp(now - 100, UTC).isoformat()}
        assert 'over 90s' in page.evaluate('([p, now]) => freshness(p, now)', [stale, now])
        regular = {**stale, 'regular_hours': True}
        after_close = epoch('2026-11-27T14:00:00-05:00')
        assert page.evaluate('([p, now]) => freshness(p, now)', [regular, after_close]) == (
            'Outside requested session')
        assert page.evaluate('([p, now]) => freshness({...p, sessions: []}, now)',
                             [base, now]) == 'Session hours unverified'

        # Countdown stops at the actual early close and disappears outside sessions.
        page.evaluate('''p => {
          const boundary = Date.parse('2026-11-27T17:00:00Z') / 1000;
          draw({...p, regular_hours: true, bars: p.bars.filter(b => b.time <= boundary)}, true);
        }''', base)
        page.evaluate('now => updateClock(now)', epoch('2026-11-27T12:59:45-05:00'))
        assert '0:15' in page.locator('#countdown').inner_text()
        page.evaluate('now => updateClock(now)', after_close)
        assert not page.locator('#countdown').inner_text()

        # Disconnection/recovery never resets time zoom or manual prices.
        page.evaluate('chart.zoom(0.5, chart.plot.x + chart.plot.w / 2); chart.setAutoscale(false)')
        view = page.evaluate('[chart.left, chart.count, chart.manualRange]')
        for state in ['disconnected', 'reconnecting', 'subscribed']:
            page.evaluate('([p, state]) => draw({...currentPayload, connection_state: state})',
                          [base, state])
            assert page.evaluate('[chart.left, chart.count, chart.manualRange]') == view
        # Missing schedules omit shading; daily/coarser bars have no intraday countdown.
        page.evaluate('''draw({...currentPayload, sessions: [],
            schedule_error: 'Session schedule unavailable'})''')
        assert 'unavailable' in page.locator('#sessions-note').inner_text()
        page.evaluate('draw({...currentPayload, interval: "1d", bars: []}, true)')
        assert not page.locator('#countdown').inner_text()
        assert not errors, errors
        browser.close()
    print('PASS: session shading across panes, early close, DST, unknown schedules, '
          'freshness, countdown and reconnect viewport')


if __name__ == '__main__':
    main()

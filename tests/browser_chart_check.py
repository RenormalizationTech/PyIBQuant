"""Manual browser regression: .venv/bin/python tests/browser_chart_check.py.

Requires Playwright and installed Google Chrome. Generates synthetic bars;
all network requests are blocked. Screenshots stay in the ignored charts/ folder.
"""

from datetime import UTC, datetime, timedelta
from math import sin
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from pyibquant import Bar, BarSeries


def main() -> None:
    Path("charts").mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="pyibquant-chart-") as temporary:
        series = BarSeries("DEMO", "1min")
        start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        for index in range(120):
            price = 100 + sin(index / 8)
            series.update(
                Bar(
                    start + timedelta(minutes=index),
                    price,
                    price + 0.4,
                    price - 0.4,
                    price + 0.1,
                    1000 + index * 10,
                )
            )
        snapshot = series.plot(Path(temporary) / "chart.html", open_browser=False)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 960}, device_scale_factor=2
            )
            context.set_offline(True)
            page = context.new_page()
            errors = []
            requests = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on(
                "request",
                lambda req: requests.append(req.url) if req.url.startswith("http") else None,
            )
            page.goto(snapshot.as_uri())
            page.wait_for_function("chart.plot && chart.bars.length > 0")
            page.evaluate("window.savedBars = chart.bars.map(bar => ({...bar}))")
            assert page.locator("canvas").count() == 1
            assert page.evaluate(
                "chart.canvas.width === Math.round(chart.width * devicePixelRatio)"
            )
            initial_count = page.evaluate("chart.count")
            assert initial_count > 8
            box = page.locator("canvas").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
            page.mouse.wheel(0, -500)
            page.wait_for_function(f"chart.count < {initial_count}")
            zoom_count = page.evaluate("chart.count")
            before = page.evaluate("chart.left")
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] / 2 + 80, box["y"] + 100, steps=5)
            page.mouse.up()
            assert page.evaluate("chart.left") < before
            page.mouse.move(box["x"] + 100, box["y"] + 100)
            page.wait_for_function("chart.hover !== null")
            assert "O " in page.locator("#legend").inner_text()
            # A panned viewport survives appends; Latest resumes following with the same zoom.
            left = page.evaluate("chart.left")
            page.evaluate("""() => {
              const last = chart.bars.at(-1);
              chart.setData([...chart.bars, {...last, time: last.time + 60}]);
            }""")
            assert page.evaluate("chart.left") == left
            page.locator("#latest").click()
            assert page.evaluate("Math.abs(chart.left + chart.count - chart.bars.length) < 0.001")
            assert page.evaluate("chart.count") == zoom_count
            page.evaluate("""() => {
              const last = chart.bars.at(-1);
              chart.setData([...chart.bars, {...last, time: last.time + 60}]);
            }""")
            assert page.evaluate("Math.abs(chart.left + chart.count - chart.bars.length) < 0.001")
            page.locator("canvas").focus()
            page.keyboard.press("Home")
            assert page.evaluate("chart.count === chart.bars.length && chart.left === 0")
            page.keyboard.press("+")
            assert page.evaluate("chart.count < chart.bars.length")
            page.keyboard.press("ArrowLeft")
            page.keyboard.press("End")
            assert page.evaluate("Math.abs(chart.left + chart.count - chart.bars.length) < 0.001")
            page.locator("#fit").click()
            page.mouse.move(0, 0)
            page.screenshot(path="charts/native-desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function("chart.width === 390")
            assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
            page.screenshot(path="charts/native-mobile.png", full_page=True)
            # Empty data, a flat single candle, and daily dates must have finite geometry.
            for bars in [
                [],
                [{"time": "2026-10-15", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}],
            ]:
                page.evaluate("(bars) => { chart.setData(bars); chart.fit(); }", bars)
                page.wait_for_timeout(50)
                assert page.evaluate("Number.isFinite(chart.count) && Number.isFinite(chart.left)")
            page.evaluate("chart.setData(savedBars); chart.fit()")
            # Hover legend remains tied to the selected candle while incoming data updates.
            page.locator("canvas").scroll_into_view_if_needed()
            box = page.locator("canvas").bounding_box()
            page.mouse.move(box["x"] + 100, box["y"] + 100)
            page.wait_for_function("chart.hover !== null")
            legend = page.locator("#legend").inner_text()
            page.evaluate("chart.setData([...chart.bars])")
            page.wait_for_timeout(50)
            assert page.locator("#legend").inner_text() == legend
            assert not requests, requests
            assert not errors, errors
            print(
                "PASS: offline drawing, DPR, zoom, drag, crosshair, keyboard, "
                "live viewport, resize, empty/flat data"
            )
            browser.close()


if __name__ == "__main__":
    main()

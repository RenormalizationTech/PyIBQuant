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


def check_price_scaling(page) -> None:
    """Exercise real pointer/keyboard controls and incoming payloads offline."""
    page.locator("#fit").click()
    page.wait_for_function("chart.frame === null")
    box = page.locator("canvas").bounding_box()
    axis_x = box["x"] + page.evaluate("chart.plot.x + chart.plot.w + 20")
    start_y = box["y"] + 100
    original = page.evaluate("({...chart.priceRange})")
    viewport = page.evaluate("[chart.left, chart.count]")
    page.mouse.move(axis_x, start_y)
    assert page.locator("canvas").evaluate("el => el.style.cursor") == "ns-resize"
    page.mouse.down()
    page.mouse.move(axis_x, start_y + 50, steps=5)
    page.mouse.up()
    page.wait_for_function("chart.frame === null")
    scaled = page.evaluate("({...chart.priceRange})")
    assert scaled["high"] - scaled["low"] > original["high"] - original["low"]
    assert page.evaluate("[chart.left, chart.count]") == viewport
    assert page.locator("#autoscale").get_attribute("aria-pressed") == "false"

    # Manual dragging translates price without changing its span or time zoom.
    page.mouse.move(box["x"] + 250, start_y)
    page.mouse.down()
    page.mouse.move(box["x"] + 250, start_y + 40, steps=5)
    page.mouse.up()
    page.wait_for_function("chart.frame === null")
    panned = page.evaluate("({...chart.priceRange})")
    assert panned["low"] > scaled["low"]
    assert abs((panned["high"] - panned["low"]) - (scaled["high"] - scaled["low"])) < 1e-10
    assert page.evaluate("[chart.left, chart.count]") == viewport

    # Poll-style updates, horizontal navigation and resizing preserve manual bounds.
    page.evaluate("draw({...initial, bars: [...chart.bars]})")
    page.evaluate("""() => {
      const last = chart.bars.at(-1);
      draw({...initial, bars: [...chart.bars, {...last, time: last.time + 60, high: 1000}]});
    }""")
    page.locator("canvas").focus()
    page.keyboard.press("+")
    page.keyboard.press("ArrowLeft")
    page.locator("#latest").click()
    count = page.evaluate("chart.count")
    page.set_viewport_size({"width": 1100, "height": 900})
    page.wait_for_function("chart.width === 1100 && chart.frame === null")
    assert page.evaluate("({...chart.priceRange})") == panned
    assert page.evaluate("chart.count") == count
    page.mouse.move(0, 0)
    page.screenshot(path="charts/native-manual-scale.png", full_page=True)

    # Even long out-of-view candle wicks must not draw into the volume pane.
    page.evaluate("""() => {
      window.volumePixels = () => {
        const ratio = devicePixelRatio;
        const top = Math.ceil((chart.plot.y + chart.priceHeight + 2) * ratio);
        return Array.from(chart.ctx.getImageData(0, top, chart.canvas.width,
          Math.floor((chart.plot.y + chart.plot.h) * ratio) - top).data);
      };
      chart.hover = null;
      chart.draw();
      window.beforeVolume = volumePixels();
      chart.setData(chart.bars.map(bar => ({...bar, low: -1000})));
    }""")
    page.wait_for_function("chart.frame === null")
    # Canvas readback can change subpixel antialiasing between GPU/CPU paths.
    # A candle leaking into volume changes colors far more than this tolerance.
    difference = page.evaluate("""() => {
      const after = volumePixels();
      return after.reduce((maximum, value, index) =>
        Math.max(maximum, Math.abs(value - beforeVolume[index])), 0);
    }""")
    assert difference <= 16, difference

    # Axis reset affects only price; automatic mode reacts to incoming extremes.
    box = page.locator("canvas").bounding_box()
    axis_x = box["x"] + page.evaluate("chart.plot.x + chart.plot.w + 20")
    viewport = page.evaluate("[chart.left, chart.count]")
    page.mouse.dblclick(axis_x, box["y"] + 100)
    page.wait_for_function("chart.manualRange === null && chart.frame === null")
    assert page.evaluate("[chart.left, chart.count]") == viewport
    assert page.evaluate("chart.priceRange.high > 1000 && chart.priceRange.low < -1000")
    assert page.locator("#autoscale").get_attribute("aria-pressed") == "true"

    # Toggle freezes current bounds; keyboard pans and resets; new selections reset.
    page.locator("#autoscale").click()
    frozen = page.evaluate("({...chart.manualRange})")
    page.locator("canvas").focus()
    page.keyboard.press("ArrowUp")
    assert page.evaluate("chart.manualRange.low") < frozen["low"]
    page.keyboard.press("a")
    assert page.evaluate("chart.manualRange === null")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("chart.manualRange !== null")
    page.keyboard.press("Home")
    assert page.evaluate(
        "chart.manualRange === null && "
        "Math.abs(chart.count * (1 - chart.rightMargin) - chart.bars.length) < 0.001"
    )
    page.locator("#autoscale").click()
    page.evaluate("draw(initial, true)")
    page.wait_for_function("chart.manualRange === null && chart.frame === null")
    assert page.locator("#autoscale").get_attribute("aria-pressed") == "true"
    page.set_viewport_size({"width": 1440, "height": 960})
    page.wait_for_function("chart.width === 1440 && chart.frame === null")


def check_time_scaling(page) -> None:
    page.locator("#fit").click()
    page.wait_for_function("chart.frame === null")
    page.locator("#autoscale").click()
    manual = page.evaluate("({...chart.manualRange})")
    count = page.evaluate("chart.count")
    page.evaluate("window.scrollTo(0, chart.canvas.getBoundingClientRect().top + scrollY - 60)")
    box = page.locator("canvas").bounding_box()
    axis_y = box["y"] + page.evaluate("chart.plot.y + chart.plot.h + 20")
    axis_x = box["x"] + 300
    page.mouse.move(axis_x, axis_y)
    assert page.locator("canvas").evaluate("el => el.style.cursor") == "ew-resize"
    page.mouse.down()
    page.mouse.move(axis_x + 60, axis_y, steps=6)
    page.mouse.up()
    page.wait_for_function("chart.frame === null")
    assert page.evaluate("chart.count") < count
    assert page.evaluate("({...chart.manualRange})") == manual
    assert page.evaluate(
        "Math.abs(chart.left + chart.count * 0.9 - chart.bars.length) < 0.001"
    )

    # Right space changes preserve zoom while following and keep manual prices.
    count = page.evaluate("chart.count")
    page.locator("#right-margin").select_option("0.3")
    assert page.evaluate("chart.count") == count
    assert page.evaluate(
        "Math.abs((chart.left + chart.count - chart.bars.length) / chart.count - 0.3) < 1e-9"
    )
    assert page.evaluate("({...chart.manualRange})") == manual

    # Changing right space or updating bars must not move a panned view.
    page.locator("canvas").focus()
    page.keyboard.press("ArrowLeft")
    viewport = page.evaluate("[chart.left, chart.count]")
    page.locator("#right-margin").select_option("0.4")
    page.evaluate("""() => {
      const last = chart.bars.at(-1);
      chart.setData([...chart.bars, {...last, time: last.time + 60}]);
    }""")
    assert page.evaluate("[chart.left, chart.count]") == viewport
    page.locator("#latest").click()
    page.evaluate("""() => {
      const last = chart.bars.at(-1);
      chart.setData([...chart.bars, {...last, time: last.time + 60}]);
    }""")
    assert page.evaluate(
        "Math.abs(chart.left + chart.count * 0.6 - chart.bars.length) < 0.001"
    )
    assert page.evaluate("chart.count") == count
    page.wait_for_function("chart.frame === null")
    page.evaluate("window.scrollTo(0, chart.canvas.getBoundingClientRect().top + scrollY - 60)")
    box = page.locator("canvas").bounding_box()
    blank_x = box["x"] + page.evaluate("chart.plot.x + chart.plot.w * 0.95")
    page.mouse.move(blank_x, box["y"] + 100)
    page.wait_for_function("chart.legend.textContent === 'No bar at this position'")
    page.mouse.move(blank_x, box["y"] + page.evaluate("chart.plot.y + chart.plot.h - 10"))
    page.wait_for_function("chart.legend.textContent === 'No bar at this position'")
    page.mouse.move(0, 0)
    page.screenshot(path="charts/native-right-space.png", full_page=True)

    # Resetting the time axis preserves manual prices and the selected margin.
    page.mouse.dblclick(axis_x, axis_y)
    assert page.evaluate("({...chart.manualRange})") == manual
    assert page.evaluate(
        "chart.left === 0 && Math.abs(chart.count * 0.6 - chart.bars.length) < 0.001"
    )
    page.locator("#right-margin").select_option("0")
    assert page.evaluate("chart.count === chart.bars.length && chart.left === 0")
    page.locator("#right-margin").select_option("0.1")
    page.evaluate("draw(initial, true)")
    assert page.evaluate("chart.rightMargin === 0.1 && chart.manualRange === null")


def check_touch_scaling(page) -> None:
    """Native touch input must still reach both axes and the pinch gesture."""
    page.evaluate("window.scrollTo(0, chart.canvas.getBoundingClientRect().top + scrollY - 100)")
    page.wait_for_function("chart.frame === null")
    page.locator("#autoscale").click()
    page.evaluate("window.scrollTo(0, chart.canvas.getBoundingClientRect().top + scrollY - 100)")
    box = page.locator("canvas").bounding_box()
    session = page.context.new_cdp_session(page)

    def touch(kind, points):
        session.send(
            "Input.dispatchTouchEvent",
            {
                "type": kind,
                "touchPoints": [
                    {"x": x, "y": y, "id": index + 1} for index, (x, y) in enumerate(points)
                ],
            },
        )

    x = box["x"] + page.evaluate("chart.plot.x + chart.plot.w + 20")
    y = box["y"] + 100
    price_range = page.evaluate("({...chart.manualRange})")
    touch("touchStart", [(x, y)])
    touch("touchMove", [(x, y + 40)])
    touch("touchEnd", [])
    page.wait_for_function("chart.frame === null")
    assert page.evaluate("chart.manualRange.high") > price_range["high"]
    price_range = page.evaluate("({...chart.manualRange})")
    count = page.evaluate("chart.count")
    y = box["y"] + page.evaluate("chart.plot.y + chart.plot.h + 20")
    touch("touchStart", [(100, y)])
    touch("touchMove", [(140, y)])
    touch("touchEnd", [])
    page.wait_for_function("chart.frame === null")
    assert page.evaluate("chart.count") < count
    assert page.evaluate("({...chart.manualRange})") == price_range
    count = page.evaluate("chart.count")
    y = box["y"] + 100
    touch("touchStart", [(100, y), (200, y)])
    touch("touchMove", [(80, y), (220, y)])
    touch("touchEnd", [])
    page.wait_for_function("chart.frame === null")
    assert page.evaluate("chart.count") < count
    assert page.evaluate("({...chart.manualRange})") == price_range
    assert page.evaluate("chart.pointers.size === 0 && chart.dragMode === null")
    session.detach()
    page.evaluate("chart.fit()")


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
            # New York labels honor DST and calendar rollovers; daily dates stay dates.
            for timestamp, expected in [
                ("2026-01-05T14:30:00Z", "Jan 5, 2026 09:30 EST"),
                ("2026-07-06T13:30:00Z", "Jul 6, 2026 09:30 EDT"),
                ("2026-07-06T02:00:00Z", "Jul 5, 2026 22:00 EDT"),
                ("2026-03-08T06:59:00Z", "Mar 8, 2026 01:59 EST"),
                ("2026-03-08T07:00:00Z", "Mar 8, 2026 03:00 EDT"),
            ]:
                assert page.evaluate(
                    "stamp => chart.timeLabel(Date.parse(stamp) / 1000, true)", timestamp
                ) == expected
            assert page.evaluate("chart.timeLabel('2026-01-01', true)") == "Jan 1, 2026"
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
            assert page.evaluate(
                "Math.abs(chart.left + chart.count * (1 - chart.rightMargin)"
                " - chart.bars.length) < 0.001"
            )
            assert page.evaluate("chart.count") == zoom_count
            page.evaluate("""() => {
              const last = chart.bars.at(-1);
              chart.setData([...chart.bars, {...last, time: last.time + 60}]);
            }""")
            assert page.evaluate(
                "Math.abs(chart.left + chart.count * (1 - chart.rightMargin)"
                " - chart.bars.length) < 0.001"
            )
            page.locator("canvas").focus()
            page.keyboard.press("Home")
            assert page.evaluate(
                "Math.abs(chart.count * (1 - chart.rightMargin) - chart.bars.length) < 0.001"
                " && chart.left === 0"
            )
            page.keyboard.press("+")
            assert page.evaluate("chart.count < chart.bars.length")
            page.keyboard.press("ArrowLeft")
            page.keyboard.press("End")
            assert page.evaluate(
                "Math.abs(chart.left + chart.count * (1 - chart.rightMargin)"
                " - chart.bars.length) < 0.001"
            )
            page.locator("#fit").click()
            check_price_scaling(page)
            check_time_scaling(page)
            page.mouse.move(0, 0)
            page.screenshot(path="charts/native-desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function("chart.width === 390")
            assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
            page.screenshot(path="charts/native-mobile.png", full_page=True)
            check_touch_scaling(page)
            # Coarser calendar intervals render dates/years without timezone shifts.
            for interval in ["1w", "1y"]:
                page.evaluate("""interval => {
                  draw({...initial, interval, bars: [
                    {time: '2024-01-01', open: 100, high: 120, low: 90, close: 110, volume: 1000},
                    {time: '2025-01-01', open: 110, high: 130, low: 100, close: 120, volume: 2000}
                  ]}, true);
                }""", interval)
                page.wait_for_function("chart.frame === null")
                if interval == "1y":
                    assert page.evaluate("chart.timeLabel('2025-01-01')") == "2025"
                    assert "2025 (calendar year)" in page.locator("#legend").inner_text()
                else:
                    assert page.evaluate("chart.timeLabel('2025-01-01')") == "Jan 1, 2025"
                assert page.evaluate("Number.isFinite(chart.priceRange.high)")
            page.evaluate("draw(initial, true)")
            # Empty data, a flat single candle, and daily dates must have finite geometry.
            for bars in [
                [],
                [{"time": "2026-10-15", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}],
            ]:
                page.evaluate("(bars) => { chart.setData(bars); chart.fit(); }", bars)
                page.wait_for_timeout(50)
                assert page.evaluate("Number.isFinite(chart.count) && Number.isFinite(chart.left)")
                page.locator("#autoscale").click()
                page.locator("canvas").focus()
                page.keyboard.press("ArrowLeft")
                page.keyboard.press("ArrowUp")
                page.keyboard.press("Home")
                page.wait_for_function("chart.frame === null")
                if bars:
                    assert page.evaluate("chart.priceRange.high > chart.priceRange.low")
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
                "live viewport, manual price scaling/panning, autoscale/reset, "
                "time-axis scaling, right space, touch axes/pinch, pane clipping, "
                "resize, weekly/yearly labels, empty/flat data"
            )
            browser.close()


if __name__ == "__main__":
    main()

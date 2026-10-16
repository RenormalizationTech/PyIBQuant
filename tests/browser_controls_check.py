"""Manual TWS integration check; run with a live chart at 127.0.0.1:8050.

Requires Playwright and installed Chrome. Switches the active chart to SPY 5min,
checks invalid input, then leaves it on AAPL daily. Requests real IBKR data.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    Path("charts").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8050/")
        assert page.locator("#symbol-input").is_enabled()
        page.wait_for_function("chart.plot && chart.bars.length > 0")
        page.locator("#right-margin").select_option("0.2")
        page.locator("canvas").focus()
        page.keyboard.press("+")
        page.keyboard.press("+")
        page.locator("#latest").click()
        page.wait_for_function("chart.frame === null")
        box = page.locator("canvas").bounding_box()
        axis_x = box["x"] + page.evaluate("chart.plot.x + chart.plot.w + 20")
        page.mouse.move(axis_x, box["y"] + 100)
        page.mouse.down()
        page.mouse.move(axis_x, box["y"] + 150, steps=5)
        page.mouse.up()
        page.wait_for_function("chart.manualRange !== null && chart.frame === null")
        price_range = page.evaluate("({...chart.manualRange})")
        count = page.evaluate("chart.count")
        # Real server polls retain manual scaling and keep Latest at the chosen margin.
        for _ in range(2):
            with page.expect_response(lambda r: r.url.endswith("/data"), timeout=10000):
                pass
            page.wait_for_function("chart.frame === null")
            assert page.evaluate("({...chart.manualRange})") == price_range
            assert page.evaluate("chart.count") == count
            assert page.evaluate(
                "Math.abs(chart.left + chart.count * 0.8 - chart.bars.length) < 0.001"
            )
        page.locator("canvas").focus()
        page.keyboard.press("ArrowLeft")
        viewport = page.evaluate("[chart.left, chart.count]")
        with page.expect_response(lambda r: r.url.endswith("/data"), timeout=10000):
            pass
        page.wait_for_function("chart.frame === null")
        assert page.evaluate("[chart.left, chart.count]") == viewport
        assert page.evaluate("({...chart.manualRange})") == price_range
        print(
            "PASS: real IBKR polling preserves manual prices, time zoom, right space, panned view"
        )
        page.locator("#symbol-input").fill("spy")
        page.locator("#interval-input").select_option("5min")
        with page.expect_response(
            lambda r: r.url.endswith("/chart") and r.request.method == "POST", timeout=30000
        ) as response:
            page.locator("#load-chart").click()
        assert response.value.status == 200, response.value.text()
        page.wait_for_function("currentSymbol === 'SPY' && currentInterval === '5min' && !loading")
        assert page.locator("#symbol").inner_text() == "SPY"
        assert "5min" in page.locator("#meta").inner_text()
        assert page.evaluate("chart.bars.length") > 10
        assert page.evaluate("chart.manualRange === null && chart.rightMargin === 0.2")
        print("SPY 5min:", page.locator("#status").inner_text())
        # Bad inputs preserve the previous chart and remain visible across polling.
        count = page.evaluate("chart.bars.length")
        page.locator("#autoscale").click()
        price_range = page.evaluate("({...chart.manualRange})")
        page.locator("#duration-input").fill("invalid")
        page.locator("#symbol-input").press("Enter")
        page.wait_for_function('selectionError !== "" && !loading')
        assert page.locator("#symbol").inner_text() == "SPY"
        assert page.evaluate("chart.bars.length") >= count
        page.wait_for_timeout(2200)
        assert page.locator("#error").is_visible()
        assert page.evaluate("({...chart.manualRange})") == price_range
        # A daily chart switches date labels and fits the new dataset.
        page.locator("#symbol-input").fill("AAPL")
        page.locator("#interval-input").select_option("1d")
        page.locator("#duration-input").fill("6 M")
        with page.expect_response(
            lambda r: r.url.endswith("/chart") and r.request.method == "POST", timeout=30000
        ) as response:
            page.locator("#load-chart").click()
        assert response.value.status == 200, response.value.text()
        page.wait_for_function("currentSymbol === 'AAPL' && currentInterval === '1d' && !loading")
        assert page.evaluate("typeof chart.bars[0].time === 'string'")
        assert page.evaluate("chart.manualRange === null && chart.rightMargin === 0.2")
        assert not page.locator("#error").is_visible()
        # Exercise each new interval through the real server/provider pipeline.
        for interval, duration in [("2h", "1 M"), ("4h", "1 M"), ("1w", "2 Y"), ("1y", "10 Y")]:
            page.locator("#interval-input").select_option(interval)
            page.locator("#duration-input").fill(duration)
            with page.expect_response(
                lambda r: r.url.endswith("/chart") and r.request.method == "POST", timeout=30000
            ) as response:
                page.locator("#load-chart").click()
            assert response.value.status == 200, response.value.text()
            page.wait_for_function(
                "interval => currentInterval === interval && !loading && chart.frame === null",
                arg=interval,
            )
            assert page.evaluate("chart.bars.length") > 1
            assert page.evaluate("chart.manualRange === null && chart.rightMargin === 0.2")
            expected_type = "string" if interval in {"1w", "1y"} else "number"
            assert page.evaluate("typeof chart.bars[0].time") == expected_type
            if interval == "1y":
                assert "may be partial" in page.locator("#error").inner_text()
                assert "calendar year" in page.locator("#legend").inner_text()
            else:
                assert not page.locator("#error").is_visible()
            print(f"AAPL {interval}:", page.locator("#status").inner_text())
        page.screenshot(path="charts/controls-yearly.png", full_page=True)
        # Restore daily bars so repeated runs retain their expected starting state.
        page.locator("#interval-input").select_option("1d")
        page.locator("#duration-input").fill("6 M")
        page.locator("#load-chart").click()
        page.wait_for_function(
            "currentInterval === '1d' && !loading && chart.frame === null && !selectionError"
        )
        page.screenshot(path="charts/controls-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path="charts/controls-mobile.png", full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        assert not errors, errors
        print("AAPL daily:", page.locator("#status").inner_text())
        print(
            "PASS: real TWS symbol/interval/history changes, Enter submit, errors, recovery, mobile"
        )
        browser.close()


if __name__ == "__main__":
    main()

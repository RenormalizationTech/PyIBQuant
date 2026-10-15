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
        print("SPY 5min:", page.locator("#status").inner_text())
        # Bad inputs preserve the previous chart and remain visible across polling.
        count = page.evaluate("chart.bars.length")
        page.locator("#duration-input").fill("invalid")
        page.locator("#symbol-input").press("Enter")
        page.wait_for_function('selectionError !== "" && !loading')
        assert page.locator("#symbol").inner_text() == "SPY"
        assert page.evaluate("chart.bars.length") >= count
        page.wait_for_timeout(2200)
        assert page.locator("#error").is_visible()
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
        assert not page.locator("#error").is_visible()
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

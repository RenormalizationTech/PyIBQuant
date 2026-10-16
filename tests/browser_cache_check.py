"""Manual cache/browser check against the IBKR chart at 127.0.0.1:8050.

Start the chart with --cache-dir charts/cache. Requires Playwright and Chrome.
Uses real IBKR data and leaves the shared chart on AAPL daily/6-month history.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    Path("charts").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8050/")

        def select(interval, duration):
            page.locator("#symbol-input").fill("AAPL")
            page.locator("#interval-input").select_option(interval)
            page.locator("#duration-input").fill(duration)
            with page.expect_response(
                lambda r: r.url.endswith("/chart") and r.request.method == "POST", timeout=40000
            ) as response:
                page.locator("#load-chart").click()
            assert response.value.status == 200, response.value.text()
            page.wait_for_function("!loading && chart.frame === null")
            assert not response.value.json()["cache_hit"]  # Live initialization always uses IBKR.

        for interval, duration in [("1d", "1 M"), ("1y", "1 Y")]:
            for attempt in range(2):
                select(interval, duration)
                page.locator("canvas").focus()
                page.keyboard.press("+")
                page.wait_for_function("chart.frame === null")
                page.locator("#autoscale").click()
                expected = page.evaluate("""() => ({
                  time: chart.bars[Math.floor(chart.left)].time,
                  fraction: chart.left % 1, count: chart.count, range: {...chart.manualRange}
                })""")
                with page.expect_response(
                    lambda r: r.url.endswith("/older") and r.request.method == "POST", timeout=40000
                ) as response:
                    page.locator("#load-older").click()
                assert response.value.status == 200, response.value.text()
                payload = response.value.json()
                page.wait_for_function("!historyLoading && chart.frame === null")
                actual = page.evaluate("""time => ({
                  index: chart.bars.findIndex(bar => bar.time === time),
                  left: chart.left, count: chart.count, range: {...chart.manualRange}
                })""", expected["time"])
                assert actual["count"] == expected["count"]
                assert actual["range"] == expected["range"]
                assert abs(actual["index"] - actual["left"] + expected["fraction"]) < 1e-8
                assert "Subscribed to bar updates" in page.locator("#status").inner_text()
                if attempt == 1:
                    assert payload["history_cache_hit"], "Start the chart with --cache-dir"
                    assert "from cache" in page.locator("#history-status").inner_text()
                    print(f"PASS {interval}: cached older page, stable viewport/manual scale, "
                          "fresh live subscription", flush=True)
                    if interval == "1d":
                        page.mouse.move(0, 0)
                        page.screenshot(path="charts/history-cache.png", full_page=True)
        select("1d", "6 M")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    main()

"""Manual IBKR pagination check against a live chart at 127.0.0.1:8050.

Uses real market data. Leaves the shared chart on AAPL daily/6-month history.
Run .venv/bin/python tests/browser_live_history_check.py with Chrome installed.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    Path("charts").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        pending = []
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

        def hold_history(route):
            # Send the real request to IBKR through our server, then delay only delivery
            # to the browser until the gesture has ended and its viewport is recorded.
            response = route.fetch(timeout=40000)
            assert response.status == 200, response.text()
            pending.append((route, response))
            page.evaluate("window.historyResponseReady = true")

        page.route("**/older", hold_history)
        for interval, duration in [("1min", "1 D"), ("1d", "1 M"),
                                   ("1w", "2 Y"), ("1y", "1 Y")]:
            select(interval, duration)
            count = page.evaluate("chart.bars.length")
            first = page.evaluate("chart.bars[0].time")
            page.locator("canvas").focus()
            page.keyboard.press("+")
            page.keyboard.press("+")
            page.wait_for_function("chart.frame === null")
            page.locator("#autoscale").click()
            box = page.locator("canvas").bounding_box()
            width = page.evaluate("chart.plot.w")
            page.mouse.move(box["x"] + width * 0.2, box["y"] + 100)
            page.evaluate("window.historyResponseReady = false")
            with page.expect_request("**/older", timeout=40000):
                page.mouse.down()
                page.mouse.move(box["x"] + width * 0.85, box["y"] + 100, steps=8)
            page.mouse.up()
            page.wait_for_function("window.historyResponseReady === true", timeout=40000)
            page.wait_for_function("historyLoading && chart.frame === null")
            expected = page.evaluate("""() => ({
              time: chart.bars[Math.floor(chart.left)].time,
              fraction: chart.left % 1, count: chart.count, range: {...chart.manualRange}
            })""")
            route, response = pending.pop(0)
            route.fulfill(response=response)
            page.wait_for_function("!historyLoading && chart.frame === null")
            actual = page.evaluate("""time => ({
              index: chart.bars.findIndex(bar => bar.time === time),
              left: chart.left, count: chart.count, range: {...chart.manualRange}
            })""", expected["time"])
            assert actual["count"] == expected["count"]
            assert actual["range"] == expected["range"]
            assert abs(actual["index"] - actual["left"] + expected["fraction"]) < 1e-8
            assert page.evaluate("chart.bars.length") > count
            assert page.evaluate("chart.bars[0].time") < first
            assert page.evaluate(
                "new Set(chart.bars.map(bar => bar.time)).size === chart.bars.length"
            )
            assert "Subscribed to bar updates" in page.locator("#status").inner_text()
            assert not page.evaluate("historyError")
            print(f"PASS {interval}: {count} -> {page.evaluate('chart.bars.length')} bars; "
                  "viewport, manual prices and live subscription preserved", flush=True)
            if interval == "1d":
                page.mouse.move(0, 0)
                page.screenshot(path="charts/history-live.png", full_page=True)
        select("1d", "6 M")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    main()

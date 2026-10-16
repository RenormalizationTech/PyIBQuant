"""Offline pagination regression with intercepted synthetic HTTP responses.

Run .venv/bin/python tests/browser_history_check.py with Playwright and Chrome.
No TWS connection or external network requests are used.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from pyibquant import Bar, BarSeries
from pyibquant.visualization.chart import render_chart


def main() -> None:
    series = BarSeries("DEMO", "1min", live=True)
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    for index in range(120):
        series.update(Bar(start + timedelta(minutes=index), 100, 102, 99, 101, 1000))
    initial = {**series.payload(), "selection_id": "synthetic-one"}
    html = render_chart(series, live_endpoint=True, controls=True, history=True,
                        selection_id=initial["selection_id"])
    state = {"payload": initial, "pending": [], "polls": [], "hold_poll": False, "calls": 0}
    Path("charts").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.set_offline(True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/":
                route.fulfill(content_type="text/html", body=html)
            elif path == "/data":
                if state["hold_poll"]:
                    state["polls"].append(route)
                else:
                    route.fulfill(json=state["payload"])
            elif path == "/older":
                state["calls"] += 1
                state["pending"].append(route)
            else:
                raise AssertionError(f"Unexpected request: {route.request.url}")

        context.route("**/*", route_request)
        page.goto("http://chart.test/")
        page.wait_for_function("chart.plot && chart.frame === null")
        page.locator("#autoscale").click()

        def view():
            return page.evaluate("""() => {
              const index = Math.floor(chart.left);
              return {time: chart.bars[index].time, count: chart.count,
                x: chart.plot.x + (index - chart.left + 0.5) * chart.plot.w / chart.count,
                range: {...chart.manualRange}};
            }""")

        def assert_view(expected):
            page.wait_for_function("!historyLoading && chart.frame === null")
            actual = page.evaluate("""time => {
              const index = chart.bars.findIndex(bar => bar.time === time);
              return {count: chart.count, range: {...chart.manualRange},
                x: chart.plot.x + (index - chart.left + 0.5) * chart.plot.w / chart.count};
            }""", expected["time"])
            assert actual["count"] == expected["count"]
            assert actual["range"] == expected["range"]
            assert abs(actual["x"] - expected["x"]) < 1e-8

        def prepend(count):
            payload = state["payload"]
            first = payload["bars"][0]
            older = [{**first, "time": first["time"] - 60 * i} for i in range(count, 0, -1)]
            state["payload"] = {**payload, "bars": older + payload["bars"]}
            return state["payload"]

        # A delayed old poll must never roll back an already merged history page.
        state["hold_poll"] = True
        with page.expect_request("**/data", timeout=10000):
            pass
        page.wait_for_function("chart.frame === null")
        assert len(state["polls"]) == 1
        with page.expect_request("**/older"):
            page.locator("#load-older").click()
        page.wait_for_function(
            "historyLoading && document.getElementById('selection-fields').disabled"
        )
        # Navigation remains usable while the server fetches history.
        page.locator("canvas").focus()
        page.keyboard.press("+")
        page.keyboard.press("ArrowLeft")
        page.wait_for_function("chart.frame === null")
        expected = view()
        assert state["pending"][0].request.post_data_json == {
            "selection_id": "synthetic-one", "before": initial["bars"][0]["time"]
        }
        state["pending"].pop(0).fulfill(json=prepend(60))
        assert_view(expected)
        state["hold_poll"] = False
        state["polls"].pop(0).fulfill(json=initial)
        page.wait_for_timeout(100)
        assert page.evaluate("chart.bars.length") == 180
        assert_view(expected)

        # Panning at the boundary triggers just one request despite repeated events.
        page.locator("#fit").click()
        page.locator("#autoscale").click()
        box = page.locator("canvas").bounding_box()
        page.mouse.move(box["x"] + 200, box["y"] + 100)
        with page.expect_request("**/older"):
            page.mouse.down()
            page.mouse.move(box["x"] + 250, box["y"] + 100, steps=5)
        page.mouse.move(box["x"] + 300, box["y"] + 100, steps=5)
        page.mouse.up()
        page.wait_for_function("chart.frame === null")
        expected = view()
        assert state["calls"] == 2
        assert len(state["pending"]) == 1
        state["pending"].pop(0).fulfill(status=400, json={"error": "Synthetic pacing error"})
        assert_view(expected)
        assert page.evaluate("chart.bars.length") == 180
        assert "Synthetic pacing error" in page.locator("#error").inner_text()
        page.locator("canvas").focus()
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(100)
        assert state["calls"] == 2  # Errors require an explicit retry, not a retry loop.
        with page.expect_request("**/older"):
            page.get_by_role("button", name="Retry older history", exact=True).click()
        state["pending"].pop(0).fulfill(json=prepend(30))
        assert_view(expected)
        assert not page.locator("#error").is_visible()
        assert page.evaluate("new Set(chart.bars.map(bar => bar.time)).size") == 210

        # Empty history disables both the button and further automatic requests.
        expected = view()
        with page.expect_request("**/older"):
            page.locator("#load-older").click()
        state["payload"] = {**state["payload"], "history_exhausted": True}
        state["pending"].pop(0).fulfill(json=state["payload"])
        assert_view(expected)
        assert page.locator("#load-older").is_disabled()
        assert "No older bars returned" in page.locator("#history-status").inner_text()
        calls = state["calls"]
        page.locator("canvas").focus()
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(100)
        assert state["calls"] == calls
        page.mouse.move(0, 0)
        page.screenshot(path="charts/history-viewport.png", full_page=True)

        # A new selection of the same symbol/interval still resets its viewport/state.
        state["payload"] = {**initial, "selection_id": "synthetic-two"}
        page.wait_for_function("selectionId === 'synthetic-two'", timeout=10000)
        assert page.evaluate("chart.left === 0 && chart.manualRange === null")
        assert page.evaluate("chart.bars.length") == 120
        assert page.locator("#load-older").is_enabled()
        # Fixed research ranges must not silently extend when viewing them.
        page.evaluate("draw({...initial, requested_start: '2026-01-01'}, true)")
        assert page.locator("#load-older").is_disabled()
        assert "Fixed historical range" in page.locator("#history-status").inner_text()
        page.evaluate("draw({...initial, requested_start: null}, true)")
        assert page.locator("#load-older").is_enabled()
        assert not errors, errors
        print(
            "PASS: automatic/button pagination, stable candles/zoom/manual price scale, "
            "navigation while loading, stale polls, retry, deduplication, "
            "exhaustion, selection reset"
        )
        browser.close()


if __name__ == "__main__":
    main()

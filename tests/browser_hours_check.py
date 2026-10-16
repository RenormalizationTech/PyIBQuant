"""Manual check against a connected TWS chart at localhost:8050.

Requests AAPL regular/extended 5-minute bars and older history, then restores
the regular-hours AAPL daily preview. Requires Playwright and Chrome.
"""

from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright


def main() -> None:
    Path("charts").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto("http://127.0.0.1:8050/")
        page.wait_for_function("chart.bars.length > 0")

        def select(hours, interval="5min", duration="2 D"):
            page.locator("#symbol-input").fill("AAPL")
            page.locator("#interval-input").select_option(interval)
            page.locator("#duration-input").fill(duration)
            page.locator("#hours-input").select_option(hours)
            with page.expect_response(
                lambda r: r.url.endswith("/chart") and r.request.method == "POST",
                timeout=60000,
            ) as response:
                page.locator("#load-chart").click()
            assert response.value.status == 200, response.value.text()
            payload = response.value.json()
            page.wait_for_function("!loading && chart.frame === null")
            assert payload["regular_hours"] is (hours == "regular")
            assert page.locator("#hours-input").input_value() == hours
            return payload

        regular = select("regular")
        extended = select("extended")
        assert len(extended["bars"]) > len(regular["bars"])
        ny = ZoneInfo("America/New_York")

        def outside_regular(bar):
            stamp = datetime.fromtimestamp(bar["time"], UTC).astimezone(ny)
            return stamp.time() < time(9, 30) or stamp.time() >= time(16)

        assert not any(outside_regular(bar) for bar in regular["bars"])
        assert any(outside_regular(bar) for bar in extended["bars"])
        assert "Extended hours included" in page.locator("#meta").inner_text()
        assert "New York" in page.locator("#meta").inner_text()
        with page.expect_response(lambda r: r.url.endswith("/older"), timeout=60000) as older:
            page.locator("#load-older").click()
        assert older.value.status == 200, older.value.text()
        assert older.value.json()["regular_hours"] is False
        page.wait_for_function("!historyLoading && chart.frame === null")
        page.screenshot(path="charts/extended-hours.png", full_page=True)
        # Reject invalid hours types without replacing the active extended session.
        invalid = page.request.post("http://127.0.0.1:8050/chart", data={
            "symbol": "AAPL", "interval": "5min", "duration": "2 D",
            "regular_hours": "false",
        })
        assert invalid.status == 400
        assert page.request.get("http://127.0.0.1:8050/data").json()["regular_hours"] is False
        restored = select("regular")
        assert not any(outside_regular(bar) for bar in restored["bars"])
        # A second tab reads the active hours setting from the server.
        other = browser.new_page()
        other.goto("http://127.0.0.1:8050/")
        assert other.locator("#hours-input").input_value() == "regular"
        other.close()
        select("regular", "1d", "6 M")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        assert not errors, errors
        print(
            f"PASS: regular {len(regular['bars'])} bars, extended {len(extended['bars'])} bars; "
            "outside-session data, older history, type validation, reload, mobile, restore"
        )
        browser.close()


if __name__ == "__main__":
    main()

"""Explicit offline Chrome check of the generated paper account report."""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("charts/paper/strategy-review.html"))
    args = parser.parse_args()
    path = args.report.resolve()
    if not path.exists():
        raise SystemExit(
            "Generate it offline: python examples/paper_report.py "
            "--output charts/paper/strategy-review.html"
        )
    output = Path("charts/paper/visual-checks")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 950}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith("file:") else route.abort()
            ),
        )
        page.goto(path.as_uri())
        page.locator("#cards .card b").first.wait_for()
        assert page.locator("canvas").count() == 5
        assert page.locator("#positions table").count() == 1
        assert page.locator("#cards .card").count() == 9
        assert page.locator("#run-cards .card").count() == 6
        options = page.locator("#run-select option").count()
        if options:
            page.select_option("#run-select", index=0)
            page.select_option("#run-select", index=options - 1)
            assert page.locator("#run-orders table").count() <= 1
            page.locator("section").filter(has=page.locator("#run-select")).screenshot(
                path=str(output / "strategy-runs-desktop.png")
            )
        page.set_viewport_size({"width": 700, "height": 900})
        page.screenshot(path=str(output / "account-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 950})
        page.screenshot(path=str(output / "account-desktop.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print("PASS: account/run cards, five canvases, run selection, resizing and no JS errors")


if __name__ == "__main__":
    main()

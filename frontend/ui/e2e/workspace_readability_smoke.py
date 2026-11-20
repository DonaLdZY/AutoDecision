import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE = os.environ.get("AUTODECISION_UI_URL", "http://127.0.0.1:5180")
OUTPUT = Path(__file__).resolve().parents[4] / ".codex-work" / "ui-readability-v0.10.3"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def mock_api(route):
            path = route.request.url.split("/api", 1)[-1].split("?", 1)[0]
            data = [] if path == "/tasks" else {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", mock_api)
        page.goto(f"{BASE}/?demo=1", wait_until="networkidle")
        page.locator(".workspace-heading h2").wait_for()

        page.get_by_role("tab", name="任务定义").click()
        page.locator("details.definition-process > summary").click()
        page.get_by_role("heading", name="任务定义", exact=True).wait_for()
        definition_text = page.locator("body").inner_text()
        for internal_label in ("READY", "PASS", "WAIT", "REVIEW", "Task Contract Compiler"):
            assert internal_label not in definition_text, f"internal task-definition label is visible: {internal_label}"
        page.screenshot(path=str(OUTPUT / "task-definition-desktop.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(OUTPUT / "task-definition-mobile.png"), full_page=True)
        mobile_width = page.evaluate("document.documentElement.scrollWidth")
        assert mobile_width <= 391, f"task definition overflows mobile viewport: {mobile_width}px"

        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("tab", name="数据理解").click()
        page.get_by_role("heading", name="数据总体认知").wait_for()
        cognition_text = page.locator("body").inner_text()
        for internal_label in ("LLM review", "agent 探查轨迹", "planned read", "final read"):
            assert internal_label not in cognition_text, f"internal data-cognition label is visible: {internal_label}"
        page.screenshot(path=str(OUTPUT / "data-cognition-desktop.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(OUTPUT / "data-cognition-mobile.png"), full_page=True)
        mobile_width = page.evaluate("document.documentElement.scrollWidth")
        assert mobile_width <= 391, f"data cognition overflows mobile viewport: {mobile_width}px"
        assert not errors, f"browser errors: {errors}"
        print(json.dumps({"passed": True, "screenshots": str(OUTPUT), "browser_errors": errors}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()

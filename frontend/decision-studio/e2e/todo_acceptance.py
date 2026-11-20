"""Smoke checks for the chat-to-research and existing-context affordances."""
from __future__ import annotations

from pathlib import Path
from playwright.sync_api import sync_playwright


BASE = "http://127.0.0.1:5178"
OUT = Path(__file__).resolve().parents[1] / "review-v0.2.6"
OUT.mkdir(exist_ok=True)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{BASE}/#chat")
        page.wait_for_load_state("networkidle")
        assert page.get_by_text("已连接", exact=True).is_visible()

        project_select = page.get_by_label("当前数据项目", exact=True)
        for option in project_select.locator("option").all():
            if "压滤液" in option.inner_text():
                project_select.select_option(option.get_attribute("value"))
                break
        page.wait_for_timeout(500)

        # Open an existing project conversation when one is present; otherwise
        # the empty state still verifies the new research entry point.
        for button in page.get_by_role("button").all():
            if "压滤液" in button.inner_text() and "预测" in button.inner_text():
                button.click()
                break
        page.wait_for_timeout(500)

        if page.get_by_role("button", name="改为新研发", exact=True).count():
            page.get_by_role("button", name="改为新研发", exact=True).first.click()
        else:
            page.get_by_role("button", name="研发新的能力", exact=True).click()

        dialog = page.get_by_role("dialog")
        assert dialog.get_by_text("创建研发任务", exact=True).is_visible()
        goal = dialog.get_by_label("研发目标", exact=True)
        assert goal.input_value().strip()
        assert dialog.get_by_role("button", name="让模型润色任务", exact=True).is_visible()
        page.screenshot(path=str(OUT / "chat-to-research.png"))
        browser.close()


if __name__ == "__main__":
    main()

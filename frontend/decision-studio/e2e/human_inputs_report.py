"""Browser checks for readable input, unchanged numeric semantics and safe reports."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from solution_check_readability import CONFIG, TASK, TASK_ID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5178")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[3] / ".codex-work/audit-20261029/frontend"
    output.mkdir(parents=True, exist_ok=True)
    project = {"id": "human-inputs", "name": "试算数据", "input_root": CONFIG["input_root"], "created_at": 1}
    schema = {"type": "object", "required": ["temperature", "enabled"], "properties": {
        "temperature": {"title": "温度", "type": "number"},
        "enabled": {"title": "是否启用", "type": "boolean"},
    }}
    markdown = "# 房价报告\n\n## 评价结果\n\n|指标|结果|\n|---|---|\n|对数误差|0.12|\n\n<script>window.badReport=1</script><img src=x onerror='window.badReport=1'>"
    received = []
    errors = []
    reads = {"delivery": 0}

    def api(route):
        path = urlparse(route.request.url).path.removeprefix("/api")
        if path == "/studio/state":
            data = {"version": "fixture", "projects": [project], "tasks": [TASK], "packages": [],
                    "links": [{"id": TASK_ID, "project_id": project["id"]}], "conversations": [], "invocations": []}
        elif path == f"/tasks/{TASK_ID}/snapshot":
            data = {"task": TASK, "auto_realize": {}, "auto_ml": {},
                    "auto_report": {"report_markdown": markdown}}
        elif path.endswith("/delivery/verify"):
            received.append(route.request.post_data_json)
            data = {"status": "passed"}
        elif path.endswith("/delivery"):
            reads["delivery"] += 1
            data = {"report_ready": True, "report_status": "ready", "delivery_id": "a" * 32, "structure_ready": True,
                    "draft": {"input_schema": schema, "input_description": "输入温度与运行状态", "dataframes": []},
                    "issues": [], "verification": {"status": "passed" if received else "not_run"}}
        elif path.endswith("/final-evaluation"):
            data = {"status": "not_started"}
        else:
            data = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data, ensure_ascii=False))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/**", api)
        page.goto(args.url + "/#tasks", wait_until="networkidle")
        page.get_by_role("button", name=TASK["task_name"], exact=False).click()
        page.get_by_role("button", name="05 报告").click()
        expect(page.get_by_role("heading", name="评价结果", exact=True)).to_be_visible()
        expect(page.locator(".report-prose table")).to_be_visible()
        assert page.evaluate("window.badReport === undefined")
        assert page.locator(".report-prose img, .report-prose script").count() == 0
        with page.expect_download() as event:
            page.get_by_role("button", name="下载报告", exact=True).click()
        event.value.save_as(str(output / "report-download.md"))
        assert (output / "report-download.md").read_text(encoding="utf-8") == markdown
        page.screenshot(path=str(output / "report-desktop.png"), full_page=True)
        page.get_by_role("button", name="04 验证与发布").click()
        expect(page.get_by_label("温度", exact=False)).to_be_visible()
        expect(page.get_by_label("输入 JSON 原文")).to_be_hidden()
        page.get_by_label("温度", exact=False).fill("0")
        page.get_by_label("是否启用", exact=False).select_option("false")
        page.get_by_role("checkbox", name="已核对输入，执行本地推理，不重新训练").check()
        page.get_by_role("button", name="运行交付试算", exact=True).click()
        expect(page.get_by_text("上次提交输入试算成功", exact=True)).to_be_visible()
        assert json.loads(received[0]["data_json"]) == {"temperature": 0, "enabled": False}, received
        count = reads["delivery"]
        page.wait_for_timeout(1100)
        assert reads["delivery"] == count
        for width, height in [(1440, 1000), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(output / f"input-{width}.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print(json.dumps({"passed": True, "checks": ["report_layout", "report_sanitized", "markdown_download",
        "form_preserves_zero_and_false", "no_repeated_inspection", "responsive"], "browser_errors": errors}))


if __name__ == "__main__":
    main()

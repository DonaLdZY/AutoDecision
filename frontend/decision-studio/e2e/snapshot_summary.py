"""Verify summary-only polling and on-demand developer detail reads."""
import argparse
import json
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from solution_check_readability import TASK, TASK_ID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5178")
    args = parser.parse_args()
    reads = {"summary": 0, "full": 0, "solution": 0}
    errors = []
    task = {**TASK, "status": "running", "phase": "automl"}
    project = {"id": "summary-project", "name": "摘要测试", "input_root": TASK["input_root"], "created_at": 1}
    node = {"id": "one", "stage": "draft", "plan": "训练回归模型", "metric": .12,
            "maximize": False, "search_eligible": True, "is_buggy": False, "is_valid": True}

    def api(route):
        url = urlparse(route.request.url)
        path = url.path.removeprefix("/api")
        if path == "/studio/state":
            data = {"projects": [project], "tasks": [task], "packages": [],
                    "links": [{"id": TASK_ID, "project_id": project["id"]}], "conversations": [], "invocations": []}
        elif path == f"/tasks/{TASK_ID}/snapshot":
            view = parse_qs(url.query).get("view", ["full"])[0]
            reads[view] += 1
            data = {"task": task, "auto_realize": {}, "auto_report": {},
                    "auto_ml": {"nodes": [{**node, **({"code": "print('lazy source')"} if view == "full" else {})}],
                                "split_seed_check": {"status": "matched"}, "best_node_id": "one"}}
        elif path.endswith("/solution"):
            reads["solution"] += 1
            data = {}
        else:
            data = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data, ensure_ascii=False))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/api/**", api)
        page.goto(args.url + "/#tasks", wait_until="networkidle")
        page.get_by_role("button", name=TASK["task_name"], exact=False).click()
        page.get_by_role("button", name="03 算法搜索").click()
        expect(page.get_by_text("训练回归模型", exact=True)).to_be_visible()
        page.wait_for_timeout(5500)
        assert reads["summary"] >= 2 and reads["full"] == 0 and reads["solution"] == 0, reads
        page.get_by_text("查看方案代码", exact=True).click()
        expect(page.locator(".code-block")).to_contain_text("lazy source")
        assert reads["full"] == 1, reads
        page.wait_for_timeout(5500)
        assert reads["full"] == 1 and reads["summary"] >= 3, reads
        assert not errors, errors
        browser.close()
    print(json.dumps({"reads": reads, "browser_errors": errors}))


if __name__ == "__main__":
    main()

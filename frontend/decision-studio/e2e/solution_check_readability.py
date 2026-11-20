"""Browser regression for readable search, invocation and solution-check views."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


BASE = os.environ.get("AUTODECISION_UI_URL", "http://127.0.0.1:5178")
ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / ".codex-work" / "ui-v0.10.3"
TASK_ID = "readability-fixture"
PACKAGE_ID = "readability-package"
INVOCATION_ID = "readability-invocation"
CONFIG = {
    "task_name": "风机能耗预测",
    "input_root": "C:/fixture/input",
    "output_root": "C:/fixture/output",
    "output_language": "zh",
    "auto_realize": {"task_hint": "预测未来一小时能耗"},
    "auto_ml": {
        "goal": "预测未来一小时能耗",
        "eval": "MAE，时间顺序切分",
        "steps": 20,
        "time_limit_secs": 1800,
        "parallel_search_num": 1,
        "web_research_enabled": True,
    },
    "auto_report": {"enabled": True},
    "resources": {"cpu_cores": 2, "memory_limit_gb": 4, "accelerator_mode": "none"},
}
TASK = {
    "id": TASK_ID,
    "task_name": CONFIG["task_name"],
    "input_root": CONFIG["input_root"],
    "output_root": CONFIG["output_root"],
    "created_at": 1790000000,
    "updated_at": 1790000100,
    "status": "completed",
    "phase": "automl_completed",
    "run_dir": "C:/fixture/run",
    "auto_ml_log_dir": "C:/fixture/run/automl/logs",
    "config": CONFIG,
    "execution_config": CONFIG,
}
PACKAGE = {
    "id": PACKAGE_ID,
    "project_id": "readability-project",
    "task_id": TASK_ID,
    "name": "风机能耗预测",
    "version": "2.1.0",
    "description": "根据运行状态估计未来一小时能耗。",
    "created_at": 1790000000,
    "entrypoint": "predict",
    "input_schema": {},
    "output_description": "未来一小时能耗",
    "fingerprint": "fixture",
    "verification_summary": "已通过接口试算",
    "manifest": {},
    "files": [],
    "validation": {"trial_status": "passed", "quality_status": "evaluated"},
}
COUNTS = {"solution": 0, "invocation_summary": 0, "invocation_full": 0}
SEARCH_METRICS = {
    "status": "success",
    "elapsed_ms": 1240,
    "search": {
        "accepted_count": 2,
        "source_hosts": ["scikit-learn.org", "xgboost.readthedocs.io"],
    },
    "fetch_attempts": [{"status": "success"}],
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    project = {
        "id": "readability-project",
        "name": "风机运行数据",
        "input_root": CONFIG["input_root"],
        "description": "风机能耗预测",
        "created_at": 1790000000,
    }
    invocation = {
        "id": INVOCATION_ID,
        "project_id": project["id"],
        "conversation_id": "readability-conversation",
        "title": "预测下一小时能耗",
        "status": "completed",
        "package_ids": [PACKAGE_ID],
        "created_at": 1790000100,
        "duration_seconds": 1.4,
        "result": {"prediction": 124.5, "unit": "kWh"},
        "steps": [{
            "index": 0,
            "package_id": PACKAGE_ID,
            "input_mode": "project",
            "input_summary": {
                "source_count": 3,
                "row_count": 240,
                "first_observation": "2026-10-01",
                "last_observation": "2026-10-10",
                "cutoff": "2026-10-10 23:00",
            },
        }],
    }
    workspace = {
        "version": "fixture",
        "projects": [project],
        "archived_projects": [],
        "conversations": [],
        "packages": [PACKAGE],
        "invocations": [invocation],
        "tasks": [TASK],
        "links": [{"id": TASK_ID, "project_id": project["id"]}],
    }
    snapshot = {
        "task": TASK,
        "auto_realize": {},
        "auto_ml": {
            "nodes": [{
                "id": "candidate-1",
                "stage": "draft",
                "label": "LightGBM 基线",
                "plan": "按时间顺序切分数据并训练梯度提升模型。",
                "metric": 18.2,
                "maximize": False,
                "is_buggy": False,
                "is_valid": True,
                "search_eligible": True,
                "evaluation_protocol": {"metric_name": "MAE"},
            }],
            "best_node_id": "candidate-1",
            "split_seed_check": {"status": "matched"},
            "web_research_metrics": SEARCH_METRICS,
        },
        "auto_report": {},
    }
    solution = {
        "available": True,
        "exportable": True,
        "trial_ready": True,
        "issues": [],
        "node_id": "candidate-1",
        "manifest": {"entrypoint": "predict"},
        "verification": {},
        "files": [],
        "usage": "",
        "portability": "wrapper_present",
        "notice": "结构检查不代表业务验收。",
        "contracts": [],
    }

    def mock_api(route) -> None:
        path = urlparse(route.request.url).path.removeprefix("/api")
        data = {}
        if path == "/studio/state":
            data = workspace
        elif path == f"/tasks/{TASK_ID}/snapshot":
            data = snapshot
        elif path == f"/tasks/{TASK_ID}/solution":
            COUNTS["solution"] += 1
            data = solution
        elif path == f"/studio/tasks/{TASK_ID}/delivery":
            data = {
                "report_status": "not_ready",
                "report_ready": False,
                "structure_ready": True,
                "issues": [],
                "verification": {"status": "not_run"},
            }
        elif path == f"/studio/tasks/{TASK_ID}/final-evaluation":
            data = {"status": "not_started", "can_repair_loading": False}
        elif path == f"/studio/invocations/{INVOCATION_ID}":
            if route.request.url.endswith("?view=summary"):
                COUNTS["invocation_summary"] += 1
                data = invocation
            else:
                COUNTS["invocation_full"] += 1
                data = {
                    **invocation,
                    "steps": [{
                        **invocation["steps"][0],
                        "execution_evidence": {"worker": "local"},
                    }],
                }
        else:
            data = {}
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(data, ensure_ascii=False),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(f"""(() => {{
          const originalFetch = window.fetch.bind(window);
          let checks = 0;
          window.fetch = async (input, init) => {{
            const url = typeof input === "string" ? input : input.url;
            if (url.includes("/api/tasks/{TASK_ID}/solution") && ++checks === 2) {{
              await new Promise(resolve => setTimeout(resolve, 1200));
            }}
            return originalFetch(input, init);
          }};
        }})();""")
        page.route("**/api/**", mock_api)
        page.goto(f"{BASE}/#tasks", wait_until="networkidle")
        expect(page.get_by_role("button", name="风机能耗预测", exact=False)).to_be_visible()
        page.get_by_role("button", name="风机能耗预测", exact=False).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.get_by_role("button", name="03 算法搜索").click()
        expect(page.get_by_role("region", name="网页检索结果")).to_contain_text("找到 2 条公开参考资料")
        expect(page.get_by_role("region", name="网页检索结果")).to_contain_text("scikit-learn.org")
        page.screenshot(path=str(OUTPUT / "search-results-desktop.png"), full_page=True)

        page.get_by_role("button", name="04 验证与发布").click()
        page.get_by_role("button", name="检查成果", exact=True).click()
        expect(page.get_by_text("可本地试算", exact=True)).to_be_visible()
        assert COUNTS["solution"] == 1, COUNTS
        page.get_by_role("button", name="重新检查", exact=True).click()
        expect(page.get_by_text("正在复核；下方保留上次结果。")).to_be_visible()
        expect(page.get_by_text("尚未检查成果。")).to_have_count(0)
        expect(page.get_by_text("可本地试算", exact=True)).to_be_visible()
        expect(page.get_by_text("正在复核；下方保留上次结果。")).to_have_count(0, timeout=5000)
        assert COUNTS["solution"] == 2, COUNTS
        stable_counts = COUNTS["solution"]
        page.wait_for_timeout(6200)
        assert COUNTS["solution"] == stable_counts, "completed task triggered an automatic solution recheck"

        page.set_viewport_size({"width": 1024, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(OUTPUT / "solution-check-tablet.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(OUTPUT / "solution-check-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="关闭详情", exact=True).click()
        page.locator(".main-nav").get_by_role("button", name="调用记录", exact=True).click()
        page.locator(".live-list-row").filter(has_text="预测下一小时能耗").click()
        expect(page.get_by_text("风机能耗预测", exact=True)).to_be_visible()
        expect(page.get_by_text("v2.1.0", exact=True)).to_have_count(0)
        expect(page.get_by_text("3 个数据源 · 240 条记录", exact=False)).to_be_visible()
        expect(page.get_by_text(PACKAGE_ID, exact=False)).to_be_hidden()
        page.screenshot(path=str(OUTPUT / "invocation-desktop.png"), full_page=True)
        page.get_by_text("技术详情", exact=True).click()
        expect(page.get_by_text("步骤 1 · 原始记录", exact=True)).to_be_visible()
        expect(page.get_by_text(PACKAGE_ID, exact=False)).to_be_hidden()
        page.get_by_text("步骤 1 · 原始记录", exact=True).click()
        expect(page.get_by_text(PACKAGE_ID, exact=False)).to_be_visible()
        assert COUNTS["invocation_summary"] == 1, COUNTS
        assert COUNTS["invocation_full"] == 1, COUNTS
        assert not errors, errors
        print(json.dumps({
            "passed": True,
            "api_reads": COUNTS,
            "browser_errors": errors,
            "screenshots": str(OUTPUT),
        }, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()

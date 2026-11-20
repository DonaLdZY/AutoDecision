import json
import os
import time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("AUTODECISION_UI_URL", "http://127.0.0.1:5180")
TASK_ID = "workbench-refresh-fixture"
CONFIG = {
    "task_name": "Refresh regression fixture",
    "input_root": "C:/fixture/input",
    "output_root": "C:/fixture/output",
    "output_language": "zh",
    "auto_realize": {"task_hint": "Regression test task"},
    "auto_ml": {"goal": "Regression test task", "eval": "accuracy", "steps": 2, "time_limit_secs": 120},
    "auto_report": {"enabled": False},
    "resources": {"cpu_cores": 2, "memory_limit_gb": 4, "accelerator_mode": "none"},
}
TASK = {
    "id": TASK_ID,
    "task_name": CONFIG["task_name"],
    "input_root": CONFIG["input_root"],
    "output_root": CONFIG["output_root"],
    "created_at": 1782000000,
    "updated_at": 1782000000,
    "status": "completed",
    "phase": "completed",
    "run_dir": "C:/fixture/run",
    "auto_ml_log_dir": "C:/fixture/run/automl/logs",
    "config": CONFIG,
}
COUNTS = {"task_list": 0, "snapshot": 0, "solution": 0, "trials": 0}
FIXTURE_STATUS = "completed"
READINESS = {
    "version": "test",
    "checked_at": 1782000000,
    "ready": True,
    "output_root": "C:/fixture/output",
    "lifecycle": "",
    "data_policy": "",
    "checks": [],
    "providers": [],
}


def main():
    global FIXTURE_STATUS
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        def mock_api(route):
            request = route.request
            path = request.url.split("/api", 1)[-1].split("?", 1)[0]
            data = {}
            if path == "/tasks" and request.method == "GET":
                COUNTS["task_list"] += 1
                data = [{
                    **TASK,
                    "status": FIXTURE_STATUS,
                    "phase": FIXTURE_STATUS,
                    "updated_at": TASK["updated_at"] + COUNTS["task_list"],
                }]
            elif path == f"/tasks/{TASK_ID}/snapshot":
                COUNTS["snapshot"] += 1
                data = {
                    "task": {
                        **TASK,
                        "status": FIXTURE_STATUS,
                        "phase": FIXTURE_STATUS,
                        "updated_at": TASK["updated_at"] + COUNTS["snapshot"],
                    },
                    "auto_realize": {},
                    "auto_ml": {"nodes": [], "best_node_id": ""},
                    "auto_report": {},
                }
            elif path == f"/tasks/{TASK_ID}/solution":
                COUNTS["solution"] += 1
                data = {"available": False, "exportable": False, "issues": [], "files": []}
            elif path == f"/tasks/{TASK_ID}/solution/trials":
                COUNTS["trials"] += 1
                data = []
            elif path.startswith("/system/readiness"):
                data = READINESS
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(data, ensure_ascii=False),
            )

        def wait_for_count(key, target, timeout=8):
            deadline = time.monotonic() + timeout
            while COUNTS[key] < target and time.monotonic() < deadline:
                page.wait_for_timeout(50)
            assert COUNTS[key] >= target, f"{key} did not reach {target}: {COUNTS[key]}"

        page.route("**/api/**", mock_api)
        page.goto(BASE, wait_until="networkidle")
        page.get_by_role("heading", name="Refresh regression fixture").wait_for()
        page.get_by_role("button", name="方案交付", exact=True).click()
        page.get_by_role("heading", name="选定方案与交付").wait_for()
        page.wait_for_timeout(6500)

        assert COUNTS == {"task_list": 1, "snapshot": 1, "solution": 1, "trials": 1}, (
            f"idle task performed redundant reads: {COUNTS}"
        )

        FIXTURE_STATUS = "running"
        wait_for_count("task_list", 2, timeout=12)
        wait_for_count("snapshot", 2)
        wait_for_count("solution", 2)
        wait_for_count("trials", 2)
        stable_solution_reads = COUNTS["solution"]
        stable_trial_reads = COUNTS["trials"]
        page.wait_for_timeout(3200)
        assert COUNTS["solution"] == stable_solution_reads, "stable running state rechecked the solution"
        assert COUNTS["trials"] == stable_trial_reads, "stable running state reloaded trial history"
        assert COUNTS["snapshot"] >= 3, "running task did not resume snapshot polling"

        previous_list_reads = COUNTS["task_list"]
        previous_snapshot_reads = COUNTS["snapshot"]
        FIXTURE_STATUS = "completed"
        wait_for_count("task_list", previous_list_reads + 1)
        wait_for_count("snapshot", previous_snapshot_reads + 1)
        wait_for_count("solution", stable_solution_reads + 1)
        wait_for_count("trials", stable_trial_reads + 1)
        completed_counts = dict(COUNTS)
        page.wait_for_timeout(6500)
        assert COUNTS == completed_counts, f"completed task continued polling: {COUNTS}"
        assert not page_errors, f"browser errors: {page_errors}"
        print(json.dumps({"passed": True, **COUNTS, "browser_errors": page_errors}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()

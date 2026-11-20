"""Browser contract tests with an isolated API fixture; never touches user runs."""
import copy
import json
import os
from pathlib import Path
import time
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("AUTODECISION_UI_URL", "http://127.0.0.1:5186")
OUTPUT = Path(__file__).resolve().parents[3] / ".codex-work/local-product-browser"
OUTPUT.mkdir(parents=True, exist_ok=True)
config = {"task_name": "本地产品验收", "input_root": "D:/fixture/input", "output_root": "D:/fixture/runs", "output_language": "zh",
          "auto_realize": {"task_hint": "降低每日电耗预测误差", "llm_concurrency": 8},
          "auto_ml": {"time_limit_secs": 1800, "parallel_search_num": 1, "steps": 12},
          "auto_report": {"enabled": True}, "resources": {"cpu_cores": 2, "memory_limit_gb": 4, "accelerator_mode": "none"}}
task = {"id": "fixture-original", "task_name": config["task_name"], "input_root": config["input_root"], "output_root": config["output_root"],
        "created_at": 1, "updated_at": 1, "status": "idle", "phase": "config", "config": config, "run_dir": None}
tasks = [task]
requests = []
ready = False

def route_api(route):
    global ready
    request = route.request
    path = request.url.split("/api", 1)[1].split("?", 1)[0]
    requests.append((request.method, path))
    status, data = 200, {}
    if path == "/tasks" and request.method == "GET": data = tasks
    elif path == "/fs/roots": data = {"roots": ["D:/fixture"]}
    elif path.endswith("/snapshot"):
        current = next(t for t in tasks if t["id"] == path.split("/")[2])
        data = {"task": current, "auto_realize": {"current_state": {}, "events": []}, "auto_ml": {"nodes": [], "pending_nodes": [], "events": []}, "auto_report": {}}
    elif path == "/system/readiness":
        data = {"version": "0.3.0-local", "checked_at": time.time(), "ready": ready, "checks": [{"key": "python", "label": "Python 环境", "status": "pass" if ready else "fail", "detail": "测试环境"}], "providers": [], "lifecycle": "关闭浏览器不会停止后台任务。", "data_policy": "本地数据与模型请求分开。", "output_root": "D:/fixture/runs"}
    elif request.method == "PUT" and path.startswith("/tasks/"):
        current = next(t for t in tasks if t["id"] == path.split("/")[2])
        current["config"] = request.post_data_json
        data = current
    elif path == "/tasks/start":
        task.update(status="running", phase="automl", run_dir="D:/fixture/runs/first", execution_config=copy.deepcopy(task["config"]))
        data = {"status": "started", "task_id": task["id"]}
    elif path == "/tasks/resume":
        task.update(status="running", phase="automl")
        data = {"status": "started", "task_id": task["id"]}
    elif path.endswith("/experiments"):
        if request.method == "POST":
            child = copy.deepcopy(task)
            child.update(id="fixture-second", task_name="第二次实验", status="idle", phase="config", run_dir=None, execution_config=None, parent_task_id=task["id"], experiment_group_id=task["id"], created_at=2)
            child["config"]["task_name"] = child["task_name"]
            tasks.append(child)
            data = child
        else: data = tasks
    elif path.endswith("/solution"):
        data = {"available": True, "exportable": True, "trial_ready": True, "issues": [], "node_id": "selected-final-node", "manifest": {"entrypoint": "predict", "evaluation_protocol": {"metric_name": "MAE", "maximize": False, "evaluation_count": 8, "contract_id": "frozen-contract"}}, "files": [{"path": "solution.py", "size": 256}, {"path": "model.bin", "size": 1024}], "directory": "D:/fixture/best_solution", "portability": "wrapper_present", "notice": "包结构检查不代表业务达标。"}
    elif path.endswith("/solution/trial"):
        assert request.post_data_json["data_json"] == '{"value":7}'
        data = {"trial_id": "test-trial", "result": {"answer": 14}, "scope": "单独记录试算，不改写历史成绩"}
    elif path.endswith("/solution/trials"): data = []
    elif path.endswith("/solution/bundle"):
        route.fulfill(status=200, body=b"PK-fixture", headers={"Content-Type": "application/zip"})
        return
    elif path == "/system/diagnostics": data = {"release": "0.3.0-local", "tasks": []}
    else: status, data = 404, {"detail": "unmocked endpoint: " + path}
    route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="msedge" if os.name == "nt" else None)
    page = browser.new_page(viewport={"width": 1440, "height": 1080})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/api/**", route_api)
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="目标、数据与预算")).to_be_visible()
    expect(page.get_by_text("有项目需要处理，暂不启动实验", exact=False)).to_be_visible()
    page.get_by_role("button", name="检查并开始", exact=True).click()
    expect(page.get_by_role("button", name="返回工作台")).to_be_visible()
    assert ("POST", "/tasks/start") not in requests
    ready = True
    page.get_by_role("button", name="返回工作台").click()
    page.get_by_role("button", name="检查并开始", exact=True).click()
    dialog = page.get_by_role("dialog", name="开始新实验")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("button", name="返回检查")).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(dialog.get_by_role("button", name="开始实验", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    page.get_by_role("button", name="检查并开始", exact=True).click()
    page.get_by_role("button", name="开始实验", exact=True).click()
    expect(page.get_by_role("button", name="停止并保留进度")).to_be_visible()
    page.get_by_role("tab", name="任务定义", exact=True).click()
    expect(page.locator(".stage-metric")).to_have_text("方案搜索")
    assert requests.count(("POST", "/tasks/start")) == 1
    assert not any("rerun-full" in path for _, path in requests)
    task.update(status="interrupted_resumable", phase="automl_interrupted")
    expect(page.get_by_role("button", name="恢复实验", exact=True)).to_be_visible(timeout=8000)
    page.get_by_role("button", name="恢复实验", exact=True).click()
    page.get_by_role("button", name="检查并恢复", exact=True).click()
    expect(page.get_by_role("button", name="停止并保留进度")).to_be_visible()
    assert requests.count(("POST", "/tasks/resume")) == 1
    task.update(status="completed", phase="completed")
    expect(page.get_by_role("button", name="查看成果", exact=True)).to_be_visible(timeout=8000)
    page.get_by_role("button", name="查看成果", exact=True).click()
    expect(page.get_by_text("selected-final-node", exact=True)).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role("button", name="导出方案包").click()
    assert download.value.suggested_filename.endswith(".zip")
    page.get_by_text("用已有方案试算", exact=True).click()
    page.get_by_label("输入 JSON", exact=True).fill('{"value":7}')
    page.get_by_role("button", name="运行一次试算", exact=True).click()
    expect(page.get_by_role("button", name="保存试算结果与来源")).to_be_visible()
    assert requests.count(("POST", "/tasks/fixture-original/solution/trial")) == 1
    page.screenshot(path=str(OUTPUT / "solution-desktop.png"), full_page=True)
    page.get_by_role("button", name="新建实验", exact=True).click()
    expect(page.get_by_role("dialog", name="任务配置", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="搜索算法参数")).not_to_be_visible()
    page.get_by_label("显示高级算法参数与阶段操作").check()
    expect(page.get_by_role("button", name="搜索算法参数")).to_be_visible()
    page.get_by_role("button", name="关闭任务配置").click()
    page.get_by_role("button", name="实验历史", exact=True).click()
    expect(page.locator(".product-table tbody tr")).to_have_count(2)
    assert task["status"] == "completed"
    page.screenshot(path=str(OUTPUT / "experiments-desktop.png"), full_page=True)
    page.get_by_role("button", name="任务概览", exact=True).click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(OUTPUT / "overview-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    page.set_viewport_size({"width": 1440, "height": 1080})
    page.goto(BASE + '/?demo=1')
    page.wait_for_load_state('networkidle')
    expect(page.locator('.graph-node')).to_have_count(20)
    page.get_by_role('button', name='任务重放', exact=True).click()
    expect(page.get_by_role('region', name='任务重放控制')).to_be_visible()
    slider = page.get_by_role('slider', name='重放进度')
    slider.evaluate("el => {el.value = el.max; el.dispatchEvent(new Event('input', {bubbles:true}))}")
    page.get_by_role('tab', name='自动机器学习', exact=True).click()
    expect(page.locator('.graph-node')).to_have_count(20)
    page.screenshot(path=str(OUTPUT / 'demo-replay.png'), full_page=True)
    assert not errors, errors
    browser.close()
    (OUTPUT / "result.json").write_text(json.dumps({"status": "passed", "requests": requests, "page_errors": errors, "backend": "isolated fixture", "screenshots": ["solution-desktop.png", "experiments-desktop.png", "overview-mobile.png", "demo-replay.png"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Local product browser scenarios passed; original runs untouched.")

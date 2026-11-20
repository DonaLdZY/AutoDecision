"""Real isolated Gateway/browser acceptance; no provider or model fixtures.

Uses the completed house-r1/r2 experiments at 18081 and never starts training.
Publication and paid planning/decision calls are explicit test actions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
UI = "http://127.0.0.1:5178"
API = "http://127.0.0.1:18081"


def api(path, value=None):
    req = urllib.request.Request(
        API + "/api" + path,
        None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


@contextmanager
def evidence(phase, out, checks, errors, calls, failed):
    """Retain partial acceptance evidence when a real provider or assertion fails."""
    result = {"phase": phase, "started_at": time.time(), "status": "running"}
    try:
        yield
        result["status"] = "passed"
    except BaseException as exc:
        result.update(status="failed", failure=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        result.update(
            finished_at=time.time(), checks=checks, page_errors=errors,
            failed_http=failed, request_count=len(calls), requests=calls,
            request_counts=dict(Counter(f'{c["method"]} {c["url"]}' for c in calls)),
        )
        (out / "browser-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["inspect", "publish", "decision", "export", "mobile"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / ".codex-work") or out.exists():
        raise ValueError("Use a new evidence directory in .codex-work.")
    out.mkdir(parents=True)
    checks, errors, calls, failed = [], [], [], []
    receipts = {
        name: json.loads((ROOT / ".codex-work/audit-20261029" / name / "receipt.json").read_text(encoding="utf-8"))
        for name in ["house-r1", "house-r2"]
    }

    def passed(name):
        checks.append(name)
        print("PASS", name, flush=True)

    with evidence(args.phase, out, checks, errors, calls, failed), sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="msedge" if sys.platform == "win32" else None)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(r):
            target = r.request.url.replace(UI + "/api", API + "/api")
            calls.append({"method": r.request.method, "url": target, "time": time.time()})
            response = r.fetch(url=target, timeout=450000)
            if response.status >= 400:
                failed.append({"status": response.status, "url": target})
            r.fulfill(response=response)

        page.route("**/api/**", route)
        page.goto(UI, wait_until="networkidle")
        expect(page.get_by_text("已连接", exact=True)).to_be_visible(timeout=15000)

        def select(run):
            page.locator("#live-project").select_option(receipts[run]["project_id"])
            page.wait_for_load_state("networkidle")

        def nav(name):
            page.locator(".main-nav").get_by_role("button", name=name, exact=True).click()
            page.wait_for_load_state("networkidle")

        def shot(name):
            page.screenshot(path=str(out / name), full_page=True, animations="disabled")
            sizes = page.evaluate("({viewport:innerWidth,document:document.documentElement.scrollWidth})")
            assert sizes["document"] <= sizes["viewport"] + 1, sizes

        def send_plan():
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/messages"), timeout=270000,
            ) as planning:
                page.get_by_role("button", name="发送需求", exact=True).click()
            response = planning.value
            receipt = response.json()
            (out / "planning-receipt.json").write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            assert response.status == 200, receipt
            return receipt

        if args.phase == "inspect":
            select("house-r2")
            nav("研发任务")
            page.get_by_role("button", name="house-prices-house-r2", exact=False).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_role("heading", name="评价标准", exact=True)).to_be_visible()
            expect(dialog.get_by_text("搜索比较", exact=True)).to_be_visible()
            expect(dialog.get_by_text("最终评估", exact=True).first).to_be_visible()
            assert dialog.locator("pre:visible").count() == 0
            shot("01-real-evaluation.png")
            passed("AutoRealize actual evaluation criteria visible; no raw JSON in overview")
            dialog.get_by_role("button", name="搜索树", exact=True).click()
            expect(dialog.get_by_role("img", name="实际候选程序搜索树")).to_be_visible()
            nodes = dialog.locator(".real-node")
            assert nodes.count() >= 10
            nodes.last.focus()
            page.keyboard.press("Space")
            expect(dialog.get_by_role("heading", name="候选方案", exact=False)).to_be_visible()
            assert dialog.locator("pre:visible").count() == 0
            shot("02-real-search-tree.png")
            passed(f"Actual candidate tree with {nodes.count()} nodes and keyboard selection")
            full_before = sum("view=summary" not in call["url"] and "/snapshot" in call["url"] for call in calls)
            dialog.get_by_text("查看方案代码", exact=True).click()
            expect(dialog.locator(".code-block")).to_be_visible(timeout=15000)
            expect(dialog.locator(".code-block")).to_contain_text("def ", timeout=15000)
            full_after = sum("view=summary" not in call["url"] and "/snapshot" in call["url"] for call in calls)
            assert full_after - full_before == 1, (full_before, full_after)
            passed("Full candidate source fetched only on expansion")
            dialog.get_by_role("button", name="算法包", exact=True).click()
            task_id = receipts["house-r2"]["task_id"]
            solution_url = f"/tasks/{task_id}/solution"
            before = sum(solution_url in call["url"] for call in calls)
            dialog.get_by_role("button", name="检查成果", exact=True).click()
            expect(dialog.get_by_role("button", name="重新检查", exact=True)).to_be_visible(timeout=45000)
            after = sum(solution_url in call["url"] for call in calls)
            assert after - before == 1, (before, after)
            baseline = len([c for c in calls if task_id in c["url"]])
            page.wait_for_timeout(16000)
            assert len([c for c in calls if task_id in c["url"]]) == baseline
            passed("One artifact check per click; completed task idle 16s has no repeat reads")
            shot("03-artifact-check.png")
            dialog.get_by_role("button", name="报告", exact=True).click()
            expect(dialog.locator(".report-prose h1").first).to_be_visible(timeout=15000)
            shot("04-readable-report.png")
            dialog.get_by_role("button", name="搜索树", exact=True).click()
            page.set_viewport_size({"width": 390, "height": 844})
            dialog.locator(".real-tree").scroll_into_view_if_needed()
            assert dialog.locator(".real-tree").evaluate("el => el.scrollHeight > el.clientHeight")
            shot("05-mobile-tree.png")
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
            page.set_viewport_size({"width": 1440, "height": 1000})
            nav("决策对话")
            page.get_by_role("button", name="新建对话", exact=True).click()
            page.get_by_label("决策需求", exact=True).fill(
                "请为当前项目研发房价预测模型，使用train.csv训练、test.csv预测，按自然对数RMSE评估，输出可复用算法包。当前没有已发布算法包。")
            assert send_plan()["plan"]["action"] == "research"
            expect(page.get_by_role("button", name="配置研发任务", exact=True).last).to_be_visible(timeout=150000)
            shot("06-no-package-research.png")
            page.get_by_role("button", name="配置研发任务", exact=True).last.click()
            expect(page.get_by_label("研发目标", exact=True)).to_have_value(__import__("re").compile("房价"))
            expect(page.get_by_label("搜索时间上限（分钟）", exact=True)).to_have_value("30")
            expect(page.get_by_label("研发数据包文件预览")).to_contain_text("train.csv")
            shot("07-research-configuration.png")
            page.keyboard.press("Escape")
            passed("Real LLM routes a project without packages to editable research, 30-minute default")

        if args.phase == "publish":
            select("house-r1")
            nav("算法模型包")
            candidate = page.locator(".candidate-row").filter(has_text="house-prices-house-r1")
            candidate.get_by_role("button", name="查看成果", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("button", name="算法包", exact=True).click()
            dialog.get_by_role("button", name="检查成果", exact=True).click()
            expect(dialog.get_by_role("heading", name="发布算法模型包", exact=True)).to_be_visible(timeout=45000)
            expect(dialog.get_by_label("交付试算输入格式")).to_have_value("csv")
            csv = str((ROOT / ".codex-work/audit-20261029/house-r1/input/test.csv").resolve())
            dialog.get_by_label("选择项目数据文件", exact=True).select_option(csv)
            dialog.get_by_label("已核对输入，执行本地推理，不重新训练", exact=True).check()
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/delivery/verify"), timeout=65000,
            ) as completed_trial:
                dialog.get_by_role("button", name="运行交付试算", exact=True).click()
            assert completed_trial.value.status == 200
            expect(dialog.get_by_text("上次提交输入试算成功", exact=True)).to_be_visible(timeout=60000)
            shot("01-real-delivery-trial.png")
            contract = api(f"/studio/tasks/{receipts['house-r1']['task_id']}/delivery")
            trial = contract["verification"]["trial"]
            rows = trial["result"]
            import csv as csv_module
            with open(csv, encoding="utf-8-sig", newline="") as stream:
                ids = [int(row["Id"]) for row in csv_module.DictReader(stream)]
            assert [row["Id"] for row in rows] == ids
            assert len(rows) == 1459 and all(math.isfinite(row["SalePrice"]) and row["SalePrice"] > 0 for row in rows)
            passed("Project CSV selection and real frozen-package inference cover all 1459 ordered rows")
            dialog.get_by_label("能力名称", exact=True).fill("Ames 房价预测")
            dialog.get_by_label("用途与适用范围", exact=True).fill(
                "使用与Kaggle House Prices test.csv相同字段的CSV预测SalePrice；返回Id和预测房价。仅用于该数据分布的离线预测，业务验收尚未开展。")
            dialog.get_by_label("已核对方案、输入要求和验证结果，同意发布", exact=True).check()
            dialog.get_by_role("button", name="发布模型包", exact=True).click()
            expect(page.get_by_role("dialog").get_by_role("heading", name="Ames 房价预测", exact=True)).to_be_visible(timeout=60000)
            shot("02-published-package.png")
            packages = api("/studio/state")["packages"]
            package = next(p for p in packages if p["name"] == "Ames 房价预测" and p["project_id"] == receipts["house-r1"]["project_id"])
            (out / "published-package.json").write_text(json.dumps({
                "package_id": package["id"], "project_id": package["project_id"], "task_id": package["task_id"],
                "scope": "Published frozen inference package after submitted-input trial; no business acceptance."
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            passed("Package published through actual user form, report and frozen artifacts retained")

        if args.phase == "decision":
            select("house-r1")
            nav("决策对话")
            page.get_by_role("button", name="新建对话", exact=True).click()
            question = "请使用本项目已发布的房价预测算法包，对test.csv全部房源预测：共有多少套、平均预测房价，以及预测价格最高的3套的Id与价格。请明确这些是预测值。"
            page.get_by_label("决策需求", exact=True).fill(question)
            assert send_plan()["plan"]["action"] == "reuse"
            expect(page.get_by_role("button", name="核对输入并调用", exact=False).last).to_be_visible(timeout=150000)
            assert page.locator(".plan-step").count() == 1, "Statistics must not add a second predictor call"
            shot("01-real-package-plan.png")
            page.get_by_role("button", name="核对输入并调用", exact=False).last.click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_label("输入方式", exact=True)).to_have_value("csv")
            expect(dialog.get_by_label("生成决策答案", exact=True)).to_be_checked()
            csv = str((ROOT / ".codex-work/audit-20261029/house-r1/input/test.csv").resolve())
            dialog.get_by_label("选择项目数据文件", exact=True).select_option(csv)
            dialog.get_by_label("已核对输入与单位，执行本地推理", exact=True).check()
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/studio/invocations"), timeout=400000,
            ) as completed_invocation:
                dialog.get_by_role("button", name="确认调用", exact=True).click()
            response = completed_invocation.value
            assert response.status == 200, response.status
            receipt = response.json()
            (out / "invocation-receipt.json").write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            assert receipt["status"] == "completed", receipt.get("error")
            expect(page.get_by_role("dialog").get_by_role("heading", name="决策答案", exact=True)).to_be_visible(timeout=180000)
            shot("02-real-decision-answer.png")
            state = api("/studio/state")
            record = next(i for i in state["invocations"] if i.get("question") == question and i["status"] == "completed")
            result = api("/studio/invocations/" + record["id"])
            rows = result["result"]
            assert len(rows) == 1459
            avg = sum(row["SalePrice"] for row in rows) / len(rows)
            top = sorted(rows, key=lambda row: row["SalePrice"], reverse=True)[:3]
            answer = result["answer"]
            assert "1459" in answer or "1,459" in answer
            for row in top:
                assert str(row["Id"]) in answer
                assert any(formatted in answer for formatted in [
                    f'{row["SalePrice"]:.2f}', f'{row["SalePrice"]:,.2f}', f'{row["SalePrice"]:.0f}', f'{row["SalePrice"]:,.0f}'
                ]), (row, answer)
            assert any(formatted in answer for formatted in [f"{avg:.2f}", f"{avg:,.2f}", f"{avg:.0f}", f"{avg:,.0f}"]), (avg, answer)
            assert "decision_program" not in record
            assert result["decision_program"]["code"].startswith("def decide(data):")
            assert result["decision_program"]["thinking_requested"] == "true"
            (out / "decision-record.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            (out / "independent-answer-check.json").write_text(json.dumps({
                "invocation_id": result["id"], "rows": len(rows), "mean_prediction": avg, "top3": top,
                "answer": answer, "usage": result["decision_program"]["usage"],
                "scope": "Numbers independently recomputed from this actual inference output; not predictive quality validation."
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            passed("Real LLM discovers package and generates code; one real model call yields a numerically verified answer")
            dialog = page.get_by_role("dialog")
            assert dialog.locator("pre:visible").count() == 0
            expect(dialog.get_by_role("heading", name="决策代码", exact=True)).to_have_count(0)
            baseline = len(calls)
            page.wait_for_timeout(16000)
            assert len(calls) == baseline, calls[baseline:]
            passed("Completed invocation idle 16s: zero API requests; default answer hides raw code/JSON")
            dialog.locator("summary").filter(has_text="技术详情").click()
            expect(dialog.get_by_role("heading", name="决策代码", exact=True)).to_be_visible(timeout=15000)
            shot("03-decision-code-on-demand.png")
            page.keyboard.press("Escape")
            page.set_viewport_size({"width": 390, "height": 844})
            shot("04-mobile-answer.png")
            page.reload(wait_until="networkidle")
            expect(page.get_by_text("查看调用结果", exact=True).last).to_be_visible(timeout=15000)
            passed("Readable decision persists after reload and fits mobile")

        if args.phase == "export":
            select("house-r1")
            nav("算法模型包")
            tile = page.locator(".package-tile").filter(has_text="Ames 房价预测")
            tile.get_by_role("button", name="查看详情", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_text("表格数据 · 80 个字段", exact=True)).to_be_visible(timeout=15000)
            assert dialog.locator("pre:visible").count() == 0
            shot("01-package-input.png")
            with page.expect_download(timeout=45000) as download:
                dialog.get_by_role("button", name="导出模型包", exact=True).click()
            archive_path = out / "Ames-house-price-package.zip"
            download.value.save_as(str(archive_path))
            package_id = json.loads((ROOT / ".codex-work/audit-20261029/frontend-r5-publish/published-package.json")
                                    .read_text(encoding="utf-8"))["package_id"]
            package = api("/studio/packages/" + package_id)
            trial = out / "export-trial"
            target = trial / "solution"
            target.mkdir(parents=True)
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                assert all((target / name).resolve().is_relative_to(target) for name in names)
                assert all(not Path(name).is_absolute() and ":" not in name for name in names)
                assert all(name in names for name in ["REPORT.md", "CAPABILITY.md", "capability.json",
                                                      "solution.py", "solution_manifest.json", "LOCAL_USAGE.md"])
                for name in names:
                    if name != "package_inventory.json":
                        assert hashlib.sha256(archive.read(name)).hexdigest() == package["sha256"][name], name
                if "package_inventory.json" in names:
                    assert "source_config" not in json.loads(archive.read("package_inventory.json"))
                archive.extractall(target)
            assert package["model_path"] in names
            passed("User export includes report, model, interface and usage; frozen-file hashes match published package")
            shutil.copyfile(ROOT / ".codex-work/audit-20261029/house-r1/input/test.csv", trial / "trial_input.csv")
            (trial / "trial_request.json").write_text(json.dumps({
                "entrypoint": package["entrypoint"], "model_path": package["model_path"], "input_mode": "csv",
            }), encoding="utf-8")
            started = time.monotonic()
            execution = subprocess.run(
                [sys.executable, "-I", str(ROOT / "frontend/backend/solution_trial_runner.py"), str(trial)],
                cwd=trial, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            (out / "export-trial-execution.json").write_text(json.dumps({
                "returncode": execution.returncode, "seconds": time.monotonic() - started,
                "stdout": execution.stdout[-8000:], "stderr": execution.stderr[-8000:],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            assert execution.returncode == 0, execution.stderr[-2000:]
            rows = json.loads((trial / "trial_result.json").read_text(encoding="utf-8"))
            import csv as csv_module
            with (trial / "trial_input.csv").open(encoding="utf-8-sig", newline="") as stream:
                ids = [int(row["Id"]) for row in csv_module.DictReader(stream)]
            assert [row["Id"] for row in rows] == ids and len(rows) == 1459
            assert all(math.isfinite(row["SalePrice"]) and row["SalePrice"] > 0 for row in rows)
            (out / "export-validation.json").write_text(json.dumps({
                "files": names, "rows": len(rows), "ids_in_input_order": True, "positive_finite_predictions": True,
                "scope": "Relocated exported frozen package, same configured Python dependencies; no training or holdout access.",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            passed("Exported package relocated and run in separate Python process: 1459 real ordered predictions")

        if args.phase == "mobile":
            select("house-r1")
            nav("调用记录")
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 1")
            expect(page.locator(".sidebar")).to_have_attribute("inert", "")
            page.get_by_role("button", name="打开导航", exact=True).click()
            expect(page.get_by_label("当前数据项目", exact=True)).to_be_focused()
            expect(page.locator(".workspace-main")).to_have_attribute("inert", "")
            page.keyboard.press("Shift+Tab")
            expect(page.get_by_role("link", name="AutoDecision", exact=False)).to_be_focused()
            page.keyboard.press("Shift+Tab")
            expect(page.get_by_role("button", name="使用说明", exact=True)).to_be_focused()
            page.keyboard.press("Tab")
            expect(page.get_by_role("link", name="AutoDecision", exact=False)).to_be_focused()
            shot("01-mobile-navigation.png")
            page.keyboard.press("Escape")
            expect(page.get_by_role("button", name="打开导航", exact=True)).to_be_focused()
            expect(page.locator(".sidebar")).to_have_attribute("inert", "")
            page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 1")
            page.get_by_role("button", name="打开导航", exact=True).click()
            page.get_by_role("button", name="关闭导航", exact=True).click(position={"x": 350, "y": 40})
            expect(page.get_by_role("button", name="打开导航", exact=True)).to_be_focused()
            passed("Mobile drawer hides offscreen focus targets, traps focus, closes with Escape/backdrop and restores focus")
            page.locator(".main-content .live-list-row").filter(has_text="Ames 房价预测").filter(has_text="已完成").first.click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_role("heading", name="决策答案", exact=True)).to_be_visible(timeout=15000)
            expect(dialog.locator(".report-prose")).to_contain_text("177647.54")
            expect(dialog.locator(".report-prose")).to_contain_text("1970")
            assert dialog.locator("pre:visible").count() == 0
            geometry = dialog.evaluate("""el => ({
                viewport: innerWidth, left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right,
                content: el.querySelector('.dialog-body').scrollWidth, available: el.querySelector('.dialog-body').clientWidth
            })""")
            assert geometry["left"] >= 0 and geometry["right"] <= geometry["viewport"] + 1, geometry
            assert geometry["content"] <= geometry["available"] + 1, geometry
            shot("02-mobile-real-answer.png")
            passed("Existing real decision answer readable on 390px mobile; no code/JSON or horizontal overflow")
            page.keyboard.press("Escape")
            page.get_by_role("button", name="打开导航", exact=True).click()
            page.locator(".main-nav").get_by_role("button", name="决策对话", exact=True).click()
            expect(page.locator(".sidebar")).to_have_attribute("inert", "")
            expect(page.get_by_label("决策需求", exact=True)).to_be_visible()
            shot("03-mobile-chat.png")
            page.set_viewport_size({"width": 1440, "height": 1000})
            expect(page.locator(".sidebar")).not_to_have_attribute("inert", "")
            expect(page.locator(".sidebar")).not_to_have_class(__import__("re").compile(r"\bopen\b"))
            page.wait_for_load_state("networkidle")
            baseline = len(calls)
            page.wait_for_timeout(16000)
            assert len(calls) == baseline, calls[baseline:]
            assert all(call["method"] == "GET" for call in calls)
            passed("Navigation closes after route changes, desktop navigation remains usable; completed workspace makes no requests in 16s")

        browser.close()
        assert not errors, errors
        assert not failed, failed
    print(json.dumps({"phase": args.phase, "passed": len(checks), "page_errors": errors, "failed_http": failed}, ensure_ascii=False))


if __name__ == "__main__":
    main()

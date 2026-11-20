"""Verify failed tasks offer local recovery, including unavailable readiness checks."""
from __future__ import annotations
import argparse
import copy
import json
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright
from solution_check_readability import CONFIG, TASK, TASK_ID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5178")
    parser.add_argument("--channel", default="msedge")
    args = parser.parse_args()
    completed = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=args.channel)
        for scenario in ("repair", "configuration", "unavailable"):
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            errors, writes = [], []
            gate_reads = [0]
            task = copy.deepcopy(TASK)
            task.update(status="failed", phase="prepare_automl_input_failed", last_error="任务定义审查未通过")
            project = {"id": "recovery-project", "name": "恢复测试", "input_root": CONFIG["input_root"], "created_at": 1}
            page.on("pageerror", lambda error: errors.append(str(error)))

            def api(route):
                path = urlparse(route.request.url).path.removeprefix("/api")
                if route.request.method not in {"GET", "HEAD"}:
                    writes.append(path)
                if path == "/studio/state":
                    data = {"version": "fixture", "projects": [project], "tasks": [task], "packages": [],
                            "links": [{"id": TASK_ID, "project_id": project["id"]}], "conversations": [], "invocations": []}
                elif path == f"/tasks/{TASK_ID}/snapshot":
                    data = {"task": task, "auto_realize": {}, "auto_ml": {}, "auto_report": {}}
                elif path == f"/tasks/{TASK_ID}/automl-readiness":
                    gate_reads[0] += 1
                    if scenario == "unavailable" and gate_reads[0] == 1:
                        route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "检查服务暂时不可用"}))
                        return
                    data = {"ready": False, "can_repair_review": scenario != "configuration", "detail": "先检查数据目录和配置"}
                elif path == f"/tasks/{TASK_ID}/review-repair-plan":
                    data = {"plan_token": "reviewed-plan", "replace_paths": ["checkpoint/description.md"]}
                elif path == "/system/readiness":
                    data = {"ready": False, "checks": [{"key": "autoMlCode", "label": "代码模型", "status": "fail", "detail": "模型连接需要检查"}], "data_policy": "本地数据"}
                else:
                    data = {}
                route.fulfill(status=200, content_type="application/json", body=json.dumps(data, ensure_ascii=False))

            page.route("**/api/**", api)
            page.goto(args.url + "/#tasks", wait_until="networkidle")
            page.get_by_role("button", name=task["task_name"], exact=False).click()
            panel = page.get_by_role("region", name="任务恢复")
            expect(panel).to_be_visible()
            if scenario == "unavailable":
                expect(panel.get_by_role("alert")).to_contain_text("恢复条件读取失败")
                panel.get_by_role("button", name="重新检查恢复条件", exact=True).click()
            if scenario != "configuration":
                expect(panel.get_by_role("button", name="修复审查并继续", exact=True)).to_be_visible()
                panel.get_by_role("button", name="修复审查并继续", exact=True).click()
                expect(page.get_by_role("heading", name="确认修复审查并继续", exact=True)).to_be_visible()
                expect(page.get_by_text("将修复以下任务材料", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="确认修复审查并继续", exact=True)).to_be_enabled()
            else:
                expect(panel.get_by_text("先检查数据目录和配置", exact=True)).to_be_visible()
                panel.get_by_role("button", name="检查配置并恢复", exact=True).click()
                expect(page.get_by_role("button", name="测试连接", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="打开运行设置", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="确认恢复原实验", exact=True)).to_be_disabled()
            page.get_by_role("button", name="取消", exact=True).click()
            page.get_by_text("高级操作", exact=True).click()
            page.get_by_role("button", name="从已有合同启动搜索", exact=True).click()
            expect(page.get_by_role("heading", name="任务材料尚未就绪", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="确认从已有合同启动搜索", exact=True)).to_be_disabled()
            confirmation = page.locator(".confirmation-panel")
            if scenario != "configuration":
                confirmation.get_by_role("button", name="修复审查并继续", exact=True).click()
                expect(page.get_by_role("heading", name="确认修复审查并继续", exact=True)).to_be_visible()
            else:
                expect(confirmation.get_by_role("button", name="新建实验并补充需求", exact=True)).to_be_visible()
            for width, height in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), scenario
            assert not writes, writes
            assert not errors, errors
            completed.append(scenario)
            context.close()
        context = browser.new_context(viewport={"width":1440,"height":1000})
        page = context.new_page()
        task = copy.deepcopy(TASK)
        project = {"id":"repair-results","name":"修复复验","input_root":CONFIG["input_root"],"created_at":1}
        errors=[]
        page.on("pageerror",lambda error:errors.append(str(error)))
        def result_api(route):
            path=urlparse(route.request.url).path.removeprefix("/api")
            if path=="/studio/state":
                data={"version":"fixture","projects":[project],"tasks":[task],"packages":[],"links":[{"id":TASK_ID,"project_id":project["id"]}],"conversations":[],"invocations":[]}
            elif path.endswith("/snapshot"):
                data={"task":task,"auto_realize":{},"auto_ml":{},"auto_report":{}}
            elif path.endswith("/final-evaluation"):
                data={"status":"completed","independent_verification":"pending","result":{"metrics":{"WAPE":0.169437,"n":3643}},
                    "inference_repair":{"status":"recorded","metrics":{"WAPE":0.170475,"MAE":11.8746,"n":3643},"scope":"测试集此前已查看，不属于新的盲测。"}}
            elif path.endswith("/delivery"):
                data={"report_ready":True,"report_status":"ready","delivery_id":"a"*32,"structure_ready":True,"draft":{"input_schema":{},"dataframes":[]},"issues":[],"verification":{"status":"not_run"}}
            else:data={}
            route.fulfill(status=200,content_type="application/json",body=json.dumps(data,ensure_ascii=False))
        page.route("**/api/**",result_api)
        page.goto(args.url+"/#tasks",wait_until="networkidle")
        page.get_by_role("button",name=task["task_name"],exact=False).click()
        page.get_by_role("button",name="算法包",exact=True).click()
        expect(page.get_by_role("heading",name="原始保留集评估",exact=True)).to_be_visible()
        repair=page.get_by_role("region",name="修复后的回归复验")
        expect(repair).to_contain_text("0.1705")
        expect(repair).to_contain_text("不属于新的盲测")
        expect(repair).to_contain_text("3643")
        for width,height in [(1440,1000),(390,844)]:
            page.set_viewport_size({"width":width,"height":height})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        assert not errors,errors
        completed.append("repair_results_preserve_original_and_exposure")
        context.close()
        browser.close()
    print(json.dumps({"passed": True, "scenarios": completed, "automatic_mutations": 0}))


if __name__ == "__main__":
    main()

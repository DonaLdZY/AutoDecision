import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
import degradation


CONFLICT = {
    "conflict_id": "material", "description": "锂和铝写法冲突",
    "source_a": {"source_path": "任务需求.txt", "evidence": "硫酸锂蒸发"},
    "source_b": {"source_path": "调研.docx", "evidence": "硫酸铝溶液"},
}


def good_plan(**overrides):
    plan = {
        "feasible": True,
        "core_goal": "预测蒸汽进气流量并识别浪费时段",
        "degraded_goal": "工艺对象按调研文档定为硫酸铝溶液三效蒸发。用设备表按时间前 80% 训练、后 20% 评估，"
                         "预测每分钟蒸汽进气流量，唯一指标 MAE，输出 predictions.csv（SampleTime,y_pred）。不做现场闭环验证。",
        "items": [
            {"category": "需求冲突", "brief": "工艺按硫酸铝处理", "original": "硫酸锂蒸发", "reason": "两份文档写法冲突", "evidence": "调研.docx",
             "action": "按证据裁决", "degraded": "按硫酸铝处理", "impact": "结论只适用于硫酸铝工段"},
            {"category": "材料缺失", "brief": "不做现场闭环验证", "original": "现场执行窗口验证", "reason": "没有执行后数据", "evidence": "审查 issues",
             "action": "舍弃", "degraded": "只做历史离线评估", "impact": "节能效果未经现场验证"},
        ],
        "infeasible_reason": "",
    }
    plan.update(overrides)
    return plan


def evidence(conflicts=True, executable=False):
    return {"authority_conflicts": [CONFLICT] if conflicts else [], "evaluation_contract": {"executable": executable}}


def test_validate_plan_accepts_complete_plan():
    plan, problems = degradation.validate_plan(good_plan(), evidence())
    assert problems == []
    assert len(plan["items"]) == 2


def test_validate_plan_requires_conflict_resolution_and_fixed_wording():
    raw = good_plan(degraded_goal="视情况预测蒸汽流量，" * 5)
    raw["items"] = [raw["items"][1]]
    _, problems = degradation.validate_plan(raw, evidence())
    assert any("需求冲突" in p for p in problems)
    assert any("视情况" in p for p in problems)


def test_validate_plan_requires_short_producer_brief():
    raw = good_plan()
    raw["items"][0]["brief"] = "工艺对象按调研文档裁定为硫酸铝溶液三效蒸发，不处理会议纪要中的硫酸锂"
    raw["items"][1]["brief"] = ""
    _, problems = degradation.validate_plan(raw, evidence())
    assert any("brief 超过" in p for p in problems)
    assert any("缺少 brief" in p for p in problems)


def test_validate_plan_infeasible_needs_reason():
    _, problems = degradation.validate_plan({"feasible": False}, evidence())
    assert problems == ["feasible=false 时必须写 infeasible_reason"]


def test_request_plan_feeds_problems_back_until_valid():
    calls = []

    def fake_model(system, user):
        calls.append(json.loads(user))
        if len(calls) == 1:
            return json.dumps(good_plan(items=[]))
        return "```json\n" + json.dumps(good_plan()) + "\n```"

    plan, attempts = degradation.request_plan(evidence(), fake_model)
    assert plan["core_goal"]
    assert "previous_problems" in calls[1]
    assert attempts[0]["problems"] and attempts[1]["problems"] == []


def test_request_plan_gives_up_after_bounded_attempts():
    with pytest.raises(degradation.DegradationError):
        degradation.request_plan(evidence(), lambda s, u: "not json", max_attempts=2)


def test_collect_evidence_extracts_conflicts(tmp_path):
    ar = tmp_path / "autorealize"
    (ar / "realize_report").mkdir(parents=True)
    (ar / "realize_report" / "evaluation_contract_report.json").write_text(
        json.dumps({"final": {"passed": True, "executable": False, "issues": ["缺路段表"]}}), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.csv").write_text("x\n1\n")
    gate = {
        "hard_blocking_issues": ["automl_context_pack.json: Unresolved authority conflict: " + json.dumps(CONFLICT, ensure_ascii=False),
                                 "task_definition_report.json: 引用了不存在文件: x.csv"],
        "review_issues": ["artifact_consistency_report.json: review retries exhausted without approval"],
    }
    found = degradation.collect_evidence(autorealize_dir=ar, gate=gate, task_hint="减少蒸汽", input_root=data)
    assert found["authority_conflicts"][0]["conflict_id"] == "material"
    assert "引用了不存在文件: x.csv" in found["gate_findings"]
    assert found["evaluation_contract"]["executable"] is False
    assert found["data"]["input_files"] == ["a.csv"]


def test_approve_reject_and_declaration(tmp_path):
    gate = {"hard_blocking_issues": ["x"], "review_issues": []}
    plan, _ = degradation.validate_plan(good_plan(), evidence())
    ledger = degradation.new_ledger(task_id="t", policy="ask", gate=gate, original_task_hint="原目标", plan=plan, attempts=[])
    rejected = degradation.reject(json.loads(json.dumps(ledger)))
    assert rejected["status"] == degradation.REJECTED
    assert degradation.summary(rejected)["approved_by"] is None

    degradation.approve(ledger, by="producer", conversation_id="c1")
    assert ledger["status"] == degradation.APPLYING
    assert ledger["degraded_task_hint"].startswith("原目标")
    assert "工艺按硫酸铝处理" in ledger["degraded_task_hint"]
    assert "现场执行窗口验证" not in ledger["degraded_task_hint"]  # long original text stays in the ledger
    with pytest.raises(degradation.DegradationError):
        degradation.approve(ledger, by="auto")

    ledger["status"] = degradation.APPLIED
    ledger["plan"]["items"][0]["original"] = "a|b"
    report = tmp_path / "report"
    report.mkdir()
    (report / "report.md").write_text("# 报告\n正文\n", encoding="utf-8")
    review_gate = {"review_issues": [
        "artifact_consistency_report.json: review retries exhausted without approval",
        "automl_context_pack.json: Final artifact consistency: 指标名不统一",
        "task_definition_report.json: Final artifact consistency: 指标名不统一",
        "task_definition_report.json: Final artifact consistency review has not passed.",
    ], "review_bypass_active": True}
    assert degradation.append_declaration(report, ledger, review_gate)
    assert degradation.append_declaration(report, ledger, review_gate)
    text = (report / "report.md").read_text(encoding="utf-8")
    assert text.count("## 降级声明") == 1
    assert "a\\|b" in text and "生产者于" in text and text.count("指标名不统一") == 1
    assert "review retries exhausted" not in text and "has not passed" not in text
    assert (report / degradation.DECLARATION_NAME).is_file()


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(app, "TASKS_FILE", tmp_path / "state/tasks.json")
    monkeypatch.setattr(app, "store", app.TaskStore())
    monkeypatch.setattr(app.replay_recorder, "observe_task", lambda *a: None)
    monkeypatch.delenv("AUTODECISION_API_TOKEN", raising=False)
    gs = app.GlobalSettingsModel(python={"executable": app.sys.executable}, llm={})
    monkeypatch.setattr(app, "get_global_settings", lambda: gs)
    data = tmp_path / "data"
    data.mkdir()
    (data / "train.csv").write_text("value\n2\n")
    return TestClient(app.app), data, tmp_path, gs


def make_task(data, tmp_path, policy):
    payload = app.TaskConfigPayload(task_name="steam", input_root=str(data), output_root=str(tmp_path / "runs"))
    payload.auto_realize.degradation_policy = policy
    payload.auto_realize.task_hint = "完成蒸汽优化"
    task = app.store.create(payload)
    layout = app._task_layout(task, app.resolve_output_root(task.output_root))
    (layout["autorealize_dir"] / "realize_report").mkdir(parents=True)
    app.store.set_status(task.id, status="running", phase="autorealize", run_dir=str(layout["task_root"]))
    paths = {**layout, "ml_exp_name": "steam", "ml_log_dir": layout["automl_logs_root"] / "steam",
             "ml_ws_dir": layout["automl_workspaces_root"] / "steam"}
    return task, paths


def blocked_gate(task, autorealize_dir):
    return {"blocking_issues": ["x"], "hard_blocking_issues": ["x"], "review_issues": [], "warnings": [],
            "review_bypass_active": False, "policy": "strict"}


def test_ask_policy_waits_then_rejection_stops(gateway, monkeypatch):
    client, data, tmp_path, gs = gateway
    task, paths = make_task(data, tmp_path, "ask")
    monkeypatch.setattr(app, "_automl_gate_decision", blocked_gate)
    monkeypatch.setattr(app, "_degradation_model_caller", lambda gs: (lambda s, u: json.dumps(good_plan())))
    proceed = app._definition_gate_with_degradation(task.id, gs=gs, paths=paths, input_root=data, ar_base="", req_timeout=1)
    assert proceed is False
    waiting = app.store.get(task.id)
    assert (waiting.status, waiting.phase) == ("awaiting_input", "awaiting_degradation_consent")
    assert waiting.degradation["count"] == 2

    response = client.post("/api/tasks/degradation/decide", json={"task_id": task.id, "approve": False, "conversation_id": "c1"})
    assert response.status_code == 200, response.text
    stopped = app.store.get(task.id)
    assert (stopped.status, stopped.phase) == ("stopped", "degradation_rejected")
    assert stopped.degradation["status"] == degradation.REJECTED
    again = client.post("/api/tasks/degradation/decide", json={"task_id": task.id, "approve": True})
    assert again.status_code == 409


def test_auto_policy_reruns_definition_with_degraded_hint(gateway, monkeypatch):
    _, data, tmp_path, gs = gateway
    task, paths = make_task(data, tmp_path, "auto")
    gates = iter([blocked_gate(None, None), {**blocked_gate(None, None), "blocking_issues": []}])
    monkeypatch.setattr(app, "_automl_gate_decision", lambda t, d: next(gates))
    monkeypatch.setattr(app, "_degradation_model_caller", lambda gs: (lambda s, u: json.dumps(good_plan())))
    seen = {}

    def fake_definition(**kwargs):
        seen["hint"] = kwargs["task"].config.auto_realize.task_hint
        seen["policy"] = kwargs["task"].config.auto_realize.review_gate_policy
        paths["autorealize_dir"].mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(app, "_run_autorealize_stage", fake_definition)
    assert app._definition_gate_with_degradation(task.id, gs=gs, paths=paths, input_root=data, ar_base="", req_timeout=1)
    assert "# 已批准的降级任务口径" in seen["hint"] and seen["policy"] == "continue_on_exhaustion"
    assert app.store.get(task.id).config.auto_realize.llm_timeout >= 600
    ledger = degradation.read_ledger(paths["task_root"])
    assert ledger["status"] == degradation.APPLIED and ledger["approval"]["by"] == "auto"
    assert list((paths["task_root"] / "stage-history").glob("autorealize-before-degradation-*"))
    assert app.store.get(task.id).degradation["status"] == degradation.APPLIED


def test_strict_policy_keeps_historical_gate(gateway, monkeypatch):
    _, data, tmp_path, gs = gateway
    task, paths = make_task(data, tmp_path, "strict")
    monkeypatch.setattr(app, "_automl_gate_decision", blocked_gate)
    monkeypatch.setattr(app, "_degradation_model_caller", lambda gs: pytest.fail("strict must not plan"))
    assert app._definition_gate_with_degradation(task.id, gs=gs, paths=paths, input_root=data, ar_base="", req_timeout=1)
    assert degradation.read_ledger(paths["task_root"]) is None


def test_collect_evidence_tolerates_string_sources_and_scalar_fields(tmp_path):
    ar = tmp_path / "autorealize"
    (ar / "realize_report").mkdir(parents=True)
    (ar / "realize_report" / "evaluation_contract_report.json").write_text(
        json.dumps({"final": {"issues": "只有一条字符串", "fixes": None}}), encoding="utf-8")
    (ar / "realize_report" / "artifact_consistency_report.json").write_text(
        json.dumps({"final": {"issues": ["纯文本问题", {"severity": "blocking", "message": "对象问题"}]}}), encoding="utf-8")
    conflict = {"conflict_id": "m", "description": "冲突", "source_a": "任务需求.txt 写硫酸锂", "source_b": None}
    gate = {"hard_blocking_issues": ["x.json: Unresolved authority conflict: " + json.dumps(conflict, ensure_ascii=False)],
            "review_issues": []}
    found = degradation.collect_evidence(autorealize_dir=ar, gate=gate, task_hint="", input_root=tmp_path / "none")
    assert found["authority_conflicts"][0]["source_a"]["evidence"] == "任务需求.txt 写硫酸锂"
    assert found["evaluation_contract"]["issues"] == ["只有一条字符串"]
    assert [i["message"] for i in found["consistency_review"]["issues"]] == ["纯文本问题", "对象问题"]


def test_unexpected_planning_crash_is_reported_as_planning_failure(gateway, monkeypatch):
    _, data, tmp_path, gs = gateway
    task, paths = make_task(data, tmp_path, "auto")
    monkeypatch.setattr(app, "_automl_gate_decision", blocked_gate)
    monkeypatch.setattr(degradation, "collect_evidence", lambda **kw: {}.get("x").get("y"))
    assert not app._definition_gate_with_degradation(task.id, gs=gs, paths=paths, input_root=data, ar_base="", req_timeout=1)
    failed = app.store.get(task.id)
    assert failed.phase == "prepare_automl_input_failed" and "降级规划也失败" in failed.last_error
    assert degradation.read_ledger(paths["task_root"])["status"] == degradation.PLANNING_FAILED


def test_plan_endpoint_degrades_a_blocked_definition_and_waits(gateway, monkeypatch):
    client, data, tmp_path, gs = gateway
    task, paths = make_task(data, tmp_path, "auto")
    (paths["autorealize_dir"] / "description.md").write_text("# 任务\n", encoding="utf-8")
    app.store.set_status(task.id, status="failed", phase="prepare_automl_input_failed")
    monkeypatch.setattr(app, "_automl_gate_decision", blocked_gate)
    monkeypatch.setattr(app, "_degradation_model_caller", lambda gs: (lambda s, u: json.dumps(good_plan())))

    class Inline:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(app.threading, "Thread", Inline)
    seen = {}
    real_gate = app._definition_gate_with_degradation

    def gate_checking_handle(task_id, **kwargs):
        # The zombie guard runs on every store read while the model call is pending.
        seen["status_during_planning"] = app.store.get(task_id).status
        return real_gate(task_id, **kwargs)

    monkeypatch.setattr(app, "_definition_gate_with_degradation", gate_checking_handle)
    assert client.get(f"/api/tasks/{task.id}/automl-readiness").json()["can_degrade"] is True
    app.store.set_status(task.id, status="failed", phase="prepare_automl_input_failed", run_started_at=1.0)
    response = client.post("/api/tasks/degradation/plan", json={"task_id": task.id})
    assert response.status_code == 200, response.text
    assert seen["status_during_planning"] == "running"
    waiting = app.store.get(task.id)
    assert (waiting.status, waiting.phase) == ("awaiting_input", "awaiting_degradation_consent")
    again = client.post("/api/tasks/degradation/plan", json={"task_id": task.id})
    assert again.status_code == 409


def test_plan_endpoint_retries_an_approved_plan_whose_rerun_broke(gateway, monkeypatch):
    client, data, tmp_path, gs = gateway
    task, paths = make_task(data, tmp_path, "auto")
    plan, _ = degradation.validate_plan(good_plan(), evidence())
    ledger = degradation.new_ledger(task_id=task.id, policy="auto", gate={}, original_task_hint="原目标", plan=plan, attempts=[])
    degradation.approve(ledger, by="auto")
    ledger["status"], ledger["outcome"] = degradation.FAILED_AFTER, "Completion stream exceeded its wall-clock deadline"
    degradation.write_ledger(paths["task_root"], ledger)
    app.store.set_status(task.id, status="failed", phase="autorealize_failed")
    started = []

    class Recorder:
        def __init__(self, target, args=(), daemon=None):
            started.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr(app.threading, "Thread", Recorder)
    response = client.post("/api/tasks/degradation/plan", json={"task_id": task.id})
    assert response.status_code == 200 and response.json()["mode"] == "retry"
    assert started == [(app._resume_after_degradation_thread, (task.id,))]
    saved = degradation.read_ledger(paths["task_root"])
    assert saved["status"] == degradation.APPLYING and saved["approval"]["by"] == "auto"
    assert saved["retries"][0]["previous_outcome"].startswith("Completion stream")
    assert app.store.get(task.id).phase == "degradation_applying"

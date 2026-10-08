from __future__ import annotations

from pathlib import Path
import json
import threading

import pytest
from fastapi import HTTPException

import app


def test_report_recovery_updates_only_verified_idle_task_and_detects_concurrent_edit(tmp_path, monkeypatch):
    task = _task(tmp_path)
    task.status, task.phase = "failed", "report_failed"
    task.run_dir = str(Path(task.output_root) / task.task_name)
    other = _task(tmp_path, task_id="other", task_name="other")
    other.status, other.phase = "running", "autorealize"
    store = object.__new__(app.TaskStore)
    store._lock = threading.Lock()
    store._tasks, store._handles = {task.id: task, other.id: other}, {}
    persisted, observed = [], []
    monkeypatch.setattr(store, "_persist", lambda: persisted.append(True))
    monkeypatch.setattr(app.replay_recorder, "observe_task", lambda _root, row: observed.append(row))

    def concurrent_edit(_snapshot, _report):
        # Hash verification must not hold the shared store lock.
        assert store._lock.acquire(blocking=False)
        try:
            task.config.auto_realize.task_hint = "Changed while report hashes were checked"
        finally:
            store._lock.release()

    monkeypatch.setattr(app, "validate_report_recovery", concurrent_edit)
    with pytest.raises(HTTPException, match="Task changed"):
        store.recover_report(task.id)
    assert not persisted and task.phase == "report_failed"
    monkeypatch.setattr(app, "validate_report_recovery", lambda *_args: {})
    result = store.recover_report(task.id)
    assert result.phase == "report_completed" and result.status == "completed"
    assert len(persisted) == len(observed) == 1
    assert other.status == "running" and other.phase == "autorealize"


def test_autorealize_recovery_archives_failure_and_reuses_only_exact_cache(tmp_path, monkeypatch):
    task = _task(tmp_path)
    task.status, task.phase = "failed", "autorealize_failed"
    root = Path(task.output_root) / task.task_name
    task.run_dir = str(root)
    report = root / "autorealize" / "realize_report"
    report.mkdir(parents=True)
    (report / "llm_cache.jsonl").write_text('{"key":"exact-request","response":"ok"}\n')
    (report / "_service_stderr.log").write_text("StreamDeadlineExceeded: expired")
    (report / "artifact_consistency_report.json").write_text('{"final":{"passed":true}}')
    statuses = []
    monkeypatch.setattr(app.store, "get", lambda _id: task)
    monkeypatch.setattr(app.store, "set_status", lambda _id, **kw: statuses.append(kw))
    monkeypatch.setattr(app, "get_global_settings", lambda: None)
    monkeypatch.setattr(app, "_service_base_urls", lambda _: ("realize", "search", "report", 30))
    monkeypatch.setattr(app, "_direct_mode_enabled", lambda _: False)

    def run_stage(**kwargs):
        assert kwargs["task"].config.auto_realize.task_hint == task.config.auto_realize.task_hint
        assert (report / "llm_cache.jsonl").read_text() == '{"key":"exact-request","response":"ok"}\n'
        assert not (report / "artifact_consistency_report.json").exists()
        assert not (report / "_service_stderr.log").exists()
        return True

    monkeypatch.setattr(app, "_run_autorealize_stage", run_stage)
    app._rerun_autorealize_thread(task.id, preserve_cache=True)
    assert statuses[-1]["phase"] == "autorealize_completed"
    archives = list((root / "stage-history").glob("autorealize-*/realize_report"))
    assert len(archives) == 1
    assert (archives[0] / "_service_stderr.log").read_text() == "StreamDeadlineExceeded: expired"
    assert (archives[0] / "artifact_consistency_report.json").is_file()


@pytest.mark.parametrize("source", ["autorealize_service", "autoreport_service"])
def test_stopping_other_stage_does_not_create_an_automl_recovery_job(tmp_path, monkeypatch, source):
    task = _task(tmp_path)
    task.status = "running"
    handle = app.RuntimeHandle(process=None, source=source, remote_base_url="http://localhost:18101",
                               remote_job_id="stage-job", started_at=1)
    calls = []

    class FakeStore:
        def get(self, _id):
            return task

        def get_handle(self, _id):
            return handle

        def pop_handle(self, _id):
            return handle

        def set_status(self, _id, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(app, "store", FakeStore())
    monkeypatch.setattr(app, "_json_post", lambda *_args, **_kwargs: {"status": "stopping"})
    result = app.stop_task(app.StopTaskRequest(task_id=task.id, confirm=True))
    assert result["status"] == "stopped"
    assert calls[-1]["auto_ml_service_job_id"] is None
    assert calls[-1]["phase"] == "stopped"


def _task(
    tmp_path: Path,
    *,
    task_id: str = "task-actions",
    task_name: str = "task-actions",
    goal: str = "",
    evaluation: str = "",
) -> app.TaskModel:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir(exist_ok=True)
    output_root.mkdir(exist_ok=True)
    config = app.TaskConfigPayload(
        task_name=task_name,
        input_root=str(input_root),
        output_root=str(output_root),
        auto_ml=app.AutoMLConfigPayload(goal=goal, eval=evaluation),
    )
    return app.TaskModel(
        id=task_id,
        task_name=task_name,
        input_root=str(input_root),
        output_root=str(output_root),
        created_at=1,
        updated_at=1,
        status="idle",
        phase="config",
        config=config,
    )


def test_automl_readiness_accepts_goal_eval_without_description(tmp_path: Path) -> None:
    task = _task(
        tmp_path,
        goal="Minimize routing cost while serving every order.",
        evaluation="Total cost, lower is better; unserved orders are infeasible.",
    )

    readiness = app._automl_input_readiness(task)

    assert readiness["ready"] is True
    assert readiness["source"] == "configured_goal_eval"
    assert readiness["configured_goal"] is True
    assert readiness["configured_eval"] is True


def test_automl_readiness_requires_both_goal_and_eval(tmp_path: Path) -> None:
    task = _task(tmp_path, goal="Predict demand")

    readiness = app._automl_input_readiness(task)

    assert readiness["ready"] is False
    assert "Goal" in readiness["detail"]
    assert "Eval" in readiness["detail"]


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("filename,key", [
    ("automl_context_pack.json", "output_contract"),
    ("description_protocol_bundle.json", "output"),
])
def test_prediction_sample_requirement_agrees_with_readiness_and_launch(tmp_path, required, filename, key):
    task = _task(tmp_path)
    root = Path(task.output_root) / task.task_name / "autorealize"
    task.run_dir = str(root.parent)
    report = root / "realize_report"
    report.mkdir(parents=True)
    (root / "description.md").write_text("Audited prediction task", encoding="utf-8")
    output = {"output_kind": "prediction_table", "columns": ["id", "probability"],
              "sample_submission_required": required}
    (report / filename).write_text(json.dumps({key: output}), encoding="utf-8")
    (report / "submission_report.json").write_text(json.dumps({
        "source": "not_regenerated_after_schema_repair", "sample_submission_available": False,
    }), encoding="utf-8")
    assert app._algoevolve_generate_submission_required(root, True) is True
    assert app._automl_input_readiness(task)["ready"] is (not required)
    if required:
        with pytest.raises(HTTPException, match="sample_submission.csv"):
            app._validate_automl_rerun(task)
        (root / "sample_submission.csv").write_text("id,probability\n", encoding="utf-8")
    assert app._automl_input_readiness(task)["ready"] is True
    assert app._validate_automl_rerun(task)[0] == root.resolve()


@pytest.mark.parametrize("filename, document", [
    ("artifact_consistency_report.json", {"final": {"passed": False}}),
    ("artifact_consistency_report.json", {"final": {"passed": True, "issues": [
        {"severity": "blocking", "message": "Wrong source field"},
    ]}}),
    ("artifact_consistency_report.json", None),
    ("evaluation_contract_report.json", {"final": {"passed": True, "executable": False}}),
    ("automl_context_pack.json", {"execution_contract": {"readiness": "blocked"}}),
    ("task_definition_report.json", {"defects_after_gate": ["Invalid split"]}),
    ("task_definition_report.json", {"downstream_context": {"artifact_consistency_review": {"passed": False}}}),
])
def test_failed_artifact_gate_blocks_readiness_and_actual_launch(tmp_path, monkeypatch, filename, document):
    task = _task(tmp_path, goal="Predict", evaluation="MAE")
    root = Path(task.output_root) / task.task_name / "autorealize"
    report = root / "realize_report"
    report.mkdir(parents=True)
    (root / "description.md").write_text("Task", encoding="utf-8")
    (report / filename).write_text(json.dumps(document), encoding="utf-8")
    readiness = app._automl_input_readiness(task)
    assert readiness["ready"] is False
    assert readiness["blocking_issues"]
    statuses = []
    monkeypatch.setattr(app.store, "set_status", lambda _id, **kwargs: statuses.append(kwargs))
    monkeypatch.setattr(app, "_json_post", lambda *a, **kw: pytest.fail("Blocked task reached service"))
    assert app._run_automl_stage(
        task_id=task.id, task=task, gs=None, autorealize_dir=root,
        automl_logs_root=tmp_path, automl_workspaces_root=tmp_path,
        exp_name="blocked", ml_log_dir=tmp_path, ml_ws_dir=tmp_path,
        env={}, algoevolve_service_base="unused", req_timeout=1,
    ) is False
    assert statuses[-1]["phase"] == "prepare_automl_input_failed"


def test_passed_artifacts_and_direct_description_remain_ready(tmp_path):
    task = _task(tmp_path)
    task.config.auto_realize.generate_sample_submission = False
    (Path(task.input_root) / "description.md").write_text("Direct task", encoding="utf-8")
    assert app._automl_input_readiness(task)["ready"] is True


def test_continue_policy_allows_only_exhausted_review_findings(tmp_path):
    task = _task(tmp_path)
    task.config.auto_realize.generate_sample_submission = False
    task.config.auto_realize.review_gate_policy = "continue_on_exhaustion"
    root = Path(task.output_root) / task.task_name / "autorealize"
    task.run_dir = str(root.parent)
    report = root / "realize_report"
    report.mkdir(parents=True)
    (root / "description.md").write_text("Task", encoding="utf-8")
    (report / "artifact_consistency_report.json").write_text(
        json.dumps({"final": {"passed": False, "issues": [{"severity": "blocking", "message": "Review finding"}]}}),
        encoding="utf-8",
    )
    (report / "evaluation_contract_report.json").write_text(
        json.dumps({"final": {"passed": False, "executable": False}}), encoding="utf-8",
    )
    (report / "automl_context_pack.json").write_text(json.dumps({
        "execution_contract": {
            "readiness": "blocked",
            "blocking_issues": [
                "Final artifact consistency review has not passed.",
                "Evaluation contract has not passed executable validation.",
            ],
        },
    }), encoding="utf-8")

    readiness = app._automl_input_readiness(task)

    assert readiness["ready"] is True
    assert readiness["blocking_issues"] == []
    assert readiness["review_bypass_active"] is True
    assert readiness["can_repair_review"] is False
    assert readiness["warnings"] == readiness["review_issues"]


@pytest.mark.parametrize("document", [
    {"defects_after_gate": ["Invalid split"]},
    {"automl_context_pack": {"execution_contract": {"readiness": "blocked", "blocking_issues": []}}},
])
def test_continue_policy_keeps_deterministic_contract_failures_blocking(tmp_path, document):
    task = _task(tmp_path)
    task.config.auto_realize.generate_sample_submission = False
    task.config.auto_realize.review_gate_policy = "continue_on_exhaustion"
    root = Path(task.output_root) / task.task_name / "autorealize"
    task.run_dir = str(root.parent)
    report = root / "realize_report"
    report.mkdir(parents=True)
    (root / "description.md").write_text("Task", encoding="utf-8")
    (report / "task_definition_report.json").write_text(json.dumps(document), encoding="utf-8")

    readiness = app._automl_input_readiness(task)

    assert readiness["ready"] is False
    assert readiness["hard_blocking_issues"]


def test_review_gate_decision_records_bypassed_findings(tmp_path):
    task = _task(tmp_path)
    task.config.auto_realize.review_gate_policy = "continue_on_exhaustion"
    root = Path(task.output_root) / task.task_name / "autorealize"
    report = root / "realize_report"
    report.mkdir(parents=True)
    (report / "artifact_consistency_report.json").write_text(
        json.dumps({"final": {"passed": False}}), encoding="utf-8",
    )
    decision = app._automl_gate_decision(task, root)

    path = app._write_review_gate_decision(task, root, decision)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["proceeded"] is True
    assert payload["review_bypass_active"] is True
    assert payload["policy"] == "continue_on_exhaustion"
    assert payload["review_issues"]
    assert payload["hard_blocking_issues"] == []


def test_review_repair_cache_keeps_cognition_and_invalidates_task_definition(tmp_path):
    source = tmp_path / "llm_cache.jsonl"
    target = tmp_path / "new" / "llm_cache.jsonl"
    rows = [
        {"key": "cognition", "prompt_name": "data_cognition_file", "response": "facts"},
        {"key": "qdi", "prompt_name": "question_investigator", "response": "answer"},
        {"key": "description", "prompt_name": "description_sections_constraints", "response": "draft"},
        {"key": "review", "prompt_name": "artifact_consistency_reviewer_2", "response": "failed"},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    summary = app._copy_review_repair_cache(source, target)
    kept = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]

    assert [row["key"] for row in kept] == ["cognition", "qdi"]
    assert summary["kept_entries"] == 2
    assert summary["invalidated_entries"] == 2


@pytest.mark.parametrize("outcome", ["success", "failed", "changed_cognition"])
def test_review_repair_preserves_live_cognition_and_publishes_only_success(monkeypatch, tmp_path, outcome):
    task = _task(tmp_path)
    task.status, task.phase = "failed", "prepare_automl_input_failed"
    root = Path(task.output_root) / task.task_name
    task.run_dir = str(root)
    source = root / "autorealize"
    report = source / "realize_report"
    report.mkdir(parents=True)
    (source / "description.md").write_text("old")
    (report / "data_description.md").write_text("Original data understanding")
    (report / "data_cognition_report.json").write_text(json.dumps({
        "task_hint": task.config.auto_realize.task_hint, "files": [{"path": "sample.csv"}],
    }))
    task.config.auto_realize.generate_sample_submission = False
    calls = []
    monkeypatch.setattr(app.store, "get", lambda _: task)
    def status(_id, **changes):
        for key, value in changes.items():
            setattr(task, key, value)
    monkeypatch.setattr(app.store, "set_status", status)
    monkeypatch.setattr(app, "get_global_settings", lambda: None)
    monkeypatch.setattr(app, "_service_base_urls", lambda _: ("ar", "ml", "report", 30))
    def repair(**kwargs):
        assert kwargs["resume_definition"] is True
        assert kwargs["run_dir"] != root
        assert (source / "description.md").read_text() == "old"
        candidate = kwargs["run_dir"] / "autorealize"
        (candidate / "description.md").write_text("repaired")
        if outcome == "changed_cognition":
            (candidate / "realize_report/data_description.md").write_text("unauthorized rewrite")
        return outcome != "failed"
    monkeypatch.setattr(app, "_run_autorealize_stage", repair)
    monkeypatch.setattr(app, "_resume_task_thread", lambda task_id: calls.append(("resume", task_id)))
    app._repair_review_and_resume_thread(task.id)
    assert calls == ([("resume", task.id)] if outcome == "success" else [])
    assert (source / "description.md").read_text() == ("repaired" if outcome == "success" else "old")
    assert (report / "data_description.md").read_text() == "Original data understanding"
    archives = list((root / "stage-history").glob("*/previous-autorealize/description.md"))
    if outcome == "success":
        assert len(archives) == 1 and archives[0].read_text() == "old"
    else:
        assert not archives


@pytest.mark.parametrize("status,phase,downstream", [
    ("completed", "autorealize_completed", False), ("running", "autorealize", False),
    ("stopped", "stopped", False), ("failed", "report_failed", True),
    ("failed", "autorealize_failed", True), ("failed", "interrupted", True),
])
def test_review_repair_cannot_rewind_completed_or_downstream_tasks(tmp_path, status, phase, downstream):
    task = _task(tmp_path)
    task.status, task.phase = status, phase
    if downstream:
        task.auto_ml_log_dir = str(tmp_path / "old-search")
    assert app._automl_input_readiness(task)["can_repair_review"] is False
    with pytest.raises(HTTPException, match="仅任务定义"):
        app._validate_review_repair(task)


def test_review_repair_requires_confirmed_current_file_plan(tmp_path, monkeypatch):
    task = _task(tmp_path)
    task.status, task.phase = "failed", "autorealize_failed"
    root = Path(task.output_root) / task.task_name / "autorealize/realize_report"
    root.mkdir(parents=True)
    checkpoint = root / "data_cognition_report.json"
    checkpoint.write_text(json.dumps({"files": [{"path": "a.csv"}], "task_hint": task.config.auto_realize.task_hint}))
    monkeypatch.setattr(app.store, "get", lambda _: task)
    plan = app._review_repair_plan(task)
    assert plan["delete_paths"] == [] and plan["files"]
    with pytest.raises(HTTPException, match="变更清单"):
        app.repair_review_and_resume(app.RepairReviewRequest(task_id=task.id, confirm=True))
    (root / "data_description.md").write_text("changed after preview")
    with pytest.raises(HTTPException, match="变更清单"):
        app.repair_review_and_resume(app.RepairReviewRequest(task_id=task.id, confirm=True, plan_token=plan["plan_token"]))


def test_report_resume_routes_before_any_upstream_validation(tmp_path, monkeypatch):
    task = _task(tmp_path)
    task.status, task.phase = "failed", "report_failed"
    calls = []
    monkeypatch.setattr(app.store, "get", lambda _: task)
    monkeypatch.setattr(app, "_rerun_autoreport_thread", lambda task_id: calls.append(task_id))
    monkeypatch.setattr(app, "_autorealize_outputs_ready", lambda *a, **kw: pytest.fail("Touched upstream"))
    app._resume_task_thread(task.id)
    assert calls == [task.id]


def test_repair_claim_is_atomic_and_prevents_repeated_or_stale_submission(tmp_path, monkeypatch):
    task = _task(tmp_path)
    task.status, task.phase = "failed", "autorealize_failed"
    store = object.__new__(app.TaskStore)
    store._lock, store._tasks, store._handles = threading.Lock(), {task.id: task}, {}
    monkeypatch.setattr(store, "_persist", lambda: None)
    expected = task.model_copy(deep=True)
    store.claim_review_repair(expected)
    assert task.status == "running" and task.phase == "review_repair"
    with pytest.raises(HTTPException, match="状态已变化"):
        store.claim_review_repair(expected)


@pytest.mark.parametrize("status", ["stopped", "failed"])
def test_report_interruption_keeps_its_stage_when_resumed(tmp_path, monkeypatch, status):
    task = _task(tmp_path)
    task.status, task.phase = status, "interrupted"
    task.interrupted_from_phase = "report"
    calls = []
    monkeypatch.setattr(app.store, "get", lambda _: task)
    monkeypatch.setattr(app, "_rerun_autoreport_thread", lambda task_id: calls.append(task_id))
    app._resume_task_thread(task.id)
    assert calls == [task.id]


def test_goal_eval_materializes_direct_automl_description(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task = _task(
        tmp_path,
        goal="Choose a feasible assignment with minimum cost.",
        evaluation="Minimize total cost and reject infeasible assignments.",
    )
    run_dir = Path(task.output_root) / task.task_name
    autorealize_dir = run_dir / "autorealize"
    statuses: list[dict[str, object]] = []

    class FakeStore:
        @staticmethod
        def set_status(task_id: str, **kwargs):
            statuses.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(app, "store", FakeStore())

    ok = app._prepare_direct_autorealize_output(
        task_id=task.id,
        task=task,
        input_root=Path(task.input_root),
        run_dir=run_dir,
        autorealize_dir=autorealize_dir,
    )

    assert ok is True
    description = (autorealize_dir / "description.md").read_text(encoding="utf-8")
    assert "Choose a feasible assignment" in description
    assert "Minimize total cost" in description
    assert statuses[-1]["phase"] == "automl_input_ready"


def test_continue_automl_requires_existing_search_tree_paths(tmp_path: Path) -> None:
    task = _task(tmp_path)

    with pytest.raises(HTTPException, match="尚未执行过 AutoML"):
        app._validate_continue_automl(task)

    run_dir = Path(task.output_root) / task.task_name
    log_dir = run_dir / "automl" / "logs" / "run-1"
    workspace_dir = run_dir / "automl" / "workspaces" / "run-1"
    log_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    autorealize_dir = run_dir / "autorealize"
    autorealize_dir.mkdir(parents=True)
    (autorealize_dir / "description.md").write_text("task", encoding="utf-8")
    task.auto_ml_log_dir = str(log_dir)
    task.auto_ml_workspace_dir = str(workspace_dir)
    task.status = "interrupted_resumable"

    resolved = app._validate_continue_automl(task)

    assert resolved[-2] == log_dir.resolve()
    assert resolved[-1] == workspace_dir.resolve()


def test_report_accepts_interrupted_automl_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task = _task(tmp_path)
    task.config.auto_realize.generate_sample_submission = False
    task.status = "interrupted_resumable"
    run_dir = Path(task.output_root) / task.task_name
    autorealize_dir = run_dir / "autorealize"
    log_dir = run_dir / "automl" / "logs" / "run-1"
    workspace_dir = run_dir / "automl" / "workspaces" / "run-1"
    autorealize_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    (autorealize_dir / "description.md").write_text("task", encoding="utf-8")
    monkeypatch.setattr(app, "_pick_local_automl_log_dir", lambda _task: log_dir)
    monkeypatch.setattr(
        app,
        "_pick_local_automl_workspace_dir",
        lambda _task, exp_name=None: workspace_dir,
    )

    resolved = app._validate_autoreport_rerun(task)

    assert resolved[3] == log_dir
    assert resolved[4] == workspace_dir


def test_delete_task_files_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    task = _task(tmp_path)
    run_dir = Path(task.output_root) / task.task_name
    run_dir.mkdir(parents=True)
    (run_dir / "keep.txt").write_text("keep", encoding="utf-8")
    deleted_ids: list[str] = []

    class FakeStore:
        @staticmethod
        def get(task_id: str):
            assert task_id == task.id
            return task

        @staticmethod
        def delete(task_id: str):
            deleted_ids.append(task_id)

    monkeypatch.setattr(app, "store", FakeStore())

    kept = app.delete_task(task.id, delete_files=False)

    assert kept["deleted_files"] == []
    assert run_dir.exists()

    removed = app.delete_task(task.id, delete_files=True)

    assert str(run_dir.resolve()) in removed["deleted_files"]
    assert not run_dir.exists()
    assert deleted_ids == [task.id, task.id]

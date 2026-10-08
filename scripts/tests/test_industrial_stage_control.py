import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("stage_control", Path(__file__).parents[1] / "industrial-stage-control.py")
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


def test_two_task_admission_remains_exclusive_per_task():
    first = {"id": "first", "status": "running"}
    second = {"id": "second", "status": "idle"}
    profile = {"simultaneous_tasks": 2}
    control.validate_concurrent_admission([first, second], second, profile)
    with pytest.raises(RuntimeError, match="active stage"):
        control.validate_concurrent_admission([first, second], first, profile)
    with pytest.raises(RuntimeError, match="limit reached"):
        control.validate_concurrent_admission([first, {**second, "status": "running"}], {"id": "third", "status": "idle"}, profile)


def test_resource_pressure_reduces_task_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(control.batch, "OUT", tmp_path)
    (tmp_path / "execution-slots/reduced-to-one").mkdir(parents=True)
    tasks = [{"id": "a", "status": "running"}, {"id": "b", "status": "running"}]
    with pytest.raises(RuntimeError, match="limit reached"):
        control.validate_concurrent_admission(tasks, {"id": "c", "status": "idle"}, {"simultaneous_tasks": 3})


def test_configured_provider_and_missing_required_fields_control_launch():
    model = {"id": "text", "model": "deepseek-v4.1", "baseUrl": "https://api.deepseek.com",
             "reasoningEffort": "default", "maxTokens": 32768, "apiKeyConfigured": True}
    settings = {"llm": {"modelLibrary": [model], "roleModels": {
        "autoRealize": "text", "autoMlCode": "text", "autoMlFeedback": "text"}}}
    control.validate_provider(settings)
    for field, invalid in (("model", ""), ("baseUrl", ""), ("apiKeyConfigured", False),
                           ("maxTokens", 8192)):
        previous = model[field]
        model[field] = invalid
        with pytest.raises(RuntimeError, match="refusing launch"):
            control.validate_provider(settings)
        model[field] = previous


@pytest.mark.parametrize("elapsed", [0, 10799.9, float("nan"), float("inf")])
def test_configured_budget_does_not_prove_actual_search(tmp_path, elapsed):
    (tmp_path / "run_status.json").write_text(json.dumps({"status": "completed", "time_limit_secs": 10800}))
    (tmp_path / "search_state.json").write_text(json.dumps({"cumulative_search_elapsed_seconds": elapsed}))
    with pytest.raises(RuntimeError):
        control.verified_search_seconds({"auto_ml_log_dir": str(tmp_path)})


def test_accepts_durable_duration_and_detects_changed_search_artifact(tmp_path):
    (tmp_path / "run_status.json").write_text('{"status":"completed"}')
    (tmp_path / "search_state.json").write_text('{"cumulative_search_elapsed_seconds":10800.2}')
    (tmp_path / "journal.json").write_text('{"nodes":[]}')
    task = {"auto_ml_log_dir": str(tmp_path), "run_dir": str(tmp_path)}
    assert control.verified_search_seconds(task) == 10800.2
    before = control.fingerprint(control.stage_artifacts(task, "automl"))
    (tmp_path / "journal.json").write_text('{"nodes":["different"]}')
    assert before != control.fingerprint(control.stage_artifacts(task, "automl"))


def test_admission_is_exclusive_and_released(tmp_path, monkeypatch):
    monkeypatch.setattr(control.batch, "OUT", tmp_path)
    with control.admission_lock():
        with pytest.raises(RuntimeError):
            with control.admission_lock():
                pytest.fail("Concurrent admission succeeded")
    assert not (tmp_path / "stage-admission.lock").exists()


def test_review_fingerprint_covers_handoff_context_and_saved_model(tmp_path):
    report = tmp_path / "autorealize/realize_report"
    report.mkdir(parents=True)
    (report.parent / "description.md").write_text("task")
    (report / "automl_context.md").write_text("context")
    (report / "evaluation_contract_report.json").write_text("{}")
    context = report / "automl_context_pack.json"
    context.write_text('{"constraint":"first"}')
    task = {"run_dir": str(tmp_path)}
    before = control.fingerprint(control.stage_artifacts(task, "autorealize"))
    context.write_text('{"constraint":"changed"}')
    assert before != control.fingerprint(control.stage_artifacts(task, "autorealize"))

    logs = tmp_path / "logs"
    logs.mkdir()
    for name in ("run_status.json", "search_state.json", "journal.json"):
        (logs / name).write_text("{}")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model = workspace / "model.joblib"
    model.write_bytes(b"first model")
    task.update(auto_ml_log_dir=str(logs), auto_ml_workspace_dir=str(workspace))
    before = control.fingerprint(control.stage_artifacts(task, "automl"))
    model.write_bytes(b"changed model")
    assert before != control.fingerprint(control.stage_artifacts(task, "automl"))


def test_task_definition_gate_rejects_failed_audit_and_divergent_contract(tmp_path):
    root = tmp_path / "autorealize/realize_report"
    root.mkdir(parents=True)
    contract = {"passed": True, "executable": True, "primary_metric": "MAE"}
    files = {
        "evaluation_contract_report.json": {"final": contract},
        "artifact_consistency_report.json": {"final": {"passed": False, "issues": []}},
        "task_definition_report.json": {"evaluation_contract": contract, "defects_after_gate": []},
        "main_task_protocol.json": {"evaluation_contract": contract},
        "automl_context_pack.json": {"evaluation_contract": contract, "execution_contract": {"readiness": "ready"}},
    }
    for name, content in files.items():
        (root / name).write_text(json.dumps(content))
    task = {"run_dir": str(tmp_path)}
    with pytest.raises(RuntimeError, match="consistency audit"):
        control.verify_task_definition(task)
    (root / "artifact_consistency_report.json").write_text('{"final":{"passed":true,"issues":[]}}')
    control.verify_task_definition(task)
    (root / "automl_context_pack.json").write_text(json.dumps({"evaluation": contract}))
    with pytest.raises(RuntimeError, match="AutoML context"):
        control.verify_task_definition(task)
    (root / "automl_context_pack.json").write_text(json.dumps(files["automl_context_pack.json"]))
    (root / "main_task_protocol.json").write_text('{"evaluation_contract":{"primary_metric":"RMSE"}}')
    with pytest.raises(RuntimeError, match="copies disagree"):
        control.verify_task_definition(task)


def test_archived_layout_is_excluded_but_unreadable_active_model_blocks_review(tmp_path, monkeypatch):
    logs, workspace = tmp_path / "logs", tmp_path / "workspace"
    logs.mkdir()
    workspace.mkdir()
    archived = workspace / "input-before-layout-repair-123" / "old-junction"
    archived.parent.mkdir()
    archived.touch()
    model = workspace / "model.joblib"
    model.write_bytes(b"model")
    task = {"run_dir": str(tmp_path), "auto_ml_log_dir": str(logs), "auto_ml_workspace_dir": str(workspace)}
    original_is_file = Path.is_file
    inaccessible = {archived}

    def guarded_is_file(path, *args, **kwargs):
        if path in inaccessible:
            raise PermissionError(str(path))
        return original_is_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    files = control.stage_artifacts(task, "automl")
    assert model in files and archived not in files
    inaccessible.add(model)
    with pytest.raises(PermissionError):
        control.stage_artifacts(task, "automl")


@pytest.mark.parametrize("phase", ["report_failed", "report_completed"])
def test_automl_rereview_after_report_requires_actual_completed_search(tmp_path, monkeypatch, phase):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run_status.json").write_text('{"status":"completed"}')
    (logs / "search_state.json").write_text('{"cumulative_search_elapsed_seconds":10800.2}')
    (logs / "journal.json").write_text('{"nodes":[]}')
    task = {"phase": phase, "status": "failed" if phase == "report_failed" else "completed",
            "run_dir": str(tmp_path), "auto_ml_log_dir": str(logs)}
    monkeypatch.setattr(control, "current_task", lambda slug: task)
    monkeypatch.setattr(control, "LEDGER", tmp_path / "ledger.json")
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{}')
    review = {"passed": True, **{field: ["verified"] for field in (
        "strengths", "weaknesses", "system_changes", "constraint_checks", "quality_checks", "usage_analysis")},
        "evidence_paths": [str(evidence)]}
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review))
    control.record_review("chemical", "automl", review_path)
    assert control.read_json(control.LEDGER)["chemical"]["automl"]["verified_search_seconds"] == 10800.2
    (logs / "search_state.json").write_text('{"cumulative_search_elapsed_seconds":100}')
    with pytest.raises(RuntimeError):
        control.record_review("chemical", "automl", review_path)
    task["status"] = "running"
    with pytest.raises(RuntimeError, match="has not completed"):
        control.record_review("chemical", "automl", review_path)

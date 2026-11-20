from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app


def test_report_evidence_prefers_current_run_over_automl_root(tmp_path: Path) -> None:
    autorealize = tmp_path / "autorealize"
    automl = tmp_path / "automl"
    logs = automl / "logs" / "current"
    workspace = automl / "workspaces" / "current"
    for path in (autorealize, logs, workspace):
        path.mkdir(parents=True)
    (automl / "workspaces" / "old").mkdir(parents=True)

    evidence = app._report_evidence_paths(
        autorealize_dir=autorealize,
        automl_root=automl,
        ml_log_dir=logs,
        ml_ws_dir=workspace,
    )

    assert [row["label"] for row in evidence] == [
        "autorealize",
        "automl_logs",
        "automl_workspace",
    ]


def test_report_retains_prior_evaluation_exposure_outside_search_input(tmp_path):
    autorealize = tmp_path / "autorealize"
    automl = tmp_path / "automl"
    autorealize.mkdir()
    automl.mkdir()
    provenance = tmp_path / "evaluation_provenance.json"
    provenance.write_text('{"prior_holdout_access":true}', encoding="utf-8")
    evidence = app._report_evidence_paths(autorealize_dir=autorealize, automl_root=automl, ml_log_dir=None, ml_ws_dir=None)
    assert [row["label"] for row in evidence] == ["autorealize", "evaluation_provenance", "automl_root"]
    assert evidence[1]["required"] is True
    assert not (autorealize / provenance.name).exists()


def test_report_evidence_falls_back_to_automl_root(tmp_path: Path) -> None:
    autorealize = tmp_path / "autorealize"
    automl = tmp_path / "automl"
    autorealize.mkdir()
    automl.mkdir()

    evidence = app._report_evidence_paths(
        autorealize_dir=autorealize,
        automl_root=automl,
        ml_log_dir=None,
        ml_ws_dir=None,
    )

    assert [row["label"] for row in evidence] == ["autorealize", "automl_root"]


def test_start_task_thread_reports_resolved_automl_directories(tmp_path: Path, monkeypatch) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    output_root = tmp_path / "runs"
    stale_log = tmp_path / "logs" / "requested-name"
    stale_workspace = tmp_path / "workspaces" / "requested-name"
    actual_log = tmp_path / "logs" / "20261024_030916_requested-name"
    actual_workspace = tmp_path / "workspaces" / "20261024_030916_requested-name"
    actual_log.mkdir(parents=True)
    actual_workspace.mkdir(parents=True)

    config = app.TaskConfigPayload(task_name="resolved-path-test", input_root=str(input_root), output_root=str(output_root))
    task = app.TaskModel(
        id="resolved-path-test-id", task_name=config.task_name, input_root=str(input_root),
        output_root=str(output_root), created_at=1, updated_at=1, status="idle", phase="idle", config=config,
    )

    class MemoryStore:
        def get(self, _task_id):
            return task

        def set_status(self, _task_id, **values):
            for name, value in values.items():
                setattr(task, name, value)
            return task

    monkeypatch.setattr(app, "store", MemoryStore())
    monkeypatch.setattr(app, "get_global_settings", lambda: SimpleNamespace(llm={}, python={"executable": "python"}))
    monkeypatch.setattr(app, "_service_base_urls", lambda _gs: ("ar", "automl", "report", 30))
    monkeypatch.setattr(app, "_validate_start", lambda _task: (input_root, output_root))
    monkeypatch.setattr(app, "_build_automl_paths", lambda *args, **kwargs: ("requested-name", stale_log, stale_workspace))
    monkeypatch.setattr(app, "_selected_model", lambda *args, **kwargs: {})
    monkeypatch.setattr(app, "_direct_mode_enabled", lambda _task: False)
    monkeypatch.setattr(app, "_run_autorealize_stage", lambda **kwargs: True)

    def run_automl(**_kwargs):
        task.auto_ml_log_dir = str(actual_log)
        task.auto_ml_workspace_dir = str(actual_workspace)
        return True

    reported = {}

    def run_report(**kwargs):
        reported.update(kwargs)
        return True

    monkeypatch.setattr(app, "_run_automl_stage", run_automl)
    monkeypatch.setattr(app, "_run_report_stage", run_report)

    app._start_task_thread(task.id)

    assert reported["ml_log_dir"] == actual_log.resolve()
    assert reported["ml_ws_dir"] == actual_workspace.resolve()
    assert task.status == "completed"


def test_autoreport_frontend_config_exposes_only_effective_controls() -> None:
    cfg = app.AutoReportConfigPayload(
        detail_level="standard",
        comparison_candidate_limit=8,
        max_retrieval_rounds=3,
        enable_report_audit=False,
    )

    assert cfg.model_dump() == {
        "enabled": True,
        "request_timeout_secs": 1200.0,
        "audience": "technical",
        "detail_level": "standard",
        "comparison_candidate_limit": 8,
        "max_retrieval_rounds": 3,
        "enable_report_audit": False,
    }


@pytest.mark.parametrize("detail,window", [("detailed", 131072), ("standard", 65536)])
def test_report_default_character_limit_follows_model_window_without_reducing_token_guards(tmp_path, monkeypatch, detail, window):
    captured = {}
    monkeypatch.setattr("delivery.begin_report", lambda *a: {"report_run_id": "test"})
    monkeypatch.setattr("delivery.import_report", lambda *a: None)
    task = SimpleNamespace(task_name="Industrial task", status="idle", config=SimpleNamespace(
        output_language="zh", auto_report=app.AutoReportConfigPayload(detail_level=detail),
    ))
    model = {"model": "gpt-5.6-luna", "baseUrl": "https://provider.example/v1", "apiKey": "test-key",
             "contextWindowTokens": window, "maxTokens": 32768, "reasoningEffort": "xhigh"}
    monkeypatch.setattr(app, "_selected_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(app, "store", SimpleNamespace(
        set_status=lambda *args, **kwargs: setattr(task, "status", kwargs["status"]), get=lambda *args: task,
        attach_handle=lambda *args: None, pop_handle=lambda *args: None,
    ))
    def post(base, endpoint, payload, **kwargs):
        captured.update(payload)
        return {"job_id": "report-job"}
    monkeypatch.setattr(app, "_json_post", post)
    monkeypatch.setattr(app, "_poll_remote_job", lambda *args, **kwargs: {"status": "completed", "exit_code": 0})
    assert app._run_report_stage(task_id="task", task=task, gs=SimpleNamespace(llm={}, python={}),
        autorealize_dir=tmp_path / "autorealize", automl_root=tmp_path / "automl", ml_log_dir=None,
        ml_ws_dir=None, report_dir=tmp_path / "report", report_base="http://localhost", req_timeout=30)
    config = captured["config"]
    assert config["generation"]["max_prompt_chars"] == window * 4
    assert config["llm"]["context_window_tokens"] == window
    assert config["llm"]["context_headroom_ratio"] == 0.01
    assert config["llm"]["request_timeout_seconds"] == 1200.0
    assert config["llm"]["max_tokens"] == 32768
    assert config["llm"]["reasoning_effort"] == "xhigh"


def test_report_requires_explicit_inference_repair_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    package = workspace / "best_solution"
    package.mkdir(parents=True)
    names = ("inference_repair_provenance.json", "inference_repair_validation.json", "inference_repair_evaluation.json")
    for name in names:
        (package / name).write_text('{"prior_holdout_exposure":true}', encoding="utf-8")
    evidence = app._report_evidence_paths(autorealize_dir=tmp_path / "autorealize", automl_root=tmp_path / "automl", ml_log_dir=None, ml_ws_dir=workspace)
    repairs = [item for item in evidence if item["label"].startswith("inference_repair_")]
    assert len(repairs) == 3 and all(item["required"] for item in repairs)
    assert {Path(item["path"]).name for item in repairs} == set(names)

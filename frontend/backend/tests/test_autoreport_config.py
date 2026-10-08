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


def test_autoreport_frontend_config_exposes_only_effective_controls() -> None:
    cfg = app.AutoReportConfigPayload(
        detail_level="standard",
        comparison_candidate_limit=8,
        max_retrieval_rounds=3,
        enable_report_audit=False,
    )

    assert cfg.model_dump() == {
        "enabled": True,
        "audience": "technical",
        "detail_level": "standard",
        "comparison_candidate_limit": 8,
        "max_retrieval_rounds": 3,
        "enable_report_audit": False,
    }


@pytest.mark.parametrize("detail,window", [("detailed", 131072), ("standard", 65536)])
def test_report_default_character_limit_follows_model_window_without_reducing_token_guards(tmp_path, monkeypatch, detail, window):
    captured = {}
    task = SimpleNamespace(task_name="Industrial task", status="idle", config=SimpleNamespace(
        output_language="zh", auto_report=app.AutoReportConfigPayload(detail_level=detail),
    ))
    model = {"model": "gpt-5.6-luna", "baseUrl": "https://provider.example/v1", "apiKey": "test-key",
             "contextWindowTokens": window, "maxTokens": 32768, "reasoningEffort": "xhigh"}
    monkeypatch.setattr(app, "_selected_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(app, "store", SimpleNamespace(
        set_status=lambda *args, **kwargs: None, get=lambda *args: task,
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
    assert config["llm"]["context_headroom_ratio"] == 0.18
    assert config["llm"]["max_tokens"] == 32768
    assert config["llm"]["reasoning_effort"] == "xhigh"

from __future__ import annotations

from pathlib import Path

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

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import app


def _task(run_dir: Path, wrapper_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        task_name="ps001",
        run_dir=str(run_dir),
        output_root=str(run_dir.parent),
        auto_ml_log_dir=str(run_dir / "automl" / "logs" / wrapper_name),
        auto_ml_workspace_dir=str(run_dir / "automl" / "workspaces" / wrapper_name),
        config=SimpleNamespace(auto_ml=SimpleNamespace(engine="mlevolve")),
    )


def test_snapshot_prefers_mlevolve_artifacts_over_service_wrapper(tmp_path: Path) -> None:
    run_dir = tmp_path / "ps001"
    logs = run_dir / "automl" / "logs"
    workspaces = run_dir / "automl" / "workspaces"
    wrapper_name = "20260713_231117_ps001__20260713_231117"
    artifact_name = "20260713231117_ps001__20260713_231117"
    wrapper = logs / wrapper_name
    artifact = logs / artifact_name
    wrapper_workspace = workspaces / wrapper_name
    artifact_workspace = workspaces / artifact_name
    for path in (wrapper, artifact, wrapper_workspace, artifact_workspace):
        path.mkdir(parents=True, exist_ok=True)

    (wrapper / "_service_stdout.log").write_text("completed", encoding="utf-8")
    (wrapper / "resource_usage.json").write_text("{}", encoding="utf-8")
    journal = {
        "nodes": [
            {
                "id": "node-1",
                "stage": "draft",
                "code": "print('ok')",
                "metric": {"value": 1.5, "maximize": False},
            }
        ],
        "node2parent": {},
        "__version": "3",
    }
    (artifact / "journal.json").write_text(json.dumps(journal), encoding="utf-8")
    best_dir = artifact_workspace / "best_solution"
    best_dir.mkdir()
    (best_dir / "solution.py").write_text("print('best')", encoding="utf-8")
    (best_dir / "metric.txt").write_text("1.5", encoding="utf-8")

    task = _task(run_dir, wrapper_name)
    snapshot = app._build_local_automl_snapshot(task)

    assert Path(snapshot["log_dir"]) == artifact.resolve()
    assert Path(snapshot["workspace_dir"]) == artifact_workspace.resolve()
    assert [node["id"] for node in snapshot["nodes"]] == ["node-1"]
    assert snapshot["best_solution_code"] == "print('best')"


def test_wrapper_is_kept_before_matching_engine_artifacts_exist(tmp_path: Path) -> None:
    run_dir = tmp_path / "ps001"
    wrapper_name = "20260713_231117_ps001__20260713_231117"
    wrapper = run_dir / "automl" / "logs" / wrapper_name
    wrapper.mkdir(parents=True)
    (wrapper / "_service_stdout.log").write_text("starting", encoding="utf-8")

    task = _task(run_dir, wrapper_name)

    assert app._pick_local_automl_log_dir(task) == wrapper.resolve()

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
                "is_buggy": False,
                "is_valid": True,
                "search_eligible": True,
                "delivery_ready": True,
                "delivery_certified": False,
                "method_mode": "non_rl_solver",
            },
            {
                "id": "node-incomplete",
                "stage": "draft",
                "code": "print('partial')",
                "metric": {"value": 0.5, "maximize": False},
                "is_buggy": False,
                "is_valid": False,
                "search_eligible": True,
                "delivery_ready": False,
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
    assert [node["id"] for node in snapshot["nodes"]] == ["node-1", "node-incomplete"]
    assert snapshot["best_node_id"] == "node-1"
    assert snapshot["best_node_kind"] == "delivery"
    assert snapshot["nodes"][0]["delivery_ready"] is True
    assert snapshot["best_solution_code"] == "print('best')"


def test_wrapper_is_kept_before_matching_engine_artifacts_exist(tmp_path: Path) -> None:
    run_dir = tmp_path / "ps001"
    wrapper_name = "20260713_231117_ps001__20260713_231117"
    wrapper = run_dir / "automl" / "logs" / wrapper_name
    wrapper.mkdir(parents=True)
    (wrapper / "_service_stdout.log").write_text("starting", encoding="utf-8")

    task = _task(run_dir, wrapper_name)

    assert app._pick_local_automl_log_dir(task) == wrapper.resolve()


def test_local_checkpoint_promotes_remote_incomplete_state(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "resume-task"
    run_name = "20260722015005_resume-task"
    log_dir = run_dir / "automl" / "logs" / run_name
    workspace_dir = run_dir / "automl" / "workspaces" / run_name
    log_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    manifest = {"status": "interrupted_resumable", "resumable": True}
    for path in (log_dir / "journal.json", log_dir / "search_state.json"):
        path.write_text("{}", encoding="utf-8")
    (log_dir / "run_status.json").write_text(
        json.dumps({"status": "interrupted_resumable"}),
        encoding="utf-8",
    )
    for path in (
        log_dir / "checkpoint_manifest.json",
        workspace_dir / "checkpoint_manifest.json",
    ):
        path.write_text(json.dumps(manifest), encoding="utf-8")

    task = _task(run_dir, run_name)
    task.id = "resume-task-id"
    task.status = "interrupted_incomplete"
    captured: dict[str, object] = {}

    class FakeStore:
        def set_status(self, task_id: str, **kwargs):
            captured.update({"task_id": task_id, **kwargs})
            return SimpleNamespace(id=task_id, **kwargs)

    monkeypatch.setattr(app, "store", FakeStore())

    promoted = app._promote_local_resumable_checkpoint(task)

    assert promoted is not None
    assert captured["status"] == "interrupted_resumable"
    assert captured["phase"] == "automl_interrupted_resumable"
    assert Path(str(captured["auto_ml_log_dir"])) == log_dir.resolve()
    assert Path(str(captured["auto_ml_workspace_dir"])) == workspace_dir.resolve()
    assert captured["auto_ml_service_job_id"] is None


def test_snapshot_marks_best_searchable_node_as_provisional(tmp_path: Path) -> None:
    run_dir = tmp_path / "task14"
    artifact_name = "20260720233100_task14"
    artifact = run_dir / "automl" / "logs" / artifact_name
    workspace = run_dir / "automl" / "workspaces" / artifact_name
    artifact.mkdir(parents=True)
    workspace.mkdir(parents=True)
    journal = {
        "nodes": [
            {
                "id": "candidate-a",
                "stage": "debug",
                "metric": {"value": 1800.0, "maximize": False},
                "is_buggy": False,
                "is_valid": False,
                "search_eligible": True,
                "delivery_ready": False,
            },
            {
                "id": "candidate-b",
                "stage": "debug",
                "metric": {"value": 1200.0, "maximize": False},
                "is_buggy": False,
                "is_valid": False,
                "search_eligible": True,
                "delivery_ready": False,
            },
        ],
        "node2parent": {},
        "__version": "3",
    }
    (artifact / "journal.json").write_text(json.dumps(journal), encoding="utf-8")
    task = _task(run_dir, artifact_name)

    snapshot = app._build_local_automl_snapshot(task)

    assert snapshot["best_node_id"] == "candidate-b"
    assert snapshot["best_node_kind"] == "provisional"

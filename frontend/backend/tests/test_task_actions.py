from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import app


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

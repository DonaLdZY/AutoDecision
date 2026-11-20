"""Historical report recovery must never open the destructive rerun guard."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app


@pytest.fixture
def historical(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(app, "PROJECT_RUNS_DIR", runs)
    monkeypatch.setattr(app, "DEFAULT_RUNS_DIR", runs)
    monkeypatch.setattr(app, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(app, "TASKS_FILE", tmp_path / "state/tasks.json")
    monkeypatch.setattr(app, "store", app.TaskStore())
    monkeypatch.setattr(app.replay_recorder, "observe_task", lambda *args: None)
    monkeypatch.delenv("AUTODECISION_API_TOKEN", raising=False)
    config = app.TaskConfigPayload(
        task_name="工业实例-逐门架车流预测", input_root=str(tmp_path / "input"),
        output_root=r"D:Files\项目\AutoDecision\runs\industrial-examples\tasks",
    )
    root = runs / "industrial-examples" / "tasks" / config.task_name
    log_dir = root / "automl/logs/run-1"
    workspace = root / "automl/workspaces/run-1"
    for path in (root / "autorealize", root / "report", log_dir, workspace):
        path.mkdir(parents=True, exist_ok=True)
    (root / "autorealize/description.md").write_text("Traffic forecast contract", encoding="utf-8")
    (log_dir / "journal.json").write_text('{"nodes":[]}', encoding="utf-8")
    (workspace / "model.bin").write_bytes(b"frozen-model")
    (root / "report/report.md").write_text("Existing report", encoding="utf-8")
    task = app.TaskModel(
        id="historical-report", task_name=config.task_name, input_root=config.input_root,
        output_root=config.output_root, config=config, created_at=1, updated_at=1,
        run_dir=str(root), auto_ml_log_dir=str(log_dir), auto_ml_workspace_dir=str(workspace),
        status="completed", phase="report_completed",
        execution_config=config.model_dump(),
    )
    app.store._tasks[task.id] = task
    return task, root


def _hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("stale_root", [r"D:Files\项目\runs", "wrong/normalized/Files/runs"])
def test_report_reuses_only_persisted_historical_artifacts(historical, stale_root):
    task, root = historical
    task.output_root = stale_root
    frozen = task.execution_config.copy()
    result = app._validate_autoreport_rerun(task)
    assert result[0] == root.resolve()
    assert result[3] == Path(task.auto_ml_log_dir)
    assert result[4] == Path(task.auto_ml_workspace_dir)
    assert result[5] == root / "report"
    assert task.output_root == stale_root and task.execution_config == frozen
    assert not app._is_safe_task_output_dir(task, root)


def test_report_exception_does_not_permit_delete_or_full_rerun(historical, monkeypatch):
    task, root = historical
    before = _hashes(root)
    with pytest.raises(HTTPException, match="Refused to delete unsafe"):
        app.delete_task(task.id, delete_files=True)
    monkeypatch.setattr(app, "_start_task_thread", lambda *_: pytest.fail("must not restart search"))
    app._full_rerun_task_thread(task.id)
    assert "Refused to delete unsafe" in task.last_error
    assert _hashes(root) == before


@pytest.mark.parametrize("problem", ["name", "unpersisted", "outside", "log", "workspace", "description"])
def test_historical_report_requires_matching_local_evidence(historical, tmp_path, problem):
    task, root = historical
    if problem == "name":
        task.task_name = "Other task"
    elif problem == "unpersisted":
        task.run_dir = None
    elif problem == "outside":
        outside = tmp_path / "external" / task.task_name
        outside.mkdir(parents=True)
        task.run_dir = str(outside)
    elif problem in {"log", "workspace"}:
        outside = tmp_path / "unrelated" / "run-1"
        outside.mkdir(parents=True)
        if problem == "log":
            task.auto_ml_log_dir = str(outside)
        else:
            # No in-run workspace remains for the local picker to prefer.
            Path(task.auto_ml_workspace_dir).rename(root / "unrelated-workspace")
            task.auto_ml_workspace_dir = str(outside)
    else:
        (root / "autorealize/description.md").unlink()
    expected = "description.md" if problem == "unpersisted" else "无法安全确认报告输出位置"
    with pytest.raises(HTTPException, match=expected):
        app._validate_autoreport_rerun(task)
    if problem == "unpersisted":
        assert not app._is_safe_report_task_dir(
            task, root, Path(task.auto_ml_log_dir), Path(task.auto_ml_workspace_dir),
        )


@pytest.mark.parametrize("stage", ["report", "stage-history", "autorealize"])
def test_report_rejects_stage_directory_symlink_escape(historical, tmp_path, stage):
    task, root = historical
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / stage
    if target.exists():
        target.rename(root / ("saved-" + stage))
    try:
        target.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")
    with pytest.raises(HTTPException):
        app._validate_autoreport_rerun(task)
    assert list(outside.iterdir()) == []


def test_report_rejects_existing_file_link(historical, tmp_path):
    task, root = historical
    outside = tmp_path / "external.txt"
    outside.write_text("preserve", encoding="utf-8")
    try:
        (root / "report/_service_stdout.log").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"File symlinks unavailable: {exc}")
    with pytest.raises(HTTPException, match="链接文件"):
        app._validate_autoreport_rerun(task)
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_report_http_confirmation_uses_real_guard_and_claims_once(historical, monkeypatch):
    task, root = historical
    launched = []

    class DeferredThread:
        def __init__(self, **kwargs):
            launched.append(kwargs)

        def start(self):
            pass

    with TestClient(app.app) as client:
        with monkeypatch.context() as patch:
            patch.setattr(app.threading, "Thread", DeferredThread)
            response = client.post("/api/tasks/rerun-autoreport", json={"task_id": task.id, "confirm": True})
            assert response.status_code == 200, response.text
            assert response.json()["mode"] == "autoreport_only"
            assert task.status == "running" and task.phase == "report"
            checkpoint = launched[0]["args"][1]
            assert checkpoint.status == "completed" and checkpoint.run_dir == str(root)
            duplicate = client.post("/api/tasks/rerun-autoreport", json={"task_id": task.id, "confirm": True})
            assert duplicate.status_code in (400, 409)
            assert len(launched) == 1


def test_report_thread_archives_before_writing_and_preserves_search(historical, monkeypatch):
    task, root = historical
    task.config.auto_report.enabled = False
    before = _hashes(root / "automl")
    original_config = task.config.model_dump()
    monkeypatch.setattr(app, "get_global_settings", lambda: app.GlobalSettingsModel())
    monkeypatch.setattr(app, "_service_base_urls", lambda *_: ("realize", "search", "report", 30))

    def run_report(**kwargs):
        assert kwargs["task"].config.auto_report.enabled
        assert len(list((root / "stage-history").glob("report-*/report.md"))) == 1
        (kwargs["report_dir"] / "report.md").write_text("New report", encoding="utf-8")
        return True

    monkeypatch.setattr(app, "_run_report_stage", run_report)
    app._rerun_autoreport_thread(task.id, task.model_copy(deep=True))
    assert task.phase == "report_completed", task.last_error
    archive = next((root / "stage-history").glob("report-*/report.md"))
    assert archive.read_text(encoding="utf-8") == "Existing report"
    assert _hashes(root / "automl") == before
    assert task.config.model_dump() == original_config


@pytest.mark.parametrize("root", [r"D:Files\runs", "D:", r"c:folder"])
def test_new_tasks_reject_ambiguous_drive_relative_output(historical, root):
    task, _ = historical
    payload = task.config.model_copy(update={"output_root": root}, deep=True)
    with pytest.raises(HTTPException, match="盘符后的路径分隔符"):
        app.store.create(payload)
    with pytest.raises(HTTPException, match="盘符后的路径分隔符"):
        app.store.update(task.id, payload)


def test_loading_legacy_drive_relative_root_preserves_task_and_config(historical):
    task, _ = historical
    app.store._persist()
    frozen = json.loads(app.TASKS_FILE.read_text(encoding="utf-8"))["tasks"][0]
    loaded = app.TaskStore().get(task.id)
    assert loaded.output_root == task.output_root
    assert loaded.config.output_root == task.config.output_root
    assert loaded.execution_config == frozen["execution_config"]


def test_configured_direct_child_report_remains_valid(historical):
    task, root = historical
    task.output_root = str(root.parent)
    assert app._is_safe_task_output_dir(task, root)
    assert app._validate_autoreport_rerun(task)[0] == root

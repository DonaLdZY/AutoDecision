from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

import app


def test_task_resource_defaults_and_global_resource_removal() -> None:
    task = app.TaskConfigPayload(task_name="resource-task")
    settings = app.GlobalSettingsModel.model_validate(
        {
            "python": {"executable": "python"},
            "resource": {"cpuLimit": 99, "memoryLimitGb": 99},
        }
    )

    assert task.resources.cpu_cores == 4
    assert task.resources.memory_limit_gb == 8.0
    assert task.resources.accelerator_mode == "all"
    assert "resource" not in settings.model_dump()


def test_mlevolve_command_and_yaml_use_task_resources(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    config = app.TaskConfigPayload(
        task_name="resource-task",
        resources=app.TaskResourceConfigPayload(
            cpu_cores=6,
            memory_limit_gb=12.5,
            accelerator_mode="selected",
            accelerator_device_ids=["cuda:0"],
        ),
    )
    task = SimpleNamespace(id="task-1", task_name="resource-task", config=config)
    settings = app.GlobalSettingsModel(
        python={"executable": "python"},
        llm={},
        coreServices={},
        mlevolve={},
    )
    command = app._build_mlevolve_command(
        task,
        settings,
        autorealize_dir=tmp_path / "autorealize",
        automl_logs_root=tmp_path / "logs",
        automl_workspaces_root=tmp_path / "workspace",
    )
    path = app._write_mlevolve_config(task.id, command)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert "cpu_number=6" in command
    assert raw["resources"]["cpu_cores"] == 6
    assert raw["resources"]["memory_limit_gb"] == 12.5
    assert raw["resources"]["accelerator_device_ids"] == ["cuda:0"]


def test_generated_global_settings_no_longer_contains_resource_block(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "config" / "global_settings.yaml"
    monkeypatch.setattr(app, "GLOBAL_SETTINGS_FILE", settings_path)
    monkeypatch.setattr(app, "LEGACY_GLOBAL_SETTINGS_FILE", tmp_path / "legacy-global-settings.json")

    app.ensure_global_settings()

    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert "resource" not in raw


def test_resource_inventory_is_proxied_from_mlevolve(monkeypatch) -> None:
    captured: dict[str, object] = {}
    expected = {
        "cpu": {"logical_count": 8, "physical_count": 4, "available_ids": list(range(8))},
        "memory": {"total_bytes": 16 * 1024**3, "total_gb": 16.0},
        "devices": [{"id": "cuda:0"}],
        "torch": {"version": "test"},
    }

    def fake_get(base_url: str, path: str, timeout_secs: int = 15):
        captured.update(base_url=base_url, path=path, timeout_secs=timeout_secs)
        return expected

    monkeypatch.setattr(app, "_json_get", fake_get)
    monkeypatch.setattr(
        app,
        "get_global_settings",
        lambda: app.GlobalSettingsModel(
            python={"executable": r"C:\envs\task\python.exe"},
            llm={},
            coreServices={},
            mlevolve={},
        ),
    )

    assert app.get_resource_inventory() == expected
    assert str(captured["path"]).startswith("/resources/inventory?")
    assert "C%3A%5Cenvs%5Ctask%5Cpython.exe" in str(captured["path"])


def test_local_automl_snapshot_includes_resource_usage(tmp_path: Path, monkeypatch) -> None:
    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    log_dir.mkdir()
    workspace_dir.mkdir()
    expected = {
        "assigned_cpu_ids": [0, 1],
        "peak_memory_bytes": 123456,
        "resource_violation": None,
    }
    (log_dir / "resource_usage.json").write_text(json.dumps(expected), encoding="utf-8")
    monkeypatch.setattr(app, "_pick_local_automl_log_dir", lambda _task: log_dir)
    monkeypatch.setattr(app, "_pick_local_automl_workspace_dir", lambda _task, exp_name=None: workspace_dir)

    snapshot = app._build_local_automl_snapshot(SimpleNamespace())

    assert snapshot["resource_usage"] == expected

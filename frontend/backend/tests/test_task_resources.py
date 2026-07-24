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
    assert task.output_language == "zh"
    assert task.auto_ml.stepwise_context_max_tokens == 90000
    assert task.auto_ml.stepwise_context_headroom_ratio == 0.15
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
    assert raw["exec"]["auto_install_missing_dependencies"] is True
    assert raw["exec"]["dependency_install_policy"] == "ai_declared"
    assert raw["exec"]["dependency_install_target_path"].endswith(
        "python_packages"
    )
    assert raw["exec"]["dependency_install_central_log_path"].endswith(
        "dependency_installations.jsonl"
    )


def test_automl_effect_and_time_controls_compile_to_task_yaml(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    auto_ml = app.AutoMLConfigPayload(
        steps=77,
        time_limit_secs=14400,
        exec_timeout_secs=900,
        parallel_search_num=6,
        initial_drafts=2,
        fast_first_draft=False,
        stepwise_context_max_tokens=42000,
        stepwise_compaction_keep_recent_steps=3,
        stepwise_compaction_max_tokens=4096,
        stepwise_context_headroom_ratio=0.2,
        search_num_drafts=12,
        search_root_new_draft_probability=0.4,
        search_num_improves=7,
        search_topk_max_improves=14,
        search_debug_prob=0.65,
        search_top_candidates_size=30,
        search_fusion_min_remaining_seconds=480,
        code_temperature=0.2,
        feedback_temperature=0.1,
        code_request_timeout_secs=1500,
        result_review_max_attempts=4,
        result_adjudicator_on_anomaly=False,
        use_optimization_experience_library=False,
        optimization_experience_max_cards=4,
        dependency_install_timeout_secs=420,
        dependency_install_max_packages=5,
    )
    config = app.TaskConfigPayload(
        task_name="effect-controls",
        output_language="zh",
        auto_ml=auto_ml,
    )
    task = SimpleNamespace(id="task-effects", task_name="effect-controls", config=config)
    settings = app.GlobalSettingsModel(
        python={"executable": "python"},
        llm={
            "modelLibrary": [
                {"id": "code", "contextWindowTokens": 65536},
                {"id": "feedback", "contextWindowTokens": 32768},
            ],
            "roleModels": {
                "autoMlCode": "code",
                "autoMlFeedback": "feedback",
            },
        },
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

    assert raw["agent"]["steps"] == 77
    assert raw["agent"]["time_limit"] == 14400
    assert raw["exec"]["timeout"] == 900
    assert raw["agent"]["initial_drafts"] == 2
    assert raw["agent"]["search"]["parallel_search_num"] == 6
    assert "generation_parallel_num" not in raw["agent"]["search"]
    assert "pending_execution_headroom" not in raw["agent"]["search"]
    assert raw["agent"]["draft"]["fast_first_draft"] is False
    assert "decouple_generation_execution" not in raw["agent"]["draft"]
    assert raw["agent"]["draft"]["fast_first_draft_compact_context"] is False
    assert raw["agent"]["draft"]["stepwise_stage_context"] is False
    assert raw["agent"]["output_language"] == "chinese"
    assert raw["agent"]["code"]["context_window_tokens"] == 65536
    assert raw["agent"]["feedback"]["context_window_tokens"] == 32768
    assert raw["agent"]["code"]["minimum_output_tokens"] == 32768
    assert raw["agent"]["code"]["max_tokens"] == 32768
    assert raw["agent"]["feedback"]["minimum_output_tokens"] == 32768
    assert raw["agent"]["feedback"]["max_tokens"] == 32768
    assert raw["agent"]["draft"]["stepwise_context_max_tokens"] == 42000
    assert raw["agent"]["draft"]["stepwise_compaction_keep_recent_steps"] == 3
    assert raw["agent"]["draft"]["stepwise_compaction_max_tokens"] == 4096
    assert raw["agent"]["draft"]["stepwise_context_headroom_ratio"] == 0.2
    assert raw["agent"]["search"]["num_drafts"] == 12
    assert raw["agent"]["search"]["num_improves"] == 7
    assert raw["agent"]["search"]["topk_max_improves"] == 14
    assert raw["agent"]["search"]["debug_prob"] == 0.65
    assert raw["agent"]["search"]["top_candidates_size"] == 30
    assert raw["agent"]["search"]["root_new_draft_probability"] == 0.4
    assert raw["agent"]["search"]["fusion_min_remaining_seconds"] == 480
    assert raw["agent"]["code"]["temp"] == 0.2
    assert raw["agent"]["feedback"]["temp"] == 0.1
    assert raw["agent"]["code"]["request_timeout_seconds"] == 1500
    assert raw["agent"]["retries"]["result_parse_max_attempts"] == 4
    assert raw["agent"]["retries"]["result_adjudicator_on_anomaly"] is False
    assert raw["agent"]["use_optimization_experience_library"] is False
    assert raw["agent"]["optimization_experience_max_cards"] == 4
    assert raw["exec"]["dependency_install_timeout_seconds"] == 420
    assert raw["exec"]["dependency_install_max_packages_per_execution"] == 5


def test_task_language_is_normalized_and_legacy_no_effect_fields_are_dropped() -> None:
    config = app.TaskConfigPayload.model_validate(
        {
            "task_name": "legacy-context-policy",
            "output_language": "zh",
            "auto_ml": {
                "generation_parallel_num": 9,
                "fast_first_draft_compact_context": True,
                "stepwise_stage_context": True,
                "k_fold_validation": 10,
            },
        }
    )

    app.normalize_automl_config_payload(config)

    assert config.output_language == "zh"
    assert "generation_parallel_num" not in config.auto_ml.model_dump()
    assert "fast_first_draft_compact_context" not in config.auto_ml.model_dump()
    assert "stepwise_stage_context" not in config.auto_ml.model_dump()
    assert "k_fold_validation" not in config.auto_ml.model_dump()


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
    dependency_summary = {"installed_requirements": ["ortools>=9.9.0,<10"]}
    (log_dir / "dependency_installations.jsonl").write_text(
        json.dumps({"requirement": "ortools>=9.9.0,<10"}) + "\n",
        encoding="utf-8",
    )
    (log_dir / "dependency_installations_summary.json").write_text(
        json.dumps(dependency_summary),
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "_pick_local_automl_log_dir", lambda _task: log_dir)
    monkeypatch.setattr(app, "_pick_local_automl_workspace_dir", lambda _task, exp_name=None: workspace_dir)

    snapshot = app._build_local_automl_snapshot(SimpleNamespace())

    assert snapshot["resource_usage"] == expected
    assert "ortools" in snapshot["dependency_installations"]
    assert snapshot["dependency_installation_summary"] == dependency_summary

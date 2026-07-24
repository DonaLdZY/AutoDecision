from __future__ import annotations

from types import SimpleNamespace

import yaml

import app


def test_autorealize_runtime_config_is_yaml_and_keeps_frontend_keys_out_of_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    config = app.TaskConfigPayload(
        task_name="task-1",
        output_language="en",
        auto_realize=app.AutoRealizeConfigPayload(
            llm_concurrency=24,
            llm_timeout=240,
            optimize_llm_cost=False,
            llm_file_cognition_mode="documents_only",
            table_profile_sample_rows=5000,
            investigation_max_questions=7,
            investigation_max_rounds_per_question=4,
            investigation_max_scripts_per_question=2,
            investigation_script_timeout_secs=45,
            prompt_token_budget=16000,
            artifact_consistency_enabled=True,
            artifact_consistency_max_rounds=3,
            cross_stage_memory_enabled=True,
            cross_stage_headroom_ratio=0.68,
            cross_stage_retrieval_enabled=False,
        ),
    )
    task = SimpleNamespace(
        id="task-1",
        config=config,
    )
    llm = {
        "modelLibrary": [
            {
                "id": "ar",
                "model": "text-model",
                "baseUrl": "https://text.invalid",
                "apiKey": "text-secret",
                "thinkingMode": "default",
                "reasoningEffort": "default",
                "maxTokens": 0,
            },
            {
                "id": "vision",
                "model": "vision-model",
                "baseUrl": "https://vision.invalid",
                "apiKey": "vision-secret",
            },
        ],
        "roleModels": {
            "autoRealize": "ar",
            "autoRealizeVision": "vision",
            "autoMlCode": "ar",
        },
    }

    path = app._write_autorealize_config(task, SimpleNamespace(llm=llm))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert path.suffix == ".yaml"
    assert raw["llm"]["api_key"] is None
    assert raw["vllm"]["api_key"] is None
    assert raw["llm"]["max_concurrent_requests"] == 24
    assert raw["llm"]["minimum_output_tokens"] == 32768
    assert raw["llm"]["max_tokens"] == 32768
    assert raw["llm"]["structured_max_tokens"] == 32768
    assert raw["llm"]["constraint_memory_max_tokens"] == 32768
    assert raw["parallel"]["cognition_max_workers"] == 24
    assert raw["switches"]["optimize_llm_cost"] is False
    assert raw["data"]["llm_file_cognition_mode"] == "documents_only"
    assert raw["data"]["table_profile_sample_rows"] == 5000
    assert raw["investigation"]["max_questions"] == 7
    assert raw["investigation"]["max_rounds_per_run"] == 4
    assert raw["investigation"]["max_scripts_per_question"] == 2
    assert raw["investigation"]["custom_python_timeout_seconds"] == 45
    assert raw["prompt"]["prompt_token_budget"] == 16000
    assert raw["prompt"]["output_language"] == "en"
    assert raw["prompt"]["control_language"] == "en"
    assert raw["prompt"]["artifact_consistency_max_rounds"] == 3
    assert raw["context"]["cross_stage_headroom_ratio"] == 0.68
    assert raw["context"]["cross_stage_retrieval_enabled"] is False


def test_mlevolve_runtime_yaml_and_cli_exclude_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    command = [
        "python",
        "run.py",
        "data_dir=D:/task/input",
        'agent.code.model="demo-code"',
        'agent.code.api_key="code-key"',
        'agent.feedback.api_key="fb-key"',
        'agent.memory_embedding_api_key="vec-key"',
        "agent.steps=12",
        "runtime.resume_budget_mode=additional",
    ]

    path = app._write_mlevolve_config("task-1", command)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    filtered = app._without_mlevolve_secret_args(command[2:])

    assert raw["agent"]["code"]["api_key"] != "code-key"
    assert raw["agent"]["feedback"]["api_key"] != "fb-key"
    assert raw["agent"]["memory_embedding_api_key"] != "vec-key"
    assert raw["agent"]["steps"] == 12
    assert raw["runtime"]["resume_budget_mode"] == "additional"
    assert not any("api_key=" in item for item in filtered)


def test_role_specific_mlevolve_keys_are_forwarded_by_environment() -> None:
    settings = app.GlobalSettingsModel(
        python={"executable": "python"},
        llm={
            "modelLibrary": [
                {"id": "code", "apiKey": "code-key"},
                {"id": "feedback", "apiKey": "feedback-key"},
                {"id": "embedding", "apiKey": "embedding-key"},
            ],
            "roleModels": {
                "autoMlCode": "code",
                "autoMlFeedback": "feedback",
                "embedding": "embedding",
            },
        },
        coreServices={},
        mlevolve={},
    )

    assert app._mlevolve_secret_env(settings) == {
        "DEEPSEEK_API_KEY": "code-key",
        "MLEVOLVE_CODE_API_KEY": "code-key",
        "MLEVOLVE_FEEDBACK_API_KEY": "feedback-key",
        "MLEVOLVE_EMBEDDING_API_KEY": "embedding-key",
    }

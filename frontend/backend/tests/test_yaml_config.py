from __future__ import annotations

from types import SimpleNamespace

import yaml

import app


def test_autorealize_runtime_config_is_yaml_and_keeps_frontend_keys_out_of_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    auto_realize = SimpleNamespace(
        llm_concurrency=100,
        enable_fewshot=False,
        generate_sample_submission=True,
        llm_timeout=180,
        llm_enable_thinking=None,
        llm_reasoning_effort=None,
        llm_structured_disable_thinking=True,
        no_telemetry=False,
        no_knowledge=False,
        no_llm_cache=False,
        enable_question_investigator=True,
        enable_vllm=True,
    )
    task = SimpleNamespace(
        id="task-1",
        config=SimpleNamespace(auto_realize=auto_realize),
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
    assert raw["llm"]["max_concurrent_requests"] == 100
    assert raw["parallel"]["cognition_max_workers"] == 100


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
    ]

    path = app._write_mlevolve_config("task-1", command)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    filtered = app._without_mlevolve_secret_args(command[2:])

    assert raw["agent"]["code"]["api_key"] != "code-key"
    assert raw["agent"]["feedback"]["api_key"] != "fb-key"
    assert raw["agent"]["memory_embedding_api_key"] != "vec-key"
    assert raw["agent"]["steps"] == 12
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

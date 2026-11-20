from __future__ import annotations

from pathlib import Path
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
    assert raw["vllm"]["enabled"] is True
    assert raw["vllm"]["model_name"] == raw["llm"]["model_name"] == 'text-model'
    assert raw["vllm"]["base_url"] == raw["llm"]["base_url"] == 'https://text.invalid'
    assert raw["vllm"]["fail_silently"] is False
    assert raw["llm"]["max_concurrent_requests"] == 24
    assert raw["llm"]["minimum_output_tokens"] == 0
    assert raw["llm"]["max_tokens"] == 32768
    assert raw["llm"]["structured_max_tokens"] == 32768
    assert raw["llm"]["structured_length_retry_max_tokens"] == 32768
    assert raw["llm"]["structured_length_retry_max_tokens"] == raw["llm"]["structured_max_tokens"]
    assert raw["llm"]["constraint_memory_max_tokens"] == 16384
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


def test_autorealize_structured_budgets_are_bounded_by_application_caps(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    config = app.TaskConfigPayload(task_name="bounded-llm-output")
    task = SimpleNamespace(id="bounded-llm-output", config=config)
    settings = SimpleNamespace(llm={
        "modelLibrary": [{
            "id": "analysis",
            "model": "deepseek-flash",
            "baseUrl": "https://api.deepseek.com",
            "apiKey": "test-secret",
            "maxTokens": 65536,
            "contextWindowTokens": 1000000,
        }],
        "roleModels": {"autoRealize": "analysis", "autoMlCode": "analysis"},
    })

    path = app._write_autorealize_config(task, settings)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert raw["llm"]["max_tokens"] == 65536
    assert raw["llm"]["enable_thinking"] is True
    assert raw["llm"]["structured_disable_thinking"] is False
    assert raw["llm"]["structured_reasoning_fallback_on_length"] is False
    assert raw["llm"]["structured_max_tokens"] == 65536
    assert raw["llm"]["structured_length_retry_max_tokens"] == 65536
    assert raw["llm"]["constraint_memory_max_tokens"] == 16384


def test_deepseek_proxy_preserves_thinking_and_explicit_opt_out():
    model = {"model": "deepseek-v4.1-flash", "baseUrl": "https://proxy.invalid/v1"}
    assert app._model_thinking_cli(model) == "true"
    assert app._model_thinking_cli({**model, "thinkingMode": "enabled"}) == "true"
    assert app._model_thinking_cli({**model, "thinkingMode": "disabled"}) == "false"
    assert app._model_thinking_cli({"model": "other-model", "baseUrl": model["baseUrl"]}) == "null"


def test_image_runtime_uses_analysis_secret_even_with_legacy_vision_override(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'STATE_DIR', tmp_path)
    monkeypatch.setattr(app, 'TASKS_FILE', tmp_path/'tasks.json')
    store = app.TaskStore()
    monkeypatch.setattr(app, 'store', store)
    task = store.create(app.TaskConfigPayload(task_name='image-routing', auto_realize=app.AutoRealizeConfigPayload(enable_vllm=False)))
    settings = app.GlobalSettingsModel(llm={'modelLibrary':[
        {'id':'analysis','model':'multimodal','baseUrl':'https://analysis.invalid','apiKey':'analysis-secret'},
        {'id':'vision','model':'old-vision','baseUrl':'https://vision.invalid','apiKey':'obsolete-secret'}],
        'roleModels':{'autoRealize':'analysis','autoMlCode':'analysis','autoRealizeVision':'vision'}})
    calls = []
    def capture(base, path, payload, **kwargs):
        calls.append(payload)
        return {}  # Stop before any remote polling or execution.
    monkeypatch.setattr(app, '_json_post', capture)
    app._run_autorealize_stage(task_id=task.id, task=task, gs=settings, input_root=tmp_path, run_dir=tmp_path/'run', ar_base='http://local.invalid', req_timeout=1)
    overrides = calls[0]['env_overrides']
    assert overrides['DEEPSEEK_API_KEY'] == 'analysis-secret'
    assert overrides['AUTOREALIZE_VISION_API_KEY'] == 'analysis-secret'
    assert Path(overrides['AUTOREALIZE_SHARED_CACHE_DIR']).is_relative_to(tmp_path)
    raw = yaml.safe_load((tmp_path/f'{task.id}.autorealize.config.yaml').read_text(encoding='utf8'))
    assert raw['vllm']['enabled'] is True  # Retained task flag no longer disables unified image input.
    assert raw['vllm']['model_name'] == raw['llm']['model_name'] == 'multimodal'
    assert 'secret' not in (tmp_path/f'{task.id}.autorealize.config.yaml').read_text(encoding='utf8')


def test_autorealize_stage_forwards_explicit_evaluation_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'STATE_DIR', tmp_path)
    config = app.TaskConfigPayload(
        task_name='evaluation-contract-forwarding',
        input_root=str(tmp_path / 'input'),
        output_root=str(tmp_path / 'runs'),
        auto_realize=app.AutoRealizeConfigPayload(task_hint='Classify equipment failures.'),
        auto_ml=app.AutoMLConfigPayload(
            goal='Predict equipment failure probability.',
            eval='Primary metric: average precision. Use random_state=20260907.',
        ),
    )
    task = app.TaskModel(
        id='evaluation-contract-forwarding',
        task_name=config.task_name,
        input_root=config.input_root,
        output_root=config.output_root,
        created_at=1,
        updated_at=1,
        status='idle',
        phase='idle',
        config=config,
    )
    store = SimpleNamespace(
        set_status=lambda *_args, **_kwargs: None,
        attach_handle=lambda *_args, **_kwargs: None,
        pop_handle=lambda *_args, **_kwargs: None,
        get=lambda *_args: task,
    )
    captured = {}
    monkeypatch.setattr(app, 'store', store)
    monkeypatch.setattr(app, '_json_post', lambda _base, _path, payload, **_kwargs: captured.update(payload) or {'job_id': 'job-1'})
    monkeypatch.setattr(app, '_poll_remote_job', lambda *_args, **_kwargs: {'status': 'completed'})

    assert app._run_autorealize_stage(
        task_id=task.id,
        task=task,
        gs=SimpleNamespace(llm={}, python={'executable': 'python'}),
        input_root=Path(config.input_root),
        run_dir=Path(config.output_root) / task.task_name,
        ar_base='http://autorealize.invalid',
        req_timeout=1,
    ) is True

    assert captured['task_hint'] == 'Classify equipment failures.'
    assert captured['evaluation_contract'] == config.auto_ml.eval


def test_algoevolve_runtime_yaml_and_cli_exclude_keys(tmp_path, monkeypatch) -> None:
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

    path = app._write_algoevolve_config("task-1", command)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    filtered = app._without_algoevolve_secret_args(command[2:])

    assert raw["agent"]["code"]["api_key"] != "code-key"
    assert raw["agent"]["feedback"]["api_key"] != "fb-key"
    assert raw["agent"]["memory_embedding_api_key"] != "vec-key"
    assert raw["agent"]["steps"] == 12
    assert raw["runtime"]["resume_budget_mode"] == "additional"
    assert not any("api_key=" in item for item in filtered)


def test_role_specific_algoevolve_keys_are_forwarded_by_environment(monkeypatch) -> None:
    # Isolate the precedence test from developer-machine credentials that may
    # be present for real DeepSeek Search smoke tests.
    monkeypatch.delenv("ALGOEVOLVE_WEB_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_SEARCH_API_KEY", raising=False)
    monkeypatch.setenv("AUTODECISION_DEEPSEEK_TOOLS_API_KEY", "tools-test-key")
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
        algoevolve={},
    )

    assert app._algoevolve_secret_env(settings) == {
        "DEEPSEEK_API_KEY": "code-key",
        "ALGOEVOLVE_CODE_API_KEY": "code-key",
        "ALGOEVOLVE_FEEDBACK_API_KEY": "feedback-key",
        "ALGOEVOLVE_EMBEDDING_API_KEY": "embedding-key",
        "ALGOEVOLVE_WEB_SEARCH_API_KEY": "tools-test-key",
    }

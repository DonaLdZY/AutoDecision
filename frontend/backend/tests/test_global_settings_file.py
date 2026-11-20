from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

import app


def _use_temp_settings(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    settings_path = tmp_path / "config" / "global_settings.yaml"
    legacy_path = tmp_path / ".state" / "global_settings.json"
    monkeypatch.setattr(app, "GLOBAL_SETTINGS_FILE", settings_path)
    monkeypatch.setattr(app, "LEGACY_GLOBAL_SETTINGS_FILE", legacy_path)
    return settings_path, legacy_path


def test_missing_global_settings_file_is_created(tmp_path: Path, monkeypatch) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)

    settings = app.ensure_global_settings()

    assert settings_path.is_file()
    saved = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert saved["python"]["executable"] == sys.executable
    assert saved["llm"]["roleModels"] == {"autoRealize": "default-deepseek", "autoMlCode": "default-deepseek", "autoMlFeedback": "default-deepseek", "promptOptimizer": "default-deepseek", "embedding": ""}
    assert len(saved["llm"]["modelLibrary"]) == 1
    code_model = saved["llm"]["modelLibrary"][0]
    assert code_model["name"] == "deepseek"
    assert code_model["model"] == "deepseek-flash"
    assert code_model["contextWindowTokens"] == 1_000_000
    assert code_model["maxTokens"] == 32768
    assert settings["coreServices"]["algoEvolveBaseUrl"] == "http://127.0.0.1:18103"


def test_unused_factory_preset_migrates_but_custom_models_and_keys_survive(tmp_path, monkeypatch):
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    old = {"modelLibrary": [], "roleModels": {
        "autoRealize":"default-autorealize", "autoMlCode":"default-code",
        "autoMlFeedback":"default-feedback", "autoRealizeVision":"default-vllm", "embedding":"default-embedding"}}
    for id, name, model, url, tokens, window in [
        ("default-code", "默认编码模型", "deepseek-v4-pro", "https://api.deepseek.com", 32768, 131072),
        ("default-autorealize", "默认 AutoRealize 模型", "deepseek-v4-pro", "https://api.deepseek.com", 32768, 131072),
        ("default-feedback", "默认反馈模型", "deepseek-v4-pro", "https://api.deepseek.com", 32768, 131072),
        ("default-vllm", "默认视觉模型", "glm-4.6v-flashx", "https://open.bigmodel.cn/api/paas/v4/", 0, 0),
        ("default-embedding", "默认向量化模型", "text-embedding-v4", "", 0, 0),
    ]:
        old['modelLibrary'].append(dict(id=id, name=name, model=model, baseUrl=url, apiKey='', maxTokens=tokens, contextWindowTokens=window))
    app.write_yaml(settings_path, {'llm':old}, sensitive=True)
    saved = app.ensure_global_settings()
    assert len(saved['llm']['modelLibrary']) == 1
    assert saved['llm']['modelLibrary'][0]['name'] == 'deepseek'
    assert saved['llm']['vllm']['model'] == 'deepseek-flash'
    old['modelLibrary'][3]['apiKey'] = 'preserve-legacy-provider-secret'
    app.write_yaml(settings_path, {'llm':old}, sensitive=True)
    saved = app.ensure_global_settings()
    assert len(saved['llm']['modelLibrary']) == 5
    assert saved['llm']['modelLibrary'][3]['apiKey'] == 'preserve-legacy-provider-secret'
    assert 'autoRealizeVision' not in saved['llm']['roleModels']
    assert saved['llm']['vllm']['model'] == saved['llm']['autoRealizeModel']['model']
    old['modelLibrary'][3]['apiKey'] = ''
    old['modelLibrary'][0]['name'] = 'My custom provider'
    app.write_yaml(settings_path, {'llm':old}, sensitive=True)
    assert len(app.ensure_global_settings()['llm']['modelLibrary']) == 5



def test_pre_library_credentials_keep_their_text_roles(tmp_path, monkeypatch):
    path, _ = _use_temp_settings(tmp_path, monkeypatch)
    app.write_yaml(path, {'llm': {'autoRealizeModel': {'model':'my-analysis', 'baseUrl':'https://analysis.invalid', 'apiKey':'analysis-key'},
        'codeModel': {'model':'my-code', 'apiKey':'code-key'},
        'vllm': {'model':'old-vision', 'apiKey':'old-key'}}}, sensitive=True)
    llm = app.ensure_global_settings()['llm']
    assert app._selected_model(llm, 'autoRealize')['model'] == 'my-analysis'
    assert app._selected_model(llm, 'autoMlCode')['apiKey'] == 'code-key'
    assert app._selected_model(llm, 'autoRealizeVision')['apiKey'] == 'analysis-key'
    assert any(m['model'] == 'old-vision' and m['apiKey'] == 'old-key' for m in llm['modelLibrary'])


def test_legacy_json_is_migrated_once_with_api_key(tmp_path: Path, monkeypatch) -> None:
    settings_path, legacy_path = _use_temp_settings(tmp_path, monkeypatch)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "llm": {
                    "modelLibrary": [
                        {
                            "id": "model-1",
                            "name": "私有模型",
                            "model": "test-model",
                            "baseUrl": "https://example.invalid",
                            "apiKey": "stored-secret",
                        }
                    ],
                    "roleModels": {
                        "autoRealize": "model-1",
                        "autoRealizeVision": "model-1",
                        "autoMlCode": "model-1",
                        "autoMlFeedback": "model-1",
                        "embedding": "model-1",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    app.ensure_global_settings()

    saved = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert saved["llm"]["modelLibrary"][0]["apiKey"] == "stored-secret"
    assert not legacy_path.exists()


def test_saving_redacted_form_preserves_stored_api_key(tmp_path: Path, monkeypatch) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    settings = app.ensure_global_settings()
    settings["llm"]["modelLibrary"][0]["apiKey"] = "stored-secret"
    app.write_yaml(settings_path, settings, sensitive=True)

    client_payload = app._redact_global_settings_for_client(app.ensure_global_settings())
    app.save_global_settings(app.GlobalSettingsModel.model_validate(client_payload))

    saved = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert saved["llm"]["modelLibrary"][0]["apiKey"] == "stored-secret"


@pytest.mark.parametrize("invalid", ["", "[]", "llm: [unclosed"])
def test_invalid_existing_settings_are_never_overwritten(tmp_path: Path, monkeypatch, invalid) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(invalid, encoding="utf-8")
    with pytest.raises(app.HTTPException) as caught:
        app.ensure_global_settings()
    assert caught.value.status_code == 503
    assert settings_path.read_text(encoding="utf-8") == invalid


def test_transient_read_failure_preserves_settings(tmp_path: Path, monkeypatch) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    app.ensure_global_settings()
    before = settings_path.read_bytes()
    original_read = Path.read_text

    def fail_settings_read(path, *args, **kwargs):
        if path == settings_path:
            raise PermissionError("sharing violation")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_settings_read)
    with pytest.raises(app.HTTPException):
        app.ensure_global_settings()
    assert settings_path.read_bytes() == before


def test_unchanged_settings_reads_do_not_write(tmp_path: Path, monkeypatch) -> None:
    _use_temp_settings(tmp_path, monkeypatch)
    app.ensure_global_settings()
    expected = app.ensure_global_settings()

    def unexpected_write(*args, **kwargs):
        pytest.fail("A settings GET must not rewrite an unchanged file")

    monkeypatch.setattr(app, "write_yaml", unexpected_write)
    assert app.ensure_global_settings() == expected


def test_test_model_override_is_process_only_and_prefers_deepseek(tmp_path: Path, monkeypatch) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    app.ensure_global_settings()
    before = settings_path.read_bytes()
    monkeypatch.setenv("AUTODECISION_TEST_LLM_OVERRIDE", "true")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_BASE_URL", "https://www.heilovehei.com/v1")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_MODEL", "deepseek-v4.1-flash")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_API_KEY", "deepseek-test-secret")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_FALLBACK_BASE_URL", "https://www.heilovehei.com/v1")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_FALLBACK_MODEL", "glm-5.3-flash")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_FALLBACK_API_KEY", "glm-test-secret")

    settings = app.get_global_settings()
    selected = settings.llm["modelLibrary"][0]
    redacted = app._redact_global_settings_for_client(settings.model_dump())

    assert selected["model"] == "deepseek-v4.1-flash"
    assert selected["apiKey"] == "deepseek-test-secret"
    assert selected["thinkingMode"] == "enabled"
    assert settings.llm["autoRealizeModel"]["structuredDisableThinking"] is False
    assert settings.llm["roleModels"]["autoRealize"] == "autodecision-test-model"
    assert settings.llm["roleModels"]["autoMlCode"] == "autodecision-test-model"
    assert redacted["llm"]["modelLibrary"][0]["apiKey"] == ""
    assert redacted["llm"]["modelLibrary"][0]["apiKeyConfigured"] is True
    assert settings_path.read_bytes() == before


def test_test_model_override_falls_back_without_persisting_or_saving(tmp_path: Path, monkeypatch) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    app.ensure_global_settings()
    before = settings_path.read_bytes()
    monkeypatch.setenv("AUTODECISION_TEST_LLM_OVERRIDE", "true")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_BASE_URL", "https://www.heilovehei.com/v1")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_MODEL", "deepseek-v4.1-flash")
    monkeypatch.delenv("AUTODECISION_TEST_LLM_API_KEY", raising=False)
    monkeypatch.setenv("AUTODECISION_TEST_LLM_FALLBACK_BASE_URL", "https://www.heilovehei.com/v1")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_FALLBACK_MODEL", "glm-5.3-flash")
    monkeypatch.setenv("AUTODECISION_TEST_LLM_FALLBACK_API_KEY", "glm-test-secret")

    settings = app.get_global_settings()

    assert settings.llm["modelLibrary"][0]["model"] == "glm-5.3-flash"
    assert settings.llm["modelLibrary"][0]["thinkingMode"] == "enabled"
    assert app._model_thinking_cli(settings.llm["modelLibrary"][0]) == "true"
    with pytest.raises(app.HTTPException) as caught:
        app.save_global_settings(settings)
    assert caught.value.status_code == 409
    assert settings_path.read_bytes() == before


def test_concurrent_reads_and_redacted_saves_preserve_provider(tmp_path: Path, monkeypatch) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    settings = app.ensure_global_settings()
    settings["llm"]["modelLibrary"][0].update(apiKey="private-key", model="chosen-model")
    app.write_yaml(settings_path, settings, sensitive=True)
    payload = app.GlobalSettingsModel.model_validate(app._redact_global_settings_for_client(app.ensure_global_settings()))

    def read_or_save(index):
        if index % 3 == 0:
            app.save_global_settings(payload)
        return app.ensure_global_settings()["llm"]["modelLibrary"][0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(read_or_save, range(40)))
    assert all(row["apiKey"] == "private-key" and row["model"] == "chosen-model" for row in rows)
    assert not list(settings_path.parent.glob("*.tmp"))


def test_prompt_optimizer_role_can_be_assigned_independently(tmp_path: Path, monkeypatch) -> None:
    settings_path, _ = _use_temp_settings(tmp_path, monkeypatch)
    original = app.ensure_global_settings()
    model = dict(original['llm']['modelLibrary'][0], id='optimizer', name='Optimizer', model='custom-optimizer')
    original['llm']['modelLibrary'].append(model)
    original['llm']['roleModels']['promptOptimizer'] = 'optimizer'
    app.save_global_settings(app.GlobalSettingsModel.model_validate(original))
    loaded = app.ensure_global_settings()['llm']
    assert loaded['roleModels']['autoRealize'] == 'default-deepseek'
    assert loaded['roleModels']['promptOptimizer'] == 'optimizer'
    assert app._selected_model(loaded, 'promptOptimizer')['model'] == 'custom-optimizer'
    assert yaml.safe_load(settings_path.read_text(encoding='utf-8'))['llm']['roleModels']['promptOptimizer'] == 'optimizer'

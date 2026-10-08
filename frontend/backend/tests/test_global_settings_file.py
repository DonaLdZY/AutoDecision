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
    assert saved["llm"]["roleModels"]["autoMlCode"] == "default-code"
    code_model = next(item for item in saved["llm"]["modelLibrary"] if item["id"] == "default-code")
    assert code_model["contextWindowTokens"] == 131072
    assert code_model["maxTokens"] == 32768
    assert settings["coreServices"]["algoEvolveBaseUrl"] == "http://127.0.0.1:18103"


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

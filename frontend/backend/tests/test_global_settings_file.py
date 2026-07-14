from __future__ import annotations

import json
import sys
from pathlib import Path

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
    assert settings["coreServices"]["mlevolveBaseUrl"] == "http://127.0.0.1:18103"


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

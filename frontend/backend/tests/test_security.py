from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

import app


def test_global_settings_response_redacts_all_provider_keys() -> None:
    settings = {
        "llm": {
            "modelLibrary": [
                {"id": "configured", "apiKey": "secret-value"},
                {"id": "empty", "apiKey": ""},
            ],
            "codeModel": {"apiKey": "legacy-secret"},
            "vllm": {"apiKey": "vision-secret"},
        },
        "algoevolve": {"embeddingApiKey": "embedding-secret"},
    }

    redacted = app._redact_global_settings_for_client(settings)

    assert redacted["llm"]["modelLibrary"][0]["apiKey"] == ""
    assert redacted["llm"]["modelLibrary"][0]["apiKeyConfigured"] is True
    assert redacted["llm"]["modelLibrary"][1]["apiKeyConfigured"] is False
    assert redacted["llm"]["codeModel"]["apiKey"] == ""
    assert redacted["llm"]["vllm"]["apiKey"] == ""
    assert redacted["algoevolve"]["embeddingApiKey"] == ""
    assert redacted["algoevolve"]["embeddingApiKeyConfigured"] is True
    assert settings["llm"]["modelLibrary"][0]["apiKey"] == "secret-value"


def test_settings_round_trip_keeps_keys_on_disk(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "global_settings.yaml"
    monkeypatch.setattr(app, "GLOBAL_SETTINGS_FILE", settings_path)
    monkeypatch.setattr(app, "LEGACY_GLOBAL_SETTINGS_FILE", tmp_path / "legacy.json")
    monkeypatch.delenv("AUTODECISION_API_TOKEN", raising=False)
    monkeypatch.delenv("AUTODECISION_TEST_LLM_OVERRIDE", raising=False)
    settings = {
        "llm": {
            "modelLibrary": [{"id": "test-model", "model": "test-model", "api_key": "test-model-canary"}],
            "providerOptions": {
                "api_key": "nested-api-secret",
                "access_token": "nested-token-secret",
                "headers": {"Authorization": "Bearer nested-header-secret"},
            },
        },
    }
    app.write_yaml(settings_path, settings, sensitive=True)

    client = TestClient(app.app)
    response = client.get("/api/settings/global")
    assert response.status_code == 200
    for secret in ("test-model-canary", "nested-api-secret", "nested-token-secret", "nested-header-secret"):
        assert secret not in response.text
    payload = response.json()
    visible = payload["llm"]["modelLibrary"][0]
    assert visible["apiKey"] == ""
    assert visible["apiKeyConfigured"] is True
    assert payload["llm"]["providerOptions"] == {"headers": {}}

    visible["model"] = "updated-model"
    assert client.put("/api/settings/global", json=payload).status_code == 200
    saved = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    model = saved["llm"]["modelLibrary"][0]
    assert model["model"] == "updated-model"
    assert model["apiKey"] == "test-model-canary"
    assert saved["llm"]["providerOptions"] == settings["llm"]["providerOptions"]

    visible["apiKey"] = "replacement-model-canary"
    assert client.put("/api/settings/global", json=payload).status_code == 200
    assert "replacement-model-canary" not in client.get("/api/settings/global").text
    saved = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert saved["llm"]["modelLibrary"][0]["apiKey"] == "replacement-model-canary"


def test_public_example_cannot_be_used_as_settings_file(tmp_path, monkeypatch) -> None:
    example_path = app.APP_ROOT / "frontend/config/global_settings.example.yaml"
    example = yaml.safe_load(example_path.read_text(encoding="utf-8"))
    assert all(model["apiKey"] == "" for model in example["llm"]["modelLibrary"])
    assert example["algoevolve"]["embeddingApiKey"] == ""

    monkeypatch.setattr(app, "GLOBAL_SETTINGS_FILE", tmp_path / example_path.name)
    monkeypatch.delenv("AUTODECISION_API_TOKEN", raising=False)
    monkeypatch.delenv("AUTODECISION_TEST_LLM_OVERRIDE", raising=False)
    response = TestClient(app.app).put("/api/settings/global", json=example)
    assert response.status_code == 503
    assert not app.GLOBAL_SETTINGS_FILE.exists()


def test_validation_errors_do_not_echo_submitted_api_keys(monkeypatch) -> None:
    monkeypatch.delenv("AUTODECISION_API_TOKEN", raising=False)
    canary = "validation-secret-canary-92731"
    response = TestClient(app.app).put(
        "/api/settings/global",
        json={"llm": [{"apiKey": canary}]},
    )

    assert response.status_code == 422
    assert canary not in response.text


def test_empty_client_key_preserves_existing_model_key() -> None:
    existing = {
        "llm": {
            "modelLibrary": [{"id": "model-1", "apiKey": "stored-secret"}],
        }
    }
    incoming = {
        "llm": {
            "modelLibrary": [{"id": "model-1", "apiKey": "", "apiKeyConfigured": True}],
        }
    }
    merged = app._deep_merge_settings(existing, incoming)

    app._preserve_sensitive_settings(merged, existing, incoming)

    assert merged["llm"]["modelLibrary"][0]["apiKey"] == "stored-secret"


def test_cors_defaults_to_local_frontend(monkeypatch) -> None:
    monkeypatch.delenv("AUTODECISION_ALLOWED_ORIGINS", raising=False)
    assert app._allowed_origins_from_env() == [
        "http://127.0.0.1:5178",
        "http://localhost:5178",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]

    monkeypatch.setenv("AUTODECISION_ALLOWED_ORIGINS", "https://one.example, https://two.example")
    assert app._allowed_origins_from_env() == ["https://one.example", "https://two.example"]


def test_optional_gateway_token_protects_api_except_health(monkeypatch) -> None:
    monkeypatch.setenv("AUTODECISION_API_TOKEN", "test-gateway-token")
    with TestClient(app.app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/settings/global").status_code == 401
        response = client.get(
            "/api/settings/global",
            headers={"Authorization": "Bearer test-gateway-token"},
        )

    assert response.status_code == 200

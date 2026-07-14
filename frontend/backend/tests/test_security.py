from __future__ import annotations

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
        "mlevolve": {"embeddingApiKey": "embedding-secret"},
    }

    redacted = app._redact_global_settings_for_client(settings)

    assert redacted["llm"]["modelLibrary"][0]["apiKey"] == ""
    assert redacted["llm"]["modelLibrary"][0]["apiKeyConfigured"] is True
    assert redacted["llm"]["modelLibrary"][1]["apiKeyConfigured"] is False
    assert redacted["llm"]["codeModel"]["apiKey"] == ""
    assert redacted["llm"]["vllm"]["apiKey"] == ""
    assert redacted["mlevolve"]["embeddingApiKey"] == ""
    assert redacted["mlevolve"]["embeddingApiKeyConfigured"] is True
    assert settings["llm"]["modelLibrary"][0]["apiKey"] == "secret-value"


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

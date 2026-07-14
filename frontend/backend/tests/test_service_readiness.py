from __future__ import annotations

import os
import urllib.error

import pytest

import app


class _HealthResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return b'{"status":"ok"}'


def test_wait_for_service_ready_recovers_from_transient_refusal(monkeypatch) -> None:
    attempts = 0

    def fake_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.URLError("connection refused")
        return _HealthResponse()

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(app.time, "sleep", lambda _: None)

    app._wait_for_service_ready(
        "http://127.0.0.1:18103",
        "AutoML",
        timeout_secs=1,
        poll_secs=0,
    )

    assert attempts == 2


def test_wait_for_service_ready_returns_actionable_error(monkeypatch) -> None:
    monkeypatch.setattr(
        app.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(urllib.error.URLError("connection refused")),
    )

    with pytest.raises(RuntimeError) as exc_info:
        app._wait_for_service_ready(
            "http://127.0.0.1:18103",
            "AutoML",
            timeout_secs=0.1,
            poll_secs=0,
        )

    message = str(exc_info.value)
    assert "http://127.0.0.1:18103/health" in message
    assert ("dev-restart.ps1" if os.name == "nt" else "dev-restart.sh") in message

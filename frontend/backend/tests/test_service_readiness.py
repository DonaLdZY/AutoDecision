from __future__ import annotations

import os
import urllib.error
from types import SimpleNamespace

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


def test_remote_job_poll_survives_more_than_five_connection_outages(monkeypatch) -> None:
    responses: list[object] = [
        RuntimeError("GET failed: connection refused") for _ in range(6)
    ] + [
        {"status": "running"},
        {"status": "completed", "exit_code": 0},
    ]
    connection_events: list[tuple[bool, int]] = []

    def fake_get(*_args, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(app, "_json_get", fake_get)
    monkeypatch.setattr(app.time, "sleep", lambda _seconds: None)

    result = app._poll_remote_job(
        "http://127.0.0.1:18103",
        "job-id",
        on_connection_state=lambda connected, attempt, _error: connection_events.append(
            (connected, attempt)
        ),
    )

    assert result["status"] == "completed"
    assert (False, 1) in connection_events
    assert (False, 5) in connection_events
    assert (True, 6) in connection_events


def test_remote_job_poll_stops_on_nonrecoverable_http_error(monkeypatch) -> None:
    monkeypatch.setattr(
        app,
        "_json_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 404 job not found")),
    )

    with pytest.raises(RuntimeError, match="HTTP 404"):
        app._poll_remote_job("http://127.0.0.1:18103", "missing-job")


def test_legacy_poll_failure_recovers_job_id_from_error_text() -> None:
    task = SimpleNamespace(
        auto_ml_service_job_id=None,
        last_error=(
            "AutoML service poll failed: GET "
            "http://127.0.0.1:18103/jobs/6f1fd0d9245c4fb9b519fdf4a1c185c3 failed"
        ),
    )

    assert app._persisted_automl_job_id(task) == "6f1fd0d9245c4fb9b519fdf4a1c185c3"


@pytest.mark.parametrize("terminal_state", ["interrupted_resumable", "interrupted_incomplete"])
def test_remote_job_poll_returns_interruption_terminal_states(monkeypatch, terminal_state: str) -> None:
    responses = [
        {"status": "running"},
        {"status": terminal_state, "checkpoint_ready": terminal_state.endswith("resumable")},
    ]
    monkeypatch.setattr(app, "_json_get", lambda *_args, **_kwargs: responses.pop(0))
    monkeypatch.setattr(app.time, "sleep", lambda _seconds: None)

    result = app._poll_remote_job("http://127.0.0.1:18103", "job-id")

    assert result["status"] == terminal_state

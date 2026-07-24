from __future__ import annotations

import app


def test_native_automl_crash_prefers_service_diagnosis_over_last_stderr_line() -> None:
    status = {
        "exit_code": 3221225725,
        "last_error": (
            "MLEvolve native crash: Windows STATUS_STACK_OVERFLOW (0xC00000FD). "
            "Peak task memory=8.03 GiB, configured limit=8.00 GiB."
        ),
        "stderr_tail": "[GlobalMemory] Failed to save node abc: Connection error.",
    }

    hint = app._automl_failure_hint(status)

    assert "STATUS_STACK_OVERFLOW" in hint
    assert "GlobalMemory" not in hint


def test_regular_automl_failure_keeps_last_stderr_line() -> None:
    status = {
        "exit_code": 1,
        "last_error": "service fallback",
        "stderr_tail": "first line\nactual python error",
    }

    assert app._automl_failure_hint(status) == "actual python error"

from types import SimpleNamespace
import json
from pathlib import Path

import pytest

import app
import snapshot_reads


def test_completed_autorealize_snapshot_uses_local_artifacts(monkeypatch, tmp_path):
    expected = {"description_text": "Completed local result"}
    monkeypatch.setattr(app, "_build_local_autorealize_snapshot", lambda _task: expected)
    monkeypatch.setattr(app, "get_global_settings", lambda: pytest.fail("completed snapshot should not call Core"))

    result = app._read_autorealize_snapshot(
        SimpleNamespace(status="completed", run_dir=str(tmp_path))
    )

    assert result is expected


def test_running_autorealize_snapshot_uses_one_bounded_request_then_local_fallback(
    monkeypatch, tmp_path
):
    expected = {"description_text": "Current local result"}
    calls = []
    monkeypatch.setattr(
        app,
        "_service_base_urls",
        lambda _settings: ("http://autorealize", "http://algoevolve", "http://report", 10),
    )
    monkeypatch.setattr(app, "get_global_settings", lambda: object())
    monkeypatch.setattr(app, "_build_local_autorealize_snapshot", lambda _task: expected)

    def fail_remote(base_url, path, payload, timeout_secs=15, *, max_attempts=5):
        calls.append((base_url, path, payload, timeout_secs, max_attempts))
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(app, "_json_post", fail_remote)
    task = SimpleNamespace(status="running", run_dir=str(tmp_path))

    assert app._read_autorealize_snapshot(task) is expected
    assert calls == [
        (
            "http://autorealize",
            "/snapshot",
            {"run_dir": str(tmp_path)},
            3,
            1,
        )
    ]


def test_completed_report_snapshot_uses_local_artifacts(monkeypatch, tmp_path):
    expected = {"report_markdown": "Completed report"}
    monkeypatch.setattr(app, "_build_local_report_snapshot", lambda _task: expected)
    monkeypatch.setattr(app, "get_global_settings", lambda: pytest.fail("completed snapshot should not call Core"))
    task = SimpleNamespace(
        status="completed",
        report_dir=str(tmp_path / "report"),
        run_dir=str(tmp_path),
    )

    assert app._read_report_snapshot(task) is expected


def test_json_post_can_disable_retry_backoff(monkeypatch):
    calls = []
    sleeps = []

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise OSError("connection refused")

    monkeypatch.setattr(app.urllib.request, "urlopen", fail)
    monkeypatch.setattr(app.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="POST http://service/snapshot failed"):
        app._json_post(
            "http://service",
            "/snapshot",
            {},
            timeout_secs=3,
            max_attempts=1,
        )

    assert len(calls) == 1
    assert sleeps == []


def test_summary_skips_hidden_reports_rpc_logs_and_readiness(monkeypatch, tmp_path):
    ar = tmp_path / "autorealize"
    report = ar / "realize_report"
    report.mkdir(parents=True)
    (ar / "description.md").write_text("# Human task", encoding="utf-8")
    (report / "data_description.md").write_text("Human data", encoding="utf-8")
    (report / "data_cognition_report.json").write_text("must not be read", encoding="utf-8")
    (report / "current_state.json").write_text('{"phase":"ready"}', encoding="utf-8")
    (report / "evaluation_contract_report.json").write_text(json.dumps({
        "final": {"primary_metric": "ln_rmse", "metric_direction": "minimize",
                  "metric_formula": "sqrt(mean(log error squared))", "evidence": ["internal records"]},
        "revision_log": ["internal history"],
    }), encoding="utf-8")
    log = tmp_path / "logs"
    log.mkdir()
    (log / "journal.json").write_text(json.dumps({
        "nodes": [{
            "id": "one", "stage": "draft", "code": "large private source",
            "_term_out": ["large private execution output"],
            "evaluation_protocol": {"raw": "developer-only"},
            "metric": {"value": .12, "maximize": False},
            "search_eligible": True, "is_buggy": False, "is_valid": True,
            "plan": "Train a model",
        }],
    }), encoding="utf-8")
    task = SimpleNamespace(model_dump=lambda: {"id": "test"})
    monkeypatch.setattr(app, "_candidate_task_run_dirs", lambda _task: [tmp_path])
    monkeypatch.setattr(app, "_pick_local_automl_log_dir", lambda _task: log)
    monkeypatch.setattr(app, "_pick_local_automl_workspace_dir", lambda *a, **k: None)
    monkeypatch.setattr(app, "_pick_local_report_dir", lambda _task: None)
    monkeypatch.setattr(app, "_automl_engine", lambda _task: "algoevolve")
    monkeypatch.setattr(app, "_automl_input_readiness", lambda _task: pytest.fail("not a summary read"))
    monkeypatch.setattr(app, "_json_post", lambda *a, **kw: pytest.fail("summary must not call Core"))
    monkeypatch.setattr(app, "safe_read_text_tail", lambda *a, **kw: pytest.fail("summary must not read logs"))
    original = app.safe_read_json

    def guarded(path, default):
        assert Path(path).name not in {"data_cognition_report.json", "automl_context_pack.json"}
        return original(path, default)

    monkeypatch.setattr(app, "safe_read_json", guarded)
    overview = app._task_summary_snapshot(task)["auto_realize"]
    assert overview == {"evaluation": {"primary_metric": "ln_rmse", "metric_direction": "minimize",
                                      "metric_formula": "sqrt(mean(log error squared))"}}
    result = app._task_summary_snapshot(task, section="data")
    assert result["snapshot_errors"] == {}
    assert result["auto_realize"]["description_text"] == "# Human task"
    assert result["auto_ml"]["nodes"][0]["metric"] == .12
    assert result["auto_ml"]["best_node_id"] == "one"
    encoded = json.dumps(result)
    assert "large private" not in encoded and "developer-only" not in encoded


def test_snapshot_cache_reads_same_revision_once_and_invalidates(monkeypatch, tmp_path):
    path = tmp_path / "journal.json"
    path.write_text('{"count":1}', encoding="utf-8")
    original = Path.read_text
    reads = []

    def read(self, *args, **kwargs):
        reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert snapshot_reads.json_artifact(path)["count"] == 1
    assert snapshot_reads.json_artifact(path)["count"] == 1
    assert len(reads) == 1
    path.write_text('{"count":22}', encoding="utf-8")
    assert snapshot_reads.json_artifact(path)["count"] == 22
    assert len(reads) == 2
    path.write_text('{"count":', encoding="utf-8")
    assert snapshot_reads.json_artifact(path, {}) == {}
    path.write_text('{"count":333}', encoding="utf-8")
    assert snapshot_reads.json_artifact(path)["count"] == 333

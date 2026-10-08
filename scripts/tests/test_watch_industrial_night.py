import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location("night_watch", Path(__file__).parents[1] / "watch-industrial-night.py")
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


def test_missing_cache_telemetry_is_unknown_not_zero_hit_rate():
    result = watch.usage_summary([{"prompt_tokens": 1000, "provider_cache_tokens_known": False}])
    assert result["known_cache_hit_ratio"] is None
    assert result["cache_telemetry_coverage"] == 0
    result = watch.usage_summary([{"prompt_tokens": 1000, "provider_cache_tokens_known": True, "prompt_cache_hit_tokens": 700}])
    assert result["known_cache_hit_ratio"] == .7


def test_active_stage_usage_excludes_previous_stage_requests(tmp_path):
    task = {"run_dir": str(tmp_path), "auto_ml_log_dir": str(tmp_path / "search"), "phase": "automl"}
    assert watch.active_usage_paths(task, {}) == [tmp_path / "search/llm_usage.jsonl"]
    task["phase"] = "autorealize"
    assert watch.active_usage_paths(task, {}) == [tmp_path / "autorealize/realize_report/llm_usage.jsonl"]
    candidate = tmp_path / "candidate"
    assert watch.active_usage_paths(task, {"candidate": str(candidate)}) == [candidate / "realize_report/llm_usage.jsonl"]
    session = candidate / "realize_report/repair_usage/one"
    session.mkdir(parents=True)
    (session / "llm_usage.jsonl").touch()
    assert watch.active_usage_paths(task, {"candidate": str(candidate)}) == [session / "llm_usage.jsonl"]


def test_failure_streak_counts_only_consecutive_failed_provider_outputs():
    result = watch.usage_summary([{"parsed_ok": False}, {"parsed_ok": True}, {"parsed_ok": False},
                                 {"finish_reason": "length"}, {"source": "local_cache"}])
    assert result["consecutive_failed_outputs"] == 2


def test_zero_input_for_nonempty_request_is_flagged_without_rewriting_usage():
    result = watch.usage_summary([
        {"prompt_tokens": 1000, "provider_cache_tokens_known": True, "prompt_cache_hit_tokens": 700},
        {"prompt_tokens": 0, "estimated_prompt_tokens": 66601, "provider_cache_tokens_known": True,
         "prompt_cache_hit_tokens": 10, "finish_reason": "provider_interrupted"},
    ])
    assert result["input_tokens"] == 1000
    assert result["input_usage_missing_calls"] == 1
    assert result["missing_input_tokens_estimate"] == 66601
    assert result["max_missing_input_tokens_estimate"] == 66601
    assert result["known_cache_hit_ratio"] == .7
    assert result["consecutive_failed_outputs"] == 1
    assert result["cache_telemetry_coverage"] is None
    assert result["known_input_cache_telemetry_coverage"] == 1


def test_tail_does_not_load_large_logs_and_tolerates_partial_json(tmp_path):
    path = tmp_path / "usage.jsonl"
    row = json.dumps({"prompt_tokens": 10, "filler": "x" * 500}) + "\n"
    path.write_text(row * 2000, encoding="utf-8")
    assert len(watch.tail_rows(path)) == 30
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"partial":')
    assert watch.tail_rows(path) == []


def test_caught_oom_artifact_is_detected_but_other_cuda_errors_are_not_oom(tmp_path):
    work = tmp_path / "node_runs/candidate/working"
    work.mkdir(parents=True)
    task = {"auto_ml_workspace_dir": str(tmp_path)}
    node = {"id": "candidate", "_term_out": "Failed to produce score"}
    failure = work / "run_failure.json"
    failure.write_text(json.dumps({"error": "CUDA out of memory"}), encoding="utf-8")
    assert watch.node_memory_failure(task, node)
    failure.write_text(json.dumps({"error": "CUBLAS_STATUS_EXECUTION_FAILED"}), encoding="utf-8")
    assert not watch.node_memory_failure(task, node)
    assert not watch.node_memory_failure(task, {"id": "another"})


def test_pressure_reduces_both_limits_and_recovery_does_not_expand_them(tmp_path, monkeypatch):
    monkeypatch.setattr(watch.batch, "OUT", tmp_path)
    monkeypatch.setattr(watch.batch, "load_state", lambda: {"tasks": {}})
    monkeypatch.setattr(watch.batch, "request", lambda path: [] if path == "/api/tasks" else {})
    monkeypatch.setattr(watch.stages, "validate_provider", lambda settings: None)
    monkeypatch.setattr(watch, "SLUGS", ())
    gpu = SimpleNamespace(returncode=0, stdout="1000, 15000, 50")
    monkeypatch.setattr(watch.subprocess, "run", lambda *a, **k: gpu)
    monkeypatch.setattr(watch.psutil, "virtual_memory", lambda: SimpleNamespace(available=16 * 1024**3))
    monkeypatch.setattr(watch, "host_commit_available_bytes", lambda: 8 * 1024**3)
    first = watch.snapshot()
    assert "gpu_memory_pressure" in first["alerts"]
    assert first["candidate_execution_limit"] == 1
    assert first["task_admission_limit"] == 2
    gpu.stdout = "14000, 2000, 10"
    recovered = watch.snapshot()
    assert "gpu_memory_pressure" not in recovered["alerts"]
    assert recovered["candidate_execution_limit"] == 1
    assert recovered["task_admission_limit"] == 2
    monkeypatch.setattr(watch, "host_commit_available_bytes", lambda: 2 * 1024**3)
    commit_pressure = watch.snapshot()
    assert "host_commit_memory_pressure" in commit_pressure["alerts"]
    assert commit_pressure["host_free_gib"] == 16
    assert commit_pressure["host_commit_free_gib"] == 2


def test_windows_paging_failure_is_memory_pressure():
    assert watch.node_memory_failure({}, {"_term_out": "OSError: [WinError 1455]"})
    assert watch.node_memory_failure({}, {"_term_out": "The paging file is too small"})


def test_report_transport_cache_fields_and_source_audits_are_counted(tmp_path):
    row = {"prompt_tokens": 1000, "cache_tokens_known": True,
           "prompt_tokens_details": {"cached_tokens": 800}, "requested_model": "requested",
           "response_model": "reported", "finish_reason": "max_output_tokens"}
    result = watch.usage_summary([row])
    assert result["known_cache_hit_ratio"] == .8
    assert result["cache_telemetry_coverage"] == 1
    assert result["requested_models"] == ["requested"]
    assert result["consecutive_failed_outputs"] == 1
    audit = tmp_path / "report/source-audit-1-0"
    audit.mkdir(parents=True)
    (audit / "llm_usage.jsonl").touch()
    assert watch.active_usage_paths({"run_dir": str(tmp_path), "phase": "report"}, {}) == [
        tmp_path / "report/llm_usage.jsonl", audit / "llm_usage.jsonl"]

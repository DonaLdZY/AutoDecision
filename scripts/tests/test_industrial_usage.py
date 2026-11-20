import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("usage_audit", Path(__file__).parents[1] / "audit-industrial-usage.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_incremental_report_usage_is_not_counted_again_in_final_trace(tmp_path):
    row = {"request_id": "one-response", "prompt_tokens": 2000, "completion_tokens": 1200,
           "completion_tokens_details": {"reasoning_tokens": 1000},
           "prompt_tokens_details": {"cached_tokens": 1792}}
    (tmp_path / "llm_usage.jsonl").write_text(json.dumps(row) + "\n")
    (tmp_path / "report_trace.json").write_text(json.dumps({"llm_usage": [row]}))
    (tmp_path / "calls.json").write_text(json.dumps({"usage": [row]}))
    totals = audit.aggregate(tmp_path)["totals"]
    assert totals["provider_calls"] == 1
    assert totals["input_tokens"] == 2000
    assert totals["reasoning_tokens"] == 1000
    assert totals["cache_hit_ratio"] == 1792 / 2000


def test_direct_provider_probes_are_included_with_unknown_cache(tmp_path):
    (tmp_path / "calls.json").write_text(json.dumps([
        {"usage": {"prompt_tokens": 1100, "completion_tokens": 200,
                   "completion_tokens_details": {"reasoning_tokens": 90}}},
        {"usage": {"prompt_tokens": 1100, "completion_tokens": 210}},
    ]))
    totals = audit.aggregate(tmp_path)["totals"]
    assert totals["provider_calls"] == 2
    assert totals["input_tokens"] == 2200
    assert totals["output_tokens"] == 410
    assert totals["reasoning_tokens"] == 90
    assert totals["cache_hit_ratio"] is None


def test_legacy_timestamped_rows_deduplicate_archives_without_merging_distinct_calls(tmp_path):
    rows = [{"ts": timestamp, "prompt_name": "review", "source": "provider",
             "prompt_tokens": 5000, "completion_tokens": 1000, "provider_cache_tokens_known": False}
            for timestamp in (1.25, 2.25)]
    for name in ("task", "repair", "archive"):
        target = tmp_path / name
        target.mkdir()
        (target / "llm_usage.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    totals = audit.aggregate(tmp_path)["totals"]
    assert totals["provider_calls"] == 2
    assert totals["input_tokens"] == 10000
    assert totals["cache_hit_ratio"] is None


def test_identical_untimestamped_probes_are_still_counted_as_separate_calls(tmp_path):
    row = {"usage": {"prompt_tokens": 50, "completion_tokens": 10}}
    (tmp_path / "calls.json").write_text(json.dumps([row, row]))
    assert audit.aggregate(tmp_path)["totals"]["provider_calls"] == 2


def test_normalized_zero_does_not_claim_unknown_reasoning_is_zero(tmp_path):
    row = {"request_id": "r", "stage_id": "draft", "stage_id_source": "explicit",
           "prompt_tokens": 900, "completion_tokens": 100, "reasoning_tokens": 0,
           "provider_cache_tokens_known": False, "raw_usage": {"prompt_tokens": 900, "completion_tokens": 100},
           "seconds": 3.25}
    (tmp_path / "llm_usage.jsonl").write_text(json.dumps(row) + "\n")
    result = audit.aggregate(tmp_path)
    assert result["totals"]["reasoning_tokens_all_calls"] is None
    stage = result["by_stage"][0]
    assert stage["stage_id"] == "draft"
    assert stage["cache_hit_ratio"] is None
    assert stage["seconds"] == 3.25
    assert stage["stage_id_source_counts"] == {"explicit": 1}


def test_live_partial_row_is_reported_without_losing_complete_usage(tmp_path):
    row = {"response_id": "r", "stage_id": "report", "prompt_tokens": 100, "completion_tokens": 20}
    (tmp_path / "llm_usage.jsonl").write_text(json.dumps(row) + '\n{"response_id":')
    result = audit.aggregate(tmp_path)
    assert result["totals"]["provider_calls"] == 1
    assert result["reading_issues"][0]["line"] == 2

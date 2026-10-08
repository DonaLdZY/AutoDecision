"""Summarize immutable provider comparisons; never infer missing cache telemetry."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core/AutoRealize"))
from autorealize.llm.client import _schema_text_for_prompt


PAIRS = {
    "actual": ("review-ab-v2/actual-old", "review-ab-v3/actual-new"),
    "conflicts": ("review-ab-v2/conflicts-old", "review-ab-v3/conflicts-new"),
    "evaluation-not-released": ("review-ab-v2/evaluation-old", "review-evaluation-v4/evaluation-new"),
    "finalizer": ("review-finalizer-v4/finalizer-old", "review-finalizer-v4/finalizer-new"),
    "controlled-clean": ("review-controlled-v1/controlled-clean-old", "review-ab-v3/controlled-clean-new"),
    "controlled-conflicts": ("review-controlled-v1/controlled-conflicts-old", "review-ab-v3/controlled-conflicts-new"),
    "retention-repeat": ("review-cache-v3/retention-old-repeat2", "review-cache-v3/retention-new-repeat2"),
}
BATCHES = ("review-ab-v2", "review-ab-v3", "review-controlled-v1", "review-cache-v3",
           "review-evaluation-v4", "review-finalizer-v4")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def summarize(base, relative):
    directory = base / relative
    result = read(directory / "result.json")
    usage = result.get("usage", [])
    successful = [item for item in usage if item.get("parsed_ok") and item.get("usage_available")]
    item = successful[-1] if successful else {}
    known = item.get("provider_cache_tokens_known", False)
    inputs = item.get("prompt_tokens")
    cached = item.get("prompt_cache_hit_tokens") if known else None
    output = result.get("output", {})
    return {
        "path": relative,
        "status": result["status"],
        "seconds_including_retries": round(result["seconds"], 3),
        "input_tokens": inputs,
        "output_tokens_including_reasoning": item.get("completion_tokens"),
        "cached_input_tokens": cached,
        "uncached_input_tokens": inputs - cached if inputs is not None and cached is not None else None,
        "cache_hit_percent": round(100 * cached / inputs, 2) if inputs and cached is not None else None,
        "requested_model": item.get("model"),
        "returned_model": item.get("response_model"),
        "max_output_tokens": item.get("max_tokens"),
        "passed": output.get("passed"),
        "issue_count": len(output.get("issues", [])),
        "coverage_dimensions": sorted(output.get("coverage", {})),
        "exact_constraints_preserved": result.get("exact_constraints_preserved"),
        "contract_defects": result.get("contract_defects"),
        "request_sha256": hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
        "result_sha256": hashlib.sha256((directory / "result.json").read_bytes()).hexdigest(),
    }


def release_matches(base, batch, case):
    tested = base / batch / case
    release = base / "review-release-final" / case
    if read(tested / "request.json") != read(release / "request.json"):
        return False
    if (tested / "schema.json").exists():
        return read(tested / "schema.json") == read(release / "schema.json")
    # Earlier calls predate the separate schema file; their actual usage still
    # records the hash of the exact schema string passed to the provider.
    schema_text = _schema_text_for_prompt(read(release / "schema.json"), compact=True)
    digest = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()[:16]
    parts = read(tested / "result.json")["usage"][-1]["prompt_parts"]
    return any(part["name"] == "json_schema" and part["sha256_16"] == digest for part in parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    base = args.root
    all_runs = {
        f"{batch}/{path.parent.name}": summarize(base, f"{batch}/{path.parent.name}")
        for batch in BATCHES for path in sorted((base / batch).glob("*/result.json"))
    }
    hashes = {batch: read(base / batch / "snapshot.json")["source_hashes"] for batch in BATCHES}
    same_sources = all(value == hashes[BATCHES[0]] for value in hashes.values())
    payload_hashes = {
        batch: hashlib.sha256(json.dumps(
            {key: value for key, value in read(base / batch / "snapshot.json").items() if key != "source_hashes"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        for batch in BATCHES
    }
    pairs = {}
    for case, (old, new) in PAIRS.items():
        before, after = all_runs[old], all_runs[new]
        pairs[case] = {
            "old": before, "new": after,
            "input_reduction_percent": round(100 * (1 - after["input_tokens"] / before["input_tokens"]), 2),
        }
    retention = [run for name, run in all_runs.items() if "/retention-" in name]
    final_audits = [all_runs[f"review-ab-v3/{case}-new"] for case in
                    ("actual", "conflicts", "controlled-clean", "controlled-conflicts")]
    release_sources = {
        "actual-new": "review-ab-v3", "conflicts-new": "review-ab-v3",
        "controlled-clean-new": "review-ab-v3", "controlled-conflicts-new": "review-ab-v3",
        "finalizer-new": "review-finalizer-v4",
    }
    release_identity = {
        case: release_matches(base, batch, case)
        for case, batch in release_sources.items()
    }
    gates = {
        "same_source_hashes": same_sources,
        "same_complete_frozen_payload_including_authority": len(set(payload_hashes.values())) == 1,
        "released_requests_and_schemas_match_tested_versions": all(release_identity.values()),
        "ordinary_evaluation_retains_original_request": (
            read(base / "review-release-final/evaluation-old/request.json")
            == read(base / "review-release-final/evaluation-new/request.json")),
        "all_final_comparisons_completed": all(run["status"] == "completed"
                                                for pair in pairs.values() for run in (pair["old"], pair["new"])),
        "all_retention_calls_exact": all(run["exact_constraints_preserved"] is True for run in retention),
        "all_final_audits_have_eight_dimensions": all(len(run["coverage_dimensions"]) == 8 for run in final_audits),
        "clean_case_no_false_positive": pairs["controlled-clean"]["new"]["passed"] is True
                                       and pairs["controlled-clean"]["new"]["issue_count"] == 0,
        "all_evaluation_contracts_pass_deterministic_checks": all(
            pairs[case][variant]["contract_defects"] == []
            for case in ("evaluation-not-released", "finalizer") for variant in ("old", "new")),
        "successful_calls_keep_32768_output_cap": all(run["max_output_tokens"] == 32768
                                                       for run in all_runs.values() if run["status"] == "completed"),
    }
    report = {
        "scope": "Frozen task-definition reviews only; not model training quality or end-to-end cost",
        "source_hashes": hashes[BATCHES[0]],
        "frozen_payload_hashes": payload_hashes,
        "automated_gates": gates,
        "release_request_identity": release_identity,
        "rollout": {
            "artifact_consistency_reviewer": "enabled_after_quality_review",
            "evaluation_contract_finalizer": "enabled_after_quality_review",
            "evaluation_contract_reviewer": "legacy_layout_retained",
            "reason": "Ordinary evaluation v4 still copied incorrect population counts; do not release that variant.",
        },
        "manual_quality_review": "See docs/review-prompt-validation-20260908.md for issue-by-issue adjudication.",
        "pairs": pairs,
        "all_runs": all_runs,
        "limitations": [
            "Encoding-only reviewer was rejected after missing population arithmetic and physical-schema issues.",
            "First optimized evaluation output was rejected for contradictory primary-versus-audit metric wording.",
            "Revised ordinary evaluation still missed population arithmetic; only artifact reviews and finalizers are released.",
            "Small repeated requests demonstrate shared cached tokens, not increased cache capacity or fleet-wide hit rate.",
            "Missing provider cache telemetry stays null; it is not a zero cache hit.",
            "Returned model differs from requested model; no independent verification of provider model routing.",
            "Failed requests without usage are excluded from token totals; recorded totals are not complete billing.",
        ],
    }
    destination = base / "review-comparison-20260908.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination), "automated_gates": gates,
                      "completed": sum(run["status"] == "completed" for run in all_runs.values()),
                      "failed": sum(run["status"] != "completed" for run in all_runs.values())}))
    if not all(gates.values()):
        raise SystemExit("Validation gates failed; inspect the report before rollout")


if __name__ == "__main__":
    main()

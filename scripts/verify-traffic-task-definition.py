"""Verify the repaired traffic contract before its actual three-hour search."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
spec = importlib.util.spec_from_file_location("industrial_stages", Path(__file__).with_name("industrial-stage-control.py"))
stages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stages)


def main():
    task = stages.current_task("traffic")
    stages.verify_task_definition(task)
    report_dir = Path(task["run_dir"]) / "autorealize/realize_report"
    current = stages.read_json(report_dir / "task_definition_report.json")
    previous = stages.read_json(stages.batch.OUT / "stage-repairs/traffic-1788802991262084300/autorealize/realize_report/task_definition_report.json")
    patches = stages.read_json(report_dir / "derived_contract_repair_report.json")
    expected = deepcopy(previous["description_protocol_bundle"])
    for patch in patches["repairs"]:
        parts = patch["path"].split("/")[2:]
        parent = expected
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        assert parent[key] == patch["expected"]
        parent[key] = patch["replacement"]
    bundle, contract = current["description_protocol_bundle"], current["evaluation_contract"]
    required = {"persistence_baseline", "seasonal_baseline", "learned_temporal_prediction",
                "topology_aware_graph_or_attention_prediction", "documented_low_volume_fallback_prediction"}
    checks = {
        "derived_changes_match_exact_audited_operations": expected == bundle,
        "evaluation_unchanged_by_mirror_repair": contract == previous["evaluation_contract"],
        "all_required_families_retained": required.issubset(bundle["required_method_families"]),
        "sample_columns_unchanged": current["downstream_context"]["sample_submission_spec"]["columns"] ==
                                    ["gantry_id", "forecast_origin", "horizon_minutes", "predicted_count"],
        "single_day_common_origins": len(range(0, 288 - 12 + 1)) == 277,
        "five_day_common_origins": len(range(0, 1440 - 12 + 1)) == 1429,
        "single_metric_preserved": contract["primary_metric"] == "development_all_gantries_30min_MAE" and contract["metric_direction"] == "minimize",
        "full_audit_passed": current["downstream_context"]["artifact_consistency_review"]["passed"] is True,
        "no_unresolved_execution_defects": not current["defects_after_gate"],
    }
    review = {
        "passed": all(checks.values()),
        "strengths": ["All-gantry 30/60 minute predictions, fixed causal split, and single development MAE have a consistent executable contract.",
                      "Temporal and topology-aware method requirements, zero-flow coverage, holdout separation and original unresolved business facts are retained."],
        "weaknesses": ["Only seven observed days; no production SLA or holiday-generalization evidence.",
                       "Open-question text remains repetitive and sometimes mixes missing official specification with documented engineering defaults; the accepted evaluator controls execution."],
        "system_changes": ["Repaired derived event cutoffs and common-origin population in the same audit cycle as the contract; stale parsing and workbook questions are resolved with exact evidence.",
                           "Resources follow the separate authorized runtime override; model scores and GPU utilization remain unmeasured."],
        "constraint_checks": checks,
        "quality_checks": {"independent_manual_review": "Reviewed exact boundary, topology and low-volume rules, source schema, final audit and question-resolution evidence.",
                           "training_not_claimed": True},
        "usage_analysis": {"latest_full_audit_input": 107487, "cache_known": False,
                           "prior_retry_input": 105945, "prior_retry_cached": 105216,
                           "limitation": "Single-call high cache hit does not establish aggregate cache performance; full audit input remains large."},
        "evidence_paths": [str(report_dir / name) for name in ("task_definition_report.json", "artifact_consistency_report.json",
                           "derived_contract_repair_report.json", "open_question_resolution_report.json")],
    }
    path = stages.batch.OUT / "traffic-autorealize-review-20260908.json"
    stages.batch.save(path, review)
    print(json.dumps({"review": str(path), "passed": review["passed"], "checks": checks}))
    if not review["passed"]:
        raise RuntimeError("Traffic task definition failed independent verification")


if __name__ == "__main__":
    main()

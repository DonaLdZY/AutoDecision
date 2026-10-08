"""Independently check the accepted deposition repair before model search."""
from copy import deepcopy
from pathlib import Path
import runpy


def main():
    stages = runpy.run_path(str(Path(__file__).with_name("industrial-stage-control.py")))
    task = stages["current_task"]("deposition")
    stages["verify_task_definition"](task)
    read = stages["read_json"]
    batch = stages["batch"]
    repair = read(batch.OUT / "stage-repairs/deposition-1788806115260948700/result.json")
    report = Path(task["run_dir"]) / "autorealize/realize_report"
    old = read(Path(repair["archive"]) / "realize_report/task_definition_report.json")
    new = read(report / "task_definition_report.json")
    expected = deepcopy(old["evaluation_contract"])
    expected["submission_checks"][3] = expected["submission_checks"][3].replace("`Time [s]`", "`time_s`")
    actual = deepcopy(new["evaluation_contract"])
    expected.pop("evidence")
    actual.pop("evidence")
    sample = new["downstream_context"]["sample_submission_spec"]
    bundle = new["description_protocol_bundle"]
    validation = bundle["ml_dl"]["validation_design"]
    guards = new["automl_context_pack"]["source_alias_guard"]
    checks = {
        "evaluator_changed_only_output_finite_check": actual == expected,
        "original_constraints_unchanged": new["downstream_context"]["constraint_memory"] == old["downstream_context"]["constraint_memory"],
        "original_authority_unchanged": new["downstream_context"]["authoritative_memory"] == old["downstream_context"]["authoritative_memory"],
        "ml_features_and_leakage_rules_unchanged": all(bundle["ml_dl"][key] == old["description_protocol_bundle"]["ml_dl"][key] for key in ("feature_boundary", "leakage_guards", "target")),
        "output_columns_retained": sample["columns"] == ["evaluation_row_id", "source_file", "strategy", "zone", "time_s", "y_pred"],
        "derived_output_name_retained": "输出列 `time_s`" in sample["source_fields"]["time_s"],
        "wide_table_tail_not_aliased": not any(row.get("alias") == "Unnamed: 254" and row.get("exact_physical_column") != "Unnamed: 254" for row in guards),
        "chronological_60_20_20_synced": all(text in validation for text in ("0.60", "0.20", "holdout", "development", "ec-v1")),
        "audit_passed": read(report / "artifact_consistency_report.json")["final"]["passed"] is True,
    }
    review = {"passed": all(checks.values()), "constraint_checks": checks,
        "strengths": ["Frozen evaluator, exact output keys and derived validation design now agree", "All original constraints and source authority retained; no model results claimed"],
        "weaknesses": ["Runtime must verify multirow header mapping and count every exclusion before training", "Results concern simulation temperature only, not experimental or unseen-strategy generalization", "Full audit input remains about 130k tokens; provider cache telemetry unavailable"],
        "system_changes": ["Full physical schema used for alias checks", "Derived outputs protected from fuzzy source-column renaming", "Bounded field repair synchronizes validation design with immutable evaluator"],
        "quality_checks": {"independent_review": "Compared previous and current evaluator, constraints, feature boundaries, source mappings and full audit"},
        "usage_analysis": {"repair_input_tokens": [55729,129753,45858,130255], "cache_hit_rate": "unknown", "output_cap": 32768},
        "evidence_paths": [str(report / "task_definition_report.json"), str(report / "artifact_consistency_report.json"), str(report / "derived_contract_repair_report.json"), str(Path(repair["archive"]) / "realize_report/task_definition_report.json")]}
    path = batch.OUT / "deposition-autorealize-review-20260908.json"
    batch.save(path, review)
    print({"passed": review["passed"], "checks": checks, "review": str(path)})
    if not review["passed"]:
        raise RuntimeError("Deposition independent verification failed")


if __name__ == "__main__":
    main()

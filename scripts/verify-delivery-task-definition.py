"""Verify the actual delivery source readers and the accepted bounded repair."""
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import runpy

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")


def main():
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-result", type=Path, required=True)
    args = parser.parse_args()
    stages = runpy.run_path(str(Path(__file__).with_name("industrial-stage-control.py")))
    task = stages["current_task"]("delivery")
    stages["verify_task_definition"](task)
    read, batch = stages["read_json"], stages["batch"]
    repair = read(args.repair_result)
    assert repair["passed"] and repair.get("applied_at")
    original = read(Path(read(Path(repair["audit_only_from"]))["candidate"]) / "realize_report/task_definition_report.json")
    root = Path(task["run_dir"]) / "autorealize"
    report = root / "realize_report"
    current = read(report / "task_definition_report.json")
    source = Path(next(row for row in read(batch.OUT / "manifest.json")["tasks"]
                       if row["slug"] == "delivery")["payload"]["input_root"])
    readers = read(args.repair_result.parent / "verified-excel-readers.json")
    reader_checks = []
    for row in readers:
        relative, _ = row["table_id"].rsplit("::", 1)
        path = (source / relative).resolve()
        assert path.is_relative_to(source.resolve())
        contract = row["verified_reader"]
        frame = pd.read_excel(path, **contract["pandas_kwargs"])
        reader_checks.append({"table_id": row["table_id"], "shape": list(frame.shape),
            "passed": list(frame.shape) == row["actual_shape"]
                and list(frame.columns) == contract["columns_exact"]})
    capacity = pd.read_excel(source / "承运商每日可用车辆数据表.xlsx", sheet_name="Sheet1", header=0)
    orders = pd.read_excel(source / "15天订单数据1027-1110.xlsx", sheet_name="订单明细信息", header=0)
    previous_sections = deepcopy(original["downstream_context"]["description_sections"])
    current_sections = current["downstream_context"]["description_sections"]
    previous_sections["output"]["facts_used"][6] = current_sections["output"]["facts_used"][6]
    facts_unchanged = all(section.get("facts_used") == current_sections[name].get("facts_used")
                          for name, section in previous_sections.items())
    contract = current["evaluation_contract"]
    frozen = current["main_task_protocol"]["frozen_description_sections"]
    checks = {
        "all_47_original_sheet_readers_reproduced": len(reader_checks) == 47 and all(row["passed"] for row in reader_checks),
        "capacity_dates_all_51_still_missing": len(capacity) == 51 and capacity["日期"].isna().all(),
        "order_grain_20381_details_2104_entities": len(orders) == 20381 and orders["订单号"].nunique() == 2104,
        "accepted_evaluator_unchanged": contract == original["evaluation_contract"],
        "original_authority_and_constraints_retained": all(current["downstream_context"][key] == original["downstream_context"][key]
            for key in ("constraint_memory", "authoritative_memory")),
        "one_fact_repaired_other_facts_retained": facts_unchanged and "assignments=[]" in current_sections["output"]["facts_used"][6],
        "all_frozen_sections_synchronized": frozen == current_sections,
        "static_solver_scope": current["problem_paradigm"]["problem_paradigm"] == "static_optimization",
        "no_invented_split": "not_applicable_static_optimization" in current["automl_context_pack"]["execution_contract"]["identity_semantics"]["split_fingerprint"],
        "explicit_blocked_output": "assignments=[]" in json.dumps(contract, ensure_ascii=False) and "blocked_data_gap" in json.dumps(contract),
        "no_official_sample_invented": current["downstream_context"]["sample_submission_spec"]["should_generate"] is False,
        "full_audit_passed": read(report / "artifact_consistency_report.json")["final"]["passed"] is True,
    }
    checks = {name: bool(passed) for name, passed in checks.items()}
    review = {"passed": all(checks.values()), "constraint_checks": checks,
        "strengths": ["Actual original-sheet reads reproduce every preserved reader contract", "Frozen evaluator, authority and business constraints remain intact", "All final output mirrors require explicit empty assignments on missing capacity dates"],
        "weaknesses": ["No capacity dates or real daily dispatch results are available", "All legal candidates tie at100on the internal software contract metric; it does not measure operational quality", "Current full audit input190712tokens remains large; cache telemetry is unknown", "Earlier layout hints remain historical and are superseded only by verified per-file read contracts"],
        "system_changes": ["Static optimization execution identity no longer invents split units or folds", "Evidence references accept verified existing subfields", "Bounded prose and fact repairs synchronize the actual frozen sections"],
        "quality_checks": {"original_sheet_reads": reader_checks, "models_executed": False, "solver_readiness": "Actual search and independent software checks still required"},
        "usage_analysis": {"full_audit_input_tokens": 190712, "cache_hit_rate": "unknown", "output_cap": 32768},
        "evidence_paths": [str(args.repair_result.resolve()), str(report / "task_definition_report.json"), str(report / "artifact_consistency_report.json"),
            str(args.repair_result.parent / "verified-excel-readers.json"), str(report / "section_fact_repair_report.json")]}
    output = batch.OUT / "delivery-autorealize-review-20260908.json"
    batch.save(output, review)
    print(json.dumps({"passed": review["passed"], "checks": checks, "review": str(output)}, ensure_ascii=False))
    if not review["passed"]:
        raise RuntimeError("Delivery independent task-definition verification failed")


if __name__ == "__main__":
    main()

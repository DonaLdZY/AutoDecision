"""Independently check the repaired AI4I task contract and realized split, without fitting models."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

SPEC = importlib.util.spec_from_file_location("industrial_stages", Path(__file__).with_name("industrial-stage-control.py"))
stages = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stages)
FEATURES = ["Type", "Air temperature [K]", "Process temperature [K]", "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]"]
EXCLUDED = ["UDI", "Product ID", "TWF", "HDF", "PWF", "OSF", "RNF"]
OUTPUTS = ["UDI", "failure_probability", "predicted_failure"]
SPLIT_CODE = (
    "remaining_positions, holdout_positions = train_test_split(all_positions, test_size=0.2, stratify=y, random_state=20260907)",
    "train_positions, development_positions = train_test_split(remaining_positions, test_size=0.25, stratify=y[remaining_positions], random_state=20260907)",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-result", type=Path, required=True)
    args = parser.parse_args()
    repair = stages.read_json(args.repair_result)
    assert repair["slug"] == "ai4i" and repair["passed"] is True
    candidate = Path(repair["candidate"])
    task = stages.current_task("ai4i")
    stages.verify_task_definition({**task, "run_dir": str(candidate.parent)})
    fingerprint = stages.fingerprint(stages.stage_artifacts({"run_dir": str(candidate.parent)}, "autorealize"))
    assert fingerprint == repair["candidate_fingerprint"]
    report_dir = candidate / "realize_report"
    report = stages.read_json(report_dir / "task_definition_report.json")
    protocol = stages.read_json(report_dir / "main_task_protocol.json")
    pack = stages.read_json(report_dir / "automl_context_pack.json")
    evaluation = stages.read_json(report_dir / "evaluation_contract_report.json")["final"]
    context = report["downstream_context"]
    assert report["automl_context_pack"] == pack
    assert context["evaluation_contract"] == evaluation
    assert report["main_task_protocol"] == protocol
    assert context["artifact_consistency_review"]["passed"] is True
    assert stages.read_json(report_dir / "authoritative_task_memory.json")["source_files"] == ["task_hint"]
    assert evaluation["primary_metric"] == "average_precision_score"
    assert evaluation["metric_direction"] == "maximize"
    description = (candidate / "description.md").read_text(encoding="utf-8")
    current_spec = protocol["sample_submission_spec"]
    assert current_spec["columns"] == OUTPUTS
    assert current_spec == context["sample_submission_spec"]
    for field in FEATURES:
        assert "ai4i2020.csv::" + field in current_spec["source_fields"]["failure_probability"]
    assert "temperature [K] temperature" not in current_spec["source_fields"]["failure_probability"]
    assert pack["output_contract"]["final_prediction_validated"] is False
    for code in SPLIT_CODE:
        match = re.search(re.escape(code.split(" = ")[0]) + r"\s*=\s*train_test_split\([^)]*\)", evaluation["validation_protocol"])
        assert match, code
        assert ast.dump(ast.parse(match[0])) == ast.dump(ast.parse(code))
        assert match[0] in description
    assert "train_positions, remaining_positions = train_test_split" not in description
    assert "row_count_basis=worksheet_used_range" not in description
    assert all(item["row_count_basis"] != "worksheet_used_range" for item in pack["source_coverage_ledger"]["entries"])
    for access in pack["data_access"]:
        if access.get("path") == "ai4i2020.csv":
            assert access["columns_scope"] == "physical_schema"
            assert set(access["columns"]) == set(FEATURES + EXCLUDED + ["Machine failure"])
            assert access["columns"] == access["read_contract"]["validated_columns_exact"]
            assert access["read_contract"]["population_verified"] is False
            assert access["read_contract"]["requires_full_parse_before_evaluation"] is True
            assert "validated_shape" not in access["read_contract"]
            for table in access.get("data_schema_contract", {}).get("tables", []):
                assert table["row_count_basis"] == "reader_shape_unverified"
                assert table.get("verified_row_count") is None
                assert not table.get("worksheet_used_range_shape")
                assert table["physical_columns_exact"] == access["columns"]
    qmem = context["agent_context_pack"]["question_memory"]
    assert qmem["unresolved_questions"]
    assert all(answer["remaining_uncertainty"] for answer in qmem["answers"])
    qdi = stages.read_json(report_dir / "question_investigation_report.json")
    assert any(record["status"] == "answered_with_uncertainty" for record in qdi["question_records"])
    assert all(item.get("status") == "declared_output_not_physical_column"
               for item in pack["source_alias_guard"] if item["alias"] in OUTPUTS[1:])

    source = Path(task["input_root"]) / "ai4i2020.csv"
    data = pd.read_csv(source, encoding="utf-8-sig")
    assert len(data) == 10000
    assert set(data.columns) == set(FEATURES + EXCLUDED + ["Machine failure"])
    assert list(data.columns) == next(access["columns"] for access in pack["data_access"] if access.get("path") == "ai4i2020.csv")
    assert data["UDI"].notna().all() and data["UDI"].is_unique
    assert data["Type"].isin(["L", "M", "H"]).all()
    assert np.isfinite(data[FEATURES[1:]].apply(pd.to_numeric, errors="raise").to_numpy()).all()
    assert data["Machine failure"].isin([0, 1]).all()
    y = data["Machine failure"].to_numpy()
    positions = np.arange(len(data))
    remaining, holdout = train_test_split(positions, test_size=0.2, stratify=y, random_state=20260907)
    train, development = train_test_split(remaining, test_size=0.25, stratify=y[remaining], random_state=20260907)
    splits = {"train": np.sort(train), "development": np.sort(development), "holdout": np.sort(holdout)}
    assert [len(values) for values in splits.values()] == [6000, 2000, 2000]
    assert len(np.unique(np.concatenate(list(splits.values())))) == len(data)
    membership = pd.DataFrame({"row_position": positions, "UDI": data["UDI"], "split": ""})
    for name, values in splits.items():
        membership.loc[values, "split"] = name
    output = stages.batch.OUT / "optimization-validation" / f"ai4i-task-definition-{time.time_ns()}"
    output.mkdir(parents=True)
    membership.to_csv(output / "independent-split-membership.csv", index=False, encoding="utf-8")
    result = {
        "passed": True, "stage": "autorealize", "slug": "ai4i",
        "scope": "Independent source/schema and split verification. No model, baseline metric or holdout prediction executed. The system must generate its own identical split during AutoML.",
        "candidate": str(candidate), "candidate_fingerprint": fingerprint,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "split_membership_sha256": hashlib.sha256((output / "independent-split-membership.csv").read_bytes()).hexdigest(),
        "features": FEATURES, "excluded": EXCLUDED, "output_columns": OUTPUTS,
        "splits": {name: {"rows": len(values), "negative": int((y[values] == 0).sum()),
                          "positive": int((y[values] == 1).sum())} for name, values in splits.items()},
        "model_execution": False, "evaluation_id": pack["execution_contract"]["evaluation_id"],
        "readiness": pack["execution_contract"]["readiness"],
    }
    stages.batch.save(output / "result.json", result)
    print(json.dumps({"result": str(output / "result.json"), "passed": True, "splits": result["splits"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Append reviewed deposition facts and renew the existing AutoML stage review."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    args = parser.parse_args()
    facts_path = args.facts.resolve()
    facts = read(facts_path)
    preparation = read(facts_path.with_name("result.json"))
    if not preparation["passed"] or preparation["facts_sha256"] != digest(facts_path):
        raise RuntimeError("Read-only report evidence preparation is absent or changed")
    spec = importlib.util.spec_from_file_location("deposition_record_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    with stages.admission_lock():
        task = stages.current_task("deposition")
        before = stages.fingerprint(stages.stage_artifacts(task, "automl"))
        if task["status"] == "running" or before != facts["automl_artifact_fingerprint"]:
            raise RuntimeError("The deposition task is active or its reviewed evidence changed")
        workspace = Path(task["auto_ml_workspace_dir"])
        independent_path = workspace / "final_evaluation/independent-verification.json"
        previous = read(independent_path)
        assert previous["node_id"] == facts["selected_manifest"]["node_id"]
        if "report_evidence_supplement" in previous:
            raise RuntimeError("The report evidence supplement was already recorded")
        ledger_review = read(stages.LEDGER)["deposition"]["automl"]
        assert ledger_review["passed"] and ledger_review["artifact_fingerprint"] == before
        archive = OUT / "stage-archives/deposition" / f"report-evidence-before-append-{time.time_ns()}"
        archive.mkdir(parents=True)
        shutil.copy2(independent_path, archive / independent_path.name)
        save(archive / "automl-review.json", ledger_review)
        raw = read(facts_path.with_name("raw-independent-verifications.json"))
        development = next(item for item in raw if Path(item["path"]).parent.name == "deposition-score-8253ea8f-1788816135676158300")
        verify = development["result"]
        assert verify["passed"] and verify["phase"] == "development" and verify["scored_rows"] == 79739
        assert verify["node"] == previous["node_id"]
        implementation = workspace / "best_solution" / facts["selected_manifest"]["implementation_path"]
        assert digest(implementation) == previous["implementation_sha256"]
        assert digest(Path(facts["models"]["final"]["path"])) == previous["model_sha256"]
        revised = copy.deepcopy(previous)
        revised["development_score_verification"] = verify
        revised["report_evidence_supplement"] = {
            "source_facts_path": str(facts_path), "source_facts_sha256": digest(facts_path),
            "scope": "Append-only factual report preparation. Existing score, prediction, model, verification and search records remain unchanged; no fitting, inference or scoring was rerun.",
            "actual_counts": facts["actual_counts"],
            "model_artifacts": facts["models"],
            "final_gate_matches_search_gate": facts["final_gate_matches_search_gate"],
            "final_tail_parameters_match_search": facts["final_tail_parameters_match_search"],
            "source_implementation": {"path": str(implementation), "sha256": digest(implementation),
                "functions": {name: facts["exact_implementation_functions"][name] for name in
                              ("final_evaluate", "_fit_artifact", "_calibrate_tail_gate", "train", "predict", "_request_frame", "_make_prediction_output")}},
            "candidate_runtime_metadata": facts["candidate_runtime_metadata"],
            "data_audit_summary": facts["data_audit_summary"],
            "candidate_comparison": [{key: item[key] for key in ("id", "stage", "method_family", "metric", "evaluation_protocol",
                "fusion_sources", "actual_saved_recipe", "actual_development_population_check")} for item in facts["accepted_candidates"]],
            "additional_independent_verifications": facts["independent_verifications"],
            "source_interpretation_requirements": facts["report_requirements"],
            "public_interface": {
                "wrapper_path": str(workspace / "best_solution/solution.py"),
                "wrapper_source": facts["public_wrapper"],
                "predict_return": "numpy.ndarray of shape (n,), dtype float64; not a DataFrame",
                "request_columns": ["evaluation_row_id", "source_file", "strategy", "zone", "time_s", "layer_scope"],
                "output_columns": ["evaluation_row_id", "source_file", "strategy", "zone", "time_s", "y_pred"],
                "train_input": "Fixed original source directory or validated full scoring-unit DataFrame; default training fits split=train only.",
                "directory_inference_api_exists": False, "inference_cli_exists": False,
                "main_behavior": "Fixed source parsing, training and development evaluation; not a prediction-only command.",
                "randomness": "No random split. Recipe initialization and optimizer starts are deterministic; preserve numerical environment, do not invent an unrecorded random seed.",
            },
            "immutability_scope": "search_and_final_model_bytes_unchanged refers to immutability during later verification, not byte equality between two distinct search/final model files.",
        }
        for key, value in previous.items():
            assert revised[key] == value
        save(independent_path, revised)
        for name in ("final_evaluation/result.json", "best_solution/solution_manifest.json"):
            assert (workspace / name).is_file()
        assert digest(Path(facts["models"]["final"]["path"])) == previous["model_sha256"]
        review = copy.deepcopy(ledger_review)
        review["strengths"].append("Report preflight compared the exact source/strategy/zone/Decimal-time keys of all eight accepted candidates: every development prediction population contains the same79739unique units.")
        review["system_changes"].append("Appended the previously completed development score verification and read-only final-model fit metadata to the independent final record; preserved all prior fields and immutable score/model bytes.")
        review["quality_checks"]["report_source_preflight"] = {
            "facts": str(facts_path), "all_accepted_population_keys_equal": True,
            "search_fit_units": 239372, "final_fit_units": 319111,
            "final_fit_splits": ["train", "development"], "final_gate_unchanged": True,
            "train_only_calibration_units": 47798, "final_tail_optimizer_success": 153,
            "final_tail_heads": 192, "final_tail_fallback": 0,
            "predict_type": "numpy.ndarray", "original_fields_preserved": True,
        }
        review["evidence_paths"].extend([str(facts_path), str(facts_path.with_name("result.json")), str(independent_path)])
        review_path = facts_path.with_name("renewed-automl-review.json")
        save(review_path, review)
        stages.record_review("deposition", "automl", review_path)
        updated_fingerprint = stages.fingerprint(stages.stage_artifacts(task, "automl"))
        receipt = {"passed": True, "archive": str(archive), "independent_record": str(independent_path),
            "independent_record_sha256": digest(independent_path), "prior_automl_artifact_fingerprint": before,
            "automl_artifact_fingerprint": updated_fingerprint, "review_path": str(review_path),
            "original_fields_preserved": True, "model_bytes_unchanged": True, "scores_unchanged": True,
            "api_called": False, "training_or_scoring_repeated": False}
        save(facts_path.with_name("recording-receipt.json"), receipt)
        print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()

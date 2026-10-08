"""Collect exact deposition report facts without fitting, scoring or calling an API."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.dont_write_bytecode = True


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    import joblib
    import pandas as pd
    from decimal import Decimal

    spec = importlib.util.spec_from_file_location("deposition_evidence_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("deposition")
    if task["status"] == "running":
        raise RuntimeError("Read a completed deposition task only")
    workspace = Path(task["auto_ml_workspace_dir"])
    logs = Path(task["auto_ml_log_dir"])
    fingerprint = stages.fingerprint(stages.stage_artifacts(task, "automl"))
    exported = workspace / "best_solution"
    manifest = read(exported / "solution_manifest.json")
    implementation = exported / manifest["implementation_path"]
    code = implementation.read_text(encoding="utf-8")
    source_functions = {node.name: ast.get_source_segment(code, node) for node in ast.parse(code).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
            "train", "predict", "_request_frame", "_make_prediction_output", "_validate_prediction_output",
            "_fit_artifact", "_calibrate_tail_gate", "final_evaluate", "main", "TailAwareHierarchicalRegressor"}}
    sys.path.insert(0, str(exported))
    import solution

    def forbidden(*args, **kwargs):
        raise AssertionError("Report evidence collection must not fit, predict or evaluate")

    implementation_module = solution._implementation
    for name in ("train", "predict", "final_evaluate", "_fit_artifact", "_fit_ridge_model", "_calibrate_tail_gate", "main"):
        setattr(implementation_module, name, forbidden)
    import sklearn.linear_model
    sklearn.linear_model.Ridge.fit = forbidden
    # The historical search pickle predates the portable module-name export.
    sys.modules["__main__"].TailAwareHierarchicalRegressor = implementation_module.TailAwareHierarchicalRegressor
    final_path = Path(solution.default_model_path())
    search_path = exported / "runtime/working/model_artifact_8253ea8f3600482283a1b7407a4377fb.pkl"
    final_model, search_model = joblib.load(final_path), joblib.load(search_path)
    model_keys = ("artifact_version", "recipe", "feature_dimension", "fit_splits", "fit_scoring_unit_count", "fit_curve_count",
        "software_versions", "feature_schema", "tail_expert_configuration", "tail_expert_fit_summary", "tail_fusion_gate", "tail_calibration",
        "tail_fusion_fingerprint", "allowed_source_files")
    model_facts = {name: {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size,
        "metadata": {key: model.get(key) for key in model_keys}}
        for name, model, path in (("search", search_model, search_path), ("final", final_model, final_path))}
    source_verification = read(workspace / "final_evaluation/independent-verification.json")
    verification_paths = [OUT / "optimization-validation/deposition-score-8253ea8f-1788816135676158300/result.json",
        *[ROOT / path for path in source_verification["evidence_paths"]],
        OUT / "optimization-validation/deposition-inference-8253ea8f-1788818823186870000/result.json",
        OUT / "optimization-validation/deposition-score-b0ff56be-1788813284373504300/result.json",
        OUT / "optimization-validation/deposition-score-71730def-1788811474618459100/result.json"]
    verifications = [{"path": str(path), "sha256": digest(path), "result": read(path)} for path in verification_paths]
    compact_verifications = []
    for verification in verifications:
        payload = verification["result"]
        compact_verifications.append({"path": verification["path"], "sha256": verification["sha256"],
            "summary": {key: payload.get(key) for key in ("passed", "node", "rmse", "reported_score", "scored_rows", "curves",
                "diagnostics", "phase", "model_code_executed", "holdout_scored", "inference", "scope", "source_model_unchanged")
                if key in payload}})
    journal = read(logs / "journal.json")
    accepted = sorted([node for node in journal["nodes"] if node.get("search_eligible")], key=lambda node: node["metric"]["value"])
    candidates = [{key: node.get(key) for key in ("id", "parent_id", "stage", "method_family", "metric", "evaluation_protocol",
        "search_eligible", "fusion_sources", "execution_time", "exec_time", "plan", "analysis")}
        for node in accepted]
    reference_keys = None
    for candidate in candidates:
        node_root = workspace / "node_runs" / candidate["id"]
        recipe_path = node_root / "working/selected_recipe.json"
        candidate["actual_saved_recipe"] = {"source": str(recipe_path), "sha256": digest(recipe_path), "content": read(recipe_path)}
        predictions_path = node_root / "submission" / f"submission_{candidate['id']}.csv"
        predictions = pd.read_csv(predictions_path, dtype={"time_s": str})
        assert predictions.columns.tolist() == ["evaluation_row_id", "source_file", "strategy", "zone", "time_s", "y_pred"]
        assert predictions["evaluation_row_id"].is_unique
        population = {(str(row.source_file), str(row.strategy), str(row.zone), Decimal(row.time_s))
                      for row in predictions.itertuples(index=False)}
        assert len(population) == len(predictions) == 79739
        if reference_keys is None:
            reference_keys = population
        candidate["actual_development_population_check"] = {"source": str(predictions_path),
            "sha256": digest(predictions_path), "rows": len(predictions), "unique_identity_keys": len(population),
            "identity_semantics": "Exact source_file,strategy,zone,Decimal(time_s), with unique evaluation_row_id separately checked",
            "matches_selected_population": population == reference_keys, "scores_recomputed_now": False}
        assert population == reference_keys
    runtime = read(exported / "runtime/working/run_metadata.json")
    counts = runtime["actual_counts"]
    assert model_facts["final"]["metadata"]["fit_splits"] == ["train", "development"]
    assert model_facts["final"]["metadata"]["fit_scoring_unit_count"] == counts["train_scoring_units"] + counts["development_scoring_units"]
    facts = {
        "schema_version": "independent.report_source_review.v1", "task_id": task["id"], "slug": "deposition",
        "source_policy": "These records supplement the complete original task rules. They do not replace or shorten the authoritative constraints. No model fitting, inference, final evaluation or provider call ran during this read-only preparation.",
        "automl_artifact_fingerprint": fingerprint,
        "autorealize_artifact_fingerprint": stages.fingerprint(stages.stage_artifacts(task, "autorealize")),
        "search_elapsed_seconds": stages.verified_search_seconds(task),
        "source_scope": "Three existing deposition strategies, 64 top-layer zones each. Simulation-temperature prediction, not measured experimental temperature, path optimization or unseen-strategy validation.",
        "actual_counts": counts, "models": model_facts,
        "final_gate_matches_search_gate": final_model["tail_fusion_gate"] == search_model["tail_fusion_gate"],
        "final_tail_parameters_match_search": final_model["tail_heads"] == search_model["tail_heads"],
        "node_count": len(journal["nodes"]), "accepted_candidate_count": len(accepted),
        "accepted_candidates": candidates, "selected_manifest": manifest,
        "final_result": read(workspace / "final_evaluation/result.json"),
        "independent_verifications": compact_verifications,
        "independent_verification_source": str(workspace / "final_evaluation/independent-verification.json"),
        "candidate_runtime_metadata": runtime,
        "data_audit_summary": read(exported / "runtime/working/data_audit_summary.json"),
        "public_wrapper": (exported / "solution.py").read_text(encoding="utf-8"),
        "exact_implementation_functions": source_functions,
        "report_requirements": [
            "Use the exact selected node ID and ID-score pairs. The exported implementation SHA256 is not a node ID.",
            "The selected development score has independent raw-source Decimal-time aggregation and saved-prediction recomputation. Do not call it merely self-reported.",
            "Separate 79739 development units from 79967 final holdout units. Scores are pooled per-scoring-unit RMSE, not a mean of per-strategy RMSE values.",
            "The final model refits Ridge, scaling and tail heads on train+development; the calibration routine still selects only split=train. Compare saved gates directly before claiming their values changed.",
            "The 192 tail-head optimizer summaries need not all report success even when finite feasible heads were accepted. Report success and fallback counts accurately without inventing a failure threshold.",
            "The pipeline uses seven time bases and 212 hierarchical categorical blocks, 1484 total feature columns, sparse Ridge/LSQR plus bounded biexponential tails and a monotone distance-dependent convex gate.",
            "predict returns a one-dimensional numpy.ndarray, not the six-column DataFrame. Build the output by copying the five request identity columns and assigning y_pred; layer_scope is input-only.",
            "Inference requires all six request columns and exact frozen source_file identities even though source_file is excluded from model features. New numeric times are supported only within the three known strategy/source identities and supported zones.",
            "The public wrapper must remain beside its implementation file and model_path.txt, solution_manifest.json, and the relative model artifact. Import solution before loading the custom serialized model.",
            "The original search runtime pickle uses a historical __main__ class name and is not the portable deliverable. Use the final default_model_path artifact with the provided wrapper and implementation; do not substitute the raw runtime search pickle.",
            "All eight accepted candidates have actual saved 79739-row development prediction key sets identical to the winner; the comparison check verifies keys, not only the protocol fingerprint string. Exact saved recipes explain their algorithm variants.",
            "No infer_new_data output-directory API or infer CLI exists in this candidate. Its main() runs the fixed training/development workflow. A separate report-side adapter can save predictions, but must be labeled and executed before certification.",
            "The chosen algorithm actually ran on CPU using scikit-learn Ridge/SciPy LSQR and numerical optimization. Do not infer GPU training from available hardware or other candidates.",
            "Preserve the parsing/field mapping audit, no cross-curve interpolation or joins, original minimum input boundary, 60/20/20 Decimal-time split, no holdout calibration, and no claims about unknown strategies or experimental ground truth.",
            "search_and_final_model_bytes_unchanged means the subsequent independent checks did not rewrite the two files; it does not mean the search and final files are identical.",
        ],
        "known_report_evidence_gaps": [
            "The current final independent-verification record omits the separate selected-development score recomputation record.",
            "Actual final model fit_splits/counts/tail-head summary and exact final_evaluate source should supplement older search-only artifact_manifest metadata.",
            "Saved candidate APIs verify ndarray prediction and new-time sensitivity; no exact final report examples exist yet and no directory adapter has been independently executed for the final article.",
        ],
    }
    assert stages.fingerprint(stages.stage_artifacts(task, "automl")) == fingerprint
    dest = OUT / "optimization-validation" / f"deposition-report-source-facts-{time.time_ns()}"
    dest.mkdir(parents=True)
    save(dest / "facts.json", facts)
    save(dest / "raw-independent-verifications.json", verifications)
    save(dest / "result.json", {"passed": True, "scope": "Read-only source preflight; not report acceptance",
        "source_artifacts_unchanged": True, "automl_artifact_fingerprint": fingerprint,
        "facts_sha256": digest(dest / "facts.json"), "model_fitting_executed": False,
        "inference_executed": False, "final_evaluation_repeated": False, "api_called": False})
    print(json.dumps({"directory": str(dest), "counts": counts,
        "search_fit": model_facts["search"]["metadata"]["fit_scoring_unit_count"],
        "final_fit": model_facts["final"]["metadata"]["fit_scoring_unit_count"],
        "final_tail_fit_summary": model_facts["final"]["metadata"]["tail_expert_fit_summary"],
        "gate_unchanged": facts["final_gate_matches_search_gate"],
        "node_count": facts["node_count"], "accepted_candidate_count": len(accepted),
        "top_candidates": [{key: row[key] for key in ("id", "method_family", "metric")} for row in candidates[:6]],
        "verifications": compact_verifications}, ensure_ascii=False))


if __name__ == "__main__":
    main()

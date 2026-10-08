"""Independently audit source-aligned steel development scores and node isolation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from engine.node_workspace import node_workspace, copy_node_outputs
from engine.search_node import Journal
from utils.serialize import load_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    args = parser.parse_args()
    task = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["steel"]
    workspace, logs = Path(task["auto_ml_workspace_dir"]), Path(task["auto_ml_log_dir"])
    node = next(node for node in load_json(logs / "journal.json", Journal).nodes if node.id == args.node)
    assert node.search_eligible and node.review_verdict == "accept"
    isolated = node_workspace(workspace, node.id)
    working = isolated / "working"
    metrics = json.loads((working / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["evaluation_phase"] == "search" and metrics["final_evaluation_accessed"] is False
    assert metrics["scoring_split"] == "development_search__pos_00021024_00028031"
    assert (isolated / "input").resolve() == (workspace / "input").resolve()
    assert (isolated / "submission").resolve() == (workspace / "submission").resolve()
    assert not list(working.rglob("holdout_evaluation.json"))
    source_path = workspace / "input/Steel_industry_data.csv"
    assert digest(source_path) == "9b1cee6f9cb9cd9df2b95814ca90a9a2ff15b7f5f1fba0fae3c643e82072eacc"
    source = pd.read_csv(source_path)
    source["timestamp"] = pd.to_datetime(source["date"], format="%d/%m/%Y %H:%M")
    source = source.sort_values("timestamp", kind="stable").reset_index(drop=True)
    expected = source.iloc[21024:28032]
    predicted = pd.read_csv(working / "validation_predictions.csv")
    times = pd.to_datetime(predicted["timestamp"], format="%d/%m/%Y %H:%M")
    assert len(source) == 35040 and len(predicted) == 7008
    np.testing.assert_array_equal(times.to_numpy(), expected["timestamp"].to_numpy())
    np.testing.assert_array_equal(predicted["y_true_Usage_kWh"], expected["Usage_kWh"])
    np.testing.assert_array_equal(predicted["persistence_prediction_Usage_kWh"], source["Usage_kWh"].iloc[21023:28031])
    np.testing.assert_array_equal(predicted["previous_day_seasonal_prediction_Usage_kWh"], source["Usage_kWh"].iloc[20928:27936])
    scores = {}
    for name, column in (("candidate", "candidate_prediction_Usage_kWh"),
                         ("persistence", "persistence_prediction_Usage_kWh"),
                         ("previous_day", "previous_day_seasonal_prediction_Usage_kWh")):
        values = predicted[column].to_numpy()
        assert np.isfinite(values).all()
        scores[name] = float(np.mean(np.abs(values - expected["Usage_kWh"].to_numpy())))
    np.testing.assert_allclose(scores["candidate"], node.metric.value, rtol=0, atol=1e-12)
    np.testing.assert_allclose(scores["candidate"], metrics["development_search"]["MAE_kWh"], rtol=0, atol=1e-12)

    migration = json.loads((OUT / "optimization-validation/steel-first-search-candidate-6e267f5a/migration-and-score-review.json").read_text(encoding="utf-8"))
    first_working = node_workspace(workspace, migration["node_id"]) / "working"
    for name, value in migration["unchanged_source_files"].items():
        assert digest(first_working / name) == value, f"Original node artifact changed: {name}"

    destination = OUT / "optimization-validation" / ("steel-search-candidate-" + node.id)
    destination.mkdir(parents=True, exist_ok=True)
    copy_node_outputs(isolated, destination / "runtime")
    (destination / "solution.py").write_text(node.code, encoding="utf-8")
    files = {str(path.relative_to(working)): digest(path) for path in working.rglob("*") if path.is_file()}
    for name, value in files.items():
        assert digest(destination / "runtime/working" / name) == value
    result = {"passed": True, "node_id": node.id, "search_eligible": node.search_eligible,
              "review_verdict": node.review_verdict, "search_score": node.metric.value,
              "source_aligned_mae": scores, "development_targets": 7008,
              "evaluation_protocol": node.evaluation_protocol,
              "original_candidate_artifacts_unchanged": True, "isolated_working_directory": str(isolated),
              "artifact_sha256": files, "code_sha256": digest(destination / "solution.py"),
              "holdout_artifacts_generated": False, "independent_inference_verified": False,
              "scope": "Full development timestamp/label/baseline/score audit and actual node isolation. Final evaluation and model reuse remain separate checks."}
    (destination / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "node_id": node.id, "scores": scores, "evidence": str(destination / "result.json")}))


if __name__ == "__main__":
    main()

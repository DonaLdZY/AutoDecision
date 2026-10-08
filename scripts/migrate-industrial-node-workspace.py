"""Preserve the sole completed pre-isolation node and verify its development score."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from engine.node_workspace import prepare_node_workspace, node_workspace
from engine.search_node import Journal
from utils.serialize import load_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location("industrial_control", ROOT / "scripts/industrial-stage-control.py")
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    task = control.current_task("steel")
    if task["status"] != "interrupted_resumable":
        raise RuntimeError("Migration requires a durable stopped checkpoint")
    logs, workspace = Path(task["auto_ml_log_dir"]), Path(task["auto_ml_workspace_dir"])
    if logs.name != "20260907_073740_工业实例-钢厂用电预测__20260907_073740":
        raise RuntimeError("This migration is bound to the verified pre-isolation trial")
    originals = {path: digest(path) for path in (logs / "journal.json", logs / "search_state.json")}
    journal = load_json(logs / "journal.json", Journal)
    candidates = [node for node in journal.nodes if node.stage != "root"]
    if len(candidates) != 1 or candidates[0].id != "6e267f5a757c4721a6f4a89506e9c9cb":
        raise RuntimeError("Shared artifacts can only be attributed while exactly this one candidate has executed")
    node = candidates[0]
    working = workspace / "working"
    metrics = json.loads((working / "metrics.json").read_text(encoding="utf-8"))
    recipe = json.loads((working / "selected_recipe.json").read_text(encoding="utf-8"))
    if metrics["candidate_id"] != recipe["candidate_id"] or metrics["final_evaluation_accessed"] is not False:
        raise RuntimeError("Saved metadata does not identify the isolated development candidate")
    source = pd.read_csv(workspace / "input/Steel_industry_data.csv")
    source["timestamp"] = pd.to_datetime(source["date"], format="%d/%m/%Y %H:%M")
    source = source.sort_values("timestamp", kind="stable").reset_index(drop=True)
    predicted = pd.read_csv(working / "validation_predictions.csv")
    actual_times = pd.to_datetime(predicted["timestamp"], format="%d/%m/%Y %H:%M")
    expected = source.iloc[21024:28032]
    assert len(source) == 35040 and len(predicted) == 7008
    np.testing.assert_array_equal(actual_times.to_numpy(), expected["timestamp"].to_numpy())
    np.testing.assert_array_equal(predicted["y_true_Usage_kWh"], expected["Usage_kWh"])
    recomputed = {}
    for name, column in (("candidate", "candidate_prediction_Usage_kWh"), ("persistence", "persistence_prediction_Usage_kWh"),
                         ("previous_day", "previous_day_seasonal_prediction_Usage_kWh")):
        assert np.isfinite(predicted[column]).all()
        recomputed[name] = float(np.mean(np.abs(predicted[column].to_numpy() - expected["Usage_kWh"].to_numpy())))
    assert np.isclose(recomputed["candidate"], node.metric.value, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(predicted["persistence_prediction_Usage_kWh"], source["Usage_kWh"].iloc[21023:28031])
    np.testing.assert_array_equal(predicted["previous_day_seasonal_prediction_Usage_kWh"], source["Usage_kWh"].iloc[20928:27936])
    assert not list(working.rglob("holdout_evaluation.json"))
    target = node_workspace(workspace, node.id)
    if target.exists():
        raise RuntimeError("Migration destination already exists; inspect its prior record")
    target = prepare_node_workspace(workspace, node.id)
    shutil.copytree(working, target / "working", dirs_exist_ok=True)
    files = {str(path.relative_to(working)): digest(path) for path in working.rglob("*") if path.is_file()}
    for name, expected_digest in files.items():
        assert digest(target / "working" / name) == expected_digest
    for path, expected_digest in originals.items():
        assert digest(path) == expected_digest
    result = {"passed": True, "node_id": node.id, "destination": str(target), "unchanged_source_files": files,
              "source_sha256": digest(workspace / "input/Steel_industry_data.csv"), "development_targets": 7008,
              "source_aligned_mae": recomputed, "search_score": node.metric.value,
              "search_journal_and_duration_unchanged": True, "model_code_unchanged": True,
              "holdout_evaluated": False, "final_inference_verified": False,
              "scope": "Exact artifact migration and independent development timestamp/label/score/baseline checks; no model training or holdout evaluation."}
    destination = control.batch.OUT / "optimization-validation/steel-first-search-candidate-6e267f5a/migration-and-score-review.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(destination), "passed": True, "scores": recomputed, "node_id": node.id}))


if __name__ == "__main__":
    main()

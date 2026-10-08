"""Audit the first AI4I search from saved development artifacts, without holdout evaluation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

os.environ.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"})
import numpy as np
import pandas as pd
import psutil
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from utils.resource_limits import WindowsJobMemoryLimiter


def main():
    guard = WindowsJobMemoryLimiter(3 * 1024 ** 3)
    guard.attach(os.getpid())
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[:2])
    task = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["ai4i"]
    logs, workspace = Path(task["auto_ml_log_dir"]), Path(task["auto_ml_workspace_dir"])
    journal = json.loads((logs / "journal.json").read_text(encoding="utf-8"))
    nodes = [node for node in journal["nodes"] if node["stage"] != "root"]
    accepted = [node for node in nodes if node["search_eligible"]]
    assert len(nodes) == 26 and len(accepted) == 1
    winner = accepted[0]
    assert winner["id"] == "22336f77c3c14a66b4b77a0dfe7fa25d"
    working = workspace / "node_runs" / winner["id"] / "working"
    source_path = workspace / "input/ai4i2020.csv"
    source = pd.read_csv(source_path)
    y = source["Machine failure"].to_numpy()
    remaining, holdout = train_test_split(np.arange(len(source)), test_size=0.2, stratify=y, random_state=20260907)
    train, development = train_test_split(remaining, test_size=0.25, stratify=y[remaining], random_state=20260907)
    expected = {"train": np.sort(train), "development": np.sort(development), "holdout": np.sort(holdout)}
    membership = pd.read_csv(working / "split_membership.csv")
    for partition, positions in expected.items():
        rows = membership.loc[membership["split"].eq(partition)]
        np.testing.assert_array_equal(rows["row_position"], positions)
        np.testing.assert_array_equal(rows["UDI"], source.iloc[positions]["UDI"])
    predictions = pd.read_csv(working / "validation_predictions.csv")
    assert set(predictions["partition"]) == {"train", "development"}
    comparison = pd.read_csv(working / "model_comparison.csv")
    scores = {}
    for candidate, group in predictions.loc[predictions["partition"].eq("development")].groupby("candidate_id"):
        group = group.sort_values("row_position", kind="stable")
        positions = expected["development"]
        np.testing.assert_array_equal(group["row_position"], positions)
        np.testing.assert_array_equal(group["UDI"], source.iloc[positions]["UDI"])
        np.testing.assert_array_equal(group["y_true"], y[positions])
        probability = group["failure_probability"].to_numpy()
        assert np.isfinite(probability).all() and ((probability >= 0) & (probability <= 1)).all()
        scores[candidate] = float(average_precision_score(y[positions], probability))
        reported = float(comparison.loc[comparison["candidate_id"].eq(candidate), "development_ap"].iloc[0])
        np.testing.assert_allclose(scores[candidate], reported, atol=1e-12, rtol=0)
    selected = comparison.loc[comparison["role"].eq("selected_candidate"), "candidate_id"].iloc[0]
    np.testing.assert_allclose(scores[selected], winner["metric"]["value"], rtol=0, atol=1e-12)
    dest = OUT / "optimization-validation" / f"ai4i-search-trial-{time.time_ns()}"
    dest.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location("ai4i_export_check", workspace / "best_solution/solution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._implementation.final_evaluate = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Holdout execution forbidden"))
    module._implementation._kernel_oof = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No fitting allowed in missing-recipe check"))
    try:
        module.train(source.iloc[expected["train"]], dest / "fresh_training_output")
    except FileNotFoundError as error:
        training_failure = str(error)
    else:
        raise AssertionError("Expected independently observed default training failure")
    submission = pd.read_csv(workspace / "submission" / f"submission_{winner['id']}.csv")
    assert len(submission) == 0
    search_state = json.loads((logs / "search_state.json").read_text(encoding="utf-8"))
    final_status = json.loads((workspace / "final_evaluation/status.json").read_text(encoding="utf-8"))
    result = {"passed": False, "verification_completed": True, "stage": "automl", "slug": "ai4i",
              "search_seconds": search_state["cumulative_search_elapsed_seconds"], "candidates": len(nodes),
              "accepted": len(accepted), "rejected": len(nodes) - len(accepted), "winner": winner["id"],
              "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
              "all_splits_source_aligned": True, "development_scores_independently_recomputed": scores,
              "selected_development_ap": scores[selected], "required_boosting_baseline_ap": scores["baseline_tree_boosting"],
              "default_train_failed_in_fresh_directory": training_failure, "production_submission_rows": len(submission),
              "final_evaluation_already_attempted_by_engine": final_status.get("status"),
              "holdout_scores_read_by_this_verifier": False, "holdout_model_execution_by_this_verifier": False,
              "scope": "Reject search quality and reusable delivery. Development scores and split membership verified from original CSV. Missing-recipe error exercised before fitting. Existing holdout results not read or re-evaluated."}
    (dest / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(dest), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

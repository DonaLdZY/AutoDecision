"""Recompute chemical development scores and population from original labels."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--phase", choices=("development", "final"), default="development")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("chemical_score_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("chemical")
    workspace = Path(task["auto_ml_workspace_dir"])
    work = workspace / "node_runs" / args.node / "working"
    final_result = None
    if args.phase == "final":
        stages.verified_search_seconds(task)
        assert task["status"] == "completed"
        final = workspace / "final_evaluation"
        state = stages.read_json(final / "status.json")
        final_result = stages.read_json(final / "result.json")
        assert state["status"] == final_result["status"] == "completed"
        assert state["selection"]["node_id"] == args.node
        work = final / "artifacts"
    source = Path(task["run_dir"]) / "autorealize"
    node = next(row for row in stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")["nodes"]
                if row["id"] == args.node)
    assert node.get("is_valid") is True and node.get("is_buggy") is False
    book = pd.read_excel(source / "\u6d53\u5ea6.xls", sheet_name=None, header=0)
    assert book["Sheet2"].empty and book["Sheet3"].empty
    raw = book["Sheet1"]
    labels = raw.loc[raw["\u53c2\u6570"].eq("Al(N\uff09") & raw["\u90e8\u4f4d"].eq("\u538b\u6ee4\u6db2")].copy()
    labels["y_true"] = pd.to_numeric(labels["\u7ed3\u679c\n[\u5355\u4f4d\u4e3a\u5f53\u91cf]"], errors="raise")
    labels["prediction_cutoff"] = pd.to_datetime(labels["\u91c7\u6837\u65f6\u95f4"], format="mixed", errors="raise")
    assert len(labels) == 1525 and np.isfinite(labels.y_true).all()
    labels["label_row_id"] = "\u6d53\u5ea6.xls::Sheet1:" + (labels.index + 2).astype(str)
    groups = sorted(labels.prediction_cutoff.unique())
    assert len(groups) == 1519
    holdout = math.ceil(.2 * len(groups))
    development = math.ceil(.25 * (len(groups) - holdout))
    train = len(groups) - holdout - development
    assert (train, development, holdout) == (911, 304, 304)
    lookup = {moment: "train" if index < train else "development" if index < train + development else "holdout"
              for index, moment in enumerate(groups)}
    labels["split"] = labels.prediction_cutoff.map(lookup)
    assert labels.groupby("split").size().to_dict() == {"train": 914, "development": 307, "holdout": 304}
    labels = labels.set_index("label_row_id")
    saved_split = pd.read_csv(work / "split_manifest.csv")
    if "label_row_id" in saved_split:
        saved_split = saved_split.set_index("label_row_id")
        assert saved_split.index.is_unique and set(saved_split.index) == set(labels.index)
        saved_split = saved_split.reindex(labels.index)
        assert labels.split.eq(saved_split.split).all()
        assert labels.prediction_cutoff.eq(pd.to_datetime(saved_split.prediction_cutoff)).all()
    else:
        saved_split["prediction_cutoff"] = pd.to_datetime(saved_split.prediction_cutoff)
        assert saved_split.prediction_cutoff.is_unique and len(saved_split) == len(groups)
        assert set(saved_split.prediction_cutoff) == set(lookup)
        assert saved_split.prediction_cutoff.map(lookup).eq(saved_split.split).all()
    samples = pd.read_csv(work / "evaluation_samples.csv").set_index("label_row_id")
    assert samples.index.is_unique and set(samples.index) == set(labels.index)
    samples = samples.reindex(labels.index)
    assert labels.split.eq(samples.split).all()
    window_column = "valid_process_rows" if "valid_process_rows" in samples else "valid_process_window_rows"
    assert samples[window_column].between(46, 61).all()
    hashes = {name: file_hash(source / name) for name in ("\u6d53\u5ea6.xls", "\u8bbe\u5907.csv")}
    if (work / "data_audit.json").is_file():
        audit = stages.read_json(work / "data_audit.json")
        assert all(audit["sources"][name]["sha256"] == value for name, value in hashes.items())
    else:
        audit = stages.read_json(work / "data_read_audit.json")
        assert all(audit[key]["source_sha256"] == hashes[audit[key]["source_file"]]
                   for key in ("label_read_audit", "device_audit"))
    prediction_path = work / "holdout_prediction_frame.csv" if final_result else workspace / "submission" / f"submission_{args.node}.csv"
    predictions = pd.read_csv(prediction_path)
    assert list(predictions.columns) == ["label_row_id", "y_pred"]
    assert predictions.label_row_id.is_unique and np.isfinite(predictions.y_pred).all()
    target = labels.loc[labels.split.eq("holdout" if final_result else "development")]
    assert set(predictions.label_row_id) == set(target.index)
    predicted = predictions.set_index("label_row_id").reindex(target.index).y_pred
    np.testing.assert_allclose(samples.loc[target.index, "y_true"], target.y_true, rtol=0, atol=1e-12)
    errors = predicted - target.y_true
    score = float(np.abs(errors).mean())
    reported = float(final_result["metrics"]["holdout_MAE"] if final_result else node["metric"]["value"])
    high = target["\u8d85\u5dee"].eq("\u9ad8")
    assert labels["\u8d85\u5dee"].eq("\u9ad8").sum() == 6
    assert high.sum() == (0 if final_result else 6)
    result = {"passed": abs(score - reported) < 1e-10, "node": args.node, "phase": args.phase,
              "mae": score, "reported_mae": reported, "rmse": float(np.sqrt(np.square(errors).mean())),
              "scored_rows": len(target), "eligible_rows": len(labels), "atomic_cutoff_groups": len(groups),
              "split_rows": labels.groupby("split").size().to_dict(), "high_labels_retained": 6,
              "high_labels_in_scoring_split": int(high.sum()), "high_label_mae": float(np.abs(errors[high]).mean()) if high.any() else None,
              "source_hashes": hashes, "model_code_executed": False, "holdout_scored": bool(final_result),
              "scope": "Independent original labels, atomic cutoff splits and complete frozen predictions; no model execution, refitting or repeated model selection"}
    if final_result:
        baseline = float(labels.loc[labels.split.ne("holdout"), "y_true"].median())
        baseline_mae = float(np.abs(target.y_true - baseline).mean())
        assert abs(baseline_mae - final_result["metrics"]["MedianBaseline_holdout_MAE"]) < 1e-10
        result.update(baseline_prediction=baseline, baseline_mae=baseline_mae, worse_than_median_baseline=score > baseline_mae)
    else:
        result.update(development_mae=score, high_label_development_mae=result["high_label_mae"])
    dest = stages.batch.OUT / "optimization-validation" / f"chemical-{args.phase}-score-{args.node[:8]}-{time.time_ns()}"
    dest.mkdir(parents=True)
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), **result}, ensure_ascii=False))
    if not result["passed"]:
        raise RuntimeError("Independent chemical development score differs from the candidate")


if __name__ == "__main__":
    main()

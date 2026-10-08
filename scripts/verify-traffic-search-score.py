"""Recompute a saved traffic development score from source events without fitting a model."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("traffic_score_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("traffic")
    source = Path(task["run_dir"]) / "autorealize"
    work = Path(task["auto_ml_workspace_dir"]) / "node_runs" / args.node / "working"
    journal = stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")
    node = next(item for item in journal["nodes"] if item["id"] == args.node)
    prediction_file = work / "development_validation_predictions.csv"
    reported = float(node["metric"]["value"])
    if args.final:
        stages.verified_search_seconds(task)
        if task["status"] == "running":
            raise RuntimeError("Final score verification requires completed service execution")
        final = Path(task["auto_ml_workspace_dir"]) / "final_evaluation"
        state, final_result = stages.read_json(final / "status.json"), stages.read_json(final / "result.json")
        assert state["status"] == final_result["status"] == "completed"
        assert state["selection"]["node_id"] == args.node
        prediction_file = final / "artifacts/final_evaluation/holdout_predictions.csv"
        reported = float(final_result["metrics"]["diagnostic_metrics"]["30"]["MAE"])
    relation = pd.read_excel(source / "\u95e8\u67b6\u5173\u7cfb\u8868(\u6cb3\u6c60).xlsx", sheet_name="\u95e8\u67b6\u5173\u7cfb\u8868", engine="openpyxl")
    endpoints = pd.concat([relation["\u5f53\u524d\u95e8\u67b6id"], relation["\u4e0a\u6e38\u95e8\u67b6id"]]).dropna().astype(str).str.strip()
    ids = sorted(set(endpoints) - {"", "/"})
    day = pd.Timestamp("2025-11-07" if args.final else "2025-11-06")
    counts = pd.DataFrame(0, index=pd.date_range(day, periods=288, freq="5min"), columns=ids, dtype=np.int64)
    source_rows, development_rows = 0, 0
    for chunk in pd.read_csv(source / "tmp_gantry_trade_info_split1_20251224_7d_hechi_result.csv",
                             usecols=["\u95e8\u67b6id", "\u95e8\u67b6\u65f6\u95f4"], dtype=str, chunksize=200000, encoding="utf-8-sig"):
        source_rows += len(chunk)
        chunk["\u95e8\u67b6id"] = chunk["\u95e8\u67b6id"].str.strip()
        event_ids = set(chunk["\u95e8\u67b6id"].dropna()) - {"", "/"}
        ids = sorted(set(ids) | event_ids)
        counts = counts.reindex(columns=ids, fill_value=0)
        timestamps = pd.to_datetime(chunk["\u95e8\u67b6\u65f6\u95f4"], dayfirst=True, errors="raise")
        selected = chunk.loc[timestamps.ge(day) & timestamps.lt(day + pd.Timedelta(days=1))].copy()
        selected["bucket"] = timestamps.loc[selected.index].dt.floor("5min")
        selected["\u95e8\u67b6id"] = selected["\u95e8\u67b6id"].str.strip()
        development_rows += len(selected)
        grouped = selected.groupby(["bucket", "\u95e8\u67b6id"]).size().unstack(fill_value=0)
        counts += grouped.reindex(index=counts.index, columns=ids, fill_value=0)
    cumulative = np.vstack([np.zeros((1, len(ids)), dtype=np.int64), counts.to_numpy().cumsum(axis=0)])
    origins = pd.date_range(day, periods=277, freq="5min")
    predictions = pd.read_csv(prediction_file, dtype={"gantry_id": str})
    assert list(predictions.columns) == ["gantry_id", "forecast_origin", "horizon_minutes", "predicted_count"]
    predictions["forecast_origin"] = pd.to_datetime(predictions["forecast_origin"], errors="raise")
    assert not predictions.duplicated(["forecast_origin", "gantry_id", "horizon_minutes"]).any()
    expected_keys = pd.MultiIndex.from_product([origins, ids, [30, 60]], names=["forecast_origin", "gantry_id", "horizon_minutes"])
    observed = predictions.set_index(expected_keys.names)["predicted_count"]
    assert len(observed) == len(expected_keys), {
        "observed_rows": len(observed), "expected_rows": len(expected_keys),
        "source_gantries": len(ids), "observed_gantries": predictions["gantry_id"].nunique(),
        "omitted_source_gantries": sorted(set(ids) - set(predictions["gantry_id"])),
        "extra_observed_gantries": sorted(set(predictions["gantry_id"]) - set(ids)),
    }
    assert len(observed.index.difference(expected_keys)) == 0
    assert np.isfinite(observed.to_numpy()).all() and observed.ge(0).all()
    scores = {}
    for horizon in (30, 60):
        truth = cumulative[np.arange(277) + horizon // 5] - cumulative[np.arange(277)]
        key = pd.MultiIndex.from_product([origins, ids], names=["forecast_origin", "gantry_id"])
        estimate = observed.xs(horizon, level="horizon_minutes").reindex(key).to_numpy().reshape(277, len(ids))
        assert np.isfinite(estimate).all()
        errors = estimate - truth
        scores[str(horizon)] = {"MAE": float(np.abs(errors).mean()), "RMSE": float(np.square(errors).mean() ** .5),
                                "samples": int(truth.size), "zero_flow_windows": int((truth == 0).sum())}
    result = {"node": args.node, "passed": abs(scores["30"]["MAE"] - reported) < 1e-9,
              "source_rows": source_rows, "scored_event_rows": development_rows, "gantries": len(ids),
              "origins": len(origins), "prediction_rows": len(predictions), "scores": scores,
              "reported_score": reported, "no_model_code_executed": True,
              "holdout_scored": args.final, "phase": "final" if args.final else "development",
              "scope": "Independent raw-event aggregation and saved prediction checks. No fitting, model invocation, or repeated final evaluation."}
    dest = stages.batch.OUT / "optimization-validation" / f"traffic-{'final-' if args.final else ''}score-{args.node[:8]}-{time.time_ns()}"
    dest.mkdir(parents=True)
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), **result}, ensure_ascii=False))
    if not result["passed"]:
        raise RuntimeError("Reported traffic score does not match the independent source-aligned development score")


if __name__ == "__main__":
    main()

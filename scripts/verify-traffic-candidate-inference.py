"""Check raw-event inference matches the frozen development feature path."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from engine.executor import Interpreter
from utils.resource_limits import WindowsJobMemoryLimiter


def main():
    import numpy as np
    import pandas as pd
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--code-file", type=Path)
    parser.add_argument("--origins", nargs="+", default=["2025-11-06T00:00:00"])
    parser.add_argument("--numerical-threads", type=int, default=2)
    parser.add_argument("--retrain", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("traffic_inference_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("traffic")
    workspace = Path(task["auto_ml_workspace_dir"])
    node = next(row for row in stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")["nodes"] if row["id"] == args.node)
    if not node.get("search_eligible"):
        raise RuntimeError("Select an accepted development candidate")
    work = workspace / "node_runs" / args.node / "working"
    models = list(work.glob("model_artifact_*.joblib"))
    if len(models) != 1:
        raise RuntimeError("Model artifact is ambiguous")
    dest = stages.batch.OUT / "optimization-validation" / f"traffic-inference-{args.node[:8]}-{time.time_ns()}"
    dest.mkdir(parents=True)
    code = node["code"]
    if args.code_file:
        from agents.code_review_agent import validate_review_edit_scope
        revised = args.code_file.read_text(encoding="utf-8")
        validate_review_edit_scope(code, revised, ["_build_panel_from_raw_events"])
        code = revised
    (dest / "candidate_solution.py").write_text(code, encoding="utf-8")
    shutil.copy2(models[0], dest / "frozen_bundle.joblib")
    original_hash = hashlib.sha256(models[0].read_bytes()).hexdigest()
    predictions = pd.read_csv(work / "development_validation_predictions.csv", dtype={"gantry_id": str})
    origins = pd.DatetimeIndex(args.origins).sort_values().unique()
    if len(origins) == 0 or not ((origins >= "2025-11-06") & (origins <= "2025-11-06T23:00:00")).all():
        raise RuntimeError("Only valid development forecast origins are allowed")
    expected = predictions.loc[pd.to_datetime(predictions["forecast_origin"]).isin(origins)].copy()
    if expected["forecast_origin"].nunique() != len(origins):
        raise RuntimeError("Every requested origin must exist in saved development predictions")
    ids = sorted(expected["gantry_id"].unique())
    timeline = pd.date_range("2025-11-01", origins.max(), freq="5min")
    counts = pd.DataFrame(0, index=timeline, columns=ids, dtype=np.int32)
    history = []
    for chunk in pd.read_csv(workspace / "input/tmp_gantry_trade_info_split1_20251224_7d_hechi_result.csv",
                             encoding="utf-8-sig", dtype=str, usecols=["\u95e8\u67b6id", "\u95e8\u67b6\u65f6\u95f4"], chunksize=200000):
        moments = pd.to_datetime(chunk["\u95e8\u67b6\u65f6\u95f4"], dayfirst=True, errors="raise")
        chunk = chunk.loc[moments.lt(origins.max())].copy()
        history.append(chunk)
        chunk["bucket"] = moments.loc[chunk.index].dt.floor("5min")
        grouped = chunk.groupby(["bucket", "\u95e8\u67b6id"]).size().unstack(fill_value=0)
        counts += grouped.reindex(index=timeline, columns=ids, fill_value=0)
    pd.concat(history, ignore_index=True).drop(columns="bucket", errors="ignore").to_csv(dest / "history.csv", index=False)
    # Match the production/raw-event C-order panel; peer correlations are rounding-sensitive.
    np.save(dest / "panel.npy", np.ascontiguousarray(counts.to_numpy()))
    stages.batch.save(dest / "request.json", {"origins": [str(value) for value in origins], "timeline": [str(value) for value in timeline], "ids": ids,
                                            "training_source": str(workspace / "input") if args.retrain else None})
    expected.to_csv(dest / "expected.csv", index=False)
    probe = '''import json, traceback
from pathlib import Path
import numpy as np
import pandas as pd
result = {"passed": False, "holdout_scored": False}
try:
    import candidate_solution as solution
    def forbidden(*args, **kwargs):
        raise AssertionError("Inference attempted training or final evaluation")
    import lightgbm
    request = json.loads(Path("request.json").read_text())
    model_path = Path("frozen_bundle.joblib")
    if request.get("training_source"):
        dataset = solution.load_fixed_data(Path(request["training_source"]))
        dataset["panel"][dataset["timeline"] >= solution.FIT_END] = 0
        model_path = Path(solution.train(dataset, Path("retrained")))
        del dataset
    solution.train = solution.final_evaluate = forbidden
    lightgbm.LGBMRegressor.fit = forbidden
    history = pd.read_csv("history.csv", dtype=str)
    expected = pd.read_csv("expected.csv", dtype={"gantry_id": str})
    _, raw_timeline, _ = solution._build_panel_from_raw_events(history, request["ids"], request["origins"])
    result.update(raw_timeline_start=str(raw_timeline[0]), panel_timeline_start=request["timeline"][0],
                  max_history_steps=int(solution.MAX_HISTORY_STEPS), bin_minutes=int(solution.BIN_MINUTES))
    keys = ["gantry_id", "forecast_origin", "horizon_minutes"]
    def aligned(frame):
        frame = frame.copy()
        frame["forecast_origin"] = pd.to_datetime(frame["forecast_origin"])
        return frame.set_index(keys)["predicted_count"].sort_index()
    panel = solution.predict(model_path, {"panel": np.load("panel.npy"),
        "timeline": pd.DatetimeIndex(request["timeline"]), "forecast_origins": request["origins"], "gantry_ids": request["ids"]})
    pd.testing.assert_index_equal(aligned(panel).index, aligned(expected).index)
    np.testing.assert_allclose(aligned(panel), aligned(expected), rtol=1e-10, atol=1e-8)
    raw = solution.predict(model_path, {"events": history, "forecast_origins": request["origins"]})
    pd.testing.assert_index_equal(aligned(raw).index, aligned(panel).index)
    result.update(panel_matches_saved_development=True, raw_max_absolute_difference=float(np.max(np.abs(aligned(raw)-aligned(panel)))),
                  requests=len(raw), raw_history_rows=len(history))
    np.testing.assert_allclose(aligned(raw), aligned(panel), rtol=1e-10, atol=1e-8)
    future = history.iloc[:1000].copy()
    future[solution.RAW_TIME] = pd.Timestamp(request["origins"][-1]).strftime("%d/%m/%Y %H:%M:%S")
    guarded = solution.predict(model_path, {
        "events": pd.concat([history, future], ignore_index=True), "forecast_origins": request["origins"]})
    pd.testing.assert_index_equal(aligned(guarded).index, aligned(raw).index)
    np.testing.assert_allclose(aligned(guarded), aligned(raw), rtol=1e-10, atol=1e-8)
    result.update(passed=True, raw_and_panel_equivalent=True, training_forbidden=True, moved_code_and_model=True)
    result.update(forecast_origins=request["origins"], synthetic_future_events_ignored=len(future))
    result.update(retrained_on_training_split_only=bool(request.get("training_source")),
                  training_during_prediction_forbidden=True)
except Exception as exc:
    result.update(error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
Path("inference_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
'''
    guard = WindowsJobMemoryLimiter(4 * 1024**3)
    guard.attach(os.getpid())
    os.environ.update(ALGOEVOLVE_GPU_EXECUTION_SLOTS="2", ALGOEVOLVE_EXECUTION_POOL_PATH=str(stages.batch.OUT / "execution-slots"),
        ALGOEVOLVE_HOST_FREE_RESERVE_GIB="2", ALGOEVOLVE_GPU_FREE_RESERVE_GIB="1", ALGOEVOLVE_TORCH_ALLOCATOR_GUARD="0",
        OMP_NUM_THREADS=str(args.numerical_threads), OPENBLAS_NUM_THREADS=str(args.numerical_threads),
        MKL_NUM_THREADS=str(args.numerical_threads))
    execution = Interpreter(dest, timeout=600 if args.retrain else 120, max_parallel_run=1).run(probe, "inference_probe")
    result = {"node": args.node, "code_sha256": hashlib.sha256(code.encode()).hexdigest(), "execution": execution.to_dict(),
              "inference": stages.read_json(dest / "inference_result.json", {}), "source_model_unchanged": hashlib.sha256(models[0].read_bytes()).hexdigest() == original_hash,
              "scope": "Independent development-model raw-event/aggregated input equivalence. Optional frozen training recipe reproduction; no holdout scoring."}
    result["passed"] = result["source_model_unchanged"] and result["inference"].get("passed") is True
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "passed": result["passed"], "inference": result["inference"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

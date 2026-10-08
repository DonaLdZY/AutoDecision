"""Verify a frozen chemical candidate on raw-history requests in a fresh process."""
from __future__ import annotations

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
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("chemical_inference_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("chemical")
    workspace = Path(task["auto_ml_workspace_dir"])
    node = next(row for row in stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")["nodes"] if row["id"] == args.node)
    assert node.get("search_eligible") and node.get("is_valid") is True
    work = workspace / "node_runs" / args.node / "working"
    models = list(work.glob("model_artifact_*.pkl"))
    assert len(models) == 1
    model = models[0]
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    dest = stages.batch.OUT / "optimization-validation" / f"chemical-inference-{args.node[:8]}-{time.time_ns()}"
    dest.mkdir(parents=True)
    (dest / "candidate_solution.py").write_text(node["code"], encoding="utf-8")
    shutil.copy2(model, dest / "frozen_bundle.pkl")
    samples = pd.read_csv(work / "evaluation_samples.csv")
    selected = samples.loc[samples.split.eq("development")].sort_values("prediction_cutoff")
    high = selected.loc[selected["\u8d85\u5dee"].eq("\u9ad8")]
    selected = pd.concat([selected.iloc[np.linspace(0, len(selected) - 1, 9, dtype=int)], high]).drop_duplicates("label_row_id")
    predictions = pd.read_csv(workspace / "submission" / f"submission_{args.node}.csv").set_index("label_row_id")
    cutoffs = pd.to_datetime(selected.prediction_cutoff)
    windows = [[] for _ in cutoffs]
    source = Path(task["run_dir"]) / "autorealize/\u8bbe\u5907.csv"
    for chunk in pd.read_csv(source, encoding="utf-8-sig", chunksize=50000, low_memory=False):
        timestamps = pd.to_datetime(chunk.SampleTime, format="mixed", errors="raise")
        for index, cutoff in enumerate(cutoffs):
            subset = chunk.loc[timestamps.gt(cutoff - pd.Timedelta(minutes=60)) & timestamps.le(cutoff)]
            if len(subset):
                windows[index].append(subset)
    requests = []
    for index, (label, cutoff) in enumerate(zip(selected.label_row_id, cutoffs)):
        history = pd.concat(windows[index], ignore_index=True)
        assert 46 <= len(history) <= 61
        history.to_pickle(dest / f"history-{index}.pkl")
        requests.append({"history": f"history-{index}.pkl", "prediction_cutoff": str(cutoff),
                         "expected": float(predictions.loc[label, "y_pred"])})
    stages.batch.save(dest / "requests.json", requests)
    code = '''import json, traceback
from pathlib import Path
import numpy as np
import pandas as pd
result = {"passed": False, "holdout_scored": False}
try:
    import candidate_solution as solution
    from catboost import CatBoostRegressor
    def forbidden(*args, **kwargs):
        raise AssertionError("Inference attempted fitting, evaluation or label loading")
    for name in ("train", "final_evaluate", "build_evaluation_data", "fit_catboost_mae", "fit_multiscale_preprocessor"):
        if hasattr(solution, name):
            setattr(solution, name, forbidden)
    CatBoostRegressor.fit = forbidden
    pd.read_excel = forbidden
    requests = json.loads(Path("requests.json").read_text(encoding="utf-8"))
    observed, expected = [], []
    for request in requests:
        history = pd.read_pickle(request["history"])
        query = {"prediction_cutoff": request["prediction_cutoff"], "history": history}
        prediction = solution.predict(Path("frozen_bundle.pkl"), query)
        assert list(prediction.columns) == ["prediction_cutoff", "y_pred"] and len(prediction) == 1
        assert pd.Timestamp(prediction.iloc[0].prediction_cutoff) == pd.Timestamp(query["prediction_cutoff"])
        observed.append(float(prediction.iloc[0].y_pred))
        expected.append(request["expected"])
    np.testing.assert_allclose(observed, expected, rtol=1e-10, atol=1e-9)
    history = pd.read_pickle(requests[0]["history"])
    query = {"prediction_cutoff": requests[0]["prediction_cutoff"], "history": history}
    invalid = [
        ("missing_field", {**query, "history": history.iloc[:, :-1]}),
        ("extra_field", {**query, "history": history.assign(extra=0)}),
        ("reordered_schema", {**query, "history": history.iloc[:, ::-1]}),
        ("label", {**query, "history": history.assign(label_row_id="forbidden")}),
        ("empty_history", {**query, "history": history.iloc[:0]}),
        ("invalid_cutoff", {**query, "prediction_cutoff": "invalid"}),
    ]
    rejected = []
    for name, request in invalid:
        try:
            solution.predict(Path("frozen_bundle.pkl"), request)
        except (ValueError, RuntimeError):
            rejected.append(name)
        else:
            raise AssertionError("Invalid inference input was accepted: " + name)
    changed = history.copy()
    for column in changed.columns[1:]:
        changed[column] = pd.to_numeric(changed[column], errors="raise") * 1.75
    altered = solution.predict(Path("frozen_bundle.pkl"), {**query, "history": changed})
    assert np.isfinite(altered.y_pred).all() and abs(float(altered.y_pred.iloc[0]) - observed[0]) > 1e-9
    result.update(passed=True, requests=len(requests), source_predictions_reproduced=True,
                  max_absolute_difference=float(np.max(np.abs(np.array(observed)-expected))),
                  raw_history_consumed=True, training_during_prediction_forbidden=True,
                  moved_code_and_model=True, rejected=rejected)
except Exception as exc:
    result.update(error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
Path("inference_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
'''
    guard = WindowsJobMemoryLimiter(4 * 1024**3)
    guard.attach(os.getpid())
    os.environ.update(ALGOEVOLVE_GPU_EXECUTION_SLOTS="2",
        ALGOEVOLVE_EXECUTION_POOL_PATH=str(stages.batch.OUT / "execution-slots"),
        ALGOEVOLVE_HOST_FREE_RESERVE_GIB="2", ALGOEVOLVE_GPU_FREE_RESERVE_GIB="1",
        ALGOEVOLVE_TORCH_ALLOCATOR_GUARD="0")
    runner = Interpreter(dest, timeout=180, max_parallel_run=1)
    execution = runner.run(code, "inference_probe")
    result = {"node": args.node, "execution": execution.to_dict(),
              "inference": stages.read_json(dest / "inference_result.json", {}),
              "source_model_unchanged": hashlib.sha256(model.read_bytes()).hexdigest() == digest,
              "scope": "Frozen development model on independent raw-history requests in a fresh process; not final evaluation"}
    result["passed"] = result["source_model_unchanged"] and result["inference"].get("passed") is True
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

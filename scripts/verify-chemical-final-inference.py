"""Verify the frozen chemical export and its default retraining API in isolation."""
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
    parser.add_argument("--retrain", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("chemical_final_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("chemical")
    stages.verified_search_seconds(task)
    assert task["status"] == "completed"
    workspace = Path(task["auto_ml_workspace_dir"])
    final, exported = workspace / "final_evaluation", workspace / "best_solution"
    state, final_result = stages.read_json(final / "status.json"), stages.read_json(final / "result.json")
    assert state["status"] == final_result["status"] == "completed"
    node_id = state["selection"]["node_id"]
    manifest = stages.read_json(exported / "solution_manifest.json")
    assert manifest["node_id"] == node_id
    implementation = exported / manifest["implementation_path"]
    model_relative = (exported / "model_path.txt").read_text(encoding="utf-8").strip()
    source_model = (exported / model_relative).resolve()
    frozen_model = final / "artifacts" / final_result["model_path"]
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert source_model.is_relative_to(exported.resolve())
    assert digest(source_model) == digest(frozen_model)
    assert digest(implementation) == manifest["implementation_file_sha256"]
    dest = stages.batch.OUT / "optimization-validation" / f"chemical-final-{'retraining' if args.retrain else 'inference'}-{time.time_ns()}"
    moved = dest / "moved_export"
    moved.mkdir(parents=True)
    for relative in ("solution.py", manifest["implementation_path"], "model_path.txt", "solution_manifest.json", model_relative):
        source, target = exported / relative, moved / relative
        assert source.resolve().is_relative_to(exported.resolve()) and target.resolve().is_relative_to(moved.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    work = workspace / "node_runs" / node_id / "working" if args.retrain else final / "artifacts"
    samples = pd.read_csv(work / "evaluation_samples.csv")
    selected = samples.loc[samples.split.eq("development" if args.retrain else "holdout")].sort_values("prediction_cutoff")
    selected = selected.iloc[np.linspace(0, len(selected) - 1, 12, dtype=int)].copy()
    predictions = pd.read_csv(work / ("development_prediction_frame.csv" if args.retrain else "holdout_prediction_frame.csv")).set_index("label_row_id")
    cutoffs = pd.to_datetime(selected.prediction_cutoff)
    windows = [[] for _ in cutoffs]
    for chunk in pd.read_csv(workspace / "input/设备.csv", encoding="utf-8-sig", chunksize=50000, low_memory=False):
        moments = pd.to_datetime(chunk.SampleTime, format="mixed", errors="raise")
        for index, cutoff in enumerate(cutoffs):
            subset = chunk.loc[moments.gt(cutoff - pd.Timedelta(minutes=60)) & moments.le(cutoff)]
            if len(subset):
                windows[index].append(subset)
    requests = []
    for index, (row_id, cutoff) in enumerate(zip(selected.label_row_id, cutoffs)):
        history = pd.concat(windows[index], ignore_index=True)
        assert 46 <= len(history) <= 61
        history.to_pickle(moved / f"history-{index}.pkl")
        requests.append({"history": f"history-{index}.pkl", "prediction_cutoff": str(cutoff),
                         "expected": float(predictions.loc[row_id, "y_pred"])})
    stages.batch.save(moved / "probe_config.json", {"requests": requests,
        "training_source": str(workspace / "input") if args.retrain else None,
        "training_labels": sorted(samples.loc[samples.split.eq("train"), "y_true"].tolist()) if args.retrain else None})
    probe = '''import json, traceback
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
result={"passed":False,"final_evaluation_repeated":False}
try:
    import solution
    from catboost import CatBoostRegressor
    implementation=solution._implementation
    config=json.loads(Path("probe_config.json").read_text(encoding="utf-8"))
    def forbidden(*args,**kwargs):
        raise AssertionError("Attempted fitting or final evaluation outside the requested verification")
    implementation.final_evaluate=forbidden
    model=solution.default_model_path()
    initial=joblib.load(model)
    if config["training_source"]:
        fit=implementation._fit_catboost
        clip=implementation._fit_robust_clipper
        fit_counts=[]
        clip_counts=[]
        def checked_fit(X,y):
            assert len(X)==len(y)==914
            np.testing.assert_allclose(np.sort(y),config["training_labels"],rtol=0,atol=1e-12)
            fit_counts.append(len(y))
            return fit(X,y)
        def checked_clip(X,names):
            assert len(X)==914
            clip_counts.append(len(X))
            return clip(X,names)
        implementation._fit_catboost=checked_fit
        implementation._fit_robust_clipper=checked_clip
        model=solution.train(Path(config["training_source"]),Path("retrained"))
        restored=joblib.load(model)
        assert fit_counts==clip_counts==[914]
        assert restored["model_config"]==initial["model_config"]
        assert restored["feature_config"]==initial["feature_config"]
        result.update(retrained_on_training_split_only=True,training_rows=914,preprocessor_fit_rows=914,
            hyperparameters_unchanged=True,default_public_training_api=True)
    for name in ("train","_fit_catboost","_fit_robust_clipper","_prepare_dataset","_read_label_source"):
        setattr(implementation,name,forbidden)
    CatBoostRegressor.fit=forbidden
    pd.read_excel=forbidden
    actual=[]
    for request in config["requests"]:
        history=pd.read_pickle(request["history"])
        observed=np.asarray(solution.predict(model,{"prediction_cutoff":request["prediction_cutoff"],"history":history}))
        assert observed.shape==(1,) and np.isfinite(observed).all()
        actual.append(float(observed[0]))
    expected=np.array([request["expected"] for request in config["requests"]])
    np.testing.assert_allclose(actual,expected,rtol=1e-10,atol=1e-9)
    first=config["requests"][0]
    history=pd.read_pickle(first["history"])
    query={"prediction_cutoff":first["prediction_cutoff"],"history":history}
    rejected=[]
    for name,bad in (("missing_field",history.iloc[:,:-1]),("extra_field",history.assign(extra=0)),
        ("reordered_schema",history.iloc[:,::-1]),("label_column",history.assign(label_row_id="forbidden")),
        ("empty_history",history.iloc[:0])):
        try:
            solution.predict(model,{**query,"history":bad})
        except (ValueError,RuntimeError):
            rejected.append(name)
        else:
            raise AssertionError("Invalid schema accepted: "+name)
    changed=history.copy()
    for column in changed.columns[1:]:
        changed[column]=pd.to_numeric(changed[column],errors="raise")*1.75
    altered=np.asarray(solution.predict(model,{**query,"history":changed}))
    assert np.isfinite(altered).all() and abs(float(altered[0])-actual[0])>1e-9
    future=history.iloc[:1].copy()
    future["SampleTime"]=(pd.Timestamp(first["prediction_cutoff"])+pd.Timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        solution.predict(model,{**query,"history":pd.concat([history,future],ignore_index=True)})
    except (ValueError,RuntimeError):
        rejected.append("future_history")
    else:
        raise AssertionError("Future history must be rejected by the frozen API")
    result.update(passed=True,requests=len(actual),moved_public_api_and_model=True,raw_history_consumed=True,
        predictions_match_frozen_outputs=True,max_absolute_difference=float(np.max(np.abs(actual-expected))),
        training_during_prediction_forbidden=True,rejected=rejected,future_rows_rejected=True,
        no_original_workspace_supplied=not bool(config["training_source"]))
except Exception as exc:
    result.update(error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
Path("inference_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False))
'''
    os.environ.update(ALGOEVOLVE_GPU_EXECUTION_SLOTS="2", ALGOEVOLVE_EXECUTION_POOL_PATH=str(stages.batch.OUT / "execution-slots"),
        ALGOEVOLVE_HOST_FREE_RESERVE_GIB="2", ALGOEVOLVE_GPU_FREE_RESERVE_GIB="1", ALGOEVOLVE_TORCH_ALLOCATOR_GUARD="0")
    guard = WindowsJobMemoryLimiter(6 * 1024**3)
    guard.attach(os.getpid())
    execution = Interpreter(moved, timeout=300, max_parallel_run=1).run(probe, "chemical_final_probe")
    result = {"slug": "chemical", "node": node_id, "export_dir": str(exported),
        "implementation_sha256": digest(implementation), "model_sha256": digest(frozen_model),
        "execution": execution.to_dict(), "inference": stages.read_json(moved / "inference_result.json", {}),
        "scope": "Copied frozen public API/model and independent raw requests; optional default train uses914training rows only"}
    result["passed"] = result["inference"].get("passed") is True and digest(source_model) == result["model_sha256"]
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "passed": result["passed"], "inference": result["inference"]}, ensure_ascii=False))
    if not result["passed"]:
        raise RuntimeError("Independent chemical export verification failed")


if __name__ == "__main__":
    main()

"""Move only the final public API and model into a fresh process and verify outputs."""
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
    import pandas as pd
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", choices=("traffic", "deposition"), required=True)
    parser.add_argument("--export-dir", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("final_inference_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task(args.slug)
    stages.verified_search_seconds(task)
    if task["status"] == "running":
        raise RuntimeError("Wait for final service execution to finish")
    workspace = Path(task["auto_ml_workspace_dir"])
    final = workspace / "final_evaluation"
    state, final_result = stages.read_json(final / "status.json"), stages.read_json(final / "result.json")
    assert state["status"] == final_result["status"] == "completed"
    exported = args.export_dir or workspace / "best_solution"
    manifest = stages.read_json(exported / "solution_manifest.json")
    implementation = exported / manifest["implementation_path"]
    model_relative = (exported / "model_path.txt").read_text(encoding="utf-8").strip()
    source_model = (exported / model_relative).resolve()
    assert source_model.is_relative_to(exported.resolve())
    frozen_model = final / "artifacts" / final_result["model_path"]
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest(source_model) == digest(frozen_model)
    assert digest(implementation) == manifest["implementation_file_sha256"]
    dest = stages.batch.OUT / "optimization-validation" / f"{args.slug}-final-inference-{time.time_ns()}"
    moved = dest / "moved_export"
    moved.mkdir(parents=True)
    for relative in ("solution.py", manifest["implementation_path"], "model_path.txt", "solution_manifest.json", model_relative):
        source, target = exported / relative, moved / relative
        assert source.resolve().is_relative_to(exported.resolve()) and target.resolve().is_relative_to(moved.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if args.slug == "traffic":
        predictions = pd.read_csv(final / "artifacts/final_evaluation/holdout_predictions.csv", dtype={"gantry_id": str})
        origins = ["2025-11-07 00:00:00", "2025-11-07 11:30:00", "2025-11-07 23:00:00"]
        selected = predictions.loc[pd.to_datetime(predictions["forecast_origin"]).isin(pd.DatetimeIndex(origins))]
        assert len(selected) == 954
        history_path = moved / "history.csv"
        for chunk in pd.read_csv(workspace / "input/tmp_gantry_trade_info_split1_20251224_7d_hechi_result.csv",
                                 dtype=str, usecols=["\u95e8\u67b6id", "\u95e8\u67b6\u65f6\u95f4"], chunksize=200000):
            moments = pd.to_datetime(chunk["\u95e8\u67b6\u65f6\u95f4"], dayfirst=True, errors="raise")
            chunk = chunk.loc[moments.lt(origins[-1])]
            chunk.to_csv(history_path, index=False, mode="a", header=not history_path.exists())
        config = {"slug": args.slug, "origins": origins}
    else:
        predictions = pd.read_csv(final / "artifacts/final_holdout_predictions.csv")
        selected = predictions.groupby(["strategy", "zone"], sort=False).head(2).reset_index(drop=True)
        assert len(selected) == 384
        selected.drop(columns="y_pred").assign(layer_scope="top_layer").to_csv(moved / "requests.csv", index=False)
        config = {"slug": args.slug}
    selected.to_csv(moved / "expected.csv", index=False)
    stages.batch.save(moved / "probe_config.json", config)
    probe = '''import json,traceback
from pathlib import Path
import numpy as np
import pandas as pd
result={"passed":False,"training_executed":False,"final_evaluation_repeated":False}
try:
    import solution
    model=solution.default_model_path()
    config=json.loads(Path("probe_config.json").read_text())
    def forbidden(*args,**kwargs):
        raise AssertionError("Prediction attempted fitting, final evaluation or original-data loading")
    implementation=solution._implementation
    for name in ("train","final_evaluate","build_dataset","load_fixed_data","_fit_artifact","fit_models"):
        if hasattr(implementation,name):
            setattr(implementation,name,forbidden)
    if config["slug"]=="traffic":
        import lightgbm
        lightgbm.LGBMRegressor.fit=forbidden
        history=pd.read_csv("history.csv",dtype=str)
        expected=pd.read_csv("expected.csv",dtype={"gantry_id":str})
        observed=solution.predict(model,{"events":history,"forecast_origins":config["origins"]})
        def align(frame):
            frame=frame.copy()
            frame["forecast_origin"]=pd.to_datetime(frame["forecast_origin"])
            return frame.set_index(["gantry_id","forecast_origin","horizon_minutes"])["predicted_count"].sort_index()
        actual,reference=align(observed),align(expected)
        pd.testing.assert_index_equal(actual.index,reference.index)
        np.testing.assert_allclose(actual,reference,rtol=1e-10,atol=1e-8)
        result.update(requests=len(observed),history_rows=len(history),raw_event_predictions_match_frozen_final=True)
    else:
        request=pd.read_csv("requests.csv")
        expected=pd.read_csv("expected.csv")["y_pred"].to_numpy()
        observed=np.asarray(solution.predict(model,request))
        np.testing.assert_allclose(observed,expected,rtol=1e-10,atol=1e-8)
        changed=request.copy()
        changed["time_s"]+=20
        altered=np.asarray(solution.predict(model,changed))
        assert np.isfinite(altered).all() and not np.allclose(observed,altered)
        rejected=[]
        for name,invalid in (("label",request.assign(y_true=1)),("layer",request.assign(layer_scope="unknown")),
                             ("duplicate",pd.concat([request,request.iloc[:1]],ignore_index=True))):
            try:
                solution.predict(model,invalid)
            except (RuntimeError,ValueError):
                rejected.append(name)
            else:
                raise AssertionError("Invalid input accepted: "+name)
        result.update(requests=len(request),new_time_consumed=True,rejected=rejected)
    result.update(passed=True,moved_public_api_and_model=True,no_original_workspace_supplied=True)
except Exception as exc:
    result.update(error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
Path("inference_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False))
'''
    os.environ.update(ALGOEVOLVE_GPU_EXECUTION_SLOTS="2", ALGOEVOLVE_EXECUTION_POOL_PATH=str(stages.batch.OUT / "execution-slots"),
                      ALGOEVOLVE_HOST_FREE_RESERVE_GIB="2", ALGOEVOLVE_GPU_FREE_RESERVE_GIB="1", ALGOEVOLVE_TORCH_ALLOCATOR_GUARD="0")
    guard = WindowsJobMemoryLimiter(4 * 1024**3)
    guard.attach(os.getpid())
    execution = Interpreter(moved, timeout=180, max_parallel_run=1).run(probe, "final_inference_probe")
    result = {"slug": args.slug, "node": state["selection"]["node_id"], "export_dir": str(exported),
              "implementation_sha256": digest(implementation), "model_sha256": digest(frozen_model),
              "execution": execution.to_dict(), "inference": stages.read_json(moved / "inference_result.json", {}),
              "scope": "Independent moved final API/model predictions compared with frozen final outputs; no fitting or repeated final evaluation"}
    result["passed"] = result["inference"].get("passed") is True and digest(source_model) == result["model_sha256"]
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "passed": result["passed"], "inference": result["inference"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

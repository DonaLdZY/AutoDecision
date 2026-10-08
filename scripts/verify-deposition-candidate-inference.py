"""Exercise a saved development model in a fresh, isolated process without labels."""
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
    parser.add_argument("--node", required=True)
    parser.add_argument("--retrain", action="store_true")
    parser.add_argument("--retrain-from-source", action="store_true")
    parser.add_argument("--numerical-threads", type=int, default=2)
    parser.add_argument("--reload-from", type=Path)
    args = parser.parse_args()
    if args.retrain_from_source and not args.retrain:
        parser.error("--retrain-from-source requires --retrain")
    spec = importlib.util.spec_from_file_location("deposition_inference_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("deposition")
    workspace = Path(task["auto_ml_workspace_dir"])
    node = next(row for row in stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")["nodes"] if row["id"] == args.node)
    if not node.get("search_eligible"):
        raise RuntimeError("Select an accepted development candidate")
    work = workspace / "node_runs" / args.node
    models = list((work / "working").glob("model_artifact_*.pkl"))
    if len(models) != 1:
        raise RuntimeError("Model artifact is ambiguous")
    model = models[0]
    if args.reload_from:
        previous = stages.read_json(args.reload_from / "result.json", {})
        if (args.retrain or previous.get("passed") is not True or previous.get("node") != args.node
                or (args.reload_from / "candidate_solution.py").read_text(encoding="utf-8") != node["code"]):
            raise RuntimeError("Reload requires this exact candidate's successful training-only reproduction")
        model = args.reload_from / "retrained/model_artifact.pkl"
    before = hashlib.sha256(model.read_bytes()).hexdigest()
    dest = stages.batch.OUT / "optimization-validation" / f"deposition-inference-{args.node[:8]}-{time.time_ns()}"
    dest.mkdir(parents=True)
    (dest / "candidate_solution.py").write_text(node["code"], encoding="utf-8")
    shutil.copy2(model, dest / "frozen_bundle.pkl")
    predictions = pd.read_csv(work / "submission" / f"submission_{args.node}.csv")
    selected = predictions.groupby(["strategy", "zone"], sort=False).head(2).reset_index(drop=True)
    requests = selected.drop(columns="y_pred").assign(layer_scope="top_layer")
    requests.to_csv(dest / "requests.csv", index=False)
    selected[["y_pred"]].to_csv(dest / "expected.csv", index=False)
    if args.retrain:
        train = []
        for chunk in pd.read_csv(work / "working/scoring_units.csv", chunksize=50000, dtype={"time_key": str}, float_precision="round_trip"):
            # The public train API validates the complete split domain. Keep
            # its keys but replace every nontraining target before the child.
            chunk.loc[~chunk["split"].eq("train"), "y_true"] = 0.0
            train.append(chunk)
        pd.concat(train, ignore_index=True).to_csv(dest / "training_population.csv", index=False)
    code = '''import json, traceback
from pathlib import Path
import numpy as np
import pandas as pd
result = {"passed": False, "holdout_scored": False}
try:
    import candidate_solution as solution
    config = json.loads(Path("probe_config.json").read_text())
    retrain = config["retrain"]
    frozen_path = Path("frozen_bundle.pkl")
    if retrain:
        if config.get("training_source"):
            train, _ = solution.build_dataset(Path(config["training_source"]))
            train.loc[~train["split"].eq("train"), "y_true"] = 0.0
        else:
            train = pd.read_csv("training_population.csv", dtype={"time_key": str}, float_precision="round_trip")
        assert train.loc[~train["split"].eq("train"), "y_true"].eq(0.0).all()
        frozen_path = Path(solution.train(train, Path("retrained")))
    def forbidden(*args, **kwargs):
        raise AssertionError("Inference attempted training, final evaluation or original-data loading")
    for name in ("train", "final_evaluate", "build_dataset", "_fit_artifact", "_fit_ridge_model", "_calibrate_tail_weight"):
        if hasattr(solution, name):
            setattr(solution, name, forbidden)
    request = pd.read_csv("requests.csv")
    expected = pd.read_csv("expected.csv")["y_pred"].to_numpy()
    observed = np.asarray(solution.predict(frozen_path, request))
    np.testing.assert_allclose(observed, expected, rtol=1e-10, atol=1e-8)
    changed = request.copy()
    changed["time_s"] = pd.to_numeric(changed["time_s"]) + 20.0
    changed["evaluation_row_id"] = "fixture-" + changed["evaluation_row_id"].astype(str)
    altered = np.asarray(solution.predict(frozen_path, changed))
    assert np.isfinite(altered).all() and not np.allclose(altered, observed)
    rejected = []
    for name, invalid in (("label", request.assign(y_true=1.0)),
                          ("layer", request.assign(layer_scope="unknown")),
                          ("duplicate_key", pd.concat([request, request.iloc[:1]], ignore_index=True))):
        try:
            solution.predict(frozen_path, invalid)
        except (ValueError, RuntimeError):
            rejected.append(name)
        else:
            raise AssertionError("Invalid input accepted: " + name)
    empty = np.asarray(solution.predict(frozen_path, request.iloc[:0]))
    assert empty.size == 0
    result.update(passed=True, requests=len(request), moved_code_and_model=True,
                  source_predictions_reproduced=True, new_time_consumed=True,
                  training_during_prediction_forbidden=True, rejected=rejected, empty_supported=True,
                  retrained_on_training_split_only=retrain,
                  original_search_artifact_loaded=not retrain and not config["reload_from"],
                  independent_retrained_artifact_reload=bool(config["reload_from"]))
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
        ALGOEVOLVE_TORCH_ALLOCATOR_GUARD="0", OMP_NUM_THREADS=str(args.numerical_threads),
        OPENBLAS_NUM_THREADS=str(args.numerical_threads), MKL_NUM_THREADS=str(args.numerical_threads))
    stages.batch.save(dest / "probe_config.json", {"retrain": args.retrain, "reload_from": str(args.reload_from) if args.reload_from else None,
                                                  "training_source": str(workspace / "input") if args.retrain_from_source else None})
    runner = Interpreter(dest, timeout=180, max_parallel_run=1)
    execution = runner.run(code, "inference_probe")
    result = {"node": args.node, "execution": execution.to_dict(),
              "inference": stages.read_json(dest / "inference_result.json", {}),
              "source_model_unchanged": hashlib.sha256(model.read_bytes()).hexdigest() == before,
              "scope": "Saved development model portability and synthetic input-sensitivity checks, not final model or future business effect"}
    result["passed"] = result["source_model_unchanged"] and result["inference"].get("passed") is True
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

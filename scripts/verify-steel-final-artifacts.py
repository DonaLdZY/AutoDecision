"""Verify the frozen steel model, final scores, training-only blend and portable APIs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from agents.prompt_policy import method_family_for_node
from engine.search_node import Journal
from engine.solution_package import package_final_solution
from utils.resource_limits import WindowsJobMemoryLimiter
from utils.serialize import load_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    import psutil
    if psutil.virtual_memory().available < 13 * 1024 ** 3:
        raise RuntimeError("Verification requires at least 13 GiB free memory")
    limiter = WindowsJobMemoryLimiter(4 * 1024 ** 3)
    limiter.attach(os.getpid())
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[:4])
    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4",
                      MKL_NUM_THREADS="4", PYTHONUTF8="1")
    import numpy as np
    import pandas as pd

    task = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["steel"]
    workspace, logs = Path(task["auto_ml_workspace_dir"]), Path(task["auto_ml_log_dir"])
    final = workspace / "final_evaluation"
    state = json.loads((final / "status.json").read_text(encoding="utf-8"))
    result = json.loads((final / "result.json").read_text(encoding="utf-8"))
    assert state["status"] == result["status"] == "completed"
    journal = load_json(logs / "journal.json", Journal)
    node = next(node for node in journal.nodes if node.id == state["selection"]["node_id"])
    assert node.id == "d37ff52bb9ff4782bec6aefcf8ede5c0" and node.search_eligible
    search_state = json.loads((logs / "search_state.json").read_text(encoding="utf-8"))
    assert search_state["cumulative_search_elapsed_seconds"] >= 10800
    working = workspace / "node_runs" / node.id / "working"
    recipe = json.loads((working / "selected_recipe.json").read_text(encoding="utf-8"))
    weights = recipe["ensemble_metadata"]["weights"]
    assert weights == result["metrics"]["ensemble"]["weights"] == [0.65, 0.2, 0.15]
    assert result["metrics"]["ensemble"]["weight_selection_mode"] == "locked_from_selected_recipe"
    source_path = workspace / "input/Steel_industry_data.csv"
    source = pd.read_csv(source_path)
    source["parsed_time"] = pd.to_datetime(source["date"], format="%d/%m/%Y %H:%M")
    source = source.sort_values("parsed_time", kind="stable").reset_index(drop=True)
    immutable = {path: digest(path) for path in (logs / "journal.json", logs / "search_state.json", source_path,
                 final / "artifacts" / result["model_path"])}
    development = pd.read_csv(working / "validation_predictions.csv")
    holdout = pd.read_csv(final / "artifacts/holdout_predictions.csv")
    score_checks = {}
    for phase, predictions, start, end in (("development", development, 21024, 28032),
                                         ("holdout", holdout, 28032, 35040)):
        assert len(predictions) == 7008
        expected = source.iloc[start:end]
        times = pd.to_datetime(predictions["timestamp"], format="%d/%m/%Y %H:%M")
        np.testing.assert_array_equal(times, expected["parsed_time"])
        np.testing.assert_array_equal(predictions["y_true_Usage_kWh"], expected["Usage_kWh"])
        np.testing.assert_array_equal(predictions["persistence_prediction_Usage_kWh"], source["Usage_kWh"].iloc[start-1:end-1])
        np.testing.assert_array_equal(predictions["previous_day_seasonal_prediction_Usage_kWh"], source["Usage_kWh"].iloc[start-96:end-96])
        metrics = {}
        for name, column in (("candidate", "candidate_prediction_Usage_kWh"),
                             ("persistence", "persistence_prediction_Usage_kWh"),
                             ("previous_day", "previous_day_seasonal_prediction_Usage_kWh")):
            values = predictions[column].to_numpy()
            assert np.isfinite(values).all()
            errors = values - expected["Usage_kWh"].to_numpy()
            daily = pd.Series(errors, index=pd.DatetimeIndex(times)).groupby(pd.DatetimeIndex(times).normalize()).sum()
            metrics[name] = {"mae": float(np.abs(errors).mean()), "rmse": float(np.sqrt(np.mean(errors ** 2))),
                             "daily_aggregate_mae": float(daily.abs().mean())}
        score_checks[phase] = metrics
    np.testing.assert_allclose(score_checks["development"]["candidate"]["mae"], node.metric.value, rtol=0, atol=1e-12)
    np.testing.assert_allclose(score_checks["holdout"]["candidate"]["mae"], result["metrics"]["candidate_metrics"]["MAE_kWh"], rtol=0, atol=1e-12)

    oof = pd.read_csv(working / "search_artifact/oof_predictions.csv")
    rows = oof["training_matrix_row"].to_numpy(dtype=int)
    assert rows.min() >= 0 and rows.max() + 2016 < 21024 and len(np.unique(rows)) == len(rows) == 7603
    y = source["Usage_kWh"].to_numpy()[rows + 2016].astype(np.float32).astype(float)
    np.testing.assert_allclose(oof["y_true_Usage_kWh"], y, rtol=0, atol=1e-10)
    members = oof[["primary_prediction_Usage_kWh", "seasonal_prediction_Usage_kWh", "l2_prediction_Usage_kWh"]].to_numpy()
    np.testing.assert_allclose(members @ weights, oof["ensemble_prediction_Usage_kWh"], rtol=0, atol=1e-10)
    grid = [(float(np.abs(members @ np.array([a, b, 20-a-b]) / 20 - y).mean()), (a / 20, b / 20, (20-a-b) / 20))
            for a in range(21) for b in range(21-a)]
    best_score, best_weights = min(grid)
    np.testing.assert_allclose(best_weights, weights, rtol=0, atol=1e-12)
    folds = recipe["ensemble_metadata"]["oof_folds"]
    assert all(fold["train_end_row_exclusive"] == fold["validation_start_row"]
               and fold["validation_end_row_exclusive"] + 2016 <= 21024 for fold in folds)

    destination = OUT / "optimization-validation" / f"steel-final-artifacts-{time.time_ns()}"
    destination.mkdir(parents=True)
    source.drop(columns="parsed_time").iloc[:21024].to_csv(destination / "fit.csv", index=False)
    source.drop(columns="parsed_time").iloc[:28032].to_csv(destination / "development_history.csv", index=False)
    source.drop(columns="parsed_time").iloc[-2016:].to_csv(destination / "future_history.csv", index=False)
    save(destination / "expected.json", {"weights": weights,
         "predictions": [{"position": pos, "value": float(development["candidate_prediction_Usage_kWh"].iloc[pos])}
                         for pos in (0, 95, 3504, 7007)]})
    exported = workspace / "best_solution"
    unpackaged = destination / "unpackaged"
    unpackaged.mkdir()
    shutil.copy2(exported / "solution.py", unpackaged / "solution.py")
    model_path = exported / (exported / "model_path.txt").read_text(encoding="utf-8").strip()
    probe = subprocess.run([sys.executable, "-c",
        "import solution; solution.predict(" + repr(str(model_path)) + ", " + repr(str(destination / "future_history.csv")) + ")"],
        cwd=unpackaged, capture_output=True, text=True, encoding="utf-8", timeout=30)
    save(destination / "unpackaged-probe.json", {"returncode": probe.returncode, "stderr": probe.stderr,
         "scope": "Actual pre-package copied-code inference attempt, no training or final evaluation."})
    package_final_solution(workspace, state)
    manifest_path = exported / "solution_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(method_family=method_family_for_node(node, task_family="prediction"),
                    historical_method_family=node.method_family, method_family_evidence="generated_code_structure")
    save(manifest_path, manifest)
    shutil.copytree(exported, destination / "exported_solution")

    child = """import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm
sys.path.insert(0, str(Path('exported_solution').resolve()))
import solution
implementation = solution._implementation
def forbidden(*args, **kwargs):
    raise AssertionError('Inference attempted training or final evaluation')
implementation.final_evaluate = forbidden
original_fit = lightgbm.LGBMRegressor.fit
original_train = implementation.train
lightgbm.LGBMRegressor.fit = forbidden
implementation.train = forbidden
history = pd.read_csv('future_history.csv')
model = solution.default_model_path()
artifact = implementation._load_artifact(model)
assert artifact['training_rows'] == 35040
expected = json.loads(Path('expected.json').read_text())
assert artifact['ensemble_weights'] == expected['weights']
prediction = np.asarray(solution.predict(model, history))
assert prediction.shape == (1,) and np.isfinite(prediction).all()
changed = history.copy()
changed.loc[changed.index[-96:], 'Usage_kWh'] += 20
new_prediction = np.asarray(solution.predict(model, changed))
assert np.isfinite(new_prediction).all() and not np.allclose(new_prediction, prediction)
invalid = history.copy()
invalid.loc[invalid.index[-1], 'date'] = invalid.iloc[-2]['date']
try:
    solution.predict(model, invalid)
except ValueError:
    pass
else:
    raise AssertionError('Duplicate history timestamps accepted')
lightgbm.LGBMRegressor.fit = original_fit
implementation.train = original_train
started = time.monotonic()
retrained = Path(solution.train(Path('fit.csv'), Path('retrained')))
retrained_artifact = implementation._load_artifact(retrained)
assert retrained_artifact['training_rows'] == 21024
assert retrained_artifact['ensemble_weights'] == expected['weights']
lightgbm.LGBMRegressor.fit = forbidden
implementation.train = forbidden
development_history = pd.read_csv('development_history.csv')
for check in expected['predictions']:
    end = 21024 + check['position']
    value = float(solution.predict(retrained, development_history.iloc[end-2016:end])[0])
    np.testing.assert_allclose(value, check['value'], rtol=0, atol=1e-10)
    check['retrained_prediction'] = value
checks = {'passed': True, 'fresh_process': True, 'moved_export': True,
          'final_full_history_training_rows': 35040, 'frozen_weights': artifact['ensemble_weights'],
          'next_timestamp': '2019-01-01T00:00:00', 'next_prediction': float(prediction[0]),
          'changed_history_prediction': float(new_prediction[0]), 'duplicate_time_rejected': True,
          'fit_forbidden_during_inference': True, 'default_train_reproduced': True,
          'default_train_rows': 21024, 'development_checks': expected['predictions'],
          'retraining_seconds': time.monotonic() - started, 'final_evaluation_repeated': False,
          'changed_history_scope': 'Software fixture only, not a measured business forecast.'}
Path('inference-and-retraining.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
print(json.dumps(checks))
"""
    execution = subprocess.run([sys.executable, "-c", child], cwd=destination, capture_output=True, text=True,
                               encoding="utf-8", timeout=300)
    (destination / "execution.log").write_text(execution.stdout + execution.stderr, encoding="utf-8")
    if execution.returncode:
        raise RuntimeError(execution.stdout + execution.stderr)
    assert all(digest(path) == checksum for path, checksum in immutable.items())
    verification = {"passed": True, "node_id": node.id, "scores": score_checks,
        "search_elapsed_seconds": search_state["cumulative_search_elapsed_seconds"],
        "search_and_final_model_bytes_unchanged": True,
        "training_only_oof": {"rows": len(rows), "weight_grid_size": len(grid), "weights": weights,
                              "independently_selected_oof_mae": best_score, "folds": folds},
        "method_family": manifest["method_family"], "historical_method_family": node.method_family,
        "fusion_operator_nodes": [n.id for n in journal.nodes if n.stage in {"fusion", "fusion_draft"}],
        "ensemble_scope": "Three trained LightGBM members with fit-only OOF weights, introduced by improve nodes. No cross-branch Fusion operator ran.",
        "inference_and_retraining": json.loads((destination / "inference-and-retraining.json").read_text(encoding="utf-8")),
        "resource_guard": limiter.describe(), "peak_memory_bytes": limiter.peak_memory_bytes(),
        "limitations": ["The same holdout was exposed by a rejected earlier trial; not a newly unseen external test.",
                        "Daily aggregate error remains worse than persistence; primary MAE is the frozen ranking metric."],
        "evidence_directory": str(destination)}
    save(destination / "result.json", verification)
    save(exported / "inference-verification.json", verification)
    save(final / "independent-verification.json", verification)
    state["independent_verification"] = "passed"
    state["independent_verification_path"] = str(final / "independent-verification.json")
    save(final / "status.json", state)
    save(exported / "final_evaluation/status.json", state)
    print(json.dumps({"passed": True, "node_id": node.id, "scores": score_checks,
                      "evidence": str(destination / "result.json")}))


if __name__ == "__main__":
    main()

"""Retrain a copied, real search candidate on its original fit population only."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
NODE_ID = "6e267f5a757c4721a6f4a89506e9c9cb"
SOURCE_SHA256 = "9b1cee6f9cb9cd9df2b95814ca90a9a2ff15b7f5f1fba0fae3c643e82072eacc"


def main():
    import psutil

    if psutil.virtual_memory().available < 13 * 1024 ** 3:
        raise RuntimeError("Retraining verification requires at least 13 GiB free memory")
    spec = importlib.util.spec_from_file_location(
        "verification_resource_limits", ROOT / "core/AlgoEvolve/utils/resource_limits.py"
    )
    limits = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = limits
    spec.loader.exec_module(limits)
    limiter = limits.WindowsJobMemoryLimiter(2 * 1024 ** 3)
    limiter.attach(os.getpid())
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[-2:])
    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)

    task = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["steel"]
    workspace = Path(task["auto_ml_workspace_dir"])
    evidence = OUT / "optimization-validation/steel-first-search-candidate-6e267f5a"
    source = workspace / "input/Steel_industry_data.csv"
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Source data changed since the accepted split was defined")
    solution = evidence / "standalone-inference/solution.py"
    destination = evidence / "standalone-retraining"
    destination.mkdir(parents=True, exist_ok=True)
    copied_solution = destination / "solution.py"
    shutil.copy2(solution, copied_solution)

    # Materialize only fit and development data for the child. No holdout path is supplied.
    import pandas as pd

    frame = pd.read_csv(source)
    ordered = frame.assign(_time=pd.to_datetime(frame["date"], format="%d/%m/%Y %H:%M"))
    ordered = ordered.sort_values("_time", kind="stable").drop(columns="_time").reset_index(drop=True)
    ordered.iloc[:21024].to_csv(destination / "fit.csv", index=False)
    ordered.iloc[:28032][["date", "Usage_kWh"]].to_csv(destination / "observed_development.csv", index=False)
    predictions = pd.read_csv(workspace / "node_runs" / NODE_ID / "working/validation_predictions.csv")
    positions = [0, 1, 95, 3504, 7007]
    checks = [{"position": pos, "prediction": float(predictions["candidate_prediction_Usage_kWh"].iloc[pos])}
              for pos in positions]
    (destination / "expected.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")

    child = """import importlib.util, json, sys, time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
spec = importlib.util.spec_from_file_location('copied_candidate', 'solution.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
def forbidden(*args, **kwargs):
    raise AssertionError('Default reusable training attempted final evaluation')
module.final_evaluate = forbidden
started = time.monotonic()
model_path = Path(module.train(Path('fit.csv'), Path('retrained_artifact')))
artifact = joblib.load(model_path)
assert artifact['training_rows'] == 21024
assert artifact['training_stats']['training_rows_used'] == 19008
assert artifact['model_config'] == module.MODEL_CONFIG
assert artifact['model_kind'] == 'lightgbm'
module.train = forbidden
import lightgbm
lightgbm.LGBMRegressor.fit = forbidden
history = pd.read_csv('observed_development.csv')
checks = json.loads(Path('expected.json').read_text())
for check in checks:
    end = 21024 + check['position']
    prediction = np.asarray(module.predict(model_path, history.iloc[end-2016:end].copy()))
    assert prediction.shape == (1,) and np.isfinite(prediction).all()
    np.testing.assert_allclose(prediction[0], check['prediction'], rtol=0, atol=1e-12)
    check['retrained_prediction'] = float(prediction[0])
result = {'passed': True, 'fresh_process': True, 'copied_generated_code': True,
          'default_train_interface': True, 'train_rows': 21024, 'fitted_rows': 19008,
          'hyperparameters_unchanged': True, 'prediction_checks': checks,
          'inference_forbids_fit': True, 'holdout_evaluated': False,
          'holdout_not_supplied_to_child': True, 'final_model_verified': False,
          'elapsed_seconds': time.monotonic() - started,
          'scope': 'First valid search candidate only; frozen fit data and selected development predictions. No final holdout or full-history refit.'}
Path('result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
"""
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "OMP_NUM_THREADS": "2",
           "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "PYTHONUTF8": "1"}
    execution = subprocess.run([sys.executable, "-c", child], cwd=destination, env=env,
                               capture_output=True, text=True, encoding="utf-8", timeout=180)
    (destination / "execution.log").write_text(execution.stdout + execution.stderr, encoding="utf-8")
    if execution.returncode:
        raise RuntimeError(execution.stdout + execution.stderr)
    result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
    result.update(source_sha256=SOURCE_SHA256, code_sha256=hashlib.sha256(solution.read_bytes()).hexdigest(),
                  resource_guard=limiter.describe(), peak_memory_bytes=limiter.peak_memory_bytes(),
                  cpu_affinity=process.cpu_affinity())
    (destination / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

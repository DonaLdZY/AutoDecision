"""Reload the actual first steel model in a fresh process and check inference only."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"


def main():
    task = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["steel"]
    workspace = Path(task["auto_ml_workspace_dir"])
    node_id = "6e267f5a757c4721a6f4a89506e9c9cb"
    source = workspace / "best_solution/solution.py"
    model = workspace / "node_runs" / node_id / "working/search_artifact" / f"model_artifact_{node_id}.joblib"
    destination = OUT / "optimization-validation/steel-first-search-candidate-6e267f5a/standalone-inference"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination / "solution.py")
    shutil.copy2(model, destination / "model.joblib")
    code = """import importlib.util, json, os
from pathlib import Path
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['OPENBLAS_NUM_THREADS'] = '2'
import numpy as np
import pandas as pd
import lightgbm
spec = importlib.util.spec_from_file_location('portable_solution', 'solution.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def forbidden(*args, **kwargs):
    raise AssertionError('Inference attempted fitting or final evaluation')
module.train = forbidden
module.final_evaluate = forbidden
lightgbm.LGBMRegressor.fit = forbidden
source = pd.read_csv(SOURCE)
source['_time'] = pd.to_datetime(source['date'], format='%d/%m/%Y %H:%M')
source = source.sort_values('_time', kind='stable').drop(columns='_time').reset_index(drop=True)
history = source.iloc[21024-2016:21024][['date','Usage_kWh']].copy()
history.to_csv('new_history.csv', index=False)
prediction = np.asarray(module.predict(Path('model.joblib'), pd.read_csv('new_history.csv')))
expected = pd.read_csv(PREDICTIONS)['candidate_prediction_Usage_kWh'].iloc[0]
assert prediction.shape == (1,) and np.isfinite(prediction).all()
np.testing.assert_allclose(prediction[0], expected, rtol=0, atol=1e-12)
changed = history.copy()
changed.loc[changed.index[-96:], 'Usage_kWh'] += 20.0
altered = np.asarray(module.predict(Path('model.joblib'), changed))
assert np.isfinite(altered).all() and not np.allclose(prediction, altered)
invalid = history.copy()
invalid.loc[invalid.index[-1], 'date'] = invalid.iloc[-2]['date']
try:
    module.predict(Path('model.joblib'), invalid)
except ValueError:
    duplicate_rejected = True
else:
    raise AssertionError('Duplicate history timestamps were silently accepted')
result = {'passed': True, 'fresh_process': True, 'moved_code_and_model': True,
          'source_aligned_first_development_prediction': float(prediction[0]),
          'changed_history_prediction': float(altered[0]), 'new_history_consumed': True,
          'training_and_final_evaluation_forbidden': True, 'duplicate_timestamps_rejected': duplicate_rejected,
          'holdout_evaluated': False, 'final_refit_model_verified': False,
          'scope': 'Actual saved search model only. Changed-history values are software sensitivity fixtures, not measured business forecasts.'}
Path('result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
"""
    prefix = f"SOURCE = {str(workspace / 'input/Steel_industry_data.csv')!r}\nPREDICTIONS = {str(workspace / 'node_runs' / node_id / 'working/validation_predictions.csv')!r}\n"
    before = hashlib.sha256(model.read_bytes()).hexdigest()
    result = subprocess.run([sys.executable, "-c", prefix + code], cwd=destination, text=True, capture_output=True, timeout=60)
    (destination / "execution.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert hashlib.sha256(model.read_bytes()).hexdigest() == before
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    print(result.stdout)


if __name__ == "__main__":
    main()

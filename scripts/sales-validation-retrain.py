"""Delivery adapter for the generated sales validation model and selected config."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parent


def _solution():
    name = "delivered_sales_solution"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "solution.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def train(data, artifact_dir):
    """Supply the recorded winning configuration before calling original train."""
    config_path = ROOT / "selected_config.json"
    selected_config = json.loads(config_path.read_text(encoding="utf-8"))
    target = Path(artifact_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    target_config = target / "selected_config.json"
    if target_config.exists():
        existing = json.loads(target_config.read_text(encoding="utf-8"))
        if existing != selected_config:
            raise ValueError("Artifact directory already contains a different training configuration")
    if target_config.resolve() != config_path.resolve():
        shutil.copy2(config_path, target_config)
    return _solution().train(data, str(target))


def predict(model_path, data):
    return _solution().predict(model_path, data)


def main():
    import numpy as np
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-data", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--predict-data", type=Path)
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args()
    if bool(args.predict_data) != bool(args.output_csv):
        parser.error("--predict-data and --output-csv must be provided together")
    model_path = train(pd.read_csv(args.train_data), args.artifact_dir)
    result = {"artifact_path": str(model_path), "training_entrypoint": "retrain.train"}
    if args.predict_data:
        data = pd.read_csv(args.predict_data)
        values = np.asarray(predict(model_path, data)).reshape(-1)
        if len(values) != len(data) or not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("Invalid sales prediction output")
        output = pd.DataFrame({"row_id": data["row_id"], "sales": values}, columns=["row_id", "sales"])
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(args.output_csv, index=False)
        result.update({"output_path": str(args.output_csv), "prediction_rows": len(output)})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

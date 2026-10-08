"""Independently recompute development RMSE from original simulation CSVs."""
import argparse
import csv
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def finite_decimal(value):
    try:
        result = Decimal(str(value).strip())
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("deposition_score_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("deposition")
    workspace = Path(task["auto_ml_workspace_dir"])
    sources = workspace / "input"
    node = next(row for row in stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")["nodes"]
                if row["id"] == args.node)
    prediction_file = workspace / "submission" / f"submission_{args.node}.csv"
    reported = float(node["metric"]["value"])
    if args.final:
        stages.verified_search_seconds(task)
        if task["status"] == "running":
            raise RuntimeError("Final score verification requires completed service execution")
        final = workspace / "final_evaluation"
        state, final_result = stages.read_json(final / "status.json"), stages.read_json(final / "result.json")
        assert state["status"] == final_result["status"] == "completed"
        assert state["selection"]["node_id"] == args.node
        prediction_file = final / "artifacts/final_holdout_predictions.csv"
        reported = float(final_result["metrics"]["holdout_rmse_c"])
    names = {"Cooling_rates_S-pattern.csv": "S-pattern", "Cooling_rates_Spiral.csv": "Spiral", "Cooling_rates_ZigZag.csv": "Zig-Zag"}
    truth, counts, source_hashes = {}, [], {}
    for filename, strategy in names.items():
        matches = list(sources.rglob(filename))
        assert len(matches) == 1
        path = matches[0]
        source = path.relative_to(sources).as_posix()
        source_hashes[source] = hashlib.sha256(path.read_bytes()).hexdigest()
        raw = pd.read_csv(path, sep=";", encoding="gb18030", header=None, dtype=str, keep_default_na=False)
        with path.open(encoding="cp1252", newline="") as stream:
            reader = csv.reader(stream, delimiter=";")
            group_header, units_header = next(reader), next(reader)
        assert raw.shape[1] == 255
        assert len(group_header) == len(units_header) == 255
        zones = set()
        for index in range(0, 255, 4):
            zone = raw.iat[0, index].strip()
            assert re.fullmatch(r"[A-H][1-8]", zone) and zone not in zones
            zones.add(zone)
            assert group_header[index] == zone
            assert units_header[index].strip().upper() == "TIME [S]"
            assert units_header[index + 2].strip().upper() in {"TEMPERATURE [\u00b0C]", "TEMPERATURE [\u00d8C]"}
            groups = defaultdict(list)
            previous = None
            invalid = 0
            for time_value, label_value in zip(raw.iloc[2:, index], raw.iloc[2:, index + 2]):
                moment, label = finite_decimal(time_value), finite_decimal(label_value)
                if moment is None or label is None:
                    invalid += 1
                    continue
                assert previous is None or moment >= previous, (source, zone, "unordered time")
                previous = moment
                groups[moment].append(float(label))
            keys = sorted(groups)
            size = len(keys)
            assert size >= 5
            train, development = math.floor(.60 * size), math.floor(.20 * size)
            assert min(train, development, size - train - development) > 0
            scoring_keys = keys[train + development:] if args.final else keys[train:train + development]
            for moment in scoring_keys:
                truth[(source, strategy, zone, moment)] = math.fsum(groups[moment]) / len(groups[moment])
            counts.append({"strategy": strategy, "zone": zone, "train": train, "development": development,
                           "holdout_count_only": size - train - development, "invalid_or_padding_rows": invalid,
                           "duplicate_valid_rows": sum(len(values) - 1 for values in groups.values())})
        assert len(zones) == 64
    predictions = pd.read_csv(prediction_file, dtype={"time_s": str})
    assert list(predictions.columns) == ["evaluation_row_id", "source_file", "strategy", "zone", "time_s", "y_pred"]
    assert not predictions.evaluation_row_id.isna().any() and predictions.evaluation_row_id.is_unique
    observed = {}
    errors_by_strategy = defaultdict(list)
    for row in predictions.itertuples(index=False):
        key = (row.source_file, row.strategy, row.zone, finite_decimal(row.time_s))
        assert key not in observed and key in truth
        assert math.isfinite(row.y_pred)
        observed[key] = row.y_pred
        errors_by_strategy[row.strategy].append(row.y_pred - truth[key])
    assert set(observed) == set(truth)
    errors = np.array([error for values in errors_by_strategy.values() for error in values])
    rmse = float(np.sqrt(np.mean(errors**2)))
    result = {"passed": abs(rmse - reported) < 1e-8,
              "node": args.node, "rmse": rmse, "reported_score": reported,
              "scored_rows": len(truth), "curves": len(counts), "source_hashes": source_hashes,
              "curve_counts": counts, "diagnostics": {key: {"RMSE": float(np.sqrt(np.mean(np.square(values)))), "count": len(values)}
                                                        for key, values in errors_by_strategy.items()},
              "model_code_executed": False, "holdout_scored": args.final, "phase": "final" if args.final else "development",
              "scope": "Independent raw headers, Decimal-time aggregation, exact saved prediction population and pooled RMSE; no model invocation or repeated final evaluation"}
    dest = stages.batch.OUT / "optimization-validation" / f"deposition-{'final-' if args.final else ''}score-{args.node[:8]}-{time.time_ns()}"
    dest.mkdir(parents=True)
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), **{key: result[key] for key in
          ("passed", "phase", "rmse", "scored_rows", "curves", "diagnostics")}}, ensure_ascii=False))
    if not result["passed"]:
        raise RuntimeError("Independent development score disagrees with candidate")


if __name__ == "__main__":
    main()

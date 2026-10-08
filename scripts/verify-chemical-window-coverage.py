"""Audit the disclosed offline window design against complete original sources."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conflict-policy", choices=("retain", "isolate"), default="retain")
    parser.add_argument("--split-policy", choices=("floor_per_partition", "ceil_tail"), default="floor_per_partition")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("chemical_coverage_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    manifest = stages.read_json(stages.batch.OUT / "manifest.json")
    source = Path(next(row for row in manifest["tasks"] if row["slug"] == "chemical")["payload"]["input_root"])
    lab_path = source / "\u6d53\u5ea6.xls"
    device_path = source / "\u8bbe\u5907.csv"
    sheets = pd.read_excel(lab_path, sheet_name=None, header=0)
    lab = sheets["Sheet1"]
    labels = lab.loc[lab["\u53c2\u6570"].eq("Al(N\uff09") & lab["\u90e8\u4f4d"].eq("\u538b\u6ee4\u6db2")].copy()
    targets = pd.to_numeric(labels["\u7ed3\u679c\n[\u5355\u4f4d\u4e3a\u5f53\u91cf]"], errors="coerce")
    cutoffs = pd.to_datetime(labels["\u91c7\u6837\u65f6\u95f4"], format="mixed", errors="coerce")
    device_times, finite_times = [], []
    source_rows, invalid_times, empty_numeric_rows = 0, 0, 0
    exact_columns = None
    for chunk in pd.read_csv(device_path, encoding="utf-8-sig", sep=",", chunksize=100000, low_memory=False):
        columns = chunk.columns.tolist()
        assert len(columns) == 63 and columns[0] == "SampleTime"
        assert exact_columns is None or columns == exact_columns
        exact_columns = columns
        timestamps = pd.to_datetime(chunk["SampleTime"], format="mixed", errors="coerce")
        has_numeric = np.isfinite(chunk.drop(columns="SampleTime").apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)).any(axis=1)
        source_rows += len(chunk)
        invalid_times += int(timestamps.isna().sum())
        empty_numeric_rows += int((~has_numeric).sum())
        device_times.append(timestamps.dropna().to_numpy(dtype="datetime64[ns]"))
        finite_times.append(timestamps[timestamps.notna() & has_numeric].to_numpy(dtype="datetime64[ns]"))
    times = np.concatenate(device_times)
    source_reversals = int((times[1:] < times[:-1]).sum())
    duplicate_device_times = len(times) - len(np.unique(times))
    good_times = np.sort(np.concatenate(finite_times))
    candidates = cutoffs.to_numpy(dtype="datetime64[ns]")
    counts = np.searchsorted(good_times, candidates, side="right") - np.searchsorted(
        good_times, candidates - np.timedelta64(60, "m"), side="right")
    eligible = cutoffs.notna().to_numpy() & np.isfinite(targets.to_numpy(dtype=float)) & (counts > 0)
    conflicts = targets.groupby(cutoffs).transform("nunique").gt(1).to_numpy()
    if args.conflict_policy == "isolate":
        eligible &= ~conflicts
    groups = np.sort(np.unique(candidates[eligible]))
    n_train, n_dev = int(.60 * len(groups)), int(.20 * len(groups))
    if args.split_policy == "ceil_tail":
        remaining = len(groups) - math.ceil(.20 * len(groups))
        n_dev = math.ceil(.25 * remaining)
        n_train = remaining - n_dev
    split_counts = {}
    for name, subset in (("train", groups[:n_train]), ("development", groups[n_train:n_train+n_dev]),
                         ("holdout_count_only", groups[n_train+n_dev:])):
        mask = eligible & np.isin(candidates, subset)
        split_counts[name] = {"groups": len(subset), "rows": int(mask.sum()),
                             "high_rows": int((mask & labels["\u8d85\u5dee"].eq("\u9ad8").to_numpy()).sum()),
                             "first_cutoff": str(subset[0]) if len(subset) else None,
                             "last_cutoff": str(subset[-1]) if len(subset) else None}
    result = {"passed": all(row["groups"] > 0 for row in split_counts.values()),
              "source_hashes": {lab_path.name: file_hash(lab_path), device_path.name: file_hash(device_path)},
              "sheet_shapes": {name: list(frame.shape) for name, frame in sheets.items()},
              "strict_target_rows": len(labels), "unique_target_times": cutoffs.nunique(),
              "high_target_rows": int(labels["\u8d85\u5dee"].eq("\u9ad8").sum()),
              "device_rows": source_rows, "device_invalid_times": invalid_times,
              "device_time_reversals": source_reversals, "device_duplicate_times": duplicate_device_times,
              "device_rows_without_finite_process_values": empty_numeric_rows,
              "device_min_time": str(times.min()), "device_max_time": str(times.max()),
              "window_eligible_labels": int(eligible.sum()), "empty_window_labels": int((counts == 0).sum()),
              "conflict_policy": args.conflict_policy, "conflicting_rows": int(conflicts.sum()),
              "split_policy": args.split_policy,
              "isolated_conflicting_rows": int(conflicts.sum()) if args.conflict_policy == "isolate" else 0,
              "invalid_label_or_time": int((cutoffs.isna() | ~np.isfinite(targets)).sum()),
              "window_record_count_quantiles": np.quantile(counts[eligible], [0, .25, .5, .75, 1]).tolist(),
              "splits": split_counts, "model_fitted": False, "holdout_scored": False,
              "scope": "Historical time-coverage audit only. 60-minute retrospective window is an experimental assumption, not verified plant delay or online availability."}
    dest = stages.batch.OUT / "optimization-validation" / f"chemical-window-coverage-{time.time_ns()}"
    dest.mkdir(parents=True)
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

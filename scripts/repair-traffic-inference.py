"""Build a versioned traffic inference repair without changing search scores or frozen evidence."""
from __future__ import annotations
import argparse, ast, hashlib, importlib.util, json, os, shutil, sys, time, urllib.request
from pathlib import Path

EXPECTED_SOURCE = "4b444099889e80cdf658fbb6de106e694c8a56f87dad9ac3aa32f26aed85d60b"
TASK_ID = "645f11ba244e4783b88fb105d93cddcc"


def repair_source(code):
    assert hashlib.sha256(code.encode()).hexdigest() == EXPECTED_SOURCE, "Unexpected frozen source; review before repair"
    old = """            if not np.isnan(piv_vals[gi, i]):
                if last_obs >= 0:
                    obs_prev[gi, i] = last_obs
                last_obs = i"""
    new = """            # A requested target has no label at inference. Its predecessor
            # depends only on earlier observed history, never its own label mask.
            if last_obs >= 0:
                obs_prev[gi, i] = last_obs
            if not np.isnan(piv_vals[gi, i]):
                last_obs = i"""
    assert code.count(old) == 1
    code = code.replace(old, new, 1)
    code = code.replace("def load_and_aggregate():", "def load_and_aggregate(data_dir=None):", 1)
    code = code.replace("pd.read_csv(DATA_CSV,", "pd.read_csv(os.path.join(str(data_dir), os.path.basename(DATA_CSV)) if data_dir is not None else DATA_CSV,", 1)
    for name in ("load_topology", "load_topology_dist"):
        code = code.replace(f"def {name}(all_gids):", f"def {name}(all_gids, data_dir=None):", 1)
    for name in ("load_topology", "load_topology_dist"):
        tree = ast.parse(code)
        f = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        lines = code.splitlines(keepends=True)
        body = "".join(lines[f.lineno-1:f.end_lineno])
        body = body.replace("if not os.path.exists(REL_XLSX):", "relation_path = os.path.join(str(data_dir), os.path.basename(REL_XLSX)) if data_dir is not None else REL_XLSX\n    if not os.path.exists(relation_path):")
        body = body.replace("pd.read_excel(REL_XLSX,", "pd.read_excel(relation_path,")
        code = "".join(lines[:f.lineno-1]) + body + "".join(lines[f.end_lineno:])
    tree = ast.parse(code)
    train = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "train")
    lines = code.splitlines(keepends=True)
    body = "".join(lines[train.lineno-1:train.end_lineno])
    body = body.replace("    agg, _ = load_and_aggregate()", "    if not isinstance(data, (str, os.PathLike)) or not os.path.isdir(data):\n        raise ValueError('train data must be an existing source directory')\n    agg, _ = load_and_aggregate(data)", 1)
    body = body.replace("load_topology(all_gids)", "load_topology(all_gids, data)", 1).replace("load_topology_dist(all_gids)", "load_topology_dist(all_gids, data)", 1)
    body = body.replace('"feat_cfg": feat_cfg,', '"feat_cfg": {k: v for k, v in feat_cfg.items() if k not in {"fit_stats", "dist_weight"}},\n                "fit_stats_and_dist_weight_in_model": True,', 1)
    code = "".join(lines[:train.lineno-1]) + body + "".join(lines[train.end_lineno:])
    tree = ast.parse(code)
    predict = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "predict")
    lines = code.splitlines(keepends=True)
    original = "".join(lines[predict.lineno-1:predict.end_lineno])
    prefix = original[:original.index("    # data expected")]
    tail = original[original.index("    X = build_features_for_targets("):]
    replacement = prefix + r'''    if isinstance(data, dict):
        if set(data) != {"history", "target_pairs"}:
            raise ValueError("predict expects history and target_pairs")
        agg = pd.DataFrame(data["history"])
        targets = data["target_pairs"]
    elif isinstance(data, pd.DataFrame):
        agg = data.copy()
        targets = data.attrs.get("target_pairs")
        if targets is None:
            targets = getattr(data, "target_pairs", None)
        if targets is None and COL_GID in data and COL_TIME in data:
            targets = list(zip(data[COL_GID], data[COL_TIME]))
    else:
        raise TypeError("predict data must be a history/target_pairs object or DataFrame")
    if targets is None:
        raise ValueError("Explicit target_pairs are required")
    pairs = [(str(g), pd.Timestamp(h)) for g, h in targets]
    if not pairs or len(pairs) != len(set(pairs)):
        raise ValueError("target_pairs must be nonempty and unique")
    if any(pd.isna(h) or h != h.floor("h") or h.tzinfo is not None for _, h in pairs):
        raise ValueError("Target times must be valid local full hours")
    if "gid" not in agg and COL_GID in agg:
        agg = agg.rename(columns={COL_GID: "gid"})
    if "hour" not in agg and COL_TIME in agg:
        agg["hour"] = pd.to_datetime(agg[COL_TIME], format="%m/%d/%Y %H:%M:%S", errors="raise").dt.floor("h")
    if not {"gid", "hour", "y", "txn"}.issubset(agg.columns):
        raise ValueError("History must contain gid, hour, y and txn")
    agg = agg[["gid", "hour", "y", "txn"]].copy()
    agg["gid"] = agg["gid"].astype(str)
    agg["hour"] = pd.to_datetime(agg["hour"], errors="raise")
    if agg.duplicated(["gid", "hour"]).any():
        raise ValueError("History contains duplicate gantry-hour records")
    for column in ("y", "txn"):
        agg[column] = pd.to_numeric(agg[column], errors="raise")
        values = agg[column].dropna().to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("History counts must be finite and nonnegative when observed")
    known = set(agg[["gid", "hour"]].itertuples(index=False, name=None))
    absent = [{"gid": g, "hour": h, "y": np.nan, "txn": np.nan} for g, h in pairs if (g, h) not in known]
    if absent:
        # Requested time slots are indexing placeholders, never zero labels.
        agg = pd.concat([agg, pd.DataFrame(absent)], ignore_index=True)
    agg = agg.sort_values(["hour", "gid"]).reset_index(drop=True)
    piv, piv_txn, gids, hours = build_pivot(agg)
    tg, th = zip(*pairs)
''' + tail
    replacement = replacement.replace("    for c in feat_cols:", "    if len(X) != len(pairs):\n        raise ValueError('Inference did not cover all explicit target pairs')\n    for c in feat_cols:", 1)
    code = "".join(lines[:predict.lineno-1]) + replacement + "".join(lines[predict.end_lineno:])
    ast.parse(code)
    return code


def build(task):
    workspace = Path(task["auto_ml_workspace_dir"])
    frozen = workspace / "final_evaluation"
    state = json.loads((frozen / "status.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    original = frozen / "selected_solution.py"
    code = repair_source(original.read_text(encoding="utf-8"))
    root = Path(task["run_dir"]) / "stage-history" / ("inference-repair-" + time.strftime("%Y%m%d_%H%M%S"))
    package = root / "best_solution"
    shutil.copytree(workspace / "best_solution", package)
    patched = root / "repaired_source.py"
    patched.write_text(code, encoding="utf-8", newline="\n")
    helper_path = Path(__file__).resolve().parents[1] / "core/AlgoEvolve/engine/solution_package.py"
    spec = importlib.util.spec_from_file_location("traffic_package_helper", helper_path)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    helper.package_inference_source(package, patched, state["serialization_module"])
    provenance = {"schema_version":"autodecision.inference_repair.v1", "task_id":task["id"], "parent_node_id":state["selection"]["node_id"],
        "original_source_sha256":EXPECTED_SOURCE, "repaired_source_sha256":hashlib.sha256(code.encode()).hexdigest(),
        "frozen_model_sha256":hashlib.sha256((frozen / "artifacts" / json.loads((frozen / "result.json").read_text())["model_path"]).read_bytes()).hexdigest(),
        "changes":["History predecessor assignment is independent of target-label presence", "Explicit JSON history and target pairs; add only NaN indexing placeholders", "Reject silent population loss, duplicate targets and invalid history", "Training uses its source-directory argument and serializes metadata without tuple-key dictionaries"],
        "search_and_final_records":"unchanged; not a new model selection or a new independent holdout", "validation":"pending"}
    (root / "repair_provenance.json").write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding="utf-8")
    print(str(root))
    return root


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id",default=TASK_ID)
    args=parser.parse_args()
    task=next(t for t in json.load(urllib.request.urlopen("http://127.0.0.1:18080/api/tasks")) if t["id"]==args.task_id)
    build(task)

"""Execute the reviewed traffic report examples against a relocated public export."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from markdown_it import MarkdownIt
import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from utils.resource_limits import WindowsJobMemoryLimiter


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def child(path):
    import numpy as np
    import pandas as pd
    import lightgbm

    spec = read(path)
    exported = Path(spec["workspace"]) / "best_solution"
    sys.path.insert(0, str(exported))
    import solution

    def forbidden(*args, **kwargs):
        raise AssertionError("A report example attempted final evaluation or fitting during prediction")

    solution._implementation.final_evaluate = forbidden
    real_train, real_predict = solution.train, solution.predict
    expected = pd.read_csv(spec["expected"], dtype={"gantry_id": str})
    calls = []

    def aligned(frame):
        assert list(frame.columns) == ["gantry_id", "forecast_origin", "horizon_minutes", "predicted_count"]
        assert len(frame) == 954
        frame = frame.copy()
        frame["forecast_origin"] = pd.to_datetime(frame["forecast_origin"])
        return frame.set_index(["gantry_id", "forecast_origin", "horizon_minutes"])["predicted_count"].sort_index()

    def checked_predict(model_path, data):
        prediction = real_predict(model_path, data)
        assert isinstance(prediction, pd.DataFrame)
        actual, reference = aligned(prediction), aligned(expected)
        pd.testing.assert_index_equal(actual.index, reference.index)
        np.testing.assert_allclose(actual, reference, rtol=1e-10, atol=1e-8)
        calls.append({"kind": "predict", "rows": len(prediction), "frozen_predictions_match": True})
        return prediction

    def checked_train(data, artifact_dir):
        dataset = solution._implementation._coerce_fixed_dataset(data)
        origins = pd.DatetimeIndex(dataset["fit_origins"])
        assert len(origins) == 1429
        assert origins.max() + pd.Timedelta(hours=1) == pd.Timestamp("2025-11-06")
        artifact = real_train(data, artifact_dir)
        calls.append({"kind": "train", "fit_origins": len(origins), "artifact_exists": Path(artifact).is_file()})
        return artifact

    solution.train = checked_train if spec["training"] else forbidden
    solution.predict = checked_predict
    if not spec["training"]:
        lightgbm.LGBMRegressor.fit = forbidden
    namespace = {"__name__": "__main__"}
    for code in spec["code"]:
        exec(compile(code, str(path), "exec"), namespace)
    if spec["training"]:
        lightgbm.LGBMRegressor.fit = forbidden
        solution._implementation.train = forbidden
        import joblib
        artifact_path = namespace["artifact_path"]
        artifact = joblib.load(artifact_path)
        assert artifact["training_window"]["origin_count"] == 1429
        assert artifact["training_window"]["end"] == "2025-11-06 00:00:00"
        history = pd.read_csv(spec["history"], dtype=str)
        checked_predict(artifact_path, {"events": history, "forecast_origins": spec["origins"]})
    else:
        output_dir = Path(namespace["output_dir"])
        predicted_path = output_dir / "submission_0dbdc708fc074653a2b0490009760a40.csv"
        pd.testing.assert_series_equal(aligned(pd.read_csv(predicted_path, dtype={"gantry_id": str})),
                                       aligned(expected), check_exact=False, rtol=1e-10, atol=1e-8)
        for name in ("fallback_audit.csv", "inference_causal_audit.json", "inference_run_audit.json"):
            assert (output_dir / name).is_file(), name
        calls.append({"kind": "directory_inference", "rows": 954, "audit_files_present": True})
    assert calls
    save(path.with_name("execution-result.json"), {"passed": True, "calls": calls,
        "final_evaluation_executed": False, "training_during_prediction": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--child", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    if not args.directory:
        parser.error("--directory is required")
    if psutil.virtual_memory().available < 7 * 1024**3:
        raise RuntimeError("Report verification needs 7 GiB free before admitting its 4 GiB job")
    limiter = WindowsJobMemoryLimiter(4 * 1024**3)
    limiter.attach(os.getpid())
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[-4:])
    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    helper_spec = importlib.util.spec_from_file_location("traffic_report_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(stages)
    task = stages.current_task("traffic")
    original = Path(task["auto_ml_workspace_dir"])
    frozen = stages.fingerprint(stages.stage_artifacts(task, "automl"))
    report_path = args.directory / "report.md"
    report = report_path.read_text(encoding="utf-8")
    tokens = MarkdownIt("commonmark").parse(report)
    section, snippets = "", {}
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h3":
            section = tokens[index + 1].content.split()[0]
        if token.type == "fence" and token.info.strip() == "python" and section in {"7.2", "7.3", "7.5", "8.2"}:
            tree = ast.parse(token.content)
            if any(isinstance(node, ast.Assign) for node in ast.walk(tree)):
                snippets.setdefault(section, []).append(token.content)
    if any(len(snippets.get(key, [])) != 1 for key in ("7.2", "7.3", "7.5", "8.2")):
        raise RuntimeError("Expected exactly one complete runnable block in each reviewed example subsection")
    dest = OUT / "optimization-validation" / f"traffic-report-examples-{time.time_ns()}"
    dest.mkdir(parents=True)
    final_fixture = OUT / "optimization-validation/traffic-final-inference-1788818363918486900/moved_export"
    dev_fixture = OUT / "optimization-validation/traffic-inference-0dbdc708-1788818931073474400"
    results = []
    for training in (False, True):
        run = dest / ("training" if training else "inference")
        relocated = run / "workspace"
        relocated.mkdir(parents=True)
        source_export = original / "best_solution"
        manifest = read(source_export / "solution_manifest.json")
        relative_model = (source_export / "model_path.txt").read_text(encoding="utf-8").strip()
        for relative in ("solution.py", "model_path.txt", "solution_manifest.json", manifest["implementation_path"], relative_model):
            target = relocated / "best_solution" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_export / relative, target)
        (relocated / "input").mkdir()
        if training:
            for source in (original / "input").iterdir():
                if source.is_file() and source.suffix.lower() in {".csv", ".xlsx"}:
                    shutil.copy2(source, relocated / "input" / source.name)
        else:
            shutil.copy2(final_fixture / "history.csv", relocated / "input/tmp_gantry_trade_info_split1_20251224_7d_hechi_result.csv")
        class Relocate(ast.NodeTransformer):
            def visit_Constant(self, node):
                if isinstance(node.value, str) and node.value.startswith(str(original)):
                    node.value = str(relocated) + node.value[len(str(original)):]
                return node
        selected = [snippets["8.2"][0]] if training else [snippets[key][0] for key in ("7.2", "7.3", "7.5")]
        code = [ast.unparse(ast.fix_missing_locations(Relocate().visit(ast.parse(item)))) for item in selected]
        fixture = dev_fixture if training else final_fixture
        spec_path = run / "example.json"
        save(spec_path, {"training": training, "original_code": selected, "code": code, "workspace": str(relocated),
            "expected": str(fixture / "expected.csv"), "history": str(fixture / "history.csv"),
            "origins": ["2025-11-06 00:00:00", "2025-11-06 11:30:00", "2025-11-06 23:00:00"]})
        environment = dict(os.environ, PYTHONUTF8="1", OMP_NUM_THREADS="18" if training else "2",
                           OPENBLAS_NUM_THREADS="18" if training else "2", MKL_NUM_THREADS="18" if training else "2")
        execution = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(spec_path)],
            cwd=run, capture_output=True, text=True, encoding="utf-8", timeout=600 if training else 180, env=environment)
        (run / "execution.log").write_text(execution.stdout + execution.stderr, encoding="utf-8")
        results.append({"training": training, "passed": execution.returncode == 0,
            "execution": read(run / "execution-result.json") if (run / "execution-result.json").is_file() else None,
            "error": execution.stderr.splitlines()[-1] if execution.returncode else None, "directory": str(run)})
    unchanged = frozen == stages.fingerprint(stages.stage_artifacts(task, "automl"))
    result = {"passed": unchanged and all(item["passed"] for item in results), "examples": results,
        "source_unchanged": unchanged, "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "report": str(report_path), "final_evaluation_repeated": False,
        "scope": "Exact report Python examples parsed and executed with only the workspace literal relocated. Both final inference and training-only reproduction are compared with 954 saved predictions. Job memory limit 4 GiB; no GPU training requested by this LightGBM recipe."}
    save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

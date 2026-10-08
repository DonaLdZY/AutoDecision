"""Execute actual chemical report examples without repeating final evaluation."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from engine.executor import Interpreter
from utils.resource_limits import WindowsJobMemoryLimiter, host_commit_available_bytes


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def child(spec_path):
    import joblib
    import numpy as np
    import pandas as pd
    from catboost import CatBoostRegressor

    spec = read(spec_path)
    workspace = Path(spec["workspace"])
    sys.path.insert(0, str(workspace / "best_solution"))
    import solution

    implementation = solution._implementation
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("Report example attempted unapproved fitting or final evaluation")

    implementation.final_evaluate = forbidden
    real_fit = implementation._fit_catboost
    real_clip = implementation._fit_robust_clipper

    def checked_fit(X, y):
        assert spec["training"] and len(X) == len(y) == 914
        np.testing.assert_allclose(np.sort(y), spec["training_labels"], rtol=0, atol=1e-12)
        calls.append({"kind": "fit", "rows": len(y)})
        return real_fit(X, y)

    def checked_clip(X, names):
        assert spec["training"] and len(X) == 914
        calls.append({"kind": "fit_preprocessor", "rows": len(X)})
        return real_clip(X, names)

    implementation._fit_catboost = checked_fit
    implementation._fit_robust_clipper = checked_clip
    if not spec["training"]:
        CatBoostRegressor.fit = forbidden
        implementation.train = forbidden
        implementation._prepare_dataset = forbidden
        implementation._read_label_source = forbidden
    real_predict = solution.predict

    def checked_predict(model_path, data):
        model = joblib.load(model_path)
        assert model["training_rows"] in {914, 1221}
        assert set(data) == {"prediction_cutoff", "history"}
        saved_fit = CatBoostRegressor.fit
        saved_clip = implementation._fit_robust_clipper
        CatBoostRegressor.fit = forbidden
        implementation._fit_robust_clipper = forbidden
        try:
            observed = real_predict(model_path, data)
        finally:
            CatBoostRegressor.fit = saved_fit
            implementation._fit_robust_clipper = saved_clip
        assert isinstance(observed, np.ndarray) and observed.shape == (1,)
        assert np.isfinite(observed).all()
        cutoff = str(pd.Timestamp(data["prediction_cutoff"]))
        expected = spec["frozen_predictions"][str(model["training_rows"])].get(cutoff)
        if expected is not None:
            np.testing.assert_allclose(observed, [expected], rtol=0, atol=1e-12)
        calls.append({"kind": "predict", "cutoff": str(data["prediction_cutoff"]),
                      "return_type": "ndarray", "shape": [1], "value": float(observed[0]),
                      "model_training_rows": model["training_rows"],
                      "frozen_prediction_checked": expected is not None})
        return observed

    solution.predict = checked_predict
    exec(compile(spec["code"], str(spec_path), "exec"), {"__name__": "__main__", "__file__": str(workspace / "example.py")})
    assert calls, "Runnable report example did not call the delivered API"
    if spec["training"]:
        assert sum(call["kind"] == "fit" for call in calls) == 1
        assert sum(call["kind"] == "fit_preprocessor" for call in calls) == 1
    else:
        assert any(call["kind"] == "predict" for call in calls)
    save(spec_path.with_name("execution-result.json"), {"passed": True, "calls": calls})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--child", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    if not args.directory:
        parser.error("--directory is required")
    import psutil
    import pandas as pd

    reserve = 6 * 1024**3
    commit = host_commit_available_bytes()
    if psutil.virtual_memory().available < reserve or (commit is not None and commit < reserve):
        raise RuntimeError("Report examples need six GiB free RAM and commit reserve")
    guard = WindowsJobMemoryLimiter(6 * 1024**3)
    guard.attach(os.getpid())
    os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2",
        ALGOEVOLVE_EXECUTION_POOL_PATH=str(OUT / "execution-slots"), ALGOEVOLVE_GPU_EXECUTION_SLOTS="2",
        ALGOEVOLVE_HOST_FREE_RESERVE_GIB="2", ALGOEVOLVE_GPU_FREE_RESERVE_GIB="1",
        ALGOEVOLVE_TORCH_ALLOCATOR_GUARD="0")
    task = read(OUT / "batch-state.json")["tasks"]["chemical"]
    original = Path(task["auto_ml_workspace_dir"])
    manifest = read(original / "best_solution/solution_manifest.json")
    assert manifest["node_id"] == "58002f37a3fd4bf88c950e4375784ecb"
    report_path = args.directory / ("report_draft.md" if args.draft else "report.md")
    tokens = MarkdownIt("commonmark").parse(report_path.read_text(encoding="utf-8"))
    dest = OUT / "optimization-validation" / f"chemical-report-examples-{time.time_ns()}"
    dest.mkdir(parents=True)
    samples = pd.read_csv(original / "final_evaluation/artifacts/evaluation_samples.csv")
    training_labels = sorted(samples.loc[samples.split.eq("train"), "y_true"].tolist())
    assert len(training_labels) == 914
    frozen_predictions = {}
    for rows, relative in ((914, "development_prediction_frame.csv"), (1221, "holdout_prediction_frame.csv")):
        predictions = pd.read_csv(original / "final_evaluation/artifacts" / relative)
        joined = predictions.merge(samples[["label_row_id", "prediction_cutoff"]], on="label_row_id", validate="one_to_one")
        assert joined.groupby("prediction_cutoff")["y_pred"].nunique().le(1).all()
        frozen_predictions[str(rows)] = {str(pd.Timestamp(row.prediction_cutoff)): row.y_pred for row in joined.itertuples()}
    examples = []
    section = ""
    groups = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2":
            section = tokens[index + 1].content
        if token.type != "fence" or token.info.strip().lower() != "python":
            continue
        if not groups or groups[-1]["section"] != section:
            groups.append({"section": section, "line": token.map[0] + 1, "blocks": []})
        groups[-1]["blocks"].append(token.content)
    for group in groups:
        code = "\n\n".join(group["blocks"])
        tree = ast.parse(code)
        if not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)):
            continue
        run = dest / f"example-{len(examples) + 1}"
        workspace = run / "workspace"
        workspace.mkdir(parents=True)
        shutil.copytree(original / "best_solution", workspace / "best_solution", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(original / "input", workspace / "input", ignore=shutil.ignore_patterns("__pycache__"))

        class Relocate(ast.NodeTransformer):
            def visit_Constant(self, node):
                if isinstance(node.value, str):
                    for old in (str(original), original.as_posix()):
                        if node.value.startswith(old):
                            node.value = str(workspace) + node.value[len(old):]
                            break
                return node

        training = any(isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "train"
            or isinstance(node.func, ast.Attribute) and node.func.attr == "train") for node in ast.walk(tree))
        spec_path = run / "example.json"
        save(spec_path, {"original_code": code, "code": ast.unparse(ast.fix_missing_locations(Relocate().visit(tree))),
            "workspace": str(workspace.resolve()), "training": training, "training_labels": training_labels,
            "frozen_predictions": frozen_predictions})
        probe = f"import runpy,sys\nsys.argv=[{str(Path(__file__).resolve())!r},'--child',{str(spec_path.resolve())!r}]\nrunpy.run_path(sys.argv[0],run_name='__main__')\n"
        execution = Interpreter(workspace, timeout=300, max_parallel_run=1).run(probe, "chemical_report_example")
        detail = read(run / "execution-result.json") if (run / "execution-result.json").is_file() else {}
        examples.append({"section": group["section"], "line": group["line"], "blocks": len(group["blocks"]), "training": training,
            "passed": detail.get("passed") is True and execution.exc_type is None,
            "execution": execution.to_dict(), "checks": detail, "directory": str(run)})
    passed = bool(examples) and all(row["passed"] for row in examples)
    result = {"passed": passed, "report": str(report_path), "draft_only": args.draft,
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(), "examples": examples,
        "holdout_evaluated": False, "scope": "Exact report Python examples in copied workspaces, grouped by report section; only source-root literals relocated. Fitting is restricted to 914 training labels. Inference uses the public API, forbids fitting, and matches frozen predictions whenever the example cutoff is in the corresponding saved evaluation population."}
    save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), "passed": passed, "examples": len(examples)}, ensure_ascii=False))
    if not passed:
        raise RuntimeError("Report examples need repair")


if __name__ == "__main__":
    main()

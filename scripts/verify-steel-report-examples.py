"""Execute report examples in a relocated workspace, forbidding final evaluation."""
from __future__ import annotations

import argparse
import ast
import hashlib
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


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def child(spec_path):
    import numpy as np
    import pandas as pd
    import lightgbm

    spec = read(spec_path)
    sys.path.insert(0, str(Path(spec["workspace"]) / "best_solution"))
    import solution

    def forbidden(*args, **kwargs):
        raise AssertionError("Report example attempted final evaluation or fitting during inference")

    solution._implementation.final_evaluate = forbidden
    solution._implementation._rolling_predict = forbidden
    real_train = solution.train
    calls = []

    def checked_train(data, artifact_dir):
        frame, _, _ = solution._implementation._coerce_data(data)
        if len(frame) != 21024:
            raise AssertionError(f"Default retraining example supplies {len(frame)} rows; reviewed fit population is 21024")
        model = real_train(data, artifact_dir)
        calls.append({"kind": "train", "input_rows": len(frame), "model_exists": Path(model).is_file()})
        return model

    solution.train = checked_train if spec["training"] else forbidden
    if not spec["training"]:
        lightgbm.LGBMRegressor.fit = forbidden
    real_predict = solution.predict

    def checked_predict(model_path, data):
        prediction = real_predict(model_path, data)
        assert isinstance(prediction, np.ndarray) and prediction.shape == (1,)
        assert np.isfinite(prediction).all()
        np.testing.assert_allclose(prediction[0], 4.0313233085425475, rtol=0, atol=1e-12)
        calls.append({"kind": "predict", "type": type(prediction).__name__, "shape": list(prediction.shape),
                      "value": float(prediction[0])})
        return prediction

    solution.predict = checked_predict
    exec(compile(spec["code"], str(spec_path), "exec"), {"__name__": "__main__"})
    outputs = []
    for path in Path(spec["workspace"]).rglob("submission.csv"):
        frame = pd.read_csv(path)
        assert list(frame.columns) == ["timestamp", "Usage_kWh"] and len(frame) == 1
        assert pd.to_datetime(frame["timestamp"], format="%d/%m/%Y %H:%M").iloc[0] == pd.Timestamp("2019-01-01")
        np.testing.assert_allclose(frame["Usage_kWh"].iloc[0], 4.0313233085425475, rtol=0, atol=1e-12)
        outputs.append(str(path))
    assert calls and (spec["training"] or outputs)
    save(spec_path.with_name("execution-result.json"), {"passed": True, "calls": calls, "outputs": outputs})


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
    if psutil.virtual_memory().available < 13 * 1024 ** 3:
        raise RuntimeError("Report verification requires 13 GiB free memory")
    limiter = WindowsJobMemoryLimiter(4 * 1024 ** 3)
    limiter.attach(os.getpid())
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[-4:])
    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4", MKL_NUM_THREADS="4", PYTHONUTF8="1")
    original = Path(read(OUT / "batch-state.json")["tasks"]["steel"]["auto_ml_workspace_dir"])
    report_path = args.directory / "report.md"
    report = report_path.read_text(encoding="utf-8")
    dest = OUT / "optimization-validation" / f"steel-report-examples-{time.time_ns()}"
    dest.mkdir(parents=True)
    tokens = MarkdownIt("commonmark").parse(report)
    findings, examples = [], []
    section = ""
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2":
            section = tokens[index + 1].content
        for inline in token.children or []:
            if inline.type == "code_inline" and Path(inline.content).is_absolute() and not Path(inline.content).exists():
                findings.append({"section": section, "kind": "missing_literal_path", "value": inline.content})
        if token.type != "fence" or token.info.strip() != "python":
            continue
        tree = ast.parse(token.content)
        if not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)):
            continue
        run = dest / f"example-{len(examples) + 1}"
        relocated = run / "workspace"
        relocated.mkdir(parents=True)
        shutil.copytree(original / "best_solution", relocated / "best_solution", ignore=shutil.ignore_patterns("__pycache__"))
        (relocated / "input").mkdir()
        shutil.copy2(original / "input/Steel_industry_data.csv", relocated / "input/Steel_industry_data.csv")

        class Relocate(ast.NodeTransformer):
            def visit_Constant(self, node):
                if isinstance(node.value, str) and node.value.startswith(str(original)):
                    node.value = str(relocated) + node.value[len(str(original)):]
                return node

        training = any(isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "train"
            or isinstance(node.func, ast.Attribute) and node.func.attr == "train") for node in ast.walk(tree))
        code = ast.unparse(ast.fix_missing_locations(Relocate().visit(tree)))
        spec_path = run / "example.json"
        save(spec_path, {"original_code": token.content, "code": code, "workspace": str(relocated), "training": training})
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(spec_path)],
                                cwd=run, capture_output=True, text=True, encoding="utf-8", timeout=120)
        (run / "execution.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        examples.append({"section": section, "line": token.map[0] + 1, "training": training,
                         "passed": result.returncode == 0, "directory": str(run),
                         "error": result.stderr.splitlines()[-1] if result.returncode else None})
    result = {"passed": bool(examples) and all(item["passed"] for item in examples) and not findings,
              "report": str(report_path), "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
              "examples": examples, "findings": findings, "holdout_evaluated": False,
              "scope": "Exact report snippets parsed as Python; only absolute workspace literals relocated. Official workspace unchanged. Training population checked before any fitting; inference forbids fitting and final evaluation."}
    save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

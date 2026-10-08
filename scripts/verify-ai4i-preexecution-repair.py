"""Exercise a repaired AI4I candidate under explicit holdout and resource guards."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time

os.environ.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from utils.resource_limits import WindowsJobMemoryLimiter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--mode", choices=("interfaces", "development", "reuse"), default="interfaces")
    parser.add_argument("--development-evidence", type=Path)
    args = parser.parse_args()
    args.source = args.source.resolve()
    if args.development_evidence:
        args.development_evidence = args.development_evidence.resolve()
    limiter = WindowsJobMemoryLimiter(4 * 1024 ** 3)
    limiter.attach(os.getpid())
    import numpy as np
    import pandas as pd
    import psutil
    from sklearn.metrics import average_precision_score
    from sklearn.model_selection import train_test_split
    from engine.solution_protocol import interface_for, preflight_code

    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[:2])
    dest = OUT / "optimization-validation" / f"ai4i-preexecution-{args.mode}-{time.time_ns()}"
    dest.mkdir(parents=True)
    source_copy = dest / "exported/solution.py" if args.mode == "reuse" else dest / "solution.py"
    source_copy.parent.mkdir(exist_ok=True)
    shutil.copy2(args.source, source_copy)
    spec = importlib.util.spec_from_file_location("ai4i_interface_probe", source_copy)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    task = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["ai4i"]
    source_csv = Path(task["auto_ml_workspace_dir"]) / "input/ai4i2020.csv"
    frame = pd.read_csv(source_csv)
    y = frame["Machine failure"].to_numpy()
    remaining, holdout = train_test_split(np.arange(len(frame)), test_size=.2, stratify=y, random_state=20260907)
    train, development = train_test_split(remaining, test_size=.25, stratify=y[remaining], random_state=20260907)
    train, development = np.sort(train), np.sort(development)
    train_ids = set(frame.iloc[train]["UDI"])
    development_ids = set(frame.iloc[development]["UDI"])
    calls = {"fit": 0, "predict": 0}
    failures = []
    checks = {}
    started = time.monotonic()
    preflight = preflight_code(source_copy.read_text(encoding="utf-8"),
                              interface_for(task_family="prediction", method_family="tree_boosting"),
                              require_final_evaluation=True)

    def forbid(*args, **kwargs):
        raise AssertionError("Model fitting, configuration search and holdout prediction are forbidden in this interface-only probe")

    if args.mode == "interfaces":
        module._fit_spec = module._predict_spec = module._candidate_specs = forbid
        blank_input, blank_output = dest / "empty_input", dest / "empty_artifacts"
        blank_input.mkdir()
        blank_output.mkdir()
        try:
            module.final_evaluate(blank_input, blank_output)
        except FileNotFoundError as exc:
            checks["final_input_directory"] = {"passed": True, "scope": "Directory accepted; missing files refused before model execution", "detail": str(exc)}
        except Exception as exc:
            failures.append({"entrypoint": "final_evaluate(data, artifact_dir)", "error": f"{type(exc).__name__}: {exc}",
                             "required_fix": "data is a Path to the complete input DIRECTORY. Resolve source files and parse them before dataframe validation; preserve two-argument signature and frozen recipe."})
        else:
            failures.append({"entrypoint": "final_evaluate", "error": "Empty input was not rejected"})
        try:
            module.train(frame.iloc[train].copy(), dest / "fresh_training_output")
        except Exception as exc:
            failures.append({"entrypoint": "train(data, fresh_artifact_dir)", "error": f"{type(exc).__name__}: {exc}",
                             "required_fix": "Load the already selected exported recipe relative to the solution. Do not enumerate/reselect candidate configs. Fit that fixed recipe on supplied training data and save to a fresh output directory."})
        else:
            failures.append({"entrypoint": "train", "error": "Training returned without the required fitter; investigate artifact validity"})
    elif args.mode == "reuse":
        if not args.development_evidence:
            parser.error("reuse requires --development-evidence")
        from agents.code_review_agent import validate_review_edit_scope
        import joblib
        prior = json.loads(args.development_evidence.read_text(encoding="utf-8"))
        assert prior["passed"] and prior["mode"] == "development"
        assert hashlib.sha256(Path(prior["source"]).read_bytes()).hexdigest() == prior["source_sha256"]
        validate_review_edit_scope(Path(prior["source"]).read_text(encoding="utf-8"),
                                   source_copy.read_text(encoding="utf-8"),
                                   ["train", "final_evaluate", "_load_exported_recipe"])
        working = source_copy.parent / "runtime/working"
        shutil.copytree(args.development_evidence.parent / "working", working)
        recipe = json.loads((working / "selected_recipe.json").read_text(encoding="utf-8"))
        checks["validated_search_and_features_unchanged"] = True
        checks["development_evidence"] = str(args.development_evidence.resolve())
        original_fit, original_predict = module._fit_spec, module._predict_spec

        def checked_fit(spec, data, labels, *values, **keywords):
            assert set(data["UDI"]) <= train_ids, "Reusable training accessed non-training rows"
            assert spec["candidate_id"] == recipe["candidate_id"] and spec["params"] == recipe["params"], "Retraining changed selected recipe"
            calls["fit"] += 1
            return original_fit(spec, data, labels, *values, **keywords)
        def checked_predict(spec, model, data, *values, **keywords):
            assert set(data["UDI"]) <= train_ids | development_ids, "Prediction accessed holdout rows"
            calls["predict"] += 1
            return original_predict(spec, model, data, *values, **keywords)
        caller = dest / "unrelated_caller"
        caller.mkdir()
        os.chdir(caller)
        module._candidate_specs = forbid
        module._fit_spec, module._predict_spec = checked_fit, checked_predict
        fresh_model = module.train(frame.iloc[train].copy(), dest / "fresh_training_output")
        checks["fresh_directory_training"] = {"passed": True, "model_exists": Path(fresh_model).is_file(),
                                               "selected_candidate": recipe["candidate_id"], "fit_calls": calls["fit"]}
        module._fit_spec = forbid
        features = frame.iloc[development][["UDI"] + module.FEATURE_COLUMNS].copy()
        output = module.predict(fresh_model, features)
        previous = pd.read_csv(working / "validation_predictions.csv")
        previous = previous.loc[previous["candidate_id"].eq(recipe["candidate_id"]) & previous["split"].eq("development")].sort_values("row_position")
        np.testing.assert_allclose(output["failure_probability"], previous["failure_probability"], atol=1e-12, rtol=0)
        np.testing.assert_array_equal(output["predicted_failure"], previous["predicted_failure"])
        np.testing.assert_array_equal(output["UDI"], previous["UDI"])
        new_path = dest / "development_features_only.csv"
        features.to_csv(new_path, index=False)
        sys.argv = [str(source_copy), "--infer", str(new_path), "--model-path", str(fresh_model), "--output-dir", str(dest / "inference_output")]
        with redirect_stdout(io.StringIO()):
            module.main()
        pd.testing.assert_frame_equal(pd.read_csv(dest / "inference_output/predictions.csv"), output.reset_index(drop=True), check_exact=False, atol=1e-12, rtol=0)
        checks["independent_cli_and_python_inference"] = {"passed": True, "rows": len(output), "no_training": True,
                                                          "scope": "development_validation_only"}
        blank_input = dest / "empty_input"
        blank_input.mkdir()
        try:
            module.final_evaluate(blank_input, dest / "empty_final_output")
        except FileNotFoundError:
            checks["empty_final_input_refused"] = True
        else:
            raise AssertionError("Final entrypoint did not reject missing source files")
        class FinalFitBoundaryReached(Exception):
            pass
        def final_boundary(spec, data, labels, *values, **keywords):
            assert set(data["UDI"]) in (train_ids, train_ids | development_ids)
            assert spec["candidate_id"] == recipe["candidate_id"] and spec["params"] == recipe["params"]
            raise FinalFitBoundaryReached()
        final_artifacts = dest / "final_interface_artifacts"
        shutil.copytree(working, final_artifacts)
        module._fit_spec = final_boundary
        module._predict_spec = forbid
        try:
            module.final_evaluate(source_csv.parent, final_artifacts)
        except FinalFitBoundaryReached:
            checks["final_directory_adapter_and_frozen_recipe"] = {"passed": True, "stopped_before_any_final_fit": True,
                                                                  "holdout_predictions_or_metrics": False}
        else:
            raise AssertionError("Final directory adapter did not reach the controlled pre-fit boundary")
    else:
        original_fit, original_predict = module._fit_spec, module._predict_spec
        def checked_fit(recipe, data, labels, *values, **keywords):
            assert set(data["UDI"]) <= train_ids, "Search fit accessed non-training rows"
            calls["fit"] += 1
            return original_fit(recipe, data, labels, *values, **keywords)
        def checked_predict(recipe, model, data, *values, **keywords):
            assert set(data["UDI"]) <= train_ids | development_ids, "Search prediction accessed holdout rows"
            calls["predict"] += 1
            return original_predict(recipe, model, data, *values, **keywords)
        module._fit_spec, module._predict_spec = checked_fit, checked_predict
        module.final_evaluate = forbid
        input_dir, working = dest / "input", dest / "working"
        input_dir.mkdir()
        shutil.copy2(source_csv, input_dir / source_csv.name)
        for name in ("description.md", "autorealize_context.md"):
            original = source_csv.parent / name
            if original.is_file():
                shutil.copy2(original, input_dir / name)
        captured = io.StringIO()
        with redirect_stdout(captured):
            module._run_training_and_evaluation(input_dir, working, output_dir=dest / "submission")
        (dest / "execution.log").write_text(captured.getvalue(), encoding="utf-8")
        predictions = pd.read_csv(working / "validation_predictions.csv")
        assert set(predictions["split"]) == {"train", "development"}
        scores = {}
        for candidate, rows in predictions.loc[predictions["split"].eq("development")].groupby("candidate_id"):
            rows = rows.sort_values("row_position")
            np.testing.assert_array_equal(rows["row_position"], development)
            np.testing.assert_array_equal(rows["UDI"], frame.iloc[development]["UDI"])
            np.testing.assert_array_equal(rows["y_true"], y[development])
            scores[candidate] = float(average_precision_score(y[development], rows["failure_probability"]))
        metadata = json.loads((working / "metrics.json").read_text(encoding="utf-8"))
        selected = metadata["selected_candidate_id"]
        np.testing.assert_allclose(scores[selected], metadata["selected_development_ap"], atol=1e-12, rtol=0)
        module._fit_spec = forbid
        features = frame.iloc[development][["UDI"] + module.FEATURE_COLUMNS].copy()
        output = module.predict(working / "model_artifact.joblib", features)
        assert list(output.columns) == ["UDI", "failure_probability", "predicted_failure"]
        np.testing.assert_array_equal(output["UDI"], features["UDI"])
        np.testing.assert_allclose(average_precision_score(y[development], output["failure_probability"]), scores[selected], atol=1e-12, rtol=0)
        checks.update(development_scores=scores, selected_candidate=selected, fit_predict_calls=calls,
                      no_holdout_fit_or_prediction=True, no_final_evaluation=True, inference_without_fitting=True)
    result = {"stage": "automl", "slug": "ai4i", "mode": args.mode, "passed": preflight.ok and not failures,
              "source": str(args.source.resolve()), "source_sha256": hashlib.sha256(source_copy.read_bytes()).hexdigest(),
              "data_sha256": hashlib.sha256(source_csv.read_bytes()).hexdigest(), "preflight": preflight.__dict__,
              "checks": checks, "failures": failures, "seconds": time.monotonic() - started,
              "resource_guard": limiter.describe(), "peak_memory_bytes": limiter.peak_memory_bytes(),
              "scope": "Independent repair verification only. No final holdout evaluation; not an accepted three-hour search."}
    (dest / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(dest), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Stage and publish a verified inference-only repair without repeating final evaluation."""
import argparse
from contextlib import nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from agents.code_review_agent import validate_review_edit_scope
from engine.executor import Interpreter
from engine.solution_package import package_final_solution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-result", type=Path)
    parser.add_argument("--development-verification", type=Path)
    parser.add_argument("--apply", type=Path)
    parser.add_argument("--final-verification", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("traffic_export_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    # Preparation writes a unique isolated export; only publication mutates shared artifacts.
    with stages.admission_lock() if args.apply else nullcontext():
        task = stages.current_task("traffic")
        stages.verified_search_seconds(task)
        if task["status"] == "running":
            raise RuntimeError("Wait for the selected candidate's final evaluation to finish")
        workspace, logs = Path(task["auto_ml_workspace_dir"]), Path(task["auto_ml_log_dir"])
        final, exported = workspace / "final_evaluation", workspace / "best_solution"
        state = stages.read_json(final / "status.json")
        assert state["status"] == "completed"
        frozen = stages.fingerprint([logs / "journal.json", logs / "search_state.json", final / "status.json",
                                     final / "result.json", final / "selected_solution.py"])
        if args.apply:
            receipt = stages.read_json(args.apply)
            verification = stages.read_json(args.final_verification)
            prepared = Path(receipt["prepared_export"])
            assert prepared.resolve().is_relative_to((stages.batch.OUT / "optimization-validation").resolve())
            assert receipt["frozen_evaluation_fingerprint"] == frozen
            assert verification.get("passed") is True and verification["node"] == state["selection"]["node_id"]
            assert Path(verification["export_dir"]).resolve() == prepared.resolve()
            assert verification["implementation_sha256"] == receipt["repaired_implementation_sha256"]
            assert stages.fingerprint(sorted(path for path in prepared.rglob("*") if path.is_file())) == receipt["prepared_fingerprint"]
            assert stages.fingerprint(sorted(path for path in exported.rglob("*") if path.is_file())) == receipt["original_export_fingerprint"]
            archive = stages.batch.OUT / "stage-archives/traffic" / f"before-inference-repair-{time.time_ns()}"
            archive.parent.mkdir(parents=True, exist_ok=True)
            assert exported.resolve().is_relative_to(stages.batch.OUT.resolve()) and archive.resolve().is_relative_to(stages.batch.OUT.resolve())
            exported.rename(archive)
            try:
                prepared.rename(exported)
            except BaseException:
                archive.rename(exported)
                raise
            receipt.update(applied=True, archive=str(archive), final_verification=str(args.final_verification))
            stages.batch.save(args.apply, receipt)
            print(json.dumps({"applied": True, "export": str(exported), "archive": str(archive)}))
            return
        if not args.review_result or not args.development_verification:
            parser.error("Preparation needs --review-result and --development-verification")
        review = stages.read_json(args.review_result)
        verification = stages.read_json(args.development_verification)
        node = next(row for row in stages.read_json(logs / "journal.json")["nodes"] if row["id"] == state["selection"]["node_id"])
        assert review.get("passed") is True and review["node"] == node["id"] == verification["node"]
        original = (args.review_result.parent / "original.py").read_text(encoding="utf-8")
        revised = (args.review_result.parent / "revised.py").read_text(encoding="utf-8")
        assert original == node["code"]
        assert hashlib.sha256(original.encode()).hexdigest() == review["original_sha256"] == state["selection"]["code_sha256"]
        assert hashlib.sha256(revised.encode()).hexdigest() == review["revised_sha256"] == verification["code_sha256"]
        validate_review_edit_scope(original, revised, ["_build_panel_from_raw_events"])
        checked = verification["inference"]
        assert verification.get("passed") is True and verification["source_model_unchanged"]
        assert checked["raw_and_panel_equivalent"] and checked["training_forbidden"]
        assert len(checked["forecast_origins"]) >= 3 and checked["synthetic_future_events_ignored"] > 0
        isolated = lambda code: Interpreter.isolate_model_path(None, Interpreter.isolate_submission_path(None, code, node["id"]), node["id"])
        assert (final / "selected_solution.py").read_text(encoding="utf-8") == isolated(original)
        dest = stages.batch.OUT / "optimization-validation" / f"traffic-final-interface-repair-{time.time_ns()}"
        staging = dest / "workspace"
        prepared = staging / "best_solution"
        shutil.copytree(exported, prepared)
        (staging / "final_evaluation").mkdir()
        (staging / "final_evaluation/selected_solution.py").write_text(isolated(revised), encoding="utf-8")
        package_final_solution(staging, state)
        manifest_path = prepared / "solution_manifest.json"
        manifest = stages.read_json(manifest_path)
        repaired_hash = digest(prepared / manifest["implementation_path"])
        manifest["inference_repair"] = {
            "scope": "Raw-event history input adapter only. Frozen training, model selection, model bytes and final scores unchanged.",
            "allowed_functions": ["_build_panel_from_raw_events"], "production_review": str(args.review_result),
            "development_verification": str(args.development_verification),
            "original_executed_code_sha256": state["executed_code_sha256"], "repaired_implementation_sha256": repaired_hash,
        }
        stages.batch.save(manifest_path, manifest)
        receipt = {"node": node["id"], "applied": False, "prepared_export": str(prepared),
                   "frozen_evaluation_fingerprint": frozen, "repaired_implementation_sha256": repaired_hash,
                   "original_export_fingerprint": stages.fingerprint(sorted(path for path in exported.rglob("*") if path.is_file())),
                   "prepared_fingerprint": stages.fingerprint(sorted(path for path in prepared.rglob("*") if path.is_file())),
                   "final_evaluation_repeated": False}
        stages.batch.save(dest / "receipt.json", receipt)
        print(json.dumps({"receipt": str(dest / "receipt.json"), "prepared_export": str(prepared), "applied": False}))


if __name__ == "__main__":
    main()

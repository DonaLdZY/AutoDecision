"""Attach independent score/API evidence to completed final exports for reporting."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--score-result", type=Path, required=True)
    parser.add_argument("--inference-result", type=Path, required=True)
    parser.add_argument("--retraining-result", type=Path)
    parser.add_argument("--numerical-threads", type=int, default=18)
    args = parser.parse_args()
    if args.numerical_threads < 1:
        parser.error("--numerical-threads must be positive")
    spec = importlib.util.spec_from_file_location("record_final_stages", Path(__file__).with_name("industrial-stage-control.py"))
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    with stages.admission_lock():
        task = stages.current_task(args.slug)
        elapsed = stages.verified_search_seconds(task)
        assert task["status"] != "running"
        workspace = Path(task["auto_ml_workspace_dir"])
        final, exported = workspace / "final_evaluation", workspace / "best_solution"
        status = stages.read_json(final / "status.json")
        assert status["status"] == "completed"
        score = stages.read_json(args.score_result)
        inference = stages.read_json(args.inference_result)
        node_id = status["selection"]["node_id"]
        assert score["passed"] is True and inference["passed"] is True
        assert score.get("phase") == "final" and score["node"] == inference["node"] == node_id
        manifest = stages.read_json(exported / "solution_manifest.json")
        assert manifest["node_id"] == node_id
        implementation = exported / manifest["implementation_path"]
        assert hashlib.sha256(implementation.read_bytes()).hexdigest() == inference["implementation_sha256"]
        source_model = exported / (exported / "model_path.txt").read_text(encoding="utf-8").strip()
        assert hashlib.sha256(source_model.read_bytes()).hexdigest() == inference["model_sha256"]
        retraining = stages.read_json(args.retraining_result) if args.retraining_result else None
        if retraining:
            assert retraining["passed"] is True and retraining["node"] == node_id
            assert retraining["inference"]["retrained_on_training_split_only"]
        verification = {"passed": True, "node_id": node_id, "search_elapsed_seconds": elapsed,
            "final_score_verification": score, "inference_verification": inference["inference"],
            "model_sha256": inference["model_sha256"], "implementation_sha256": inference["implementation_sha256"],
            "retraining_verification": retraining["inference"] if retraining else {"status": "not_independently_tested"},
            "reproducibility_environment": {name: args.numerical_threads for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
            "reproducibility_note": "Match original numerical thread counts for training reproduction. Inference-only checks use2threads. Lower-thread retraining can differ at numerical solver precision; do not claim bitwise portability across numerical environments.",
            "evidence_paths": [str(path) for path in (args.score_result, args.inference_result, args.retraining_result) if path],
            "final_evaluation_repeated": False, "search_and_final_model_bytes_unchanged": True}
        stages.batch.save(exported / "inference-verification.json", verification)
        stages.batch.save(final / "independent-verification.json", verification)
        status.update(independent_verification="passed", independent_verification_path=str(final / "independent-verification.json"))
        stages.batch.save(final / "status.json", status)
        stages.batch.save(exported / "final_evaluation/status.json", status)
        print(json.dumps({"passed": True, "node_id": node_id, "path": str(final / "independent-verification.json")}))


if __name__ == "__main__":
    main()

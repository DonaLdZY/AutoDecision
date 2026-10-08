"""Register independently reviewed AutoReport outputs without repeating generation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend/backend"))
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from report_recovery import REPORT_FILES, config_digest, file_digest, validate_report_recovery
from autoreport.config import load_config
from autoreport.generator import _validate_report_article


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--review-file", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    stages = runpy.run_path(str(Path(__file__).with_name("industrial-stage-control.py")))
    with stages["admission_lock"]():
        task = stages["current_task"](args.slug)
        if task["status"] == "running":
            raise RuntimeError("Wait for the active task stage before report registration")
        review = stages["read_json"](args.review_file)
        if review.get("passed") is not True:
            raise RuntimeError("An independently passed report review is required")
        for field in ("strengths", "weaknesses", "system_changes", "constraint_checks", "quality_checks", "usage_analysis", "evidence_paths"):
            if not review.get(field):
                raise RuntimeError(f"Report review must include {field}")
        artifacts = []
        for stage in ("autorealize", "automl"):
            files = stages["stage_artifacts"](task, stage)
            if review.get(stage + "_artifact_fingerprint") != stages["fingerprint"](files):
                raise RuntimeError(f"Report review does not match current {stage} evidence")
            artifacts.extend(files)
        stages["verified_search_seconds"](task)
        report = Path(task["run_dir"]) / "report"
        report_sha = {name: file_digest(report / name) for name in REPORT_FILES}
        if report_sha != review.get("report_sha256"):
            raise RuntimeError("Installed report differs from the independently reviewed report")
        cfg = load_config(report / "resolved_config.yaml")
        _validate_report_article(cfg, (report / "report.md").read_text(encoding="utf-8-sig"), require_outline=True)
        for evidence in review["evidence_paths"]:
            if not Path(evidence).is_file():
                raise RuntimeError(f"Missing independent review evidence: {evidence}")
        independent = report / "independent-review.json"
        if independent.resolve() != args.review_file.resolve():
            shutil.copy2(args.review_file, independent)
        receipt = {
            "passed": True, "task_id": task["id"],
            "task_config_sha256": config_digest(task["config"]),
            "report_sha256": report_sha,
            "evidence_sha256": {str(path.resolve()): file_digest(path) for path in artifacts},
            "independent_review": {"path": str(independent.resolve()), "sha256": file_digest(independent)},
        }
        stages["batch"].save(report / "recovery-review.json", receipt)
        validate_report_recovery(task, report)
        if args.apply:
            response = stages["batch"].request("/api/tasks/recover-report", {"task_id": task["id"], "confirm": True})
            stages["record_review"](args.slug, "report", independent)
            print(json.dumps(response, ensure_ascii=False))
        else:
            print(json.dumps({"ready": True, "task_id": task["id"], "report_dir": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

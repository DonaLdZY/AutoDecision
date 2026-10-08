"""Validate a reviewed report against the task and the evidence it describes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPORT_FILES = ("report.md", "report.json", "report_trace.json")


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def config_digest(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_report_recovery(task: dict, report_dir: Path) -> dict:
    if task.get("status") == "running" or task.get("phase") not in {
        "automl_completed", "report_failed", "report_completed",
    }:
        raise ValueError("Report recovery requires a completed search and an idle task")
    root = Path(task["run_dir"]).resolve()
    report_dir = report_dir.resolve()
    if report_dir != root / "report":
        raise ValueError("Recovered report must be in this task's report directory")
    receipt = json.loads((report_dir / "recovery-review.json").read_text(encoding="utf-8-sig"))
    if not isinstance(receipt, dict) or receipt.get("passed") is not True or receipt.get("task_id") != task["id"]:
        raise ValueError("Report recovery review is absent or belongs to another task")
    if receipt.get("task_config_sha256") != config_digest(task["config"]):
        raise ValueError("Task configuration changed after report review")
    declared_reports = receipt.get("report_sha256", {})
    if not isinstance(declared_reports, dict) or set(declared_reports) != set(REPORT_FILES):
        raise ValueError("Every final report artifact must be reviewed")
    for name in REPORT_FILES:
        if declared_reports[name] != file_digest(report_dir / name):
            raise ValueError(f"Report artifact changed after review: {name}")
    document = json.loads((report_dir / "report.json").read_text(encoding="utf-8-sig"))
    markdown = (report_dir / "report.md").read_text(encoding="utf-8-sig")
    if not isinstance(document, dict) or not markdown.strip() or str(document.get("article_markdown") or "").strip() != markdown.strip():
        raise ValueError("Report JSON and Markdown do not contain the same complete article")
    trace = json.loads((report_dir / "report_trace.json").read_text(encoding="utf-8-sig"))
    audit = trace.get("audit", {}) if isinstance(trace, dict) else {}
    if not isinstance(audit, dict) or audit.get("status") not in {"pass", "revised"} or audit.get("complete_draft_covered") is not True:
        raise ValueError("The complete report has not passed its audit")
    evidence = receipt.get("evidence_sha256", {})
    if not isinstance(evidence, dict):
        raise ValueError("Recovery source evidence must be a fingerprint mapping")
    allowed_roots = (root, Path(task["input_root"]).resolve())
    required = {root / "autorealize/description.md",
                root / "autorealize/realize_report/automl_context_pack.json"}
    if not task.get("auto_ml_log_dir"):
        raise ValueError("Completed search evidence is unavailable")
    logs = Path(task["auto_ml_log_dir"]).resolve()
    run_status = json.loads((logs / "run_status.json").read_text(encoding="utf-8-sig"))
    if not isinstance(run_status, dict) or run_status.get("status") != "completed":
        raise ValueError("Search has not completed")
    required.update(logs / name for name in ("run_status.json", "search_state.json", "journal.json"))
    resolved_evidence = {Path(name).resolve(): digest for name, digest in evidence.items()}
    if not required.issubset(resolved_evidence):
        raise ValueError("Recovery review omits task definition or search evidence")
    for path, expected in resolved_evidence.items():
        if not any(path.is_relative_to(parent) for parent in allowed_roots):
            raise ValueError("Recovery evidence is outside the task's input and output directories")
        if file_digest(path) != expected:
            raise ValueError(f"Report source evidence changed: {path.name}")
    independent = receipt.get("independent_review", {})
    if not isinstance(independent, dict):
        raise ValueError("Independent review evidence must be specified")
    review_path = Path(independent.get("path", "")).resolve()
    if (not review_path.is_relative_to(report_dir)
            or independent.get("sha256") != file_digest(review_path)):
        raise ValueError("Independent review evidence is missing or changed")
    review = json.loads(review_path.read_text(encoding="utf-8-sig"))
    if not isinstance(review, dict) or review.get("passed") is not True:
        raise ValueError("Independent report review did not pass")
    return receipt

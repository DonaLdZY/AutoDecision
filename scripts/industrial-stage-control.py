"""Start one real service stage only after its input and prior stage were reviewed."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from contextlib import contextmanager
from pathlib import Path
import shutil
import sys
import time

import psutil

SPEC = importlib.util.spec_from_file_location("industrial_batch", Path(__file__).with_name("industrial-examples.py"))
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)
sys.path.insert(0, str(batch.ROOT / "core/AlgoEvolve"))
from utils.resource_limits import host_commit_available_bytes
STAGES = ("autorealize", "automl", "report")
LEDGER = batch.OUT / "stage-reviews.json"


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def fingerprint(paths):
    digest = hashlib.sha256()
    for path in sorted(paths, key=str):
        if not path.is_file():
            raise RuntimeError(f"Missing reviewed artifact: {path}")
        digest.update(str(path.resolve()).encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def stage_artifacts(task, stage):
    root = Path(task["run_dir"])
    if stage == "autorealize":
        required = {root / "autorealize/description.md", root / "autorealize/realize_report/automl_context.md",
                    root / "autorealize/realize_report/evaluation_contract_report.json"}
        return sorted(required | {path for path in (root / "autorealize/realize_report").rglob("*")
                                  if path.is_file() and path.suffix in {".json", ".md"}})
    if stage == "automl":
        logs = Path(task["auto_ml_log_dir"])
        paths = [logs / name for name in ("run_status.json", "search_state.json", "journal.json")] + sorted(
            path for path in logs.rglob("*") if path.is_file() and path.suffix in {".py", ".yaml"}
        )
        workspace = task.get("auto_ml_workspace_dir")
        if workspace:
            workspace_root = Path(workspace)
            for path in workspace_root.rglob("*"):
                parts = path.relative_to(workspace_root).parts
                # Superseded input layouts may contain broken directory junctions.
                # Active inputs, predictions, code and model bytes remain mandatory.
                if parts[0].startswith("input-before-layout-repair-") or "__pycache__" in parts:
                    continue
                if path.is_file():
                    paths.append(path)
        return sorted(set(paths))
    return [Path(task["report_dir"]) / "report.md", Path(task["report_dir"]) / "report_trace.json"]


def current_task(slug):
    state = batch.load_state()
    task_id = state["tasks"][slug]["id"]
    return next(task for task in batch.request("/api/tasks") if task["id"] == task_id)


def task_definition_source_artifacts(task):
    if task.get("phase") not in {"autorealize_failed", "stopped"}:
        return stage_artifacts(task, "autorealize")
    root = Path(task["run_dir"]) / "autorealize"
    required = [root / "realize_report/data_cognition_report.json", root / "realize_report/original_requirements.txt"]
    return sorted(set(required) | {path for path in root.rglob("*")
                                  if path.is_file() and ("data" in path.relative_to(root).parts
                                                       or path.suffix in {".json", ".md"})})


def recovered_task_definition_completed(task):
    if task.get("status") == "running" or task.get("phase") not in {
        "autorealize_failed", "stopped", "prepare_automl_input_failed",
    }:
        return False
    receipt = read_json(Path(task["run_dir"]) / "task-definition-recovery.json", {})
    if receipt.get("passed") is not True:
        return False
    verify_task_definition(task)
    return receipt.get("artifact_fingerprint") == fingerprint(stage_artifacts(task, "autorealize"))


def validate_optimization_review():
    review = read_json(batch.OUT / "optimization-review.json", {})
    if review.get("status") != "passed" or set(review.get("stages_reviewed", [])) != set(STAGES):
        raise RuntimeError("Complete and record the three-stage prompt/workflow optimization before starting examples")
    for path, expected in review.get("reviewed_files", {}).items():
        actual = hashlib.sha256((batch.ROOT / path).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Prompt/code changed since optimization verification: {path}")
    if not review.get("reviewed_files") or not review.get("verification_evidence"):
        raise RuntimeError("Optimization review needs source fingerprints and actual verification evidence")
    for evidence in review["verification_evidence"]:
        if not (batch.ROOT / evidence).is_file():
            raise RuntimeError(f"Missing optimization verification evidence: {evidence}")


def verified_search_seconds(task):
    logs = Path(task["auto_ml_log_dir"])
    status = read_json(logs / "run_status.json", {})
    state = read_json(logs / "search_state.json", {})
    elapsed = float(state.get("cumulative_search_elapsed_seconds", 0))
    if not math.isfinite(elapsed) or elapsed < 0:
        raise RuntimeError("Invalid durable search duration")
    if status.get("status") != "completed" or elapsed < 10800:
        raise RuntimeError(f"Three hours of completed search required; durable duration={elapsed:.2f}s")
    return elapsed


def verify_task_definition(task):
    report_dir = Path(task["run_dir"]) / "autorealize/realize_report"
    contract = read_json(report_dir / "evaluation_contract_report.json", {}).get("final", {})
    audit = read_json(report_dir / "artifact_consistency_report.json", {}).get("final", {})
    report = read_json(report_dir / "task_definition_report.json", {})
    protocol = read_json(report_dir / "main_task_protocol.json", {})
    context = read_json(report_dir / "automl_context_pack.json", {})
    if contract.get("passed") is not True or contract.get("executable") is not True:
        raise RuntimeError("Task evaluation contract did not pass executable validation")
    if audit.get("passed") is not True or any(issue.get("severity") == "blocking" for issue in audit.get("issues", [])):
        raise RuntimeError("Final artifact consistency audit has not passed")
    if report.get("defects_after_gate") or context.get("execution_contract", {}).get("readiness") == "blocked":
        raise RuntimeError("Task definition has unresolved execution blockers")
    if any(value != contract for value in (report.get("evaluation_contract"), protocol.get("evaluation_contract"))):
        raise RuntimeError("Task evaluation contract copies disagree")
    if any(context.get("evaluation_contract", {}).get(key) != value for key, value in contract.items()):
        raise RuntimeError("AutoML context does not contain the accepted evaluation contract")


@contextmanager
def admission_lock():
    path = batch.OUT / "stage-admission.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Another stage admission is in progress; inspect stage-admission.lock") from None
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def start(slug, stage, *, resume=False):
    validate_optimization_review()
    validate_provider(batch.request("/api/settings/global"))
    state = batch.load_state()
    process = psutil.Process(state["pid"])
    if "industrial-examples.py" not in " ".join(process.cmdline()):
        raise RuntimeError("Guarded service supervisor is not running")
    profile = read_json(batch.OUT / "runtime-resource-profile.json", {})
    minimum_free = profile.get("minimum_free_gib_to_start", 13)
    if psutil.virtual_memory().available < minimum_free * batch.GIB:
        raise RuntimeError(f"Less than {minimum_free} GiB free system memory")
    commit_available = host_commit_available_bytes()
    if commit_available is not None and commit_available < minimum_free * batch.GIB:
        raise RuntimeError(f"Less than {minimum_free} GiB free system commit memory")
    tasks = batch.request("/api/tasks")
    task = current_task(slug)
    validate_concurrent_admission(tasks, task, profile)
    ledger = read_json(LEDGER, {})
    index = STAGES.index(stage)
    if index:
        previous = STAGES[index - 1]
        review = ledger.get(slug, {}).get(previous, {})
        if review.get("passed") is not True or review.get("artifact_fingerprint") != fingerprint(stage_artifacts(task, previous)):
            raise RuntimeError(f"Review the current {previous} artifacts before starting {stage}")
    if stage == "automl" and int(task["config"]["auto_ml"]["time_limit_secs"]) != 10800:
        raise RuntimeError("Every AutoML example must run a 10800-second search")
    elapsed = 0
    if resume and stage == "autorealize":
        if task["phase"] not in {"autorealize_failed", "stopped"}:
            raise RuntimeError("AutoRealize recovery requires a failed or stopped stage")
    elif resume:
        if stage != "automl" or not task.get("auto_ml_log_dir"):
            raise RuntimeError("Resume requires an existing AutoML search")
        if task["status"] == "completed":
            raise RuntimeError("The backend appends budget to completed jobs; inspect early completion before resuming")
        durable = read_json(Path(task["auto_ml_log_dir"]) / "search_state.json", {})
        elapsed = float(durable.get("cumulative_search_elapsed_seconds", 0))
        if not math.isfinite(elapsed) or elapsed >= 10800:
            raise RuntimeError("Search already exhausted its three-hour budget or has invalid timing")
    root = Path(task.get("run_dir") or (Path(task["output_root"]) / task["task_name"]))
    source = (root / stage).resolve()
    if not source.is_relative_to(batch.OUT.resolve()):
        raise RuntimeError(f"Stage path is outside this batch: {source}")
    if source.is_dir() and not resume:
        archive = batch.OUT / "stage-archives" / slug / f"{stage}-{time.time_ns()}"
        shutil.copytree(source, archive)
    endpoint = {"autorealize": "rerun-autorealize", "automl": "rerun-automl", "report": "rerun-autoreport"}[stage]
    if resume and stage == "automl":
        endpoint = "continue-automl"
    payload = {"task_id": task["id"], "confirm": True}
    if resume and stage == "autorealize":
        payload["preserve_cache"] = True
    response = batch.request("/api/tasks/" + endpoint, payload)
    stages = ledger.setdefault(slug, {})
    for invalidated in STAGES[index:]:
        stages.pop(invalidated, None)
    stages[stage] = {"passed": False, "status": "running", "started_at": time.time(), "task_id": task["id"],
                     "resumed": resume, "prior_search_seconds": elapsed if resume else 0}
    batch.save(LEDGER, ledger)
    deadline = time.monotonic() + 30
    while current_task(slug)["status"] != "running":
        if time.monotonic() >= deadline:
            raise RuntimeError("Stage launch acknowledged but no running state observed; inspect backend before retrying")
        time.sleep(0.2)
    print(json.dumps(response))


def validate_provider(settings):
    llm = settings["llm"]
    models = {item["id"]: item for item in llm["modelLibrary"]}
    for role in ("autoRealize", "autoMlCode", "autoMlFeedback"):
        model = models.get(llm["roleModels"].get(role), {})
        if (not str(model.get("model") or "").strip()
                or not str(model.get("baseUrl") or "").strip()
                or model.get("maxTokens") != 32768
                or not (model.get("apiKeyConfigured") or model.get("apiKey"))):
            raise RuntimeError(f"Configured provider/model/32768 output settings missing for {role}; refusing launch")


def validate_concurrent_admission(tasks, task, profile):
    if task["status"] == "running":
        raise RuntimeError("This task already has an active stage")
    active = [row for row in tasks if row["status"] == "running"]
    limit = int(profile.get("simultaneous_tasks", 1))
    if (batch.OUT / "execution-slots/reduced-to-one").exists():
        limit = min(limit, 2)
    if len(active) >= limit:
        raise RuntimeError("Concurrent task limit reached")
    allowed = profile.get("active_slugs")
    if allowed:
        approved_ids = {batch.load_state()["tasks"][slug]["id"] for slug in allowed}
        if task["id"] not in approved_ids:
            raise RuntimeError("Task is outside the current concurrent batch")


def record_review(slug, stage, path):
    task = current_task(slug)
    recovered = stage == "autorealize" and recovered_task_definition_completed(task)
    downstream_report = stage == "automl" and task["phase"] in {"report_failed", "report_completed"}
    if task["status"] == "running" or (task["phase"] != stage + "_completed" and not recovered and not downstream_report):
        raise RuntimeError("The requested real service stage has not completed")
    review = read_json(path, {})
    if type(review.get("passed")) is not bool:
        raise RuntimeError("Stage review passed must be a boolean")
    for field in ("strengths", "weaknesses", "system_changes", "constraint_checks", "quality_checks", "usage_analysis", "evidence_paths"):
        if not review.get(field):
            raise RuntimeError(f"Stage analysis must include {field}")
    if stage == "automl":
        review["verified_search_seconds"] = verified_search_seconds(task)
    if stage == "autorealize" and review["passed"]:
        verify_task_definition(task)
    for evidence in review["evidence_paths"]:
        if not Path(evidence).is_file():
            raise RuntimeError(f"Missing review evidence: {evidence}")
    review["artifact_fingerprint"] = fingerprint(stage_artifacts(task, stage))
    review["reviewed_at"] = time.time()
    ledger = read_json(LEDGER, {})
    ledger.setdefault(slug, {})[stage] = review
    batch.save(LEDGER, ledger)
    print(json.dumps({"slug": slug, "stage": stage, "passed": bool(review.get("passed"))}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "resume", "review", "status"))
    parser.add_argument("--slug", choices=("steel", "ai4i", "traffic", "chemical", "deposition", "delivery"))
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--review-file", type=Path)
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(read_json(LEDGER, {}), ensure_ascii=False, indent=2))
    elif not args.slug or not args.stage:
        parser.error("--slug and --stage are required")
    elif args.command in {"start", "resume"}:
        with admission_lock():
            start(args.slug, args.stage, resume=args.command == "resume")
    elif args.review_file:
        record_review(args.slug, args.stage, args.review_file)
    else:
        parser.error("review requires --review-file")


if __name__ == "__main__":
    main()

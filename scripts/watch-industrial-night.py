"""Persist bounded, credential-free runtime telemetry for the overnight stage reviews."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import psutil

SPEC = importlib.util.spec_from_file_location("night_stages", Path(__file__).with_name("industrial-stage-control.py"))
stages = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stages)
batch = stages.batch
sys.path.insert(0, str(batch.ROOT / "core/AlgoEvolve"))
from engine.execution_evidence import candidate_failure_evidence
from utils.resource_limits import host_commit_available_bytes

SLUGS = ("traffic", "chemical", "deposition", "delivery")
OOM = re.compile(r"out[ -]of[ -]memory|\bMemoryError\b|\bOutOfMemoryError\b|unable to allocate|cannot allocate memory|CUBLAS_STATUS_ALLOC_FAILED|cudaErrorMemoryAllocation|WinError 1455|paging file is too small", re.I)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def tail_rows(path, limit=30):
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - 512000))
            lines = stream.read().splitlines()
        if size > 512000:
            lines = lines[1:]
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
    except (OSError, ValueError):
        return []


def usage_summary(rows):
    paid = [row for row in rows if row.get("source") not in {"local_cache", "cache"}]
    total = sum(int(row.get("prompt_tokens") or 0) for row in paid)
    missing = [row for row in paid if row.get("prompt_usage_available") is False
               or (not row.get("prompt_tokens") and row.get("estimated_prompt_tokens", 0) > 0)]
    known_rows = [row for row in paid if (row.get("provider_cache_tokens_known") is True or row.get("cache_tokens_known") is True)
                  and int(row.get("prompt_tokens") or 0) > 0 and row not in missing]
    known = sum(int(row.get("prompt_tokens") or 0) for row in known_rows)
    cached = sum(int(row.get("prompt_cache_hit_tokens") or (row.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
                 for row in known_rows)
    failures = 0
    for row in reversed(paid):
        if row.get("parsed_ok") is False or row.get("finish_reason") in {"length", "max_tokens", "max_output_tokens", "provider_interrupted"}:
            failures += 1
        else:
            break
    return {"scope": "Latest 30 rows per active usage file, not lifetime totals", "calls": len(paid),
            "input_tokens": total, "max_input_tokens": max([int(row.get("prompt_tokens") or 0) for row in paid] or [0]),
            "input_usage_missing_calls": len(missing),
            "missing_input_tokens_estimate": sum(int(row.get("estimated_prompt_tokens") or 0) for row in missing),
            "max_missing_input_tokens_estimate": max([int(row.get("estimated_prompt_tokens") or 0) for row in missing] or [0]),
            "known_cache_hit_ratio": cached / known if known else None,
            "cache_telemetry_coverage": known / total if total and not missing else None,
            "known_input_cache_telemetry_coverage": known / total if total else None,
            "consecutive_failed_outputs": failures,
            "requested_models": sorted({str(row.get("requested_model") or row.get("model")) for row in paid}),
            "response_models": sorted({str(row.get("response_model")) for row in paid if row.get("response_model")}),
            "largest_requests": [{"prompt": row.get("prompt_name") or row.get("component"),
                                  "input_tokens": row.get("prompt_tokens"), "seconds": row.get("seconds"),
                                  "largest_part": max(row.get("prompt_parts") or [{}], key=lambda part: part.get("estimated_tokens", 0)).get("name")}
                                 for row in sorted(paid, key=lambda row: int(row.get("prompt_tokens") or 0), reverse=True)[:3]]}


def active_usage_paths(task, repair):
    root = Path(task["run_dir"])
    if repair and not repair.get("finished_at"):
        report = Path(repair["candidate"]) / "realize_report"
        sessions = list((report / "repair_usage").rglob("llm_usage.jsonl"))
        return sessions if sessions else [report / "llm_usage.jsonl"]
    phase = str(task.get("phase", ""))
    if phase.startswith("automl"):
        return [Path(task["auto_ml_log_dir"]) / "llm_usage.jsonl"] if task.get("auto_ml_log_dir") else []
    if phase.startswith("report"):
        directory = Path(task.get("report_dir") or root / "report")
        return [directory / "llm_usage.jsonl", *sorted(directory.glob("source-audit-*/llm_usage.jsonl"))]
    return [root / "autorealize/realize_report/llm_usage.jsonl"]


def node_memory_failure(task, node):
    if OOM.search(str(node.get("_term_out", ""))):
        return True
    workspace = task.get("auto_ml_workspace_dir")
    if not workspace or not node.get("id"):
        return False
    try:
        evidence = candidate_failure_evidence(workspace, node["id"])
    except (OSError, ValueError):
        return False
    return bool(evidence and OOM.search(json.dumps(evidence.get("content", {}))))


def snapshot():
    state = batch.load_state()
    tasks = {task["id"]: task for task in batch.request("/api/tasks")}
    profile = read_json(batch.OUT / "runtime-resource-profile.json", {})
    alerts, rows = [], []
    try:
        stages.validate_provider(batch.request("/api/settings/global"))
        provider_ok = True
    except RuntimeError:
        provider_ok = False
        alerts.append("provider_configuration_changed")
    free = psutil.virtual_memory().available / batch.GIB
    commit_available = host_commit_available_bytes()
    commit_free = commit_available / batch.GIB if commit_available is not None else None
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.free,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=5,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    gpu_values = [float(value.strip()) for value in gpu.stdout.splitlines()[0].split(",")] if gpu.returncode == 0 and gpu.stdout.strip() else []
    gpu_free = gpu_values[0] / 1024 if gpu_values else None
    if free < profile.get("emergency_free_gib", 2) + 1:
        alerts.append("host_memory_pressure")
    if commit_free is not None and commit_free < profile.get("emergency_free_gib", 2) + 1:
        alerts.append("host_commit_memory_pressure")
    if gpu_free is not None and gpu_free < profile.get("gpu_free_reserve_gib", 1) + .5:
        alerts.append("gpu_memory_pressure")
    if gpu_free is None:
        alerts.append("gpu_telemetry_unavailable")
    for slug in SLUGS:
        task = tasks[state["tasks"][slug]["id"]]
        root = Path(task["run_dir"])
        logs = Path(task["auto_ml_log_dir"]) if task.get("auto_ml_log_dir") else None
        repairs = sorted((batch.OUT / "stage-repairs").glob(slug + "-*/result.json"), key=lambda path: path.parent.name)
        repair = read_json(repairs[-1], {}) if repairs else {}
        repairing = bool(repair and not repair.get("finished_at"))
        usage_paths = active_usage_paths(task, repair)
        usage = usage_summary(sorted([row for path in usage_paths for row in tail_rows(path)], key=lambda row: row.get("ts", 0)))
        search = read_json(logs / "search_state.json", {}) if logs else {}
        journal = read_json(logs / "journal.json", {}) if logs else {}
        nodes = journal.get("nodes", [])
        consecutive = 0
        for node in reversed(nodes):
            if node.get("is_buggy") is True or node.get("is_valid") is False:
                consecutive += 1
            else:
                break
        if any(node_memory_failure(task, node) for node in nodes[-4:]):
            alerts.append(slug + ":memory_allocation_failure")
        if consecutive >= 3:
            alerts.append(slug + ":three_or_more_failed_candidates")
        if (task["status"] == "running" or repairing) and usage["max_input_tokens"] >= 65000:
            alerts.append(slug + ":large_prompt_requires_inspection")
        if (task["status"] == "running" or repairing) and usage["input_usage_missing_calls"]:
            alerts.append(slug + ":input_usage_unavailable")
            if usage["max_missing_input_tokens_estimate"] >= 65000:
                alerts.append(slug + ":large_estimated_prompt_requires_inspection")
        if usage["consecutive_failed_outputs"] >= 3:
            alerts.append(slug + ":repeated_output_failure")
        if task["status"] == "failed":
            alerts.append(slug + ":stage_failed")
        events = tail_rows(root / "autorealize/realize_report/trajectory_events.jsonl", 1)
        event = events[-1] if events else {}
        rows.append({"slug": slug, "status": task["status"], "phase": task["phase"],
                     "repair_running": repairing, "latest_repair_result": str(repairs[-1]) if repairs else None,
                     "search_seconds": search.get("cumulative_search_elapsed_seconds", 0),
                     "nodes": len(nodes), "consecutive_failed_nodes": consecutive, "usage": usage,
                     "last_event": {key: event.get(key) for key in ("ts", "stage", "kind")}})
    if any("memory_pressure" in item or "memory_allocation_failure" in item for item in alerts):
        (batch.OUT / "execution-slots/reduced-to-one").mkdir(parents=True, exist_ok=True)
    reduced = (batch.OUT / "execution-slots/reduced-to-one").exists()
    return {"updated_at": time.time(), "watcher_pid": os.getpid(), "provider_verified": provider_ok,
            "host_free_gib": round(free, 3), "cpu_percent": psutil.cpu_percent(),
            "host_commit_free_gib": round(commit_free, 3) if commit_free is not None else None,
            "gpu_free_gib": gpu_free, "gpu_utilization_percent": gpu_values[2] if gpu_values else None,
            "candidate_execution_limit": 1 if reduced else profile.get("gpu_execution_slots", 2),
            "task_admission_limit": min(2, profile.get("simultaneous_tasks", 3)) if reduced else profile.get("simultaneous_tasks", 3),
            "alerts": alerts, "tasks": rows,
            "stage_progression": "Actual stage reviews and repairs handled by this thread's existing 5-minute heartbeat"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("once", "run", "launch"))
    args = parser.parse_args()
    path = batch.OUT / "night-watch.json"
    if args.command == "launch":
        prior = read_json(path, {})
        pid = prior.get("watcher_pid")
        if pid and psutil.pid_exists(pid) and "watch-industrial-night.py" in " ".join(psutil.Process(pid).cmdline()):
            raise RuntimeError("Night watcher is already running")
        with (batch.OUT / "night-watch.log").open("a", encoding="utf-8") as stream:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run"], cwd=batch.ROOT,
                                     stdout=stream, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        print(json.dumps({"watcher_launcher_pid": child.pid}))
        return
    while True:
        try:
            result = snapshot()
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, path)
            if args.command == "once":
                print(json.dumps(result, ensure_ascii=False))
                return
        except Exception as exc:
            print(json.dumps({"time": time.time(), "monitor_error_type": type(exc).__name__}), flush=True)
            if args.command == "once":
                raise
        if (batch.OUT / "STOP-NIGHT-WATCH").exists():
            return
        time.sleep(20)


if __name__ == "__main__":
    main()

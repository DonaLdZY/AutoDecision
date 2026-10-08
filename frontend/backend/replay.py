"""Durable, sanitized observation history and conservative legacy reconstruction."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE_KEYS = {"data_cognition": "auto_realize", "task_definition": "auto_realize", "automl": "auto_ml", "report": "auto_report"}
PENDING = {"generating", "pending_execution", "executing", "reviewing"}
PRIVATE_KEYS = re.compile(r"api.?key|authorization|password|secret|access.?token|refresh.?token", re.I)
TOKEN_TEXT = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_.~+/-]{12,})", re.I)
ASSIGNMENT_TEXT = re.compile(r"((?:api[_-]?key|authorization|password|access[_-]?token)\s*[=:]\s*['\"]?)[^\s'\",;}]+", re.I)
AR_FIELDS = {
    "current_state", "frontend_manifest", "run_summary", "data_cognition_report",
    "question_investigation_report", "task_definition_report", "submission_report",
    "evaluation_contract_report", "main_task_protocol", "automl_context_pack",
    "directory_tree_text", "output_tree_text", "description_text", "data_description_text",
    "automl_context_text", "original_requirements_text", "file_cognition_index",
}
ML_FIELDS = {"engine", "resource_usage", "dependency_installation_summary", "best_solution_code", "best_metric_text"}
REPORT_FIELDS = {"current_state", "report", "report_markdown"}
CUMULATIVE_NODE_FIELDS = {"visits", "total_reward", "uct"}


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items() if not PRIVATE_KEYS.search(str(k)) and str(k) not in {"resolved_config", "config", "environment", "env"}}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return ASSIGNMENT_TEXT.sub(r"\1[REDACTED]", TOKEN_TEXT.sub("[REDACTED]", value))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def timestamp(value: Any, fallback: float) -> float:
    try:
        number = float(value)
        if math.isfinite(number) and number > 0:
            return number / 1000 if number > 100_000_000_000 else number
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def stage_of(value: Any, default: str = "data_cognition") -> str:
    text = str(value or "").lower()
    if "task_definition" in text or "stage.p2" in text:
        return "task_definition"
    if "automl" in text or "algoevolve" in text:
        return "automl"
    if "autorealize" in text or "data_cognition" in text or "stage.p1" in text:
        return "data_cognition"
    if "report" in text and "autorealize" not in text:
        return "report"
    return default


def safe_task(task: dict[str, Any]) -> dict[str, Any]:
    return sanitize({key: task.get(key) for key in ("id", "task_name", "status", "phase")})


def node_state(node: dict[str, Any]) -> dict[str, Any]:
    result = sanitize(node)
    sources = result.get("fusion_sources") or result.get("parent_ids") or []
    if not isinstance(sources, list):
        sources = []
    result["fusion_sources"] = list(dict.fromkeys(str(item) for item in sources if item))
    result["parent_ids"] = list(dict.fromkeys([str(result["parent_id"])] if result.get("parent_id") else []))
    result["parent_ids"] = list(dict.fromkeys(result["parent_ids"] + result["fusion_sources"]))
    return result


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read_events(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except (ValueError, TypeError):
                continue  # A crash can leave the final append incomplete.
    return rows


def empty_snapshot(task: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"task": task or {}, "auto_realize": {"events": []}, "auto_ml": {"nodes": [], "pending_nodes": [], "events": [], "best_node_id": None, "best_node_kind": None}, "auto_report": {"events": []}}


def reset_snapshot(*stages: str) -> dict[str, Any]:
    # Replay clients merge stage fields, so every retained artifact needs an explicit empty value.
    blank = empty_snapshot()
    for stage, fields in (("auto_realize", AR_FIELDS), ("auto_ml", ML_FIELDS), ("auto_report", REPORT_FIELDS)):
        for field in fields:
            blank[stage][field] = "" if field.endswith("_text") or field in {"engine", "best_solution_code", "report_markdown"} else {}
    return {stage: blank[stage] for stage in stages}


def clear_digests(digests: dict[str, str], *stages: str) -> None:
    prefixes = tuple(prefix for stage in stages for prefix in (f"{stage}:", f"event:{stage}:"))
    for key in list(digests):
        if key.startswith(prefixes) or ("auto_ml" in stages and (key.startswith("node:") or key == "run_identity")):
            del digests[key]


def _best(ml: dict[str, Any]) -> None:
    candidates = [node for node in ml["nodes"] if isinstance(node.get("metric"), (int, float)) and not isinstance(node.get("metric"), bool) and math.isfinite(node["metric"]) and node.get("is_buggy") is not True and node.get("is_valid") is not False]
    delivered = [node for node in candidates if (node.get("delivery_ready") is True and node.get("is_valid") is not False) or (node.get("delivery_ready") is None and node.get("is_valid") is True and node.get("is_buggy") is False)]
    eligible = delivered or [node for node in candidates if node.get("search_eligible") is True]
    maximize = next((node["maximize"] for node in eligible if isinstance(node.get("maximize"), bool)), True)
    eligible = [node for node in eligible if not isinstance(node.get("maximize"), bool) or node["maximize"] == maximize]
    best = None
    for node in eligible:
        if best is None or (node["metric"] > best["metric"] if maximize else node["metric"] < best["metric"]):
            best = node
    ml["best_node_id"] = best.get("id") if best else None
    ml["best_node_kind"] = ("delivery" if delivered else "provisional") if best else None


def apply_event(snapshot: dict[str, Any], event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    snapshot["task"].update(payload.get("task") or {})
    for key, value in (payload.get("snapshot") or {}).items():
        if key in snapshot and isinstance(value, dict):
            snapshot[key].update(copy.deepcopy(value))
    if isinstance(payload.get("event"), dict):
        snapshot[STAGE_KEYS[event["stage"]]].setdefault("events", []).append(copy.deepcopy(payload["event"]))
    node = payload.get("node")
    ml = snapshot["auto_ml"]
    if isinstance(node, dict) and node.get("id"):
        for key in ("nodes", "pending_nodes"):
            ml[key] = [item for item in ml[key] if item.get("id") != node["id"]]
        key = "pending_nodes" if node.get("pending_execution") or node.get("status") in PENDING else "nodes"
        ml[key].append(copy.deepcopy(node))
    _best(ml)


def project(events: list[dict[str, Any]], sequence: int) -> dict[str, Any]:
    snapshot = empty_snapshot()
    for event in events:
        if event["sequence"] > sequence:
            break
        apply_event(snapshot, event)
    return snapshot


class ReplayRecorder:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}

    def path(self, state_dir: Path, task_id: str) -> Path:
        return state_dir / "replays" / f"{hashlib.sha256(task_id.encode()).hexdigest()}.jsonl"

    def _state(self, state_dir: Path, task_id: str) -> tuple[Path, dict[str, Any]]:
        path = self.path(state_dir, task_id)
        key = str(path)
        if key not in self._states:
            rows = read_events(path)
            digests = {}
            for row in rows:
                if row.get("label") == "task_reset":
                    digests.clear()
                elif row.get("label") == "search_reset":
                    clear_digests(digests, "auto_ml", "auto_report")
                payload = row.get("payload") or {}
                if payload.get("task"):
                    digests["task"] = _digest(payload["task"])
                if payload.get("node"):
                    digests[f"node:{payload['node']['id']}"] = _digest(payload["node"])
                if payload.get("event"):
                    digest = _digest(payload["event"])
                    digests[f"event:{STAGE_KEYS[row['stage']]}:{digest}"] = digest
                for stage_key, fields in (payload.get("snapshot") or {}).items():
                    for field, value in fields.items():
                        digests[f"{stage_key}:{field}"] = _digest(value)
                if row.get("run_identity"):
                    digests["run_identity"] = row["run_identity"]
            self._states[key] = {"sequence": max((row.get("sequence", 0) for row in rows), default=0), "digests": digests, "time": max((row.get("timestamp", 0) for row in rows), default=0), "stage": rows[-1]["stage"] if rows else "data_cognition"}
        return path, self._states[key]

    def _append(self, path: Path, state: dict[str, Any], stage: str, kind: str, label: str, payload: dict[str, Any], observed_at: float) -> None:
        state["sequence"] += 1
        state["time"] = max(observed_at, state["time"])
        state["stage"] = stage
        row = {"sequence": state["sequence"], "timestamp": state["time"], "stage": stage, "kind": kind, "label": label, "payload": sanitize(payload), "fidelity": "recorded"}
        if state["digests"].get("run_identity"):
            row["run_identity"] = state["digests"]["run_identity"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()

    def observe_task(self, state_dir: Path, task: dict[str, Any], observed_at: float | None = None) -> None:
        if not task.get("run_dir") or task.get("status") == "idle":
            return
        with self._lock:
            path, state = self._state(state_dir, task["id"])
            safe = safe_task(task)
            digest = _digest(safe)
            if state["digests"].get("task") != digest:
                self._append(path, state, stage_of(task.get("phase"), state.get("stage", "data_cognition")), "stage", str(task.get("phase") or task.get("status")), {"task": safe}, observed_at or time.time())
                state["digests"]["task"] = digest

    def reset_task(self, state_dir: Path, task: dict[str, Any], observed_at: float | None = None) -> None:
        """Record the explicit full-rerun boundary; resumes must not call this."""
        with self._lock:
            path, state = self._state(state_dir, task["id"])
            state["digests"].clear()
            safe = safe_task(task)
            self._append(path, state, "data_cognition", "artifact", "task_reset", {"task": safe, "snapshot": reset_snapshot("auto_realize", "auto_ml", "auto_report")}, observed_at or time.time())
            state["digests"]["task"] = _digest(safe)

    def capture(self, state_dir: Path, task: dict[str, Any], snapshot: dict[str, Any], observed_at: float | None = None) -> None:
        observed_at = observed_at or time.time()
        with self._lock:
            self.observe_task(state_dir, task, observed_at)
            path, state = self._state(state_dir, task["id"])
            digests = state["digests"]
            ml = snapshot.get("auto_ml") or {}
            run_identity = _digest(str(ml["log_dir"])) if ml.get("log_dir") else ""
            if run_identity and digests.get("run_identity") not in {None, run_identity}:
                clear_digests(digests, "auto_ml", "auto_report")
                digests["run_identity"] = run_identity
                self._append(path, state, "automl", "artifact", "search_reset", {"snapshot": reset_snapshot("auto_ml", "auto_report")}, observed_at)
            if run_identity:
                digests["run_identity"] = run_identity
            for key, fields, default_stage in (("auto_realize", AR_FIELDS, "data_cognition"), ("auto_ml", ML_FIELDS, "automl"), ("auto_report", REPORT_FIELDS, "report")):
                part = snapshot.get(key) or {}
                for raw in part.get("events") or []:
                    safe = sanitize(raw)
                    digest = _digest(safe)
                    event_key = f"event:{key}:{digest}"
                    if event_key not in digests:
                        stage = stage_of(raw.get("component"), default_stage)
                        self._append(path, state, stage, "event", str(raw.get("event") or raw.get("message") or "progress")[:160], {"event": safe}, observed_at)
                        digests[event_key] = digest
                changes = {}
                for field in fields:
                    if field not in part:
                        continue
                    safe = sanitize(part[field])
                    digest = _digest(safe)
                    if digests.get(f"{key}:{field}") != digest:
                        changes[field] = safe
                        digests[f"{key}:{field}"] = digest
                if changes:
                    stage = stage_of(task.get("phase"), default_stage) if key == "auto_realize" and "autorealize" in str(task.get("phase")) else default_stage
                    self._append(path, state, stage, "artifact", key, {"snapshot": {key: changes}}, observed_at)
            for node in [*(ml.get("nodes") or []), *(ml.get("pending_nodes") or [])]:
                if not node.get("id"):
                    continue
                safe = node_state(node)
                digest = _digest(safe)
                key = f"node:{safe['id']}"
                if digests.get(key) != digest:
                    self._append(path, state, "automl", "node", f"{safe.get('stage') or 'node'} {safe['id']}", {"node": safe}, observed_at)
                    digests[key] = digest
            phase = str(task.get("phase") or "")
            if task.get("status") != "running":
                terminal_stage = "report" if (snapshot.get("auto_report") or {}).get("report_markdown") else "automl" if ml.get("nodes") or ml.get("pending_nodes") else "task_definition"
            else:
                terminal_stage = stage_of(phase, state["stage"])
            if state["stage"] != terminal_stage:
                self._append(path, state, terminal_stage, "stage", phase or str(task.get("status")), {"task": safe_task(task)}, observed_at)


def reconstruct(task: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Only publish terminal evidence at known completion boundaries."""
    if not any(part for part in snapshot.values() if isinstance(part, dict)):
        return []
    rows: list[dict[str, Any]] = []
    start = timestamp(task.get("run_started_at"), timestamp(task.get("created_at"), 1.0))
    end = max(start, timestamp(task.get("updated_at"), start))
    ml = snapshot.get("auto_ml") or {}
    nodes = [node_state(node) for node in [*(ml.get("nodes") or []), *(ml.get("pending_nodes") or [])] if node.get("id")]
    ml_start = min((timestamp(node.get("created_time"), timestamp(node.get("finish_time"), end)) for node in nodes), default=end)
    ml_end = max((timestamp(node.get("finish_time"), end) for node in nodes), default=end)
    known_times = [timestamp(node.get("created_time"), timestamp(node.get("finish_time"), start)) for node in nodes]
    for part in snapshot.values():
        if isinstance(part, dict):
            known_times.extend(timestamp(raw.get("ts") or raw.get("timestamp") or raw.get("time"), start) for raw in part.get("events") or [])
    start = min([start, *known_times])

    def add(ts: float, stage: str, kind: str, label: str, payload: dict[str, Any]) -> None:
        rows.append({"timestamp": ts, "stage": stage, "kind": kind, "label": label, "payload": sanitize(payload), "fidelity": "reconstructed"})

    initial = safe_task(task)
    initial.update(status="running", phase="autorealize" if snapshot.get("auto_realize") else "automl")
    add(start, "data_cognition" if snapshot.get("auto_realize") else "automl", "stage", "task_started", {"task": initial})
    for key, fields, stage, boundary in (("auto_realize", AR_FIELDS, "data_cognition", ml_start), ("auto_ml", ML_FIELDS, "automl", ml_end), ("auto_report", REPORT_FIELDS, "report", end)):
        part = snapshot.get(key) or {}
        for raw in part.get("events") or []:
            ts = timestamp(raw.get("ts") or raw.get("timestamp") or raw.get("time"), boundary)
            add(ts, stage_of(raw.get("component"), stage), "event", str(raw.get("event") or raw.get("message") or "progress")[:160], {"event": raw})
        artifact = {field: part[field] for field in fields if field in part and part[field] not in ({}, "", [], None)}
        if artifact:
            actual_stage = "task_definition" if key == "auto_realize" else stage
            add(boundary, actual_stage, "artifact", key, {"snapshot": {key: artifact}})
    if nodes:
        add(ml_start, "automl", "stage", "automl_started", {"task": {"status": "running", "phase": "automl"}})
    for node in nodes:
        finish = timestamp(node.get("finish_time"), end)
        created = timestamp(node.get("created_time"), finish)
        if created < finish:
            skeleton = {key: node.get(key) for key in ("id", "parent_id", "parent_ids", "fusion_sources", "stage", "branch_id", "created_time")}
            skeleton.update(status="generating", pending_execution=True, metric=None)
            add(created, "automl", "node", f"node_created {node['id']}", {"node": skeleton})
        terminal = {key: value for key, value in node.items() if key not in CUMULATIVE_NODE_FIELDS}
        add(finish, "automl", "node", f"node_finished {node['id']}", {"node": terminal})
    if nodes:
        add(ml_end, "automl", "artifact", "final_search_statistics", {"snapshot": {"auto_ml": {"nodes": [node for node in nodes if not node.get("pending_execution") and node.get("status") not in PENDING], "pending_nodes": [node for node in nodes if node.get("pending_execution") or node.get("status") in PENDING]}}})
    report = snapshot.get("auto_report") or {}
    if report:
        report_times = [timestamp(raw.get("ts") or raw.get("timestamp"), end) for raw in report.get("events") or []]
        add(max(ml_start, min(report_times, default=ml_end)), "report", "stage", "report_started", {"task": {"status": "running", "phase": "report"}})
    add(max(end, ml_end), stage_of(task.get("phase"), "report" if report else "automl"), "stage", "task_finished", {"task": safe_task(task)})
    return sorted(rows, key=lambda row: row["timestamp"])


def bundle(task: dict[str, Any], snapshot: dict[str, Any], recorded: list[dict[str, Any]]) -> dict[str, Any]:
    historical = reconstruct(task, snapshot)
    reset_index = next((index for index in range(len(recorded) - 1, -1, -1) if recorded[index].get("label") == "task_reset"), None)
    if reset_index is not None:
        recorded = recorded[reset_index:]
    if recorded:
        first = min(row["timestamp"] for row in recorded)
        prefix = [row for row in historical if row["timestamp"] < first]
        # A reconstructed prefix is needed only when recording began after this run.
        start = timestamp(task.get("run_started_at"), first)
        prefix = prefix if reset_index is None and first - start > 5 else []
        rows = prefix + recorded
        fidelity = "mixed" if prefix else "recorded"
        observed = project([{**row, "sequence": index + 1} for index, row in enumerate(sorted(rows, key=lambda row: row["timestamp"]))], len(rows))
        final_ml = snapshot.get("auto_ml") or {}
        observed_nodes = {node.get("id"): node for key in ("nodes", "pending_nodes") for node in observed["auto_ml"][key]}
        # A final capture can be missed if Gateway exits between observations.
        boundary = max(timestamp(task.get("updated_at"), first), max(row["timestamp"] for row in rows))
        for raw in [*(final_ml.get("nodes") or []), *(final_ml.get("pending_nodes") or [])]:
            node = node_state(raw)
            if node.get("id") and _digest(node) != _digest(observed_nodes.get(node["id"])):
                rows.append({"timestamp": boundary, "stage": "automl", "kind": "node", "label": "recovered_final_node", "payload": {"node": node}, "fidelity": "reconstructed"})
                fidelity = "mixed"
        for key, fields, stage in (("auto_realize", AR_FIELDS, "task_definition"), ("auto_ml", ML_FIELDS, "automl"), ("auto_report", REPORT_FIELDS, "report")):
            part = snapshot.get(key) or {}
            changes = {field: sanitize(part[field]) for field in fields if field in part and _digest(sanitize(part[field])) != _digest(observed[key].get(field))}
            if changes:
                rows.append({"timestamp": boundary, "stage": stage, "kind": "artifact", "label": "recovered_final_artifact", "payload": {"snapshot": {key: changes}}, "fidelity": "reconstructed"})
                fidelity = "mixed"
        if safe_task(task) != observed["task"] or fidelity == "mixed":
            stage = stage_of(task.get("phase"), "report" if snapshot.get("auto_report") else "automl")
            rows.append({"timestamp": boundary, "stage": stage, "kind": "stage", "label": "recovered_final_status", "payload": {"task": safe_task(task)}, "fidelity": "reconstructed"})
            fidelity = "mixed"
    else:
        rows = historical
        fidelity = "reconstructed"
    rows = sorted(rows, key=lambda row: row["timestamp"])
    started = min((row["timestamp"] for row in rows), default=0)
    ended = max((row["timestamp"] for row in rows), default=started)
    normalized = [{**sanitize(row), "sequence": index + 1, "offset_ms": max(0, round((row["timestamp"] - started) * 1000))} for index, row in enumerate(rows)]
    notes = []
    if fidelity in {"recorded", "mixed"}:
        notes.append("Gateway records observed state changes; changes between capture intervals are not implied.")
    if fidelity in {"reconstructed", "mixed"}:
        notes.append("Legacy timing is reconstructed from available events and node timestamps; unrecorded intermediate states are unknown.")
        notes.append("Final artifacts are revealed at stage boundaries. Historical UCT, visit counts and rewards are withheld until the final search snapshot.")
    return {"schema_version": 1, "task_id": task["id"], "task_name": sanitize(task.get("task_name", "")), "fidelity": fidelity, "fidelity_notes": notes, "started_at": started, "ended_at": ended, "duration_ms": round((ended - started) * 1000), "events": normalized}

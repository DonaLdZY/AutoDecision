from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReportEventWriter:
    def __init__(self, output_dir: Path, *, run_id: str = "") -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.event_path = self.output_dir / "event_stream.jsonl"
        self.state_path = self.output_dir / "current_state.json"
        self.run_id = run_id
        self.seq = 0
        self.recent_events: list[dict[str, Any]] = []
        self.status = "created"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.write_state()

    def log(self, component: str, event: str, **fields: Any) -> dict[str, Any]:
        self.seq += 1
        status = self._infer_status(event)
        if status in {"running", "created"} and self.status in {"created", "running"}:
            self.status = "running"
        elif status == "failed":
            self.status = "failed"
        elif component == "autoreport.pipeline" and event.upper() == "COMPLETED":
            self.status = "completed"
        payload = {
            "schema_version": "autoreport.event.v1",
            "seq": self.seq,
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "component": component,
            "event": event,
            "status": status,
            "fields": self._safe(fields),
        }
        with self.event_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.recent_events.append(payload)
        if len(self.recent_events) > 120:
            del self.recent_events[: len(self.recent_events) - 120]
        self.write_state()
        print(f"[AutoReport] {component}.{event} {payload['fields']}", flush=True)
        return payload

    def write_state(self) -> None:
        payload = {
            "schema_version": "autoreport.state.v1",
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "event_count": self.seq,
            "recent_events": self.recent_events,
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _infer_status(event: str) -> str:
        e = event.upper()
        if e.endswith("FAILED") or e in {"FAILED", "ERROR"}:
            return "failed"
        if e.endswith("COMPLETED") or e in {"COMPLETED", "GENERATED_FILE"}:
            return "completed"
        if e.endswith("STARTED") or e in {"STARTED", "ACTIVATED", "RUNNING"}:
            return "running"
        if e == "CREATED":
            return "created"
        return "info"

    @classmethod
    def _safe(cls, value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except TypeError:
            if isinstance(value, dict):
                return {str(k): cls._safe(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [cls._safe(v) for v in value]
            return str(value)

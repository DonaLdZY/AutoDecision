from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AutoReportConfig, EvidencePath
from .events import ReportEventWriter


TEXT_SUFFIXES = {".md", ".txt", ".log", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".py", ".csv"}
IMPORTANT_NAMES = {
    "data_description.md",
    "description.md",
    "data_cognition_report.json",
    "constraint_memory.json",
    "knowledge_base.json",
    "sample_submission.csv",
    "report.json",
    "report.md",
    "run_summary.json",
    "current_state.json",
    "event_stream.jsonl",
    "best_solution.py",
    "solution.py",
    "metric.txt",
    "ml-master.log",
    "mlevolve.log",
}


@dataclass
class EvidenceItem:
    id: str
    label: str
    source_root: str
    path: str
    kind: str
    size: int = 0
    text_excerpt: str = ""
    json_summary: dict[str, Any] = field(default_factory=dict)
    table_preview: list[dict[str, str]] = field(default_factory=list)


@dataclass
class EvidenceBundle:
    task_name: str
    roots: list[dict[str, Any]]
    items: list[EvidenceItem]
    warnings: list[str] = field(default_factory=list)
    derived: dict[str, Any] = field(default_factory=dict)


def collect_evidence(cfg: AutoReportConfig, events: ReportEventWriter) -> EvidenceBundle:
    events.log("autoreport.collector", "ACTIVATED", paths=len(cfg.evidence_paths))
    roots: list[dict[str, Any]] = []
    items: list[EvidenceItem] = []
    warnings: list[str] = []

    for evidence in cfg.evidence_paths:
        root = Path(evidence.path).expanduser().resolve()
        root_info = {
            "label": evidence.label,
            "path": str(root),
            "kind": evidence.kind,
            "exists": root.exists(),
            "is_dir": root.is_dir() if root.exists() else False,
        }
        roots.append(root_info)
        if not root.exists():
            msg = f"Evidence path not found: {root}"
            warnings.append(msg)
            events.log("autoreport.collector", "PATH_FAILED", label=evidence.label, path=str(root), required=evidence.required)
            if evidence.required:
                raise FileNotFoundError(msg)
            continue
        path_items = _collect_from_path(evidence, root, cfg)
        items.extend(path_items)
        events.log("autoreport.collector", "PATH_COMPLETED", label=evidence.label, path=str(root), items=len(path_items))

    bundle = EvidenceBundle(
        task_name=cfg.task_name,
        roots=roots,
        items=items,
        warnings=warnings,
        derived=_derive_summary(items),
    )
    events.log("autoreport.collector", "COMPLETED", items=len(items), warnings=len(warnings))
    return bundle


def _collect_from_path(evidence: EvidencePath, root: Path, cfg: AutoReportConfig) -> list[EvidenceItem]:
    if root.is_file():
        item = _read_item(evidence, root, root.parent, cfg)
        return [item] if item else []

    candidates: list[Path] = []
    for path in root.rglob("*"):
        if len(candidates) >= cfg.max_files_per_path:
            break
        if not path.is_file():
            continue
        rel_name = path.name.lower()
        if rel_name in IMPORTANT_NAMES or path.suffix.lower() in TEXT_SUFFIXES:
            candidates.append(path)

    def sort_key(path: Path) -> tuple[int, str]:
        important = 0 if path.name.lower() in IMPORTANT_NAMES else 1
        return important, str(path).lower()

    out: list[EvidenceItem] = []
    for path in sorted(candidates, key=sort_key):
        item = _read_item(evidence, path, root, cfg)
        if item:
            out.append(item)
    return out


def _read_item(evidence: EvidencePath, path: Path, root: Path, cfg: AutoReportConfig) -> EvidenceItem | None:
    suffix = path.suffix.lower()
    if suffix not in TEXT_SUFFIXES and path.name.lower() not in IMPORTANT_NAMES:
        return None
    try:
        rel = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        rel = path.name
    text = ""
    json_summary: dict[str, Any] = {}
    table_preview: list[dict[str, str]] = []
    if suffix in {".json", ".jsonl"}:
        text = _read_text(path, cfg.max_text_chars_per_file)
        json_summary = _summarize_json_text(text, suffix=suffix)
    elif suffix == ".csv":
        text = _read_text(path, min(cfg.max_text_chars_per_file, 12000))
        table_preview = _read_csv_preview(path)
    elif suffix in {".log"}:
        if not cfg.include_raw_logs:
            return None
        text = _read_text_tail(path, cfg.max_text_chars_per_file)
    elif suffix == ".py":
        if not cfg.include_code_excerpt:
            return None
        text = _read_text(path, cfg.max_text_chars_per_file)
    else:
        text = _read_text(path, cfg.max_text_chars_per_file)

    return EvidenceItem(
        id=f"{evidence.label}:{rel}",
        label=evidence.label,
        source_root=str(root),
        path=str(path),
        kind=_classify_item(path, evidence.kind),
        size=path.stat().st_size,
        text_excerpt=text,
        json_summary=json_summary,
        table_preview=table_preview,
    )


def _read_text(path: Path, max_chars: int) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return raw[:max(1000, max_chars)]


def _read_text_tail(path: Path, max_chars: int) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    max_chars = max(1000, max_chars)
    return raw[-max_chars:]


def _summarize_json_text(text: str, *, suffix: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        if suffix == ".jsonl":
            rows = [json.loads(line) for line in text.splitlines()[:200] if line.strip()]
            return {
                "type": "jsonl",
                "rows_sampled": len(rows),
                "first_keys": sorted(list(rows[0].keys()))[:30] if rows and isinstance(rows[0], dict) else [],
            }
        obj = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        return {"parse_error": str(exc)[:160]}
    if isinstance(obj, dict):
        return {
            "type": "object",
            "keys": sorted([str(k) for k in obj.keys()])[:80],
            "summary": _summarize_known_json(obj),
        }
    if isinstance(obj, list):
        return {
            "type": "array",
            "length": len(obj),
            "first_item_keys": sorted(list(obj[0].keys()))[:40] if obj and isinstance(obj[0], dict) else [],
        }
    return {"type": type(obj).__name__, "value": str(obj)[:200]}


def _summarize_known_json(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "summary" in obj and isinstance(obj["summary"], dict):
        out["summary"] = obj["summary"]
    if "files" in obj and isinstance(obj["files"], list):
        out["files"] = len(obj["files"])
    if "relations" in obj and isinstance(obj["relations"], list):
        out["relations"] = len(obj["relations"])
    if "nodes" in obj and isinstance(obj["nodes"], list):
        out["nodes"] = len(obj["nodes"])
    if "best_node_id" in obj:
        out["best_node_id"] = obj.get("best_node_id")
    if "best_metric_text" in obj:
        out["best_metric_text"] = str(obj.get("best_metric_text", ""))[:500]
    return out


def _read_csv_preview(path: Path, limit: int = 8) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for idx, row in enumerate(reader):
                if idx >= limit:
                    break
                rows.append({str(k): str(v)[:120] for k, v in row.items()})
            return rows
    except Exception:
        return []


def _classify_item(path: Path, parent_kind: str) -> str:
    name = path.name.lower()
    if name in {"data_description.md", "data_cognition_report.json", "constraint_memory.json", "knowledge_base.json"}:
        return "data_cognition"
    if name in {"description.md", "sample_submission.csv"}:
        return "task_definition"
    if "metric" in name or "best_solution" in str(path).lower() or name.endswith(".py"):
        return "solution"
    if name.endswith(".log") or name == "event_stream.jsonl" or name == "current_state.json":
        return "runtime_trace"
    if parent_kind and parent_kind != "auto":
        return parent_kind
    return "generic"


def _derive_summary(items: list[EvidenceItem]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for item in items:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1

    def find_text(names: set[str]) -> str:
        for item in items:
            if Path(item.path).name.lower() in names and item.text_excerpt.strip():
                return item.text_excerpt
        return ""

    return {
        "item_count": len(items),
        "kind_counts": by_kind,
        "data_description": find_text({"data_description.md"}),
        "description": find_text({"description.md"}),
        "best_metric_text": find_text({"metric.txt"}),
        "best_solution_code": find_text({"solution.py", "best_solution.py"}),
        "sample_submission_preview": [
            item.table_preview
            for item in items
            if Path(item.path).name.lower() == "sample_submission.csv" and item.table_preview
        ][:1],
    }

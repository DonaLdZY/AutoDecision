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
    "autorealize_context.md",
    "automl_context.md",
    "sample_submission.csv",
    "submission.csv",
    "submissions.csv",
    "assignments.csv",
    "unassigned_orders.csv",
    "metrics.json",
    "report.json",
    "report.md",
    "run_summary.json",
    "run_status.json",
    "current_state.json",
    "event_stream.jsonl",
    "journal.json",
    "filtered_journal.json",
    "node_summary_compact.json",
    "pending_nodes.json",
    "best_solution.py",
    "solution.py",
    "metric.txt",
    "node_id.txt",
    "model_path.txt",
    "model_artifacts_manifest.md",
    "llm_usage_brief.json",
    "llm_usage_summary.json",
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
            "object_excerpt": _compact_json_value(obj, max_depth=3, max_items=80),
        }
    if isinstance(obj, list):
        return {
            "type": "array",
            "length": len(obj),
            "first_item_keys": sorted(list(obj[0].keys()))[:40] if obj and isinstance(obj[0], dict) else [],
            "items_excerpt": _compact_json_value(obj[:20], max_depth=3, max_items=80),
        }
    return {"type": type(obj).__name__, "value": str(obj)[:200]}


def _compact_json_value(value: Any, *, max_depth: int = 2, max_items: int = 40) -> Any:
    if max_depth <= 0:
        return _short_scalar(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for idx, (key, val) in enumerate(value.items()):
            if idx >= max_items:
                out["_omitted_keys"] = max(0, len(value) - idx)
                break
            out[str(key)] = _compact_json_value(val, max_depth=max_depth - 1, max_items=max_items)
        return out
    if isinstance(value, list):
        out = [_compact_json_value(x, max_depth=max_depth - 1, max_items=max_items) for x in value[:max_items]]
        if len(value) > max_items:
            out.append({"_omitted_items": len(value) - max_items})
        return out
    return _short_scalar(value)


def _short_scalar(value: Any) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


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
        "solution_evidence": _derive_solution_evidence(items),
    }


def _derive_solution_evidence(items: list[EvidenceItem]) -> dict[str, Any]:
    """Build a delivery-oriented evidence pack for the report writer.

    AutoReport should persuade users that the selected solution is usable. This
    pack therefore focuses on the final solution, reusable code interface,
    validation artifacts, and how other explored methods compared.
    """

    by_name: dict[str, list[EvidenceItem]] = {}
    for item in items:
        by_name.setdefault(Path(item.path).name.lower(), []).append(item)

    best_solution = _best_solution_summary(items)
    node_rows = _candidate_nodes_from_items(items)
    candidate_summary = _summarize_candidate_nodes(node_rows)
    top_solutions = _top_solution_summaries(items)
    artifacts = _delivery_artifact_summary(items)
    reusable = _reusable_code_summary(best_solution.get("code_excerpt", ""))

    return {
        "best_solution": best_solution,
        "top_solutions": top_solutions,
        "candidate_comparison": candidate_summary,
        "delivery_artifacts": artifacts,
        "reusable_code_interface": reusable,
        "available_evidence_files": {
            "journal_files": [item.path for item in by_name.get("journal.json", [])[:5]],
            "node_summary_files": [item.path for item in by_name.get("node_summary_compact.json", [])[:5]],
            "metric_files": [item.path for item in by_name.get("metric.txt", [])[:12]],
            "solution_files": [
                item.path
                for item in items
                if Path(item.path).name.lower() in {"solution.py", "best_solution.py"}
            ][:12],
        },
    }


def _best_solution_summary(items: list[EvidenceItem]) -> dict[str, Any]:
    metric_items = [
        item
        for item in items
        if Path(item.path).name.lower() == "metric.txt" and _path_has_part(item.path, "best_solution")
    ]
    if not metric_items:
        metric_items = [item for item in items if Path(item.path).name.lower() == "metric.txt"]
    solution_items = [
        item
        for item in items
        if Path(item.path).name.lower() in {"solution.py", "best_solution.py"} and _path_has_part(item.path, "best_solution")
    ]
    if not solution_items:
        solution_items = [item for item in items if Path(item.path).name.lower() in {"solution.py", "best_solution.py"}]
    node_id_items = [
        item
        for item in items
        if Path(item.path).name.lower() == "node_id.txt" and _path_has_part(item.path, "best_solution")
    ]
    model_manifest = [
        item
        for item in items
        if Path(item.path).name.lower() == "model_artifacts_manifest.md" and _path_has_part(item.path, "best_solution")
    ]
    metric = _parse_metric_text(metric_items[0].text_excerpt) if metric_items else {}
    code_excerpt = solution_items[0].text_excerpt if solution_items else ""
    return {
        "metric": metric,
        "metric_text": metric_items[0].text_excerpt[:3000] if metric_items else "",
        "metric_path": metric_items[0].path if metric_items else "",
        "node_id": node_id_items[0].text_excerpt.strip()[:120] if node_id_items else "",
        "solution_path": solution_items[0].path if solution_items else "",
        "code_excerpt": code_excerpt[:12000],
        "code_functions": _extract_python_defs(code_excerpt),
        "model_artifacts_manifest": model_manifest[0].text_excerpt[:4000] if model_manifest else "",
        "model_artifacts_manifest_path": model_manifest[0].path if model_manifest else "",
    }


def _top_solution_summaries(items: list[EvidenceItem]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    metric_items = [
        item
        for item in items
        if Path(item.path).name.lower() == "metric.txt" and _path_has_part(item.path, "top_solution")
    ]
    for item in sorted(metric_items, key=lambda x: x.path.lower())[:8]:
        parent = str(Path(item.path).parent)
        sibling = _find_item_by_path(items, str(Path(parent) / "node_id.txt"))
        solution = _find_item_by_path(items, str(Path(parent) / "solution.py"))
        out.append(
            {
                "rank_dir": Path(parent).name,
                "metric": _parse_metric_text(item.text_excerpt),
                "metric_path": item.path,
                "node_id": sibling.text_excerpt.strip()[:120] if sibling else "",
                "solution_path": solution.path if solution else "",
                "code_functions": _extract_python_defs(solution.text_excerpt) if solution else [],
            }
        )
    return out


def _delivery_artifact_summary(items: list[EvidenceItem]) -> list[dict[str, Any]]:
    interesting_names = {
        "submission.csv",
        "submissions.csv",
        "assignments.csv",
        "unassigned_orders.csv",
        "metrics.json",
        "model_artifacts_manifest.md",
        "model_path.txt",
    }
    out: list[dict[str, Any]] = []
    for item in items:
        name = Path(item.path).name.lower()
        if name not in interesting_names:
            continue
        entry: dict[str, Any] = {
            "path": item.path,
            "name": Path(item.path).name,
            "kind": item.kind,
            "size": item.size,
        }
        if item.table_preview:
            entry["table_preview"] = item.table_preview[:3]
            entry["columns"] = list(item.table_preview[0].keys()) if item.table_preview else []
        if item.json_summary:
            entry["json_summary"] = item.json_summary.get("summary") or item.json_summary.get("object_excerpt") or item.json_summary
        elif item.text_excerpt:
            entry["text_excerpt"] = item.text_excerpt[:1200]
        out.append(entry)
    return out[:40]


def _candidate_nodes_from_items(items: list[EvidenceItem]) -> list[dict[str, Any]]:
    compact_items = [item for item in items if Path(item.path).name.lower() == "node_summary_compact.json"]
    for item in compact_items:
        rows = _load_json_from_item(item)
        if isinstance(rows, list):
            return [_normalize_compact_node(row) for row in rows if isinstance(row, dict)]

    journal_items = [item for item in items if Path(item.path).name.lower() in {"journal.json", "filtered_journal.json"}]
    for item in journal_items:
        obj = _load_json_from_item(item)
        nodes = obj.get("nodes") if isinstance(obj, dict) else None
        if isinstance(nodes, list):
            return [_normalize_journal_node(row) for row in nodes if isinstance(row, dict)]
    return []


def _summarize_candidate_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not nodes:
        return {
            "node_count": 0,
            "successful_metric_nodes": [],
            "failed_nodes": [],
            "failure_patterns": [],
            "method_signals": {},
        }

    metric_nodes = [n for n in nodes if n.get("metric") not in (None, "", {})]
    maximize = _first_non_none([n.get("maximize") for n in metric_nodes])
    successful = [n for n in metric_nodes if not n.get("buggy")]
    successful = sorted(
        successful,
        key=lambda n: _metric_sort_key(n.get("metric"), maximize=maximize),
        reverse=_boolish(maximize),
    )
    failed = [n for n in nodes if n.get("buggy") or n.get("exc_type")]
    failure_patterns = _failure_patterns(failed)
    method_signals = {
        "nodes_with_greedy": sum(1 for n in nodes if n.get("has_greedy")),
        "nodes_with_rl_env": sum(1 for n in nodes if n.get("has_rl_env")),
        "nodes_with_decision_summary": sum(1 for n in nodes if n.get("has_decision_summary")),
        "valid_nodes": sum(1 for n in nodes if n.get("valid") is True),
        "buggy_nodes": sum(1 for n in nodes if n.get("buggy") is True),
    }
    return {
        "node_count": len(nodes),
        "maximize": maximize,
        "successful_metric_nodes": [_compact_node_for_report(n) for n in successful[:12]],
        "failed_nodes": [_compact_node_for_report(n) for n in failed[:10]],
        "failure_patterns": failure_patterns,
        "method_signals": method_signals,
    }


def _normalize_compact_node(row: dict[str, Any]) -> dict[str, Any]:
    metric = row.get("metric")
    if isinstance(metric, dict):
        metric_value = metric.get("value")
        maximize = metric.get("maximize")
    else:
        metric_value = metric
        maximize = row.get("maximize")
    return {
        "id": str(row.get("id") or ""),
        "stage": str(row.get("stage") or ""),
        "step": row.get("step"),
        "parent": str(row.get("parent") or ""),
        "exec_time": row.get("exec_time"),
        "buggy": row.get("buggy"),
        "valid": row.get("valid"),
        "metric": metric_value,
        "maximize": maximize,
        "exc_type": str(row.get("exc_type") or ""),
        "exc_msg": str(row.get("exc_msg") or "")[:500],
        "plan": str(row.get("plan") or "")[:1000],
        "analysis": str(row.get("analysis") or "")[:1400],
        "llm_insight": str(row.get("llm_insight") or row.get("insight") or "")[:1400],
        "funcs": str(row.get("funcs") or "")[:800],
        "classes": str(row.get("classes") or "")[:800],
        "has_greedy": bool(row.get("has_greedy")),
        "has_rl_env": bool(row.get("has_rl_env")),
        "has_decision_summary": bool(row.get("has_decision_summary")),
        "term_tail": str(row.get("term_tail") or "")[:1000],
    }


def _normalize_journal_node(row: dict[str, Any]) -> dict[str, Any]:
    metric = row.get("metric") if isinstance(row.get("metric"), dict) else {}
    code = str(row.get("code") or "")
    return {
        "id": str(row.get("id") or ""),
        "stage": str(row.get("stage") or ""),
        "step": row.get("step"),
        "parent": str(row.get("parent") or ""),
        "exec_time": row.get("exec_time"),
        "buggy": row.get("is_buggy"),
        "valid": row.get("is_valid"),
        "metric": metric.get("value"),
        "maximize": metric.get("maximize"),
        "exc_type": str(row.get("exc_type") or ""),
        "exc_msg": _exc_message(row.get("exc_info"))[:500],
        "plan": str(row.get("plan") or "")[:1000],
        "analysis": str(row.get("parser_analysis") or row.get("analysis") or "")[:1400],
        "llm_insight": str(row.get("llm_insight") or "")[:1400],
        "funcs": ", ".join(_extract_python_defs(code))[:800],
        "classes": ", ".join(_extract_python_classes(code))[:800],
        "has_greedy": "greedy" in code.lower(),
        "has_rl_env": any(tok in code for tok in ["Env", "PPO", "DQN", "ActorCritic", "policy"]),
        "has_decision_summary": "Decision Validation Summary" in code or "decision validation" in code.lower(),
        "term_tail": str(row.get("_term_out") or "")[-1000:],
    }


def _compact_node_for_report(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "stage": node.get("stage"),
        "step": node.get("step"),
        "metric": node.get("metric"),
        "maximize": node.get("maximize"),
        "valid": node.get("valid"),
        "buggy": node.get("buggy"),
        "exec_time": node.get("exec_time"),
        "method_flags": {
            "greedy": bool(node.get("has_greedy")),
            "rl_env": bool(node.get("has_rl_env")),
            "decision_summary": bool(node.get("has_decision_summary")),
        },
        "failure": {
            "exc_type": node.get("exc_type"),
            "exc_msg": node.get("exc_msg"),
        },
        "plan": str(node.get("plan") or "")[:700],
        "insight": str(node.get("llm_insight") or node.get("analysis") or "")[:900],
    }


def _failure_patterns(failed_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for node in failed_nodes:
        key = str(node.get("exc_type") or "").strip() or _failure_family(str(node.get("analysis") or node.get("term_tail") or "unknown"))
        key = key or "unknown"
        bucket = buckets.setdefault(key, {"type": key, "count": 0, "examples": []})
        bucket["count"] += 1
        if len(bucket["examples"]) < 3:
            bucket["examples"].append(
                {
                    "id": node.get("id"),
                    "stage": node.get("stage"),
                    "message": str(node.get("exc_msg") or node.get("analysis") or node.get("term_tail") or "")[:500],
                }
            )
    return sorted(buckets.values(), key=lambda row: (-int(row["count"]), str(row["type"])))[:12]


def _failure_family(text: str) -> str:
    lower = text.lower()
    if "keyerror" in lower or "not in the [columns]" in lower:
        return "KeyError/schema_mismatch"
    if "nameerror" in lower:
        return "NameError"
    if "typeerror" in lower:
        return "TypeError"
    if "runtimeerror" in lower:
        return "RuntimeError"
    if "coverage_ok is not true" in lower or "unassigned" in lower:
        return "incomplete_solution"
    return "unknown"


def _reusable_code_summary(code: str) -> dict[str, Any]:
    defs = _extract_python_defs(code)
    return {
        "has_predict": "predict" in defs,
        "has_load_problem_data": "load_problem_data" in defs,
        "has_validate_solution": "validate_solution" in defs,
        "has_score_solution": "score_solution" in defs,
        "has_main": "main" in defs,
        "functions": defs[:80],
        "recommended_usage": [
            "Place the expected input files under ./input or pass the input directory used by the solution.",
            "Run python solution.py for an end-to-end reproduction when main() is available.",
            "For integration, call predict(model_path, data) if the solution exposes predict(); otherwise reuse load_problem_data + solver/validation functions shown in the code.",
        ],
    }


def _parse_metric_text(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in str(text or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        norm = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if norm in {"metric", "score", "final_validation_score"}:
            out["metric"] = _maybe_number(value)
        elif norm == "maximize":
            out["maximize"] = value.lower() in {"true", "1", "yes"}
        elif norm == "branch_id":
            out["branch_id"] = value
        elif norm == "stage":
            out["stage"] = value
        elif norm in {"execution_time(s)", "execution_time", "execution_time_seconds"}:
            out["execution_time_seconds"] = _maybe_number(value)
        elif norm == "created_time":
            out["created_time"] = value
        else:
            out[norm] = value[:500]
    return out


def _maybe_number(value: Any) -> Any:
    text = str(value).strip()
    try:
        if "." in text or "e" in text.lower():
            return float(text)
        return int(text)
    except Exception:
        return value


def _metric_sort_key(value: Any, *, maximize: Any) -> tuple[int, float]:
    try:
        numeric = float(value)
    except Exception:
        return (1, 0.0)
    if numeric != numeric:  # NaN should not outrank real metrics.
        return (1, 0.0)
    return (0, numeric)


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", "", "none", "null"}:
        return False
    return bool(value)


def _load_json_from_item(item: EvidenceItem) -> Any:
    try:
        text = Path(item.path).read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        text = item.text_excerpt
    try:
        return json.loads(text)
    except Exception:
        return {}


def _extract_python_defs(code: str) -> list[str]:
    import re

    return list(dict.fromkeys(re.findall(r"(?m)^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", str(code or ""))))[:120]


def _extract_python_classes(code: str) -> list[str]:
    import re

    return list(dict.fromkeys(re.findall(r"(?m)^class\s+([A-Za-z_][A-Za-z0-9_]*)\b", str(code or ""))))[:80]


def _exc_message(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("message") or value.get("error") or value)[:800]
    return str(value or "")[:800]


def _find_item_by_path(items: list[EvidenceItem], path: str) -> EvidenceItem | None:
    normalized = str(Path(path)).replace("\\", "/").lower()
    for item in items:
        if str(Path(item.path)).replace("\\", "/").lower() == normalized:
            return item
    return None


def _path_has_part(path: str, part: str) -> bool:
    wanted = part.lower().replace("\\", "/")
    return wanted in str(path).lower().replace("\\", "/").split("/")


def _first_non_none(values: list[Any]) -> Any:
    for value in values:
        if value is not None:
            return value
    return None

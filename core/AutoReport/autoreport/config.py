from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvidencePath:
    label: str
    path: str
    kind: str = "auto"
    required: bool = False


@dataclass
class AutoReportConfig:
    task_name: str
    output_dir: str
    report_title: str = ""
    audience: str = "technical"
    language: str = "zh-CN"
    evidence_paths: list[EvidencePath] = field(default_factory=list)
    max_files_per_path: int = 700
    max_text_chars_per_file: int = 40000
    max_report_chars_per_section: int = 60000
    include_raw_logs: bool = True
    include_code_excerpt: bool = True
    use_llm: bool = True
    llm: dict[str, Any] = field(default_factory=dict)


def _as_evidence_path(item: Any) -> EvidencePath:
    if isinstance(item, EvidencePath):
        return item
    if isinstance(item, str):
        return EvidencePath(label=Path(item).name or "evidence", path=item)
    if isinstance(item, dict):
        return EvidencePath(
            label=str(item.get("label") or Path(str(item.get("path", ""))).name or "evidence"),
            path=str(item.get("path") or ""),
            kind=str(item.get("kind") or "auto"),
            required=bool(item.get("required", False)),
        )
    raise TypeError(f"Unsupported evidence path item: {item!r}")


def config_from_dict(raw: dict[str, Any]) -> AutoReportConfig:
    evidence = [_as_evidence_path(x) for x in raw.get("evidence_paths", [])]
    return AutoReportConfig(
        task_name=str(raw.get("task_name") or raw.get("run_name") or "autoreport_task"),
        output_dir=str(raw.get("output_dir") or raw.get("report_dir") or "runs/autoreport"),
        report_title=str(raw.get("report_title") or ""),
        audience=str(raw.get("audience") or "technical"),
        language=str(raw.get("language") or "zh-CN"),
        evidence_paths=evidence,
        max_files_per_path=int(raw.get("max_files_per_path") or 700),
        max_text_chars_per_file=int(raw.get("max_text_chars_per_file") or 40000),
        max_report_chars_per_section=int(raw.get("max_report_chars_per_section") or 60000),
        include_raw_logs=bool(raw.get("include_raw_logs", True)),
        include_code_excerpt=bool(raw.get("include_code_excerpt", True)),
        use_llm=bool(raw.get("use_llm", True)),
        llm=dict(raw.get("llm") or {}),
    )


def load_config(path: str | Path) -> AutoReportConfig:
    p = Path(path).expanduser().resolve()
    suffix = p.suffix.lower()
    if suffix == ".json":
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    elif suffix in {".toml", ".tml"}:
        raw = tomllib.loads(p.read_text(encoding="utf-8-sig"))
    else:
        raise ValueError(f"Unsupported config format: {p}. Use JSON or TOML.")
    if not isinstance(raw, dict):
        raise ValueError("AutoReport config must be an object")
    return config_from_dict(raw)


def config_schema() -> dict[str, Any]:
    return {
        "schema_version": "autoreport.config.v1",
        "required": ["task_name", "output_dir", "evidence_paths", "llm"],
        "properties": {
            "task_name": "Report task/run name.",
            "output_dir": "Directory where AutoReport writes report.md, report.json, events and state.",
            "report_title": "Optional human-facing report title.",
            "audience": "technical | executive | delivery; used to tune the LLM-written article.",
            "language": "zh-CN or en-US.",
            "evidence_paths": [
                {
                    "label": "autorealize",
                    "path": "path/to/autorealize/output",
                    "kind": "autorealize | automl | mlevolve | generic",
                    "required": False,
                }
            ],
            "max_files_per_path": "Maximum files scanned below each evidence path.",
            "max_text_chars_per_file": "Maximum text excerpt read from each file.",
            "include_raw_logs": "Whether raw logs may be read as evidence for the LLM. Logs are not pasted into the report body.",
            "include_code_excerpt": "Whether best-solution code may be read as evidence for the LLM. Code is not pasted verbatim into the report body.",
            "use_llm": "Must be true. AutoReport is an LLM-written report generator and will fail when disabled.",
            "llm": {
                "model": "Required model name.",
                "base_url": "Required OpenAI-compatible base URL. DeepSeek /v1 is automatically redirected to /beta.",
                "api_key": "Required API key. CLI may also read DEEPSEEK_API_KEY.",
                "temperature": "Optional, default 0.25.",
                "max_tokens": "Optional, default 8192.",
                "max_prompt_chars": "Optional evidence briefing budget, default max_report_chars_per_section.",
            },
        },
    }


def dump_config(cfg: AutoReportConfig) -> dict[str, Any]:
    return {
        "task_name": cfg.task_name,
        "output_dir": cfg.output_dir,
        "report_title": cfg.report_title,
        "audience": cfg.audience,
        "language": cfg.language,
        "evidence_paths": [item.__dict__ for item in cfg.evidence_paths],
        "max_files_per_path": cfg.max_files_per_path,
        "max_text_chars_per_file": cfg.max_text_chars_per_file,
        "max_report_chars_per_section": cfg.max_report_chars_per_section,
        "include_raw_logs": cfg.include_raw_logs,
        "include_code_excerpt": cfg.include_code_excerpt,
        "use_llm": cfg.use_llm,
        "llm": cfg.llm,
    }

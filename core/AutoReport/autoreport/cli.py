from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from .collector import collect_evidence
from .config import AutoReportConfig, EvidencePath, config_from_dict, dump_config, load_config
from .events import ReportEventWriter
from .generator import generate_report


def parse_evidence(value: str) -> EvidencePath:
    if "=" not in value:
        path = value
        return EvidencePath(label=Path(path).name or "evidence", path=path)
    label, rest = value.split("=", 1)
    kind = "auto"
    path = rest
    if "::" in rest:
        path, kind = rest.rsplit("::", 1)
    return EvidencePath(label=label.strip() or "evidence", path=path.strip(), kind=kind.strip() or "auto")


def build_config(args: argparse.Namespace) -> AutoReportConfig:
    if args.config:
        cfg = load_config(args.config)
        raw = dump_config(cfg)
    else:
        raw = {
            "task_name": args.task_name or "autoreport_task",
            "output_dir": args.output_dir or "runs/autoreport",
            "report_title": args.report_title or "",
            "audience": args.audience or "technical",
            "language": args.language or "zh-CN",
            "evidence_paths": [],
        }
    if args.task_name:
        raw["task_name"] = args.task_name
    if args.output_dir:
        raw["output_dir"] = args.output_dir
    if args.report_title:
        raw["report_title"] = args.report_title
    llm = dict(raw.get("llm") or {})
    if args.llm_model:
        llm["model"] = args.llm_model
    if args.llm_base_url:
        llm["base_url"] = args.llm_base_url
    if args.llm_api_key:
        llm["api_key"] = args.llm_api_key
    raw["llm"] = llm
    raw["use_llm"] = True
    if args.evidence:
        raw["evidence_paths"] = [item.__dict__ for item in [parse_evidence(x) for x in args.evidence]]
    if not raw.get("evidence_paths"):
        raise ValueError("At least one evidence path is required. Use config.evidence_paths or --evidence label=path.")
    return config_from_dict(raw)


def run(cfg: AutoReportConfig) -> dict:
    output_dir = Path(cfg.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    events = ReportEventWriter(output_dir, run_id=run_id)
    events.log("autoreport.pipeline", "STARTED", task_name=cfg.task_name, output_dir=str(output_dir))
    (output_dir / "resolved_config.json").write_text(json.dumps(dump_config(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    bundle = collect_evidence(cfg, events)
    payload = generate_report(cfg, bundle, events)
    events.log("autoreport.pipeline", "COMPLETED", report_json=str(output_dir / "report.json"), report_md=str(output_dir / "report.md"))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an AutoDecision evidence-driven report.")
    parser.add_argument("--config", help="Path to AutoReport JSON/TOML config.")
    parser.add_argument("--task-name", help="Override task name.")
    parser.add_argument("--output-dir", help="Directory for AutoReport outputs.")
    parser.add_argument("--report-title", default="", help="Human-facing report title.")
    parser.add_argument("--audience", default="technical", help="technical | executive | delivery")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--llm-model", default="", help="Required LLM model name when not provided by config.")
    parser.add_argument("--llm-base-url", default="", help="Required OpenAI-compatible LLM base URL when not provided by config.")
    parser.add_argument("--llm-api-key", default="", help="Required LLM API key when not provided by config or DEEPSEEK_API_KEY.")
    parser.add_argument(
        "--evidence",
        action="append",
        help="Evidence path in form label=path or label=path::kind. Can be repeated.",
    )
    args = parser.parse_args(argv)
    try:
        cfg = build_config(args)
        run(cfg)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"AutoReport failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

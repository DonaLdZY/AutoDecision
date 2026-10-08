"""Resume a saved production article at its interrupted full audit."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.config import LLMConfig, write_config_yaml
from autoreport.audit_chunks import apply_audit_edits
from autoreport.events import ReportEventWriter
import autoreport.generator as generator


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    source, dest = args.source.resolve(), args.directory.resolve()
    if dest.exists() or not all(path.is_relative_to(OUT.resolve()) for path in (source, dest)):
        raise RuntimeError("Use an existing batch source and a fresh destination inside the batch")
    stages = module("industrial-stage-control")
    task = stages.current_task(args.slug)
    current = stages.fingerprint(stages.stage_artifacts(task, "automl"))
    old_result = read(source / "result.json")
    if old_result["source_fingerprint"] != current:
        raise RuntimeError("Saved production outputs no longer match current AutoML artifacts")
    if old_result.get("slug") != args.slug or old_result.get("output_limit") != 32768:
        raise RuntimeError("Saved generation identity or output limit does not match")
    source_paths = [source / "report_analysis.json", source / "report_draft.md"]
    hashes = {str(path): digest(path) for path in source_paths}
    analysis = read(source_paths[0])
    if analysis.get("analysis_complete") is not True or not analysis.get("method_cards"):
        raise RuntimeError("A completed real method analysis is required")
    draft = source_paths[1].read_text(encoding="utf-8")
    independent_edits = None
    if old_result.get("draft_independently_edited"):
        original_directory = Path(old_result["original_production_directory"])
        original_draft = (original_directory / "report_draft.md").read_text(encoding="utf-8")
        independent_edits = read(source / "independent-editorial-edits.json")
        if independent_edits["source_sha256"] != hashlib.sha256(original_draft.encode("utf-8")).hexdigest() or apply_audit_edits(original_draft, independent_edits) != draft:
            raise RuntimeError("Corrected draft does not match its exact independently recorded source edits")
    cfg, bundle, _ = module("measure-report-context").source_bundle(args.slug)
    cfg.output_dir = str(dest)
    if independent_edits and args.slug == "chemical":
        cfg.task_name, cfg.report_title = "压滤液铝浓度预测", "压滤液铝浓度预测方案交付报告"
    entry = module("validate-industrial-prompts").model_entry()
    cfg.llm = LLMConfig(model=entry["model"], base_url=entry["baseUrl"], api_key=entry["apiKey"],
        reasoning_effort="xhigh", max_tokens=32768, minimum_output_tokens=32768,
        request_timeout_seconds=900, max_retries=2, context_window_tokens=196608)
    generator._validate_report_article(cfg, draft, require_outline=True)
    usage = [json.loads(line) for line in (source / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not any(row.get("component") == "autoreport.writer" and row.get("finish_reason") == "stop" for row in usage):
        raise RuntimeError("The saved draft must have completed actual production writing")
    original_analyzer, original_writer = generator._analyze_report_context, generator._write_report_article
    dest.mkdir(parents=True)
    provenance = {"source_directory": str(source), "source_fingerprint": current,
        "saved_production_output_sha256": hashes, "prior_generation_result": old_result,
        "prior_usage": usage, "analysis_and_writer_reissued": False, "independent_draft_edits": independent_edits}
    save(dest / "audit-resume-provenance.json", provenance)
    result = {"passed": False, "slug": args.slug, "started_at": time.time(), "source_fingerprint": current,
        "output_limit": 32768, "configured_context_window_tokens": 196608,
        "scope": "Production full-source audit of unchanged saved real analysis and article; independent factual and executable-example review remains required"}
    save(dest / "result.json", result)
    events = ReportEventWriter(dest, print_events_to_console=False)
    print(json.dumps({"directory": str(dest), "stage": "resume_full_audit"}), flush=True)
    try:
        generator._analyze_report_context = lambda *_args, **_kwargs: analysis
        generator._write_report_article = lambda *_args, **_kwargs: draft
        os.environ["AUTOREPORT_PROMPT_CACHE_KEY_MODE"] = "enabled"
        with module("validate-report-partitions").report_validation_slot(stages):
            generator.generate_report(cfg, bundle, events)
        trace = read(dest / "report_trace.json")
        trace["resumed_saved_generation"] = provenance
        trace["llm_usage"] = [*usage, *trace["llm_usage"]]
        save(dest / "report_trace.json", trace)
        write_config_yaml(cfg, dest / "resolved_config.yaml")
        unchanged = current == stages.fingerprint(stages.stage_artifacts(task, "automl")) and hashes == {str(path): digest(path) for path in source_paths}
        audit = trace["audit"]
        result.update(passed=unchanged and audit.get("complete_draft_covered") is True and audit.get("status") in {"pass", "revised"},
            source_unchanged=unchanged, audit_status=audit.get("status"), usage=trace["llm_usage"], analysis_and_writer_reissued=False)
    except Exception as exc:
        result["error"] = str(exc).replace(entry["apiKey"], "[REDACTED]")
        raise
    finally:
        generator._analyze_report_context, generator._write_report_article = original_analyzer, original_writer
        result["finished_at"] = time.time()
        save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), "passed": result["passed"]}), flush=True)


if __name__ == "__main__":
    main()

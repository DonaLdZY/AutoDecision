"""Rewrite the rejected traffic article using saved real analysis and complete evidence."""
from __future__ import annotations

import argparse
import ast
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
from autoreport.config import LLMConfig
from autoreport.events import ReportEventWriter
from autoreport.prompt_context import encode_task_context
import autoreport.generator as generator


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    dest = args.directory.resolve()
    if dest.exists() or not dest.is_relative_to(OUT.resolve()):
        raise RuntimeError("A fresh validation directory inside this batch is required")
    stages = module("industrial-stage-control")
    task = stages.current_task("traffic")
    current = stages.fingerprint(stages.stage_artifacts(task, "automl"))
    source_result = read(args.source / "result.json")
    if source_result["source_fingerprint"] != current:
        raise RuntimeError("Saved source analysis does not match the current AutoML artifacts")
    analysis = read(args.source / "report_analysis.json")
    cfg, bundle, _ = module("measure-report-context").source_bundle("traffic")
    cfg.task_name = "门架车流预测"
    cfg.output_dir = str(dest)
    entry = module("validate-industrial-prompts").model_entry()
    cfg.llm = LLMConfig(model=entry["model"], base_url=entry["baseUrl"], api_key=entry["apiKey"],
        reasoning_effort="xhigh", max_tokens=32768, minimum_output_tokens=32768,
        request_timeout_seconds=900, max_retries=2, context_window_tokens=196608)
    workspace = Path(task["auto_ml_workspace_dir"])
    exported = workspace / "best_solution"
    manifest = read(exported / "solution_manifest.json")
    implementation = exported / manifest["implementation_path"]
    code = implementation.read_text(encoding="utf-8")
    requested = {"_prepare_prediction_data", "predict", "infer_new_data", "main", "train"}
    snippets = {node.name: ast.get_source_segment(code, node) for node in ast.parse(code).body
                if isinstance(node, ast.FunctionDef) and node.name in requested}
    journal = read(Path(task["auto_ml_log_dir"]) / "journal.json")
    node_facts = [{key: node.get(key) for key in ("id", "method_family", "metric", "evaluation_protocol", "stage", "fusion_sources")}
                  for node in journal["nodes"] if node.get("search_eligible")]
    evidence = {
        "source_policy": "These exact source records and code excerpts supplement, and do not replace, the complete original task rules and measured result facts. Distinguish node IDs from SHA256 values and use exact ID-score pairs.",
        "accepted_node_facts": node_facts,
        "public_wrapper_path": str(exported / "solution.py"),
        "public_wrapper": (exported / "solution.py").read_text(encoding="utf-8"),
        "exported_implementation_path": str(implementation),
        "exported_implementation_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        "verified_api_source": snippets,
        "candidate_baselines": read(exported / "runtime/working/candidate_comparison.json"),
        "candidate_development_runtime": read(exported / "runtime/working/development_metrics.json"),
        "independent_development_score": read(OUT / "optimization-validation/traffic-score-0dbdc708-1788816138141114400/result.json"),
        "corrections": [
            "The previous writer returned provider failure text and no usable article. Generate the complete requested ten-section report, not an audit replacement or a narrow delivery review.",
            "32b13867507b452f8fb84f8dc5ecce07 is ensemble with development MAE4.242446510802672; 0a8c6ccf540d4634ae86eca33a6bc988 is tree_boosting with MAE4.245311327873923. A 64-character implementation SHA256 is not a node ID.",
            "The winner uses deterministic causal peer-attention features followed by Poisson and log-L1 LightGBM experts with training-only rolling OOF weight selection. Relation-topology graph attention was not executed; do not conflate that limitation with absence of all attention features. Cross-branch Fusion operator was not executed.",
            "The exact predict source returns a pandas DataFrame with the four output columns. The exported wrapper delegates extra symbols through __getattr__, so infer_new_data exists and accepts model_path,input_dir,output_dir,forecast_origins. The implementation also has an infer CLI. Do not claim these entrypoints do not exist. Existing verification does not certify untested CLI examples.",
            "The selected development score has independent recomputation. The source and verification are included; do not call it only a candidate self-report.",
            "Report actual final business threshold failures and both PDF/DOCX60-minute strata. Model/inference completion is not overall business acceptance or production SLA completion.",
        ],
    }
    analysis["independent_review_corrections"] = evidence["corrections"]
    original_analyzer = generator._analyze_report_context
    original_prepare = generator._prepare_report_context

    def reuse_analysis(*_args, **_kwargs):
        return analysis

    def prepare(*positional, **kwargs):
        original_prepare(*positional, **kwargs)
        settings = positional[1]
        settings["task_context_prefix"] += encode_task_context(evidence, heading="Independent report review source records")
        settings["audit_feedback"] = evidence["corrections"]

    dest.mkdir(parents=True)
    save(dest / "independent-review-evidence.json", evidence)
    result = {"passed": False, "slug": "traffic", "started_at": time.time(), "source_fingerprint": current,
              "analysis_source": str(args.source.resolve()), "output_limit": 32768, "configured_context_window_tokens": 196608,
              "scope": "Real production writer and full-source auditor with independently reviewed saved real analyzer output; final independent review required"}
    save(dest / "result.json", result)
    events = ReportEventWriter(dest, print_events_to_console=False)
    print(json.dumps({"directory": str(dest), "stage": "writer_and_auditor"}), flush=True)
    try:
        generator._analyze_report_context = reuse_analysis
        generator._prepare_report_context = prepare
        os.environ["AUTOREPORT_PROMPT_CACHE_KEY_MODE"] = "enabled"
        with module("validate-report-partitions").report_validation_slot(stages):
            generator.generate_report(cfg, bundle, events)
        trace = read(dest / "report_trace.json")
        unchanged = current == stages.fingerprint(stages.stage_artifacts(task, "automl"))
        result.update(passed=unchanged and trace["audit"].get("complete_draft_covered") is True,
                      source_unchanged=unchanged, audit_status=trace["audit"].get("status"), usage=trace["llm_usage"])
    except Exception as exc:
        result["error"] = str(exc).replace(entry["apiKey"], "[REDACTED]")
        raise
    finally:
        generator._analyze_report_context = original_analyzer
        generator._prepare_report_context = original_prepare
        result["finished_at"] = time.time()
        save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), "passed": result["passed"]}), flush=True)


if __name__ == "__main__":
    main()

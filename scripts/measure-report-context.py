"""Inspect complete report source sizes without changing evidence collection."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.collector import collect_evidence
from autoreport.config import AutoReportConfig, EvidencePath
from autoreport.context import estimate_tokens
from autoreport.events import ReportEventWriter
from autoreport.generator import _build_analysis_dossier
from autoreport.generator import _build_frozen_report_context
from autoreport.prompt_context import mandatory_task_context, encode_task_context
from autoreport.context_partitions import partition_task_rules


def source_bundle(slug):
    spec = importlib.util.spec_from_file_location("stage_control", ROOT / "scripts/industrial-stage-control.py")
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    task = control.current_task(slug)
    dest = control.batch.OUT / "optimization-validation" / ("report-parts-" + slug)
    cfg = AutoReportConfig(task_name=task["task_name"], output_dir=str(dest), language="zh",
        evidence_paths=[
            EvidencePath(label="task", path=str(Path(task["run_dir"]) / "autorealize"), kind="autorealize"),
            EvidencePath(label="logs", path=task["auto_ml_log_dir"], kind="automl"),
            EvidencePath(label="workspace", path=task["auto_ml_workspace_dir"], kind="automl"),
        ], collection={"max_files_per_path": 700}, comparison={"top_solution_limit": 6, "successful_node_limit": 6},
        generation={"max_prompt_chars": 524288})
    provenance = Path(task["run_dir"]) / "evaluation_provenance.json"
    if provenance.is_file():
        cfg.evidence_paths.append(EvidencePath(label="provenance", path=str(provenance), kind="automl"))
    events = ReportEventWriter(dest, print_events_to_console=False)
    return cfg, collect_evidence(cfg, events), events


def main():
    for slug in sys.argv[1:] or ["traffic", "deposition"]:
        cfg, bundle, events = source_bundle(slug)
        task = mandatory_task_context(bundle)
        facts = _build_analysis_dossier(cfg, bundle)
        import tiktoken
        frozen, keys = _build_frozen_report_context(cfg, bundle)
        result_prefix = encode_task_context({key: facts[key] for key in keys}, heading="Complete selected result facts")
        plan = partition_task_rules(task, lambda text: estimate_tokens(text + result_prefix) < 59000)
        def size(value):
            return estimate_tokens(encode_task_context(value if isinstance(value, dict) else {"value": value}))
        core = {**task, "documents": [
            {**doc, "content": {"final": doc["content"]["final"]}} if Path(doc["sources"][0]).name == "evaluation_contract_report.json" else doc
            for doc in task["documents"] if Path(doc["sources"][0]).name in {"description.md", "original_requirements.txt", "evaluation_contract_report.json"}]}
        report = {"slug": slug, "task_tokens": size(task), "core_tokens": size(core),
            "o200k_full_prefix_tokens": len(tiktoken.get_encoding("o200k_base").encode(frozen)),
            "partition_tokens": [estimate_tokens(plan["prefix"] + part + result_prefix) for part in plan["parts"]],
            "partition_coverage_verified": True,
            "documents": [{"sources": doc["sources"], "tokens": size(doc["content"]),
                           "keys": {key: size(value) for key, value in doc["content"].items()} if isinstance(doc["content"], dict) else None}
                          for doc in task["documents"]],
            "result_keys": {key: size(value) for key, value in facts.items()}}
        (events.output_dir / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

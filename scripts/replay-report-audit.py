"""Audit an existing report draft with real API in a new evidence directory.

No search, training, holdout evaluation, historical report mutation or package
publication. Credentials come only from runtime environment/private settings.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rewrite", action="store_true", help="Replay writer from saved analysis before audit.")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".codex-work") or output.exists():
        raise ValueError("Use a new output directory inside .codex-work.")
    sys.path.insert(0, str(ROOT / "core/AutoReport"))
    from autoreport.config import load_config
    from autoreport.collector import collect_evidence
    from autoreport.events import ReportEventWriter
    from autoreport.generator import _validate_llm_config, _prepare_report_context, _audit_report_article, _write_report_article

    os.environ["AUTOREPORT_COMPACT_CONTEXT"] = "enabled"
    original = args.report_dir.resolve()
    cfg = load_config(original / "resolved_config.yaml")
    private = yaml.safe_load((ROOT / "frontend/config/global_settings.yaml").read_text(encoding="utf-8-sig"))["llm"]
    model = next(m for m in private["modelLibrary"] if m["model"] == cfg.llm.model)
    cfg = replace(cfg, output_dir=str(output), llm=replace(
        cfg.llm, api_key=os.environ.get("AUTODECISION_TEST_LLM_API_KEY") or model["apiKey"], enable_thinking=True))
    output.mkdir(parents=True)
    events = ReportEventWriter(output, print_events_to_console=True)
    bundle = collect_evidence(cfg, events)
    settings = _validate_llm_config(cfg)
    _prepare_report_context(cfg, settings, bundle, events, allow_partitions=True)
    draft = (original / "report_draft.md").read_text(encoding="utf-8")
    analysis = json.loads((original / "report_analysis.json").read_text(encoding="utf-8"))
    if args.rewrite:
        draft = _write_report_article(cfg, settings, analysis, events)
        (output / "rewritten-draft.md").write_text(draft, encoding="utf-8")
    article, audit = _audit_report_article(cfg, settings, analysis, draft, events)
    (output / "audited-draft.md").write_text(article, encoding="utf-8")
    (output / "audit-result.json").write_text(json.dumps({
        "scope": "Real auditor only; no training, holdout access, historical edits or delivery publication.",
        "original_draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(), "audit": audit,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: audit.get(k) for k in ("status", "complete_draft_covered", "complete_task_sources_covered", "parts")}))


if __name__ == "__main__":
    main()

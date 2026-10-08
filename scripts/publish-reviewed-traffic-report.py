"""Install the independently verified traffic report without changing gateway state."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

from markdown_it import MarkdownIt
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.config import load_config
from autoreport.generator import _validate_report_article


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_examples(markdown):
    return [token.content for token in MarkdownIt("commonmark").parse(markdown)
            if token.type == "fence" and token.info.strip() == "python"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--examples-result", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(OUT.resolve()):
        raise ValueError("The reviewed report must belong to this batch")
    spec = importlib.util.spec_from_file_location("publish_traffic_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    with stages.admission_lock():
        task = stages.current_task("traffic")
        if task["status"] == "running":
            raise RuntimeError("Cannot publish over an active task stage")
        seconds = stages.verified_search_seconds(task)
        source_fingerprint = stages.fingerprint(stages.stage_artifacts(task, "automl"))
        prepared = read(directory / "result.json")
        examples = read(args.examples_result)
        if not prepared.get("passed") or not examples.get("passed") or not examples.get("source_unchanged"):
            raise RuntimeError("Both independent review and actual report examples must pass")
        if prepared["source_fingerprint"] != source_fingerprint:
            raise RuntimeError("The reviewed AutoML evidence changed")
        files = ("report.md", "report.json", "report_trace.json")
        hashes = {name: digest(directory / name) for name in files}
        if prepared["report_fingerprints"] != hashes:
            raise RuntimeError("The independently reviewed report was modified")
        tested_path = Path(examples["report"])
        if digest(tested_path) != examples["report_sha256"]:
            raise RuntimeError("The tested report changed after executing its examples")
        article = (directory / "report.md").read_text(encoding="utf-8")
        tested_article = tested_path.read_text(encoding="utf-8")
        if python_examples(article) != python_examples(tested_article):
            raise RuntimeError("The final article's examples differ from the actually executed examples")
        for code in python_examples(article):
            ast.parse(code)
        report, trace = read(directory / "report.json"), read(directory / "report_trace.json")
        if report["article_markdown"] != article:
            raise RuntimeError("Report JSON and Markdown disagree")
        assert len(report["sections"]) == 10
        assert trace["audit"]["complete_draft_covered"] is True
        required_strings = (
            "0dbdc708fc074653a2b0490009760a40", "4.238087056452185", "5.071793636400893",
            "8.644157232465892", "0.8905660666653785", "0.8419297667129133",
            "0.7994285976427259", "1,717", "0.48", "0.84", "88,086", "318 行",
            "32b13867507b452f8fb84f8dc5ecce07", "4.242446510802672",
            "0a8c6ccf540d4634ae86eca33a6bc988", "4.245311327873923",
            "PDF", "DOCX", "Fusion operator 未执行", "验证集指纹不匹配",
        )
        if any(value not in article for value in required_strings):
            raise RuntimeError("A reviewed key result or limitation disappeared from the final article")
        config = report["config"]
        if config["llm"].get("api_key"):
            raise RuntimeError("Resolved report configuration must not contain credentials")
        target = Path(task["run_dir"]).resolve() / "report"
        if not target.is_relative_to(OUT.resolve()):
            raise RuntimeError("Task report path is outside this batch")
        config = {**config, "output_dir": str(target)}
        config_path = directory / "resolved_config.yaml"
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _validate_report_article(load_config(config_path), article, require_outline=True)
        source = Path(prepared["source_directory"])
        provider_usage = read(source / "result.json")["usage"]
        known_input = sum(row["prompt_tokens"] for row in provider_usage if row.get("cache_tokens_known"))
        known_cache = sum(row.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                          for row in provider_usage if row.get("cache_tokens_known"))
        review = {
            "passed": True, "installation_allowed": True, "task_id": task["id"],
            "autorealize_artifact_fingerprint": stages.fingerprint(stages.stage_artifacts(task, "autorealize")),
            "automl_artifact_fingerprint": source_fingerprint, "report_sha256": hashes,
            "verified_search_seconds": seconds,
            "strengths": [
                "The real system produced a full ten-section report and completed a full-source provider audit.",
                "The report explains the 92 causal features, deterministic peer attention, Poisson/log-L1 experts, rolling training-only OOF weights and actual final six-day expert refit.",
                "Exact report inference and output-directory examples reproduce 954 frozen final predictions; the training entrypoint reproduces 954 development predictions in a relocated export.",
            ],
            "weaknesses": [
                "The provider auditor missed an incorrect no-refit conclusion, a guessed model path, unreported existing weights and an undefined training-example variable; independent exact edits corrected them.",
                "Final 30-minute high-flow thresholds fail, and the two 60-minute source strata disagree. One week of data cannot establish production SLA or long-term generalization.",
                "The requested model was gpt-5.6-luna but the provider reported gpt-5.6-terra for both calls; the writer did not report cached tokens.",
            ],
            "system_changes": [
                "Provider busy and reasoning-markup content is rejected; the writer retries unusable content once and all executed-candidate reports must retain substantive required sections.",
                "Full independent-verification records and directory-linked training metadata now enter the frozen report context.",
                "Independent report edits and relocated executable examples are preserved separately from the provider's full audit, with exact artifact fingerprints.",
            ],
            "constraint_checks": [
                "Day-first seven-day parsing, 159-gantry default universe, common forecast origins, 30/60-minute target windows and strict B-01 event causality are retained.",
                "Search-development MAE and final holdout MAE/RMSE remain separated; final refit keeps the original OOF weights frozen and never fits to seventh-day labels.",
                "Unresolved topology semantics, both PDF/DOCX acceptance strata, missing business NEW input, fallback limitations and production SLA gaps remain explicit.",
                "No cross-branch Fusion execution or causal feature-ablation gain is claimed; an incompatible split-fingerprint candidate is not ranked against the winner.",
            ],
            "quality_checks": {
                "required_substantive_sections": 10, "report_json_markdown_equal": True,
                "exact_final_code_examples_equal_tested_examples": True,
                "final_edit_after_example_source": "Only verified per-gantry output-path prose and table rows differ from the executed report; all Python fences are byte-identical.",
                "report_examples": examples, "independent_source_evidence": str(directory / "independent-source-evidence.json"),
                "final_per_gantry_rows": 318, "final_prediction_rows": 88086,
                "final_evaluation_repeated": False, "source_artifacts_unchanged": True,
            },
            "usage_analysis": {
                "calls": provider_usage,
                "prompt_tokens": sum(row["prompt_tokens"] for row in provider_usage),
                "completion_tokens": sum(row["completion_tokens"] for row in provider_usage),
                "reported_cache_fraction_among_known_calls": known_cache / known_input,
                "cache_scope": "The auditor reported cached tokens; the writer cache rate is unknown, not zero.",
                "output_limit": 32768,
                "remaining_improvement": "Keep complete task authority, but make finalization source and exported path roles explicit so the analyzer cannot conflate post-verification immutability with skipped final refitting.",
            },
            "evidence_paths": [str(directory / name) for name in files] + [
                str(directory / "independent-editorial-edits.json"), str(directory / "independent-source-evidence.json"),
                str(args.examples_result.resolve()), str(source / "report_draft.md"), str(source / "audit-part-1.json"),
                str(Path(task["auto_ml_workspace_dir"]) / "final_evaluation/independent-verification.json"),
                str(ROOT / "scripts/review-traffic-report.py"), str(ROOT / "scripts/verify-traffic-report-examples.py"),
            ],
        }
        review_path = directory / "independent-review.json"
        save(review_path, review)
        archive = None
        if target.exists():
            archive = OUT / "stage-archives/traffic" / f"report-before-independent-publication-{time.time_ns()}"
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, archive)
        target.mkdir(parents=True, exist_ok=True)
        for name in (*files, "resolved_config.yaml", "independent-review.json", "current_state.json", "event_stream.jsonl"):
            if (directory / name).is_file():
                shutil.copy2(directory / name, target / name)
        if {name: digest(target / name) for name in files} != hashes:
            raise RuntimeError("Installed report file checksums disagree")
        if stages.fingerprint(stages.stage_artifacts(task, "automl")) != source_fingerprint:
            raise RuntimeError("AutoML evidence changed during installation")
        receipt = {"installed": True, "source": str(directory), "target": str(target),
            "archive": str(archive) if archive else None, "review": str(review_path), "report_sha256": hashes,
            "gateway_state_changed": False, "next": "register-completed-report.py validates a recovery receipt before the parent activates the new gateway recovery endpoint."}
        save(directory / "installation.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()

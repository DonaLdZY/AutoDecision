"""Install an independently accepted chemical report without changing task state."""
from __future__ import annotations

import argparse
import ast
from contextlib import nullcontext
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
from autoreport.config import load_config, write_config_yaml
from autoreport.generator import _validate_report_article


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blocks(markdown):
    return [token.content for token in MarkdownIt("commonmark").parse(markdown)
        if token.type == "fence" and token.info.strip() == "python"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--examples-result", type=Path, required=True)
    parser.add_argument("--review-only", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(OUT.resolve()):
        raise ValueError("The report must belong to this batch")
    spec = importlib.util.spec_from_file_location("publish_chemical_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    with nullcontext() if args.review_only else stages.admission_lock():
        task = stages.current_task("chemical")
        if task["status"] == "running":
            raise RuntimeError("Cannot install over an active task stage")
        seconds = stages.verified_search_seconds(task)
        automl_fingerprint = stages.fingerprint(stages.stage_artifacts(task, "automl"))
        prepared, examples = read(directory / "result.json"), read(args.examples_result)
        if not prepared.get("passed") or prepared.get("source_fingerprint") != automl_fingerprint or not examples.get("passed"):
            raise RuntimeError("Source-bound independent report review and examples must pass")
        tested = Path(examples["report"])
        if digest(tested) != examples["report_sha256"]:
            raise RuntimeError("The tested report changed after execution")
        article = (directory / "report.md").read_text(encoding="utf-8")
        if blocks(article) != blocks(tested.read_text(encoding="utf-8")):
            raise RuntimeError("Final Python examples differ from the actually executed examples")
        for code in blocks(article):
            ast.parse(code)
        assert len(examples["examples"]) == 2 and {row["training"] for row in examples["examples"]} == {True, False}
        for row in examples["examples"]:
            assert row["passed"] and any(call.get("frozen_prediction_checked") for call in row["checks"]["calls"])
        report, trace = read(directory / "report.json"), read(directory / "report_trace.json")
        assert report["article_markdown"] == article and len(report["sections"]) == 10
        assert trace["audit"]["complete_draft_covered"] is True
        assert trace["prior_audit"]["complete_draft_covered"] is True
        required = ("58002f37a3fd4bf88c950e4375784ecb", "0.09462905691526995", "0.08282314083102459",
            "0.08039473684210528", "3.02%", "0.701661217363691", "1525", "1519", "914", "1221",
            "10800.4204284", "25 个节点", "9 个候选", "12 个；另有独立非法输入拒绝检查",
            "pinned_memory_bytes=268435456", "并非显存不足", "`fusion`", "硫酸锂", "硫酸铝",
            "prediction_cutoff-60分钟 < SampleTime <= prediction_cutoff", "shape == (1,)", "label_available_at")
        if any(value not in article for value in required):
            raise RuntimeError("A reviewed material result or constraint disappeared")
        target = Path(task["run_dir"]).resolve() / "report"
        if not target.is_relative_to(OUT.resolve()):
            raise RuntimeError("The target report directory is outside this batch")
        cfg = load_config(directory / "resolved_config.yaml")
        raw_config = yaml.safe_load((directory / "resolved_config.yaml").read_text(encoding="utf-8"))
        assert not raw_config["llm"].get("api_key") and not report["config"]["llm"].get("api_key")
        assert cfg.llm.max_tokens == cfg.llm.minimum_output_tokens == 32768
        cfg.output_dir = str(target)
        write_config_yaml(cfg, directory / "resolved_config.yaml")
        _validate_report_article(cfg, article, require_outline=True)
        files = ("report.md", "report.json", "report_trace.json")
        hashes = {name: digest(directory / name) for name in files}
        production_usage = trace["llm_usage"]
        partition_dir = OUT / "optimization-validation/report-full-chemical-20260908"
        attempts = read(partition_dir / "attempt-history.json")
        partition_usage = [json.loads(line) for line in (partition_dir / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        partition_usage = [row for row in partition_usage if row["ts"] >= attempts["first_full_attempt_started_at"]]
        all_usage = {row["request_id"]: row for row in [*partition_usage, *production_usage]}
        known = [row for row in all_usage.values() if row.get("cache_tokens_known")]
        known_input = sum(row["prompt_tokens"] for row in known)
        known_cached = sum(row["prompt_tokens_details"].get("cached_tokens", 0) for row in known)
        source = Path(prepared["source_directory"])
        review = {
            "passed": True, "installation_allowed": True, "task_id": task["id"],
            "autorealize_artifact_fingerprint": stages.fingerprint(stages.stage_artifacts(task, "autorealize")),
            "automl_artifact_fingerprint": automl_fingerprint, "report_sha256": hashes,
            "verified_search_seconds": seconds,
            "strengths": [
                "The real system completed method analysis, source-code retrieval, writing and a complete original-source report audit; the final document contains ten substantive sections.",
                "The final report preserves all target rows, atomic-time splits, duplicate and high-status labels, the exact historical window, actual model recipe and the worse final holdout result.",
                "Both exact public API examples passed in copied workspaces. Final inference uses the1221-row model; default training fits914rows and914preprocessor rows. Both example predictions match their frozen outputs.",
            ],
            "weaknesses": [
                "Final holdout MAE0.08282314083102459 is about3.02% worse than the median baseline0.08039473684210528. All six high-status labels occur in development and have MAE0.701661217363691; holdout high-status performance is unavailable.",
                "The provider auditor introduced unsupported changes to default-model training population, valid inference-request count and train return values. Independent source checks and actual example execution corrected these rather than accepting the audit blindly.",
                "Production batch relationships, laboratory delay, chemical unit semantics, online feature availability and real future requests remain unverified.",
                "Renice repeatedly returned reasoning-prefixed responses, HTTP524 and a stream deadline. Cache metadata is missing on several successful calls, and requested gpt-5.6-luna responses reported gpt-5.6-terra.",
            ],
            "system_changes": [
                "Use the empirically supported196608context declaration for this complete88,460-token frozen prefix while retaining32768output and headroom; all original task sources remain present.",
                "Saved completed real analysis and writing are reused after auditor failures with source fingerprints and content hashes, avoiding repeated generation of valid stages.",
                "Reject service-error envelopes and reasoning-markup responses, retain failure usage and retry within a finite bound; completed stages are not represented as business failures.",
                "Independent edits preserve exact delivered code, journal flags and model metadata; structured Markdown headings avoid false boundaries from Python comments or mathematical equals signs.",
            ],
            "constraint_checks": [
                "1525labels,1519atomic groups,914/307/304split rows and911/304/304split groups are preserved; all high-status and conflicting duplicate labels remain scored.",
                "The history window is cutoff-60min < SampleTime <= cutoff; schema is exactly63ordered original device columns. No labels, weather, absent external flow or future observations become features.",
                "Search selection uses development MAE only. The frozen final1221-row fit and final holdout score remain unchanged; this report work did not repeat holdout evaluation.",
                "The selected node executed a cross-branch fusion operation; the actual delivered predictor remains a single robustly preprocessed CatBoostRegressor.",
                "GPU fallback is the recorded pinned_memory_bytes parameter parsing error, not OOM; persistent reduced execution concurrency remains in force.",
            ],
            "quality_checks": {"required_substantive_sections": 10, "report_json_markdown_equal": True,
                "exact_python_examples_equal_executed": True, "report_examples": examples,
                "final_evaluation_repeated": False, "source_artifacts_unchanged": True,
                "model_sha256": "0eb0b53a8b1aa71fbf6c406861c4f1c8d7c0e408025617c62d63092ccb6f713c",
                "reviewed_provider_changes": "Preserved the verified common evaluation protocol and production limitations; corrected unsupported API and candidate-count claims using original source and actual execution."},
            "usage_analysis": {"completed_full_prefix_pipeline_calls_including_rejected_content": len(production_usage),
                "complete_prefix_input_tokens": sum(row["prompt_tokens"] for row in production_usage),
                "complete_prefix_output_tokens": sum(row["completion_tokens"] for row in production_usage),
                "generation_attempt_calls_with_usage_including_prior_partition_failures": len(all_usage),
                "generation_attempt_input_tokens": sum(row["prompt_tokens"] for row in all_usage.values()),
                "generation_attempt_output_tokens": sum(row["completion_tokens"] for row in all_usage.values()),
                "known_cache_call_count": len(known), "known_cache_input_tokens": known_input,
                "reported_cached_tokens": known_cached,
                "cache_ratio_on_calls_with_cache_telemetry_only": known_cached / known_input if known_input else None,
                "overall_cache_ratio": None, "requested_output_limit": 32768,
                "requested_model": "gpt-5.6-luna", "response_models": sorted({row.get("response_model") for row in all_usage.values()}),
                "limitations": "API errors without usage remain unknown and are excluded from token sums, not counted as zero. Earlier semantic A/B and read-only probes are separate validation cost. No provider price schedule or reliable overall cache telemetry was supplied.",
                "calls": list(all_usage.values())},
            "evidence_paths": [str(directory / name) for name in files] + [
                str(directory / "independent-editorial-edits.json"), str(directory / "independent-source-evidence.json"),
                str(args.examples_result.resolve()), str(source / "result.json"), str(source / "audit-part-1.json"),
                str(source / "audit-resume-provenance.json"), str(partition_dir / "attempt-history.json"),
                str(OUT / "optimization-validation/report-full-prefix-chemical-20260908/result.json"),
                str(OUT / "optimization-validation/report-audit-resume-chemical-20260908/result.json"),
                str(OUT / "optimization-validation/report-partition-chemical-semantic-20260908/result.json"),
                str(Path(task["auto_ml_workspace_dir"]) / "final_evaluation/independent-verification.json"),
                str(ROOT / "scripts/verify-chemical-report-examples.py"), str(ROOT / "scripts/review-chemical-report.py"),
            ],
        }
        for path in review["evidence_paths"]:
            if not Path(path).is_file():
                raise RuntimeError("Missing independent review evidence: " + path)
        save(directory / "independent-review.json", review)
        if args.review_only:
            print(json.dumps({"independently_accepted": True, "installed": False,
                "review": str(directory / "independent-review.json"), "report_sha256": hashes}, ensure_ascii=False))
            return
        archive = None
        if target.exists():
            archive = OUT / "stage-archives/chemical" / f"report-before-independent-publication-{time.time_ns()}"
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, archive)
        target.mkdir(parents=True, exist_ok=True)
        for name in (*files, "resolved_config.yaml", "independent-review.json", "current_state.json", "event_stream.jsonl"):
            if (directory / name).is_file():
                shutil.copy2(directory / name, target / name)
        assert {name: digest(target / name) for name in files} == hashes
        assert stages.fingerprint(stages.stage_artifacts(task, "automl")) == automl_fingerprint
        receipt = {"installed": True, "source": str(directory), "target": str(target),
            "archive": str(archive) if archive else None, "review": str(directory / "independent-review.json"),
            "report_sha256": hashes, "gateway_state_changed": False}
        save(directory / "installation.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()

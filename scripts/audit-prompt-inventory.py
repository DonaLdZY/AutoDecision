"""Measure prompt sources and available task context, and seal a reviewed optimization."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autorealize.prompt_cache import estimate_text_tokens, lossless_json
from autoreport.collector import collect_evidence
from autoreport.config import AutoReportConfig, EvidencePath
from autoreport.events import ReportEventWriter
from autoreport.prompt_context import encode_task_context, mandatory_task_context


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args()
    files = []
    for directory in ("core/AutoRealize/autorealize", "core/AutoRealize/config", "core/AlgoEvolve/config", "core/AlgoEvolve/agents", "core/AlgoEvolve/engine",
                      "core/AlgoEvolve/llm", "core/AlgoEvolve/utils", "core/AutoReport/autoreport"):
        files.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and path.suffix in {".py", ".md", ".yaml"} and "__pycache__" not in path.parts)
    files.extend(ROOT / name for name in ("core/AlgoEvolve/run.py", "core/AlgoEvolve/service_api.py", "frontend/backend/app.py",
                 "scripts/industrial-examples.py", "scripts/industrial-stage-control.py",
                 "scripts/repair-industrial-task-definition.py", "scripts/recover-industrial-generation.py",
                 "scripts/audit-industrial-usage.py", "scripts/validate-industrial-search-phase.py",
                 "scripts/validate-industrial-report-context.py", "core/AutoReport/requirements.txt"))
    files.append(ROOT / "scripts/migrate-industrial-node-workspace.py")
    files.append(ROOT / "scripts/restart-industrial-services.py")
    files.append(ROOT / "scripts/audit-delivery-authority-request.py")
    files.append(ROOT / "scripts/audit-delivery-investigation-context.py")
    files.append(ROOT / "scripts/validate-qdi-record-encoding.py")
    files.append(ROOT / "scripts/rewrite-traffic-report.py")
    files.append(ROOT / "scripts/validate-report-partitions.py")
    files.append(ROOT / "scripts/register-completed-report.py")
    files.append(ROOT / "frontend/backend/report_recovery.py")
    files.extend(ROOT / "scripts" / name for name in (
        "validate-industrial-prompts.py", "verify-steel-candidate-inference.py",
        "verify-steel-candidate-retraining.py", "verify-steel-search-artifacts.py",
        "recover-steel-final-input.py", "verify-steel-final-artifacts.py",
        "revise-industrial-report.py",
        "verify-ai4i-task-definition.py",
        "verify-steel-report-examples.py",
        "review-industrial-search-candidate.py",
        "verify-ai4i-search-trial.py",
        "verify-ai4i-preexecution-repair.py",
        "probe-industrial-gpu.py",
        "configure-industrial-gpu.py",
        "simplify-industrial-task-hints.py",
        "audit-autorealize-latency.py",
        "validate-qdi-routing.py",
        "restore-industrial-provider.py",
        "watch-industrial-night.py",
        "validate-industrial-provenance.py",
        "recompile-industrial-task-definition.py",
        "verify-traffic-task-definition.py",
        "verify-deposition-task-definition.py",
        "validate-industrial-continuation.py",
        "repair-industrial-input-layout.py",
        "verify-deposition-input-layout.py",
        "verify-traffic-search-score.py",
        "verify-deposition-search-score.py",
        "verify-deposition-candidate-inference.py",
        "verify-traffic-candidate-inference.py",
        "verify-industrial-final-inference.py",
        "repair-traffic-final-interface.py",
        "validate-planner-schema.py",
        "validate-full-rewrite-prompt.py",
        "verify-delivery-read-contracts.py",
        "diagnose-industrial-gpu-candidate.py",
        "validate-offline-prediction-policy.py",
        "verify-chemical-window-coverage.py",
        "verify-chemical-candidate-inference.py",
        "verify-chemical-final-inference.py",
        "verify-chemical-search-score.py",
        "verify-chemical-report-examples.py",
        "verify-delivery-task-definition.py",
        "verify-delivery-solver.py",
        "prepare-delivery-recovery-context.py",
        "resume-report-audit.py",
        "review-chemical-report.py",
    ))
    files.extend(OUT.glob("*-protocol.md"))
    files.append(OUT / "manifest.json")
    files.extend(OUT.glob("runtime-resource-profile.json"))
    files.extend((OUT / "tasks").glob("*/runtime_resource_override.json"))
    fingerprints = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    prompt_files = []
    for path in files:
        if "prompt" in path.as_posix().lower() and path.suffix == ".md":
            content = path.read_text(encoding="utf-8-sig")
            prompt_files.append({"path": path.relative_to(ROOT).as_posix(), "chars": len(content),
                                 "estimated_tokens": estimate_text_tokens(content)})
    tasks = []
    for item in read(OUT / "manifest.json")["tasks"]:
        payload = item["payload"]
        protocol = payload["auto_realize"]["task_hint"]
        root = Path(payload["output_root"]) / payload["task_name"] / "autorealize"
        row = {"slug": item["slug"], "protocol_chars": len(protocol),
               "protocol_estimated_tokens": estimate_text_tokens(protocol),
               "task_definition_complete": (root / "description.md").is_file(),
               "available_structured_artifacts": []}
        for name in ("constraint_memory.json", "authoritative_task_memory.json", "agent_context_pack.json", "automl_context_pack.json"):
            path = root / "realize_report" / name
            if path.is_file():
                value = read(path)
                raw = json.dumps(value, ensure_ascii=False, indent=2)
                encoded = lossless_json(value)
                row["available_structured_artifacts"].append({"name": name, "raw_chars": len(raw),
                    "lossless_chars": len(encoded), "estimated_tokens": estimate_text_tokens(encoded)})
        if root.is_dir():
            cfg = AutoReportConfig(task_name=item["slug"], output_dir=str(OUT / "inventory"),
                evidence_paths=[EvidencePath(label="available task definition", path=str(root))])
            events = ReportEventWriter(OUT / "inventory", run_id=item["slug"], print_events_to_console=False)
            bundle = collect_evidence(cfg, events)
            context = encode_task_context(mandatory_task_context(bundle))
            row["available_report_mandatory_chars"] = len(context)
            row["available_report_mandatory_estimated_tokens"] = estimate_text_tokens(context)
            row["context_measurement_scope"] = "Currently available artifacts only; final handoff must be remeasured before next stage"
        tasks.append(row)
    probes = []
    for path in sorted((OUT / "optimization-validation").glob("*/result.json")):
        result = read(path)
        probes.append({"path": path.relative_to(ROOT).as_posix(), **result})
    inventory = {"created_at": time.time(), "source_fingerprints": fingerprints,
                 "prompt_files": prompt_files, "tasks": tasks, "provider_probes": probes}
    save(OUT / "prompt-inventory.json", inventory)
    print(json.dumps({"source_files": len(fingerprints), "prompt_files": len(prompt_files), "tasks": tasks}, ensure_ascii=False))
    if args.seal:
        review_path = OUT / "optimization-validation/provider-review.json"
        review = read(review_path)
        if review.get("passed") is not True:
            raise RuntimeError("Actual outputs require a passed quality review before formal examples")
        accepted_paths = set(review.get("accepted_probe_paths", []))
        accepted_probes = [probe for probe in probes if probe["path"] in accepted_paths]
        if not accepted_paths or len(accepted_probes) != len(accepted_paths):
            raise RuntimeError("Quality review must name existing, individually accepted provider probes")
        for stage in ("autorealize", "automl", "report"):
            if not any(probe.get("passed") is True and probe.get("stage") == stage for probe in accepted_probes):
                raise RuntimeError(f"No passed actual-provider probe for {stage}")
        if not any(probe.get("passed") is True and probe.get("slug") == "delivery" and probe.get("stage") == "autorealize" for probe in accepted_probes):
            raise RuntimeError("Delivery missing-input scope requires an actual compiler probe")
        evidence = ["docs/prompt-optimization-review-20260907.md",
                    str((OUT / "prompt-inventory.json").relative_to(ROOT)),
                    str((OUT / "optimization-validation/regression-results.json").relative_to(ROOT)),
                    str(review_path.relative_to(ROOT))] + [probe["path"] for probe in accepted_probes]
        latest_review = OUT / "optimization-validation/review-comparison-20260908.json"
        if latest_review.is_file():
            comparison = read(latest_review)
            if not comparison.get("automated_gates") or not all(comparison["automated_gates"].values()):
                raise RuntimeError("Latest prompt A/B validation has unresolved release gates")
            evidence.extend([latest_review.relative_to(ROOT).as_posix(), "docs/review-prompt-validation-20260908.md"])
        runtime_review = OUT / "optimization-validation/overnight-regression-review.json"
        if runtime_review.is_file():
            runtime = read(runtime_review)
            if runtime.get("passed") is not True:
                raise RuntimeError("Overnight runtime and contract-repair verification failed")
            evidence.append(runtime_review.relative_to(ROOT).as_posix())
            evidence.extend(runtime["evidence"])
        recovery_review = OUT / "optimization-validation/delivery-recovery-regression-20260908.json"
        if recovery_review.is_file():
            if read(recovery_review).get("passed") is not True:
                raise RuntimeError("Delivery recovery regressions failed")
            evidence.append(recovery_review.relative_to(ROOT).as_posix())
        save(OUT / "optimization-review.json", {"status": "passed", "stages_reviewed": ["autorealize", "automl", "report"],
            "reviewed_at": time.time(), "reviewed_files": fingerprints, "verification_evidence": evidence,
            "scope": "Pre-example optimization validated. Model effectiveness and complete per-task constraint coverage still require actual stage reviews."})


if __name__ == "__main__":
    main()

"""Compare unencoded and partitioned real report evidence through the provider."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.config import LLMConfig
from autoreport.events import ReportEventWriter
from autoreport.generator import _prepare_report_context, _validate_llm_config, _chat_json, _read_task_partitions, generate_report


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@contextmanager
def report_validation_slot(stages):
    import psutil
    from utils.resource_limits import WindowsJobMemoryLimiter, host_commit_available_bytes
    minimum = 4 * 1024**3
    commit = host_commit_available_bytes()
    if psutil.virtual_memory().available < minimum or (commit is not None and commit < minimum):
        raise RuntimeError("Insufficient reserve for an isolated report validation")
    path = stages.batch.OUT / "report-validation.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    limiter = WindowsJobMemoryLimiter(2 * 1024**3) if os.name == "nt" else None
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        if limiter:
            limiter.attach(os.getpid())
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, choices=["traffic", "deposition", "chemical"])
    parser.add_argument("--mode", choices=["probe", "read", "semantic", "full"], default="probe")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--context-window-tokens", type=int, default=131072)
    parser.add_argument("--parts", help="Comma-separated one-based partitions; omitted means every partition")
    args = parser.parse_args()
    cfg, bundle, _ = module("measure-report-context").source_bundle(args.slug)
    dest = args.directory or ROOT / "runs/industrial-examples-20260907/optimization-validation" / f"report-partition-{args.slug}-{time.time_ns()}"
    dest.mkdir(parents=True, exist_ok=True)
    cfg.output_dir = str(dest)
    entry = module("validate-industrial-prompts").model_entry()
    cfg.llm = LLMConfig(model=entry["model"], base_url=entry["baseUrl"], api_key=entry["apiKey"],
        reasoning_effort="xhigh", max_tokens=32768, minimum_output_tokens=32768, request_timeout_seconds=900, max_retries=1,
        context_window_tokens=args.context_window_tokens)
    events = ReportEventWriter(dest, print_events_to_console=False)
    if args.mode == "full":
        stages = module("industrial-stage-control")
        task = stages.current_task(args.slug)
        stages.validate_provider(stages.batch.request("/api/settings/global"))
        source_fingerprint = stages.fingerprint(stages.stage_artifacts(task, "automl"))
        review = stages.read_json(stages.LEDGER, {}).get(args.slug, {}).get("automl", {})
        if not review.get("passed") or review.get("artifact_fingerprint") != source_fingerprint:
            raise RuntimeError("Full report validation requires accepted unchanged AutoML artifacts")
        result = {"passed": False, "started_at": time.time(), "slug": args.slug,
                  "source_fingerprint": source_fingerprint, "output_limit": 32768,
                  "configured_context_window_tokens": args.context_window_tokens,
                  "scope": "Isolated production report generation and complete source audit; independent review still required"}
        result_path = dest / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with report_validation_slot(stages):
            old_mode = os.environ.get("AUTOREPORT_PARTITIONED_CONTEXT")
            os.environ["AUTOREPORT_PARTITIONED_CONTEXT"] = "validated"
            os.environ["AUTOREPORT_PROMPT_CACHE_KEY_MODE"] = "enabled"
            print(json.dumps({"directory": str(dest), "mode": "full"}), flush=True)
            try:
                generate_report(cfg, bundle, events)
                trace = json.loads((dest / "report_trace.json").read_text(encoding="utf-8"))
                audit = trace["audit"]
                unchanged = source_fingerprint == stages.fingerprint(stages.stage_artifacts(task, "automl"))
                partitioned = bool(trace.get("task_source_manifest"))
                coverage = audit.get("complete_task_sources_covered") is True if partitioned else audit.get("complete_draft_covered") is True
                result.update(passed=unchanged and coverage
                    and audit.get("status") in {"pass", "revised"}, source_unchanged=unchanged,
                    source_mode="partitioned" if partitioned else "complete_prefix_in_every_request",
                    audit_status=audit.get("status"), usage=trace.get("llm_usage", []))
            except Exception as exc:
                result["error"] = str(exc).replace(entry["apiKey"], "[REDACTED]")
                raise
            finally:
                result["finished_at"] = time.time()
                result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                if old_mode is None:
                    os.environ.pop("AUTOREPORT_PARTITIONED_CONTEXT", None)
                else:
                    os.environ["AUTOREPORT_PARTITIONED_CONTEXT"] = old_mode
        print(json.dumps({"directory": str(dest), "passed": result["passed"]}), flush=True)
        return
    settings = _validate_llm_config(cfg)
    _prepare_report_context(cfg, settings, bundle, events, allow_partitions=True)
    os.environ["AUTOREPORT_PROMPT_CACHE_KEY_MODE"] = "enabled"
    print(json.dumps({"directory": str(dest), "parts": len(settings["task_context_partitions"])}), flush=True)
    if args.mode == "read":
        notes = _read_task_partitions(cfg, settings, events)
        result = {"passed": True, "notes": notes, "usage": settings["usage"], "scope": "Source reading only; not final report validation"}
    else:
        plan = json.loads((dest / "task-context-partitions.json").read_text(encoding="utf-8"))
        rows = []
        for index, records in enumerate(plan["record_groups"]):
            if args.parts and index + 1 not in {int(value) for value in args.parts.split(",")}:
                continue
            # Compare the exact same source records, once without reference
            # encoding and once through the production partition renderer.
            expected, questions = {}, {}
            def samples(value, path):
                if isinstance(value, str) and len(value) >= 60:
                    yield path, value
                elif isinstance(value, dict):
                    for key, item in value.items():
                        yield from samples(item, path + [key])
                elif isinstance(value, list):
                    for key, item in enumerate(value):
                        yield from samples(item, path + [key])
            values = []
            for path, value in samples(records, []):
                for line in value.splitlines():
                    if 40 <= len(line) <= 500 and sum(other.startswith(line[:40]) for other in value.splitlines()) == 1:
                        values.append((path, line))
            for label, (path, line) in zip(("first_source_line", "last_source_line"), (values[0], values[-1])):
                expected[label] = line
                questions[label] = {"instruction": "Return the complete original line starting with the supplied prefix, excluding only its newline. Preserve all remaining characters exactly.",
                                    "line_prefix": line[:40], "path_relative_to_records": path}
            expected["may_use_holdout_for_selection"] = False
            questions["may_use_holdout_for_selection"] = "May holdout scores select candidate algorithms or tune model weights? Return boolean."
            expected["search_budget_seconds"] = 10800
            questions["search_budget_seconds"] = "Return the required actual accumulated global search duration in seconds as an integer."
            if args.mode == "semantic":
                expected = {"may_use_holdout_for_selection": False, "search_budget_seconds": 10800}
                questions = {key: value for key, value in questions.items() if key in expected}
                checks = ([
                    ("horizons", "Return the two forecast horizon lengths in minutes, ascending, as an integer array.", [30, 60]),
                    ("raw_event_at_origin_is_history", "Can a raw event exactly at forecast_origin enter history features? Boolean.", False),
                    ("history_bucket_right_at_origin_allowed", "Is a completed history bucket whose right endpoint equals forecast_origin permitted? Boolean.", True),
                    ("common_origins_required", "Must 30- and 60-minute forecasts share the same evaluated origins? Boolean.", True),
                    ("gantries", "How many gantries are in the independently verified final evaluation? Integer.", 159),
                    ("final_origins", "How many common final evaluation forecast origins are independently verified? Integer.", 277),
                    ("final_rows", "How many predictions are in the independently verified final evaluation? Integer.", 88086),
                    ("cross_branch_fusion_executed", "Does the actual search journal establish an executed cross-branch Fusion operator node? Boolean; internal expert blending alone does not establish it.", False),
                ] if args.slug == "traffic" else [
                    ("target_rows", "How many finite strict-target chemical label rows are retained? Integer.", 1525),
                    ("atomic_groups", "How many atomic prediction-cutoff groups are retained? Integer.", 1519),
                    ("split_rows", "Return the actual [training,development,holdout] row counts as integers.", [914, 307, 304]),
                    ("split_groups", "Return the actual [training,development,holdout] atomic-group counts as integers.", [911, 304, 304]),
                    ("drop_high_status_rows", "May the six high-status chemical target rows be removed from the main scored population? Boolean.", False),
                    ("average_conflicting_duplicates", "May conflicting same-time chemical labels be averaged into one row? Boolean.", False),
                    ("window_minutes", "What is the retrospective device-history window length in minutes? Integer.", 60),
                    ("window_lower_bound_included", "Can a device record exactly 60 minutes before prediction_cutoff enter the window? Boolean.", False),
                    ("window_upper_bound_included", "Can a device record exactly at prediction_cutoff enter the retrospective window? Boolean.", True),
                    ("weather_required", "Does the standalone prediction API require weather or the uncollected external discharge-flow field? Boolean.", False),
                    ("label_table_features_allowed", "May label-table metadata or the target value be used as model features? Boolean.", False),
                    ("production_online_validated", "Does this retrospective experiment verify production online availability or laboratory delay? Boolean.", False),
                    ("selected_node", "Return the exact frozen final selected node ID.", "58002f37a3fd4bf88c950e4375784ecb"),
                    ("final_holdout_mae", "Return independently verified final holdout MAE rounded to six decimal places.", 0.082823),
                    ("median_holdout_mae", "Return independently verified median-baseline holdout MAE rounded to six decimal places.", 0.080395),
                    ("selected_beats_holdout_baseline", "Did the selected model beat the median baseline on final holdout MAE? Boolean.", False),
                    ("high_holdout_performance_available", "Does the holdout contain high-status labels sufficient to compute high-status MAE? Boolean.", False),
                    ("cross_branch_fusion_executed", "Did an actual cross-branch fusion search operation produce the selected node? Boolean.", True),
                    ("final_training_rows", "How many rows fitted the actual final exported model? Integer; distinguish default training reproduction.", 1221),
                    ("default_training_verified_rows", "How many training rows were used by the independently verified default public train entry? Integer.", 914),
                    ("actual_training_device", "Return actual final training device exactly as reported in the independent model metadata.", "CPU_fallback"),
                    ("gpu_failure_due_to_oom", "Was the frozen model's GPU attempt rejected because of out-of-memory rather than pinned_memory_bytes parameter parsing? Boolean.", False),
                    ("moved_api_verified", "Did an independent fresh-directory API and model load pass? Boolean.", True),
                    ("predict_fit_allowed", "May standalone predict fit the model or preprocessing? Boolean.", False),
                ] if args.slug == "chemical" else [
                    ("curve_count", "How many complete source curves are in the accepted population? Integer.", 192),
                    ("final_rows", "How many final holdout rows have independently recomputed scores? Integer.", 79967),
                    ("split_by_time_within_curve", "Is the accepted evaluation split by time within each curve, instead of unseen whole-curve groups? Boolean.", True),
                    ("experimental_generalization_verified", "Does evaluation of the supplied simulation establish real experimental generalization? Boolean.", False),
                    ("cross_branch_fusion_executed", "Does the actual search journal establish an executed cross-branch Fusion operator node? Boolean; an internal tail-expert blend alone does not establish it.", False),
                ])
                for key, question, value in checks:
                    expected[key], questions[key] = value, question
            instruction = "\n# Latest stage instruction\nResolve all lossless encodings. This is a literal and semantic reading check. Return one JSON object answering every key exactly.\n" + json.dumps(questions, ensure_ascii=False)
            for variant, context in (("unencoded", "# Original task source partition\n" + json.dumps({"source_manifest": plan["manifest"], "records": records}, ensure_ascii=False, separators=(",", ":"))),
                                     ("partitioned", plan["parts"][index])):
                path = dest / f"{args.mode}-{index + 1}-{variant}.json"
                identity = hashlib.sha256((settings["task_context_prefix"] + context + instruction + cfg.llm.model + str(cfg.llm.reasoning_effort)).encode("utf-8")).hexdigest()
                cached = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                if cached.get("input_sha256") == identity:
                    row = cached
                else:
                    started = time.monotonic()
                    answer = _chat_json(cfg, settings, context + instruction, events, component="autoreport.partition_probe")
                    row = {"input_sha256": identity, "part": index + 1, "variant": variant, "expected": expected, "answer": answer,
                        "passed": answer == expected, "seconds": time.monotonic() - started, "usage": settings["usage"][-1:]}
                    path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
                rows.append(row)
                print(json.dumps({"part": index + 1, "variant": variant, "passed": row["passed"]}), flush=True)
        result = {"passed": all(row["passed"] for row in rows), "rows": rows, "output_limit": 32768,
                  "scope": "Real provider same-source encoding A/B and exact whole-source partition coverage; final report quality still requires raw-source audit"}
    (dest / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(dest), "passed": result["passed"]}), flush=True)


if __name__ == "__main__":
    main()

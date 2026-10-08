"""Check complete real report input round trips and provider constraint reading."""
from __future__ import annotations

import importlib.util
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.collector import collect_evidence
from autoreport.config import AutoReportConfig, EvidencePath
from autoreport.events import ReportEventWriter
from autoreport.context import estimate_tokens
from autoreport.prompt_context import encode_task_context, mandatory_task_context
from autoreport.generator import _base_system_prompt, _chat_json, _context_input_budget, _validate_llm_config, _build_frozen_report_context, _build_analysis_dossier


def restore(encoded):
    root = json.loads(encoded.split("\n", 1)[1])
    def resolve(value):
        if isinstance(value, dict) and set(value) == {"$prompt_ref"}:
            target = root
            for part in value["$prompt_ref"].split("/")[1:]:
                part = part.replace("~1", "/").replace("~0", "~")
                target = target[int(part)] if isinstance(target, list) else target[part]
            return resolve(target)
        if isinstance(value, dict) and set(value) == {"$prompt_text"}:
            return "".join(resolve(part) for part in value["$prompt_text"])
        if isinstance(value, dict):
            return {key: resolve(part) for key, part in value.items()}
        if isinstance(value, list):
            return [resolve(part) for part in value]
        return value
    return resolve(root["data"]) if "_prompt_encoding" in root else root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=("literal", "constraint_facts"), default="literal")
    parser.add_argument("--include-search", action="store_true")
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("provider_probe", ROOT / "scripts/validate-industrial-prompts.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    dest = OUT / "optimization-validation" / f"report-context-steel-{time.time_ns()}"
    dest.mkdir(parents=True)
    model = helper.model_entry()
    task = OUT / "tasks/工业实例-钢厂用电预测/autorealize"
    evidence_paths = [EvidencePath(label="actual completed task definition", path=str(task), kind="autorealize")]
    if args.include_search:
        live = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["steel"]
        for label, path in (("automl_logs", live["auto_ml_log_dir"]),
                            ("automl_workspace", live["auto_ml_workspace_dir"]),
                            ("evaluation_provenance", str(task.parent / "evaluation_provenance.json"))):
            if Path(path).exists():
                evidence_paths.append(EvidencePath(label=label, path=path, kind="automl"))
    cfg = AutoReportConfig(task_name="钢厂完整报告输入验证", output_dir=str(dest), language="zh",
        evidence_paths=evidence_paths,
        comparison={"top_solution_limit": 6, "successful_node_limit": 6},
        generation={"max_prompt_chars": 524288},
        llm={"model": model["model"], "base_url": model["baseUrl"], "api_key": model["apiKey"],
             "reasoning_effort": "xhigh", "max_tokens": 32768, "minimum_output_tokens": 32768,
             "request_timeout_seconds": 900, "max_retries": 1})
    events = ReportEventWriter(dest, run_id="report-context", print_events_to_console=False)
    bundle = collect_evidence(cfg, events)
    context = mandatory_task_context(bundle)
    encoded = encode_task_context(context)
    if restore(encoded) != context:
        raise RuntimeError("Lossless report context roundtrip failed")
    frozen, keys = _build_frozen_report_context(cfg, bundle) if args.include_search else (encoded, ())
    if args.include_search:
        result_part = "# Complete selected result facts" + frozen.split("# Complete selected result facts", 1)[1]
        facts = _build_analysis_dossier(cfg, bundle)
        if restore(result_part) != {key: facts[key] for key in keys}:
            raise RuntimeError("Lossless selected result facts roundtrip failed")
    if args.measure_only:
        settings = _validate_llm_config(cfg)
        system_tokens = estimate_tokens(_base_system_prompt(cfg))
        remaining = _context_input_budget(settings) - estimate_tokens(frozen) - system_tokens
        measurement = {"stage": "report_context_measurement", "passed": remaining > 0,
                       "exact_roundtrip": True, "characters": len(frozen), "task_rules_characters": len(encoded),
                       "estimated_mandatory_and_system_tokens": estimate_tokens(frozen) + system_tokens,
                       "estimated_evidence_room": remaining, "include_search": args.include_search,
                       "frozen_result_keys": list(keys),
                       "scope": "Local complete-source measurement only; no provider call or final report validation."}
        helper.save(dest / "logical-context.json", context)
        (dest / "complete-prefix.txt").write_text(frozen, encoding="utf-8")
        helper.save(dest / "result.json", measurement)
        print(json.dumps({"directory": str(dest), **measurement}, ensure_ascii=False))
        return
    expected = {}
    questions = []
    for index, document in enumerate(context["documents"]):
        name = Path(document["sources"][0]).name
        if name == "evaluation_contract_report.json":
            contract = document["content"]["final"]
            for field in ("authority_status", "primary_metric", "metric_direction", "metric_formula", "validation_protocol", "leakage_guards", "invalid_solution_rules"):
                expected[field] = contract[field]
                questions.append({"key": field, "read_json_pointer": f"/documents/{index}/content/final/{field}"})
        elif name in {"description.md", "automl_context.md"}:
            lines = document["content"].splitlines()
            candidates = [line for line in lines if 96 <= len(line) <= 450 and sum(other.startswith(line[:40]) for other in lines) == 1]
            line = candidates[-1]
            expected[name] = line
            questions.append({"key": name, "read_markdown_string_at": f"/documents/{index}/content", "return_complete_line_starting_with": line[:40]})
    settings = _validate_llm_config(cfg)
    settings["task_context_prefix"] = frozen
    system_tokens = estimate_tokens(_base_system_prompt(cfg))
    check = {"passed": True, "exact_roundtrip": True, "characters": len(frozen),
             "estimated_mandatory_and_system_tokens": estimate_tokens(frozen) + system_tokens,
             "estimated_evidence_room": _context_input_budget(settings) - estimate_tokens(frozen) - system_tokens,
             "expected": expected, "questions": questions}
    helper.save(dest / "context-check.json", check)
    os.environ["AUTOREPORT_PROMPT_CACHE_KEY_MODE"] = "enabled"
    instruction = (
        "This is a lossless-input reading check, not a report or model evaluation. "
        "Resolve all reference/text encodings. Read the original logical data object. "
        "Return one JSON object mapping each requested key to its exact original value. "
        "For Markdown return the complete matching line without its newline; do not paraphrase or trim its other characters. "
        "Preserve strings, arrays, punctuation and every array element. No analysis or additional keys.\n"
        + json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
    )
    if args.check == "constraint_facts":
        facts = [
            ("row_count", "What is the verified full source row count? Return an integer.", 35040),
            ("raw_adjacent_inversions", "How many adjacent timestamp inversions exist in raw order? Return an integer.", 365),
            ("grid_minutes", "What is the verified sorted timestamp interval in minutes?", 15),
            ("fit_positions", "Return fit's zero-based start-inclusive/end-exclusive positions as [start,end].", [0, 21024]),
            ("development_positions", "Return development_search's zero-based start-inclusive/end-exclusive positions.", [21024, 28032]),
            ("holdout_positions", "Return holdout's zero-based start-inclusive/end-exclusive positions.", [28032, 35040]),
            ("metric", "Return the main metric identifier, without units or formatting.", "MAE"),
            ("direction", "Return the main metric direction: minimize or maximize.", "minimize"),
            ("full_evaluation_counts", "Return the required number of targets in [development,holdout].", [7008, 7008]),
            ("known_history_across_boundary", "May actually observed lookback history cross split boundaries without target purge? Boolean.", True),
            ("purge_future_labels", "Must training targets whose horizon crosses the allowed training endpoint be purged? Boolean.", True),
            ("predict_before_target_observed", "Must each rolling prediction precede observing its target? Boolean.", True),
            ("append_actual_after_scoring", "Must rolling history append the actual Usage_kWh only after prediction/scoring? Boolean.", True),
            ("fit_during_development_scoring", "May a base model refit while development labels are being scored? Boolean.", False),
            ("same_period_power_features", "May same-period power/reactive-energy proxies unavailable at forecast time be used? Boolean.", False),
            ("seasonal_lag", "What is the previous-day baseline lag in 15-minute positions? Integer.", 96),
            ("drop_history_short_targets", "May a candidate drop evaluation targets because its own lookback history is insufficient? Boolean.", False),
            ("default_fallback", "Name the evaluator-level default short-history fallback as a lowercase baseline identifier.", "persistence"),
            ("reject_without_previous_actual", "If even the prior actual Usage_kWh is absent, must the entire evaluation reject? Boolean.", True),
            ("fusion_oof", "Must learned fusion/stacking weights use training-only held-out or out-of-fold predictions? Boolean.", True),
            ("holdout_selection_allowed", "May holdout results select configurations or fusion weights? Boolean.", False),
            ("final_refit_positions", "After global recipe lock, which zero-based history range may train the model used to score holdout? [start,end].", [0, 28032]),
            ("holdout_evaluations", "How many evaluations of the separate holdout are permitted after configuration lock? Integer.", 1),
            ("full_history_refit_after_persisted_holdout", "Must actual holdout results be persisted before full-history refitting? Boolean.", True),
            ("unrun_score_zero_allowed", "May an unexecuted or failed score be filled with zero? Boolean.", False),
            ("daily_incomplete_changes_main_targets", "May incomplete daily aggregation windows alter the primary metric's target population? Boolean.", False),
            ("worker_limit", "Return the maximum simultaneous search worker count.", 2),
            ("fit_thread_limit", "Return the total thread cap across generated fitting processes.", 4),
            ("task_memory_gib", "Return the maximum task process-tree memory in GiB.", 8),
            ("node_seconds", "Return the execution timeout per search node in seconds.", 900),
            ("search_seconds", "Return the required actual cumulative AutoML search seconds, excluding interruption/repair/cleanup.", 10800),
            ("gpu_allowed", "May this task use a GPU? Boolean.", False),
            ("infer_new_history", "Must inference accept NEW history and predict a previously unseen next timestamp? Boolean.", True),
            ("inference_training_allowed", "May standalone inference train, search or download external data? Boolean.", False),
            ("strict_invalid_inputs", "Must malformed dates, duplicate times, grid gaps or invalid labels cause explicit rejection rather than silent deletion? Boolean.", True),
            ("keep_valid_scores_after_timeout", "Must already accepted, valid candidates and their actual scores survive search timeout unchanged? Boolean.", True),
        ]
        if args.include_search:
            facts.extend([
                ("selected_node", "Return the actual final selected node ID.", "d37ff52bb9ff4782bec6aefcf8ede5c0"),
                ("development_mae", "Return the selected model development MAE rounded to six decimal places.", 4.136216),
                ("final_holdout_mae", "Return the independently verified final selected model holdout MAE rounded to six decimal places.", 3.946800),
                ("accepted_count", "How many search candidates were accepted across the entire completed journal, not just the displayed selection?", 9),
                ("rejected_count", "How many search candidates failed across the entire completed journal?", 3),
                ("ensemble_weights", "Return the frozen three member weights in member order.", [0.65, 0.20, 0.15]),
                ("weight_selection_rows", "How many training-only OOF rows selected the ensemble weights?", 7603),
                ("weight_grid_size", "How many simplex weight configurations were independently checked?", 231),
                ("actual_fusion_operator", "Did any actual cross-branch Fusion operator node run, according to independent verification? Boolean; distinguish an improve-node ensemble.", False),
                ("daily_error_better", "Does the selected model improve daily aggregate MAE over persistence? Boolean.", False),
                ("newly_unseen_holdout", "Can this holdout truthfully be described as newly unseen given the prior rejected trial? Boolean.", False),
                ("final_training_rows", "How many history rows trained the final exported model after holdout results were persisted?", 35040),
                ("moved_inference_verified", "Did independent verification actually move the package and run inference in a fresh process without fitting? Boolean.", True),
                ("default_retrain_verified", "Was the actual default train entry independently retrained and checked against development predictions? Boolean.", True),
                ("final_refit_feature_rows", "Read final_evaluation artifact_metadata for artifacts/full_history_refit. How many feature_rows_retained were recorded?", 33024),
                ("final_refit_oof_rows", "In the same full_history_refit training_stats, what is ensemble_oof_rows? This is diagnostic OOF, not weight-selection OOF.", 13209),
                ("locked_refit_feature_rows", "Read artifact_metadata for artifacts/holdout_locked_fit. What is feature_rows_retained?", 26016),
                ("locked_refit_oof_rows", "In holdout_locked_fit training_stats, what is ensemble_oof_rows?", 10406),
                ("final_sidecar_files_exist", "Does the actual artifacts/full_history_refit directory inventory include BOTH selected_recipe.json and training_stats.json? Boolean.", True),
            ])
        expected = {key: value for key, question, value in facts}
        questions = {key: question for key, question, value in facts}
        instruction = ("Read the complete original task rules, resolving all lossless references and text fragments. "
                       "This is a constraint-understanding check. Return exactly one JSON object with the requested keys, "
                       "each mapped to the specified type/value form. Answer from the source, including exceptions; "
                       "do not echo these questions or add prose.\n" + json.dumps(questions, ensure_ascii=False))
        check.update(expected=expected, questions=questions, check_kind=args.check)
        helper.save(dest / "context-check.json", check)
    started = time.monotonic()
    value = _chat_json(cfg, settings, instruction, events, component="autoreport.context_reading_probe")
    helper.save(dest / "provider-response.json", value)
    mismatches = [key for key in expected if expected[key] != value.get(key)]
    result = {"stage": "report_context", "slug": "steel", "passed": not mismatches,
              "check_kind": args.check, "verified_fields": len(expected) - len(mismatches), "total_fields": len(expected),
              "scope": "Actual complete task-context exact roundtrip and production-provider reading check; literal and constraint-facts probes have distinct acceptance criteria, and neither proves a completed report or model effectiveness.",
              "seconds": time.monotonic() - started, "mismatched_keys": mismatches,
              "characters": check["characters"], "estimated_mandatory_and_system_tokens": check["estimated_mandatory_and_system_tokens"],
              "estimated_evidence_room": check["estimated_evidence_room"], "usage": settings["usage"]}
    helper.save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

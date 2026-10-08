"""Exercise production prompt builders against the authorized provider before examples."""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
for name in ("AutoRealize", "AutoReport", "AlgoEvolve"):
    sys.path.insert(0, str(ROOT / "core" / name))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def model_entry():
    settings = yaml.safe_load((OUT / "settings.yaml").read_text(encoding="utf-8-sig"))
    return next(item for item in settings["llm"]["modelLibrary"] if item["model"] == "gpt-5.6-luna")


def evaluation_probe(slug, dest, *, repair_from=None, feedback=None):
    from autorealize.config import AutoRealizeConfig
    from autorealize.llm.client import LLMClient
    from autorealize.modules.task_definition import TaskDefinitionModule
    from autorealize.modules.types import RuntimeServices
    from autorealize.prompts.manager import PromptManager
    from autorealize.trajectory import TrajectoryLogger
    from autorealize.report_writer import evaluation_contract_defects
    from autorealize.models import EvaluationContractReview

    entry = model_entry()
    cfg = AutoRealizeConfig()
    cfg.llm.model_name = entry["model"]
    cfg.llm.api_key = entry["apiKey"]
    cfg.llm.base_url = entry["baseUrl"]
    cfg.llm.reasoning_effort = "xhigh"
    cfg.llm.max_tokens = 32768
    cfg.llm.enable_cache = False
    cfg.llm.request_timeout_seconds = 900
    cfg.llm.max_retries = 1
    cfg.prompt.prompt_token_budget = 24000
    cfg.prompt.evaluation_contract_max_rounds = 1
    os.environ["AUTOREALIZE_PROMPT_CACHE_KEY_MODE"] = "enabled"
    client = LLMClient(cfg, dest)
    services = RuntimeServices(llm_client=client, prompt_mgr=PromptManager(cfg),
                               registry=SimpleNamespace(), trajectory=TrajectoryLogger(dest))
    module = TaskDefinitionModule(cfg, services, dest, dest)
    protocol = (OUT / f"{slug}-protocol.md").read_text(encoding="utf-8")
    facts = json.loads((OUT / "inspection/task-defining-facts.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    contract = module._review_evaluation_contract(
        original_text=protocol, downstream_context={},
        evaluation_evidence_pack={"source": "independent full-table inspection", "facts": facts.get(slug, {})},
        previous_contract=EvaluationContractReview.model_validate(json.loads(repair_from.read_text(encoding="utf-8-sig"))) if repair_from else None,
        reflection_feedback=feedback)
    defects = evaluation_contract_defects(contract)
    save(dest / "contract.json", contract.model_dump())
    result = {"stage": "autorealize", "slug": slug, "seconds": time.monotonic() - started,
              "passed": contract.passed and contract.executable and not defects,
              "deterministic_defects": defects, "metric": contract.primary_metric,
              "direction": contract.metric_direction, "provider_usage": str(dest / "llm_usage_summary.json"),
              "scope": "production evaluation compiler probe; not a completed example"}
    save(dest / "result.json", result)
    return result


def automl_probe(dest):
    from agents.prompt_cache import task_section
    from llm.openai import _apply_deepseek_request_options, _build_messages
    from openai import OpenAI

    entry = model_entry()
    protocol = (OUT / "delivery-protocol.md").read_text(encoding="utf-8")
    client = OpenAI(base_url=entry["baseUrl"], api_key=entry["apiKey"], timeout=600, max_retries=0)
    rows = []
    os.environ["ALGOEVOLVE_PROMPT_CACHE_KEY_MODE"] = "enabled"
    stage = SimpleNamespace(reasoning_effort="xhigh", base_url=entry["baseUrl"])
    for index in range(2):
        user = task_section(protocol) + (
            '\n# Implementation\nThis is a constraint-routing probe before any search. Return JSON with '
            'capacity_dates_available (boolean), may_assume_capacity_dates (boolean), '
            'may_claim_real_dispatch_performance (boolean), delivery_stop_count_cap (integer or null), '
            'required_search_metric (string), forbidden_sharing_owners (array of exact owner codes). '
            f'Probe sequence: {index}. No implementation or fabricated results.')
        instructions = ("Generate a constraint interpretation.", "Review the task constraints.")[index]
        messages = _build_messages(instructions + " Read every task rule. Return the requested JSON only.", user)
        params = {"model": entry["model"], "messages": messages, "max_completion_tokens": 8192,
                  "response_format": {"type": "json_object"}}
        _apply_deepseek_request_options(params, stage, entry["model"], None)
        if rows and rows[0]["prompt_cache_key"] != params["prompt_cache_key"]:
            raise AssertionError("Production cache key changed with stage instructions")
        started = time.monotonic()
        response = client.chat.completions.create(**params)
        value = json.loads(response.choices[0].message.content)
        passed = (value.get("capacity_dates_available") is False
                  and value.get("may_assume_capacity_dates") is False
                  and value.get("may_claim_real_dispatch_performance") is False
                  and value.get("delivery_stop_count_cap", "missing") is None
                  and value.get("required_search_metric") == "contract_check_pass_fraction"
                  and all(code in json.dumps(value.get("forbidden_sharing_owners"))
                          for code in ("FYP01", "MH101", "NH001", "SMG01", "YPF01")))
        rows.append({"passed": passed, "response": value, "seconds": time.monotonic() - started,
                     "prompt_cache_key": params["prompt_cache_key"], "messages": messages,
                     "usage": response.usage.model_dump() if response.usage else {}})
        save(dest / "calls.json", rows)
    return {"stage": "automl", "passed": all(row["passed"] for row in rows),
            "scope": "production message-builder compatibility and constraint-routing probe; not search quality"}


def report_probe(dest):
    from autoreport.collector import collect_evidence
    from autoreport.config import AutoReportConfig, EvidencePath
    from autoreport.events import ReportEventWriter
    from autoreport.generator import generate_report
    from autoreport.prompt_context import encode_task_context, mandatory_task_context

    entry = model_entry()
    evidence = dest / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    protocol = (OUT / "delivery-protocol.md").read_text(encoding="utf-8")
    (evidence / "original_requirements.txt").write_text(protocol, encoding="utf-8")
    (evidence / "description.md").write_text(
        "# Prompt validation fixture\nNo AutoML has run for this fixture. There are no measured solver results.\n"
        "Source facts: 51 capacity rows have blank dates. The user authorizes model and data-gap report only.\n"
        "This validates report behavior on absent model evidence, not an actual example deliverable.\n", encoding="utf-8")
    os.environ["AUTOREPORT_PROMPT_CACHE_KEY_MODE"] = "enabled"
    cfg = AutoReportConfig(task_name="配送缺口报告提示词验证", output_dir=str(dest / "report"), language="zh",
        evidence_paths=[EvidencePath(label="validation fixture", path=str(evidence))],
        generation={"max_prompt_chars": 110000},
        analysis={"max_retrieval_rounds": 1, "enable_report_audit": True},
        llm={"model": entry["model"], "base_url": entry["baseUrl"], "api_key": entry["apiKey"],
             "reasoning_effort": "xhigh", "request_timeout_seconds": 900, "max_retries": 1})
    events = ReportEventWriter(dest / "events", run_id="optimization-probe", print_events_to_console=False)
    bundle = collect_evidence(cfg, events)
    context = encode_task_context(mandatory_task_context(bundle))
    save(dest / "context-size.json", {"chars": len(context), "files": len(bundle.items)})
    report = generate_report(cfg, bundle, events)
    return {"stage": "report", "passed": report["summary"]["audit_status"] in {"pass", "revised"},
            "report": str(dest / "report/report.md"), "audit_status": report["summary"]["audit_status"],
            "scope": "production report pipeline on declared absent-results fixture; human review required"}


def report_transport_probe(dest):
    from autoreport.config import AutoReportConfig
    from autoreport.events import ReportEventWriter
    from autoreport.generator import _chat_json, _validate_llm_config
    entry = model_entry()
    cfg = AutoReportConfig(task_name="Streaming verification", output_dir=str(dest),
        llm={"model": entry["model"], "base_url": entry["baseUrl"], "api_key": entry["apiKey"],
             "reasoning_effort": "xhigh", "request_timeout_seconds": 600, "max_retries": 1})
    settings = _validate_llm_config(cfg)
    settings["task_context_prefix"] = (OUT / "delivery-protocol.md").read_text(encoding="utf-8")
    os.environ["AUTOREPORT_PROMPT_CACHE_KEY_MODE"] = "enabled"
    events = ReportEventWriter(dest, run_id="transport-probe", print_events_to_console=False)
    response = _chat_json(cfg, settings,
        'Return only {"model_delivery_requires_runnable_code":true,"may_assume_capacity_dates":false,"real_dispatch_measured":false} after checking the complete task rules.',
        events, component="autoreport.transport_validation")
    expected = {"model_delivery_requires_runnable_code": True, "may_assume_capacity_dates": False, "real_dispatch_measured": False}
    save(dest / "calls.json", {"response": response, "usage": settings["usage"]})
    return {"stage": "report_transport", "passed": response == expected, "scope": "production streaming adapter and complete rule prefix"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("autorealize", "automl", "report", "report_transport"))
    parser.add_argument("--slug", choices=("steel", "delivery"), default="steel")
    parser.add_argument("--repair-from", type=Path)
    parser.add_argument("--feedback", action="append")
    args = parser.parse_args()
    dest = OUT / "optimization-validation" / f"{args.stage}-{args.slug}-{time.time_ns()}"
    dest.mkdir(parents=True)
    logging.basicConfig(filename=dest / "validation.log", level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s", encoding="utf-8")
    try:
        result = evaluation_probe(args.slug, dest, repair_from=args.repair_from, feedback=args.feedback) if args.stage == "autorealize" else (
            automl_probe(dest) if args.stage == "automl" else
            report_transport_probe(dest) if args.stage == "report_transport" else report_probe(dest))
        save(dest / "result.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not result["passed"]:
            raise RuntimeError("Production prompt validation requires review")
    except Exception as exc:
        message = str(exc).replace(model_entry()["apiKey"], "[REDACTED]")
        save(dest / "failure.json", {"error": message})
        print(json.dumps({"error": message, "directory": str(dest)}, ensure_ascii=False), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

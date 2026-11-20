"""Run a real QDI stage against an isolated source snapshot and frozen case inputs.

Requires DEEPSEEK_API_KEY in the process environment. Does not persist config
objects or credentials. Each invocation is one independently budgeted run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--max-input", type=int, default=1500000)
    parser.add_argument("--max-output", type=int, default=100000)
    args = parser.parse_args()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY missing; no requests sent")
    if args.output.exists():
        raise SystemExit("Output must be a new directory; prior experiments are immutable")
    args.output.mkdir(parents=True)
    sys.path.insert(0, str(args.source_root.resolve()))
    from autorealize.config import AutoRealizeConfig
    from autorealize.investigation import _run_question_investigator_inner
    from autorealize.llm import client as client_module
    from autorealize.llm.client import LLMClient
    from autorealize.models import FileSummary
    from autorealize.prompt_cache import estimate_text_tokens
    from autorealize.prompts.manager import PromptManager

    cfg = AutoRealizeConfig()
    cfg.llm.api_key = os.environ["DEEPSEEK_API_KEY"]
    cfg.llm.base_url = "https://api.deepseek.com"
    cfg.llm.model_name = "deepseek-flash"
    cfg.llm.temperature = 0
    cfg.llm.enable_cache = False
    cfg.llm.max_retries = 2
    cfg.llm.request_timeout_seconds = 120
    cfg.llm.max_concurrent_requests = 1
    cfg.llm.context_window_tokens = 1000000
    # Both variants retain the production structured non-thinking mode/output cap.
    cfg.investigation.max_questions = 5
    cfg.investigation.max_rounds_per_run = 6
    cfg.investigation.custom_python_timeout_seconds = 60
    cfg.investigation.custom_python_max_retries = 2
    client_module.NETWORK_RETRY_MAX_ATTEMPTS = 1
    cognition = json.loads((args.case / "initial_cognition.json").read_text(encoding="utf-8"))
    knowledge = deepcopy(cognition["knowledge_base"])
    knowledge.pop("question_investigation", None)
    started = time.monotonic()
    records = []
    counts = {"requests": 0, "input": 0, "output": 0, "cache_hit": 0, "cache_miss": 0}
    def write_json(name, obj):
        (args.output / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = {"label": args.label, "model": cfg.llm.model_name, "base_url": cfg.llm.base_url,
        "started_utc": datetime.now(timezone.utc).isoformat(), "data_root": str((args.case / 'input').resolve()),
        "source_root": str(args.source_root.resolve()), "stage": "QDI only; saved initial cognition reused",
        "local_llm_cache": False, "structured_disable_thinking": cfg.llm.structured_disable_thinking,
        "max_tokens_per_request": cfg.llm.structured_max_tokens, "max_questions": 5, "max_actions_per_question": 6,
        "custom_python_timeout_seconds": 60, "script_repair_attempts": 2, "structured_attempts": 2,
        "network_attempts": 1, "temperature": 0,
        "budgets": {"requests": args.max_calls, "input_tokens": args.max_input, "output_tokens": args.max_output},
        "cognition_sha256": hashlib.sha256((args.case / 'initial_cognition.json').read_bytes()).hexdigest()}
    write_json("metadata.json", metadata)
    client = LLMClient(cfg, args.output)
    original_call = client._chat_completion_with_network_retry
    def metered(**kwargs):
        request = kwargs["create_kwargs"]
        estimate = estimate_text_tokens(json.dumps(request.get("messages", []), ensure_ascii=False))
        if (counts["requests"] >= args.max_calls or counts["input"] + estimate > args.max_input
                or counts["output"] >= args.max_output or time.monotonic() - started > 1500):
            raise RuntimeError("Online QDI experiment budget exhausted")
        request["max_tokens"] = min(request.get("max_tokens", 32768), args.max_output - counts["output"])
        counts["requests"] += 1
        record = {"sequence": counts["requests"], "prompt": kwargs.get("prompt_name"),
                  "started_utc": datetime.now(timezone.utc).isoformat()}
        print(json.dumps({"event": "request_started", "label": args.label, **record}, ensure_ascii=False), flush=True)
        call_started = time.monotonic()
        try:
            response = original_call(**kwargs)
            usage = response.usage.model_dump() if hasattr(response.usage, "model_dump") else response.usage
            usage = usage or {}
            record.update(usage=usage, response_model=getattr(response, "model", None),
                          finish_reason=response.choices[0].finish_reason)
            counts["input"] += int(usage.get("prompt_tokens", 0) or 0)
            counts["output"] += int(usage.get("completion_tokens", 0) or 0)
            counts["cache_hit"] += int(usage.get("prompt_cache_hit_tokens", 0) or 0)
            counts["cache_miss"] += int(usage.get("prompt_cache_miss_tokens", 0) or 0)
            return response
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            record["status_code"] = getattr(exc, "status_code", None)
            raise
        finally:
            record["seconds"] = round(time.monotonic() - call_started, 3)
            records.append(record)
            write_json("provider_calls.json", records)
            print(json.dumps({"event": "request_finished", "label": args.label, **record}, ensure_ascii=False), flush=True)
    client._chat_completion_with_network_retry = metered
    status = "failed"
    try:
        report = _run_question_investigator_inner(cfg=cfg, llm_client=client, prompt_mgr=PromptManager(cfg),
            data_root=(args.case / "input").resolve(), report_dir=args.output / "report",
            task_hint=cognition["task_hint"], file_summaries=[FileSummary.model_validate(x) for x in cognition["files"]],
            relation_hints=cognition["relations"], constraint_memory=cognition["constraint_memory"],
            authoritative_memory=cognition["authoritative_memory"], knowledge_base=knowledge)
        write_json("qdi_report.json", report)
        status = "completed"
    except Exception as exc:
        write_json("failure.json", {"error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)})
    finally:
        client.client.close()
        write_json("run_summary.json", {"status": status, "counts": counts,
            "seconds": round(time.monotonic() - started, 2), "finished_utc": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"label": args.label, "status": status, "counts": counts}, ensure_ascii=False), flush=True)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

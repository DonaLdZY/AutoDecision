"""Replay one saved interrupted response, then request its tail through the real backend."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import re
import sys
import time

import yaml
from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from llm import openai as backend
from utils.response import extract_code


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--reuse-tail-from", type=Path)
    args = parser.parse_args()
    stages = module("continuation_stages", "industrial-stage-control.py")
    recovery = module("continuation_recovery", "recover-industrial-generation.py")
    task = stages.current_task(args.slug)
    logs = Path(task["auto_ml_log_dir"])
    dest = stages.batch.OUT / "optimization-validation" / f"{args.slug}-continuation-{time.time_ns()}"
    dest.mkdir(parents=True)
    logging.basicConfig(filename=dest / "validation.log", level=logging.INFO, encoding="utf-8")
    raw_log = (logs / "AlgoEvolve.verbose.log").read_text(encoding="utf-8")
    responses = re.findall(r"INFO: generate response: (.*?)(?=\n\[\d{4}-\d{2}-\d{2} )", raw_log, re.S)
    usage = [json.loads(line) for line in (logs / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    usage = [row for row in usage if row.get("prompt_name") == "generate:agents.coder.base_coder.plan_and_code_query"]
    index, saved = next((i, response) for i, response in enumerate(responses)
                        if backend._normalize_stream_completion(response, "stop")[1] == "provider_interrupted")
    partial, _ = backend._normalize_stream_completion(saved, "stop")
    record = {"provider_prompt_signatures": [{"role": part["role"], "sha256_16": part["sha256_16"]}
                                              for part in usage[index]["prompt_parts"]]}
    from config import prep_cfg
    from engine.search_node import Journal
    config_path = logs / "config.yaml"
    if not config_path.is_file():
        config_path = ROOT / "frontend/backend/.state" / f"{task['id']}.algoevolve.config.yaml"
    cfg = OmegaConf.create(yaml.unsafe_load(config_path.read_text(encoding="utf-8")), flags={"allow_objects": True})
    cfg.log_dir, cfg.workspace_dir = str(logs), task["auto_ml_workspace_dir"]
    cfg.data_dir = str(cfg.data_dir)
    cfg.runtime.resume_run = True
    cfg = prep_cfg(cfg)
    recovery.reconstruct_original_prompt(logs, record, cfg=cfg, journal=Journal())
    messages = record["source_prompt_messages"]
    reused_tail = None
    if args.reuse_tail_from:
        previous = stages.read_json(args.reuse_tail_from / "result.json")
        prior_request = stages.read_json(args.reuse_tail_from / "source-request.json")
        if (previous.get("error") != "Continuation changed saved output prefix"
                or prior_request != record or len(previous.get("calls", [])) != 2
                or previous["calls"][-1].get("source") != "real_api"):
            raise RuntimeError("Expected a matching saved real API continuation from the prefix-cleanup failure")
        reused_tail = (args.reuse_tail_from / "continued-response.txt").read_text(encoding="utf-8")
    stages.batch.save(dest / "source-request.json", record)
    (dest / "source-response.txt").write_text(saved, encoding="utf-8")
    settings = yaml.safe_load((stages.batch.OUT / "settings.yaml").read_text(encoding="utf-8-sig"))
    stages.validate_provider(settings)
    model = next(item for item in settings["llm"]["modelLibrary"] if item["id"] == settings["llm"]["roleModels"]["autoMlCode"])
    cfg.log_dir = dest
    stage = cfg.agent.code
    stage.api_key, stage.base_url, stage.model = model["apiKey"], model["baseUrl"], model["model"]
    stage.reasoning_effort = "xhigh"
    stage.max_tokens = stage.minimum_output_tokens = 32768
    original_collect = backend._collect_stream_response
    original_log_usage = backend.log_llm_usage
    calls = []

    def collect(client, params, **kwargs):
        if not calls:
            if params["messages"] != messages:
                raise RuntimeError("Production initial prompt differs from saved provider fingerprints")
            calls.append({"source": "saved_provider_response"})
            return saved, "stop", {}, 0.0
        if params["messages"][:len(messages)] != messages:
            raise RuntimeError("Continuation lost original task context")
        if params.get("max_tokens") != 32768 or params.get("reasoning_effort") != "xhigh":
            raise RuntimeError("Continuation changed confirmed provider configuration")
        calls.append({"source": "saved_real_api_tail" if reused_tail is not None else "real_api", "max_tokens": params["max_tokens"], "reasoning_effort": params["reasoning_effort"]})
        stages.batch.save(dest / f"continuation-request-{len(calls)-1}.json", params["messages"])
        collected = (reused_tail, "stop", {}, 0.0) if reused_tail is not None else original_collect(client, params, **kwargs)
        (dest / f"continuation-response-{len(calls)-1}.txt").write_text(collected[0], encoding="utf-8")
        return collected

    def log_usage(**kwargs):
        if len(calls) == 1 or reused_tail is not None:
            kwargs["source"] = "saved_response_replay"
        return original_log_usage(**kwargs)

    result = {"slug": args.slug, "passed": False, "started_at": time.time(), "source_log": str(logs),
              "scope": "Saved response replay followed by real API continuation; live search artifacts are untouched",
              "original_prompt_hashes_equal": record["verified_original_prompt_hashes_equal"],
              "partial_sha256": hashlib.sha256(partial.encode()).hexdigest()}
    if args.reuse_tail_from:
        result["scope"] = "Reassemble the matching saved real API tail after a verified prefix-cleanup bug; no new API call"
        result["real_api_source"] = str(args.reuse_tail_from)
    stages.batch.save(dest / "result.json", result)
    print(str(dest), flush=True)
    try:
        backend._collect_stream_response = collect
        backend.log_llm_usage = log_usage
        output = backend.generate(messages, cfg, max_retries=1)
        (dest / "continued-response.txt").write_text(output, encoding="utf-8")
        if not output.startswith(partial):
            raise RuntimeError("Continuation changed saved output prefix")
        result["partial_preserved_exactly"] = True
        result["continuation_transport_verified"] = output.rstrip().endswith("```") and len(output) > len(partial)
        code = extract_code(output)
        if not code:
            if "```python" in output:
                outer = output[output.index("```python") + 9:output.rfind("```")].strip()
                try:
                    ast.parse(outer)
                except SyntaxError as exc:
                    result["syntax_error"] = {"line": exc.lineno, "message": exc.msg, "text": exc.text}
                    prefix_code = partial[partial.index("```python") + 9:]
                    if exc.lineno and exc.lineno <= len(prefix_code.splitlines()):
                        result["syntax_error_origin"] = "original_provider_partial_before_continuation"
            raise RuntimeError("Continuation did not produce a complete Python script")
        ast.parse(code)
        (dest / "candidate.py").write_text(code, encoding="utf-8")
        result.update(passed=True, partial_preserved_exactly=True, code_parses=True, code_characters=len(code))
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc).replace(model["apiKey"], "[REDACTED]"))
    finally:
        backend._collect_stream_response = original_collect
        backend.log_llm_usage = original_log_usage
        result.update(finished_at=time.time(), calls=calls)
        stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "passed": result["passed"]}), flush=True)


if __name__ == "__main__":
    main()

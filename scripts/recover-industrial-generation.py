"""Bind an unexecuted original provider draft to an interrupted empty search."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from agents.coder.recovery import text_sha256
from utils.autorealize_context import build_autorealize_context_md, load_autorealize_description_md
from utils.response import extract_code


def reconstruct_original_prompt(logs, record, *, cfg=None, journal=None):
    """Reproduce legacy package shuffling only when actual provider hashes match."""
    import yaml
    from omegaconf import OmegaConf
    from engine.agent_search import AgentSearch
    from engine.search_node import Journal
    from engine.expansion_profile import ExpansionProfile
    from utils.serialize import load_json
    from agents import draft_agent
    from llm.openai import _prompt_to_messages

    if cfg is None:
        cfg = OmegaConf.create(yaml.unsafe_load((logs / "config.yaml").read_text(encoding="utf-8")), flags={"allow_objects": True})
    if journal is None:
        journal = load_json(logs / "journal.json", Journal)
    from engine import agent_search
    original_context_builder = agent_search.build_autorealize_context_md
    try:
        agent_search.build_autorealize_context_md = lambda input_dir, **kwargs: original_context_builder(input_dir, write_context_file=False)
        agent = AgentSearch("", cfg, journal)
    finally:
        agent_search.build_autorealize_context_md = original_context_builder
    agent.update_data_preview()
    original_environment = draft_agent.get_prompt_environment
    original_recovery = draft_agent.recover_first_draft
    captured = {}

    class Captured(Exception):
        pass

    def capture(agent, prompt):
        captured["prompt"] = prompt
        raise Captured()

    def legacy_environment():
        packages = ["numpy", "pandas", "scikit-learn", "statsmodels", "xgboost", "lightGBM", "torch", "torchvision", "torch-geometric", "bayesian-optimization", "timm", "transformers", "sentence-transformers", "opencv-python", "Pillow"]
        random.shuffle(packages)
        text = ", ".join(f"`{name}`" for name in packages)
        return {"Installed Packages": f"Your solution can use any relevant machine learning packages such as: {text}. Feel free to use any other packages too (all packages are already installed!). For neural networks we suggest using PyTorch rather than TensorFlow."}

    profile = ExpansionProfile.create(1, task_family="prediction")
    try:
        draft_agent.recover_first_draft = capture
        random.seed(cfg.agent.seed)
        try:
            draft_agent.run(agent, expansion_profile=profile, fast_draft_mode=True, use_stepwise_generation=False)
        except Captured:
            pass
        messages = _prompt_to_messages(captured["prompt"], model=agent.acfg.code.model, base_url=agent.acfg.code.base_url)
        signatures = [{"role": item["role"], "sha256_16": text_sha256(item["content"])[:16]} for item in messages]
        if signatures == record["provider_prompt_signatures"]:
            record["source_prompt_messages"] = messages
            record["expansion_profile"] = profile.to_payload()
            record["verified_original_prompt_hashes_equal"] = True
            return
        draft_agent.get_prompt_environment = legacy_environment
        for offset in range(60):
            random.seed(cfg.agent.seed)
            for _ in range(offset):
                random.getrandbits(32)
            try:
                draft_agent.run(agent, expansion_profile=profile, fast_draft_mode=True, use_stepwise_generation=False)
            except Captured:
                pass
            messages = _prompt_to_messages(captured["prompt"], model=agent.acfg.code.model, base_url=agent.acfg.code.base_url)
            signatures = [{"role": item["role"], "sha256_16": text_sha256(item["content"])[:16]} for item in messages]
            if signatures == record["provider_prompt_signatures"]:
                record["source_prompt_messages"] = messages
                record["expansion_profile"] = profile.to_payload()
                record["verified_original_prompt_hashes_equal"] = True
                return
        raise RuntimeError("Could not reconstruct the exact original provider prompt")
    finally:
        draft_agent.get_prompt_environment = original_environment
        draft_agent.recover_first_draft = original_recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--response-index", type=int, default=0)
    parser.add_argument("--reconstruct-prompt", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("stage_control", Path(__file__).with_name("industrial-stage-control.py"))
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    task = control.current_task(args.slug)
    if task["status"] == "running":
        raise RuntimeError("Stop the search and wait for its durable checkpoint first")
    control.verify_task_definition(task)
    logs = Path(task["auto_ml_log_dir"])
    state = control.read_json(logs / "search_state.json", {})
    status = control.read_json(logs / "run_status.json", {})
    journal = control.read_json(logs / "journal.json", {})
    nodes = journal.get("nodes", [])
    if len(nodes) != 1 or nodes[0].get("stage") != "root" or state.get("active_actions"):
        raise RuntimeError("Recovery is restricted to the first unexecuted draft in an empty tree")
    if status.get("status") != "interrupted_resumable":
        raise RuntimeError("A resumable interruption checkpoint is required")
    source = logs / "AlgoEvolve.verbose.log"
    raw = source.read_bytes()
    matches = list(re.finditer(rb"INFO: generate final response after continuations: (.*?)(?=\r?\n\[\d{4}-\d{2}-\d{2} )", raw, re.S))
    match = matches[args.response_index]
    usage_rows = [json.loads(line) for line in (logs / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    generation_rows = [row for row in usage_rows if row.get("prompt_name") == "generate:agents.coder.base_coder.plan_and_code_query"]
    usage = generation_rows[args.response_index]
    if usage.get("finish_reason") != "stop" or not usage.get("prompt_parts"):
        raise RuntimeError("The selected paid response must be complete and have actual prompt fingerprints")
    response_bytes = match[1]
    response = response_bytes.decode("utf-8")
    code = extract_code(response)
    outer = response[response.index("```python") + 9:response.rfind("```")].strip()
    if not code or ast.dump(ast.parse(code)) != ast.dump(ast.parse(outer)):
        raise RuntimeError("Parsed code must exactly preserve the full original response AST")
    input_dir = Path(task["run_dir"]) / "autorealize"
    record = {
        "schema": "algoevolve.first_draft_response_recovery.v1",
        "parent_id": nodes[0]["id"],
        "task_description_sha256": text_sha256(load_autorealize_description_md(input_dir)),
        "data_context_sha256": text_sha256(build_autorealize_context_md(input_dir, write_context_file=False)),
        "source_log": source.name,
        "response_offset": match.start(1),
        "response_bytes": len(response_bytes),
        "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "provider_prompt_signatures": [{"role": item["role"], "sha256_16": item["sha256_16"]} for item in usage["prompt_parts"]],
        "verified_original_ast_equal": True,
        "cumulative_search_elapsed_seconds": state["cumulative_search_elapsed_seconds"],
        "reason": "Valid original Python was discarded because documentation fences inside a string confused the parser. No generated model code or search duration is edited.",
    }
    path = logs / "draft_response_recovery.json"
    if args.reconstruct_prompt:
        reconstruct_original_prompt(logs, record)
    if path.exists():
        previous = control.read_json(path)
        if not args.reconstruct_prompt or previous.get("response_sha256") != record["response_sha256"]:
            raise RuntimeError("A recovery manifest already exists")
    control.batch.save(path, record)
    print(json.dumps({"recovery_manifest": str(path), "code_characters": len(code), "original_ast_equal": True}))


if __name__ == "__main__":
    main()

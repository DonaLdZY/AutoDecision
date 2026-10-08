"""Re-review a saved real candidate in an isolated copy without executing model code."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")

import yaml
from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from agents import code_review_agent, result_parse_agent
from engine.agent_search import AgentSearch
from engine.execution import update_node_certification
from engine.executor import ExecutionResult
from engine.node_workspace import copy_node_outputs, node_workspace
from engine.search_node import Journal
from engine.solution_protocol import interface_for, preflight_code
from utils.serialize import load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--expect", choices=("accept", "reject"), required=True)
    parser.add_argument("--pre-execution", action="store_true")
    parser.add_argument("--code-file", type=Path)
    parser.add_argument("--probe-evidence", type=Path)
    parser.add_argument("--allowed-functions", nargs="+")
    args = parser.parse_args()
    stage_spec = importlib.util.spec_from_file_location("review_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(stage_spec)
    stage_spec.loader.exec_module(stages)
    task = stages.current_task(args.slug)
    logs, workspace = Path(task["auto_ml_log_dir"]), Path(task["auto_ml_workspace_dir"])
    dest = OUT / "optimization-validation" / f"review-{args.slug}-{args.node[:8]}-{time.time_ns()}"
    isolated = dest / "workspace"
    isolated.mkdir(parents=True)
    (isolated / "input").symlink_to(workspace / "input", target_is_directory=True)
    (isolated / "submission").mkdir()
    copy_node_outputs(node_workspace(workspace, args.node), node_workspace(isolated, args.node))
    submission = workspace / "submission" / f"submission_{args.node}.csv"
    if submission.is_file():
        shutil.copy2(submission, isolated / "submission" / submission.name)
    cfg = OmegaConf.create(yaml.unsafe_load((logs / "config.yaml").read_text(encoding="utf-8")), flags={"allow_objects": True})
    cfg.log_dir = dest
    cfg.workspace_dir = isolated
    helper_spec = importlib.util.spec_from_file_location("provider_probe", ROOT / "scripts/validate-industrial-prompts.py")
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    model = helper.model_entry()
    for stage in (cfg.agent.code, cfg.agent.feedback):
        stage.api_key = model["apiKey"]
        stage.base_url = model["baseUrl"]
        stage.model = model["model"]
        stage.reasoning_effort = "xhigh"
    os.environ["ALGOEVOLVE_PROMPT_CACHE_KEY_MODE"] = "enabled"
    journal = load_json(logs / "journal.json", Journal)
    node = next(item for item in journal.nodes if item.id == args.node)
    before = {"verdict": node.review_verdict, "reason_codes": node.review_reason_codes, "score": node.metric.value}
    logger = logging.getLogger("AlgoEvolve")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.FileHandler(dest / "review.log", encoding="utf-8"))
    print(str(dest), flush=True)
    agent = AgentSearch("", cfg, journal)
    agent.update_data_preview()
    if args.pre_execution:
        if args.code_file:
            node.code = args.code_file.read_text(encoding="utf-8")
        if args.probe_evidence:
            node.interface_probe_evidence = json.loads(args.probe_evidence.read_text(encoding="utf-8"))
        node.review_allowed_definitions = args.allowed_functions
        original = node.code
        interface = interface_for(task_family="prediction", method_family=node.method_family)
        initial = preflight_code(original, interface, require_final_evaluation=True)
        (dest / "original.py").write_text(original, encoding="utf-8")
        started = time.monotonic()
        revised = code_review_agent.run(agent, node)
        (dest / "original.py").write_text(original, encoding="utf-8")
        (dest / "revised.py").write_text(revised, encoding="utf-8")
        final = preflight_code(revised, interface, require_final_evaluation=True)
        result = {"stage": "automl", "slug": args.slug, "node": node.id,
                  "passed": final.ok and revised != original and (dest / "llm_usage.jsonl").is_file(),
                  "review_kind": "production_pre_execution_repair", "before_preflight": initial.__dict__,
                  "after_preflight": final.__dict__, "seconds": time.monotonic() - started,
                  "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                  "revised_sha256": hashlib.sha256(revised.encode()).hexdigest(),
                  "scope": "Real code reviewer repairs a saved failed candidate in isolation. No model execution or holdout evaluation. Semantic inspection and development-only execution still required."}
        (dest / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"directory": str(dest), **result}, ensure_ascii=False))
        return
    execution = ExecutionResult(term_out=list(node._term_out), exec_time=node.exec_time,
                                exc_type=node.exc_type, exc_info=node.exc_info, exc_stack=node.exc_stack)
    started = time.monotonic()
    node = result_parse_agent.run(agent, node, execution)
    update_node_certification(agent, node)
    result = {"stage": "automl", "slug": args.slug, "node": node.id,
              "passed": node.review_verdict == args.expect and (dest / "llm_usage.jsonl").is_file(),
              "expected_verdict": args.expect, "before": before, "verdict": node.review_verdict,
              "metric": node.metric.value, "output_scope": node.output_scope,
              "search_eligible": node.search_eligible, "delivery_ready": node.delivery_ready,
              "analysis": node.parser_analysis, "seconds": time.monotonic() - started,
              "scope": "Actual production provider review of unchanged saved code/output in copied artifacts. No model execution, original journal edit or holdout evaluation. This tests reviewer behavior, not final model acceptance."}
    (dest / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(dest), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

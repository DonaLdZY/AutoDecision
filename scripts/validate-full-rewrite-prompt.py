"""Compare real full-rewrite fallback prompts without modifying a running search."""
import argparse
import ast
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
import yaml
from omegaconf import OmegaConf
from agents import improve_agent
from agents.coder.base_coder import complete_script_prompt
from engine.agent_search import AgentSearch
from engine.search_node import Journal
from engine.solution_protocol import interface_for, preflight_code
from llm import generate
from utils.response import extract_plan_and_code
from utils.serialize import load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--node", required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("fallback_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task(args.slug)
    logs = Path(task["auto_ml_log_dir"])
    dest = stages.batch.OUT / "optimization-validation" / f"full-rewrite-{time.time_ns()}"
    dest.mkdir(parents=True)
    config = OmegaConf.create(yaml.unsafe_load((logs / "config.yaml").read_text(encoding="utf-8")), flags={"allow_objects": True})
    settings = yaml.safe_load((stages.batch.OUT / "settings.yaml").read_text(encoding="utf-8-sig"))
    stages.validate_provider(settings)
    entry = next(row for row in settings["llm"]["modelLibrary"] if row["model"] == "gpt-5.6-luna")
    for role in (config.agent.code, config.agent.feedback):
        role.model, role.base_url, role.api_key = entry["model"], entry["baseUrl"], entry["apiKey"]
        role.reasoning_effort, role.max_tokens = "xhigh", 32768
    config.log_dir = dest
    config.agent.use_diff_mode = True
    logger = logging.getLogger("AlgoEvolve")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.FileHandler(dest / "validation.log", encoding="utf-8"))
    journal = load_json(logs / "journal.json", Journal)
    node = next(row for row in journal.nodes if row.id == args.node)
    agent = AgentSearch("", config, journal)
    agent.update_data_preview()
    agent.global_memory = None
    captured = {}
    class Captured(BaseException):
        pass
    def failed_diff(*args, **kwargs):
        raise RuntimeError("Isolated capture of production full-rewrite fallback")
    def capture(agent, prompt):
        captured["prompt"] = prompt
        raise Captured()
    original_diff, original_coder = improve_agent._diff_improve, improve_agent.plan_and_code_query
    improve_agent._diff_improve, improve_agent.plan_and_code_query = failed_diff, capture
    try:
        improve_agent.run(agent, node)
    except Captured:
        pass
    finally:
        improve_agent._diff_improve, improve_agent.plan_and_code_query = original_diff, original_coder
    original = captured["prompt"]
    revised = complete_script_prompt(original)
    assert original["system"] == revised["system"] and original["assistant"] == revised["assistant"]
    assert revised["user"].startswith(original["user"])
    print(str(dest), flush=True)
    calls = []
    for name, prompt in (("old", original), ("new", revised)):
        config.log_dir = dest / name
        config.log_dir.mkdir()
        stages.batch.save(config.log_dir / "request.json", prompt)
        row = {"variant": name, "started_at": time.time()}
        try:
            response = generate(prompt=prompt, cfg=config, temperature=config.agent.code.temp,
                                max_tokens=32768, max_retries=1)
            (config.log_dir / "response.txt").write_text(response, encoding="utf-8")
            plan, code = extract_plan_and_code(response, default_plan="Complete solution")
            (config.log_dir / "solution.py").write_text(code, encoding="utf-8")
            preflight = preflight_code(code, interface_for(task_family="prediction", method_family=node.method_family),
                                      require_final_evaluation=True)
            row.update(completed=True, code_chars=len(code), plan=plan, preflight=preflight.__dict__)
        except Exception as exc:
            row.update(completed=False, error_type=type(exc).__name__, error=str(exc).replace(entry["apiKey"], "[REDACTED]"))
        row["seconds"] = time.time() - row["started_at"]
        calls.append(row)
        stages.batch.save(config.log_dir / "result.json", row)
    stages.batch.save(dest / "result.json", {"slug": args.slug, "node": node.id, "calls": calls,
        "complete_task_code_context_preserved": True, "quality_review_pending": True,
        "scope": "Real old/new provider outputs; full task and original code retained. No search edits, model training or final evaluation."})
    print(json.dumps({"result": str(dest / "result.json"), "calls": calls}, ensure_ascii=False))


if __name__ == "__main__":
    main()

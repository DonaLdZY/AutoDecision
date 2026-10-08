"""Compare old/new wire schemas with the exact same real production planning prompt."""
import argparse
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
from agents.planner import base_planner
from engine.agent_search import AgentSearch
from engine.search_node import Journal
from llm import openai as provider
from utils.serialize import load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", default="traffic")
    parser.add_argument("--node", required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("schema_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task(args.slug)
    logs = Path(task["auto_ml_log_dir"])
    dest = stages.batch.OUT / "optimization-validation" / f"planner-schema-{time.time_ns()}"
    dest.mkdir(parents=True)
    config = OmegaConf.create(yaml.unsafe_load((logs / "config.yaml").read_text(encoding="utf-8")), flags={"allow_objects": True})
    settings = yaml.safe_load((stages.batch.OUT / "settings.yaml").read_text(encoding="utf-8-sig"))
    entry = next(row for row in settings["llm"]["modelLibrary"] if row["model"] == "gpt-5.6-luna")
    for stage in (config.agent.code, config.agent.feedback):
        stage.model, stage.base_url, stage.api_key = entry["model"], entry["baseUrl"], entry["apiKey"]
        stage.reasoning_effort, stage.max_tokens = "xhigh", 32768
    config.log_dir = dest
    journal = load_json(logs / "journal.json", Journal)
    node = next(row for row in journal.nodes if row.id == args.node)
    logger = logging.getLogger("AlgoEvolve")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.FileHandler(dest / "validation.log", encoding="utf-8"))
    agent = AgentSearch("", config, journal)
    agent.update_data_preview()
    agent.global_memory = None
    captured = {}
    class Captured(BaseException):
        pass
    original_planner = improve_agent.run_planner
    def capture(**kwargs):
        captured.update(kwargs)
        raise Captured()
    improve_agent.run_planner = capture
    try:
        improve_agent.run(agent, node)
    except Captured:
        pass
    finally:
        improve_agent.run_planner = original_planner
    if not captured:
        raise RuntimeError("Production planner invocation was not captured")
    calls = []
    original_generate = base_planner.generate
    original_builder = base_planner.build_planning_json_schema
    def generate_with_schema(**kwargs):
        label = calls[-1]["variant"]
        allowed = kwargs["json_schema"]["properties"]["module"]["items"]["enum"]
        schema = (base_planner.build_closed_planning_json_schema if label == "new" else original_builder)(allowed)
        stages.batch.save(dest / label / "request.json", {"prompt": kwargs["prompt"], "schema": schema})
        return original_generate(**{**kwargs, "json_schema": schema})
    base_planner.generate = generate_with_schema
    print(str(dest), flush=True)
    try:
        for variant in ("old", "new"):
            config.log_dir = dest / variant
            config.log_dir.mkdir()
            row = {"variant": variant, "started_at": time.time()}
            calls.append(row)
            try:
                value = original_planner(**{**captured, "max_retries": 1})
                row.update(output=value, completed=True)
                modules, plans = value.get("module", []), value.get("plan", {})
                row["structural_passed"] = (value.get("parse_success") is True and 1 <= len(modules) <= 3
                    and set(modules) == set(plans) and all(isinstance(plan, str) and plan.strip() for plan in plans.values()))
            except Exception as exc:
                row.update(completed=False, error_type=type(exc).__name__, error=str(exc).replace(entry["apiKey"], "[REDACTED]"))
            row["seconds"] = time.time() - row["started_at"]
            stages.batch.save(dest / variant / "result.json", row)
    finally:
        base_planner.generate = original_generate
        base_planner.build_planning_json_schema = original_builder
    old_request, new_request = [stages.read_json(dest / name / "request.json") for name in ("old", "new")]
    result = {"slug": args.slug, "node": args.node, "stage": "automl", "calls": calls,
              "prompt_identical": old_request["prompt"] == new_request["prompt"],
              "quality_review_pending": True, "scope": "Actual production planner with identical complete task/context/code; only JSON wire schema differs. No model execution or search journal edit."}
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "calls": calls}, ensure_ascii=False))


if __name__ == "__main__":
    main()

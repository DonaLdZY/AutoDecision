"""Independently audit a saved candidate and exercise the real result reviewer."""
from pathlib import Path
import importlib.util
import json
import logging
import sys
import time

import numpy as np
import pandas as pd
import yaml
from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from agents import result_parse_agent
from engine.agent_search import AgentSearch
from engine.executor import ExecutionResult
from engine.execution import update_node_certification
from engine.search_node import Journal
from utils.serialize import load_json


def main():
    root = OUT / "tasks/工业实例-钢厂用电预测"
    logs = next(root.glob("automl/logs/20260907_060850*"))
    work = next(root.glob("automl/workspaces/20260907_060850*"))
    dest = OUT / "optimization-validation" / f"automl-score-phase-steel-{time.time_ns()}"
    dest.mkdir(parents=True)
    logger = logging.getLogger("AlgoEvolve")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.FileHandler(dest / "review.log", encoding="utf-8"))
    cfg = OmegaConf.create(yaml.unsafe_load((logs / "config.yaml").read_text(encoding="utf-8")), flags={"allow_objects": True})
    cfg.log_dir = dest
    spec = importlib.util.spec_from_file_location("provider_probe", ROOT / "scripts/validate-industrial-prompts.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    model = helper.model_entry()
    for stage in (cfg.agent.code, cfg.agent.feedback):
        stage.api_key = model["apiKey"]
        stage.base_url = model["baseUrl"]
        stage.model = model["model"]
        stage.reasoning_effort = "xhigh"
    journal = load_json(logs / "journal.json", Journal)
    node = next(n for n in journal.nodes if n.id == "80aeeef1f2fa41558167bb94c89acf4b")
    source = pd.read_csv(work / "input/Steel_industry_data.csv")
    source["date"] = pd.to_datetime(source["date"], format="%d/%m/%Y %H:%M")
    source = source.sort_values("date", kind="stable").reset_index(drop=True)
    metrics = json.loads((work / "working/metrics.json").read_text(encoding="utf-8"))
    selected_id = metrics["selection"]["selected_candidate_id"]
    scores = {}
    for split, start, end in [("development", 21024, 28032), ("holdout", 28032, 35040)]:
        predictions = pd.read_csv(work / f"working/validation_predictions_{split}.csv")
        predictions = predictions.loc[predictions["candidate_id"] == selected_id]
        target = source.iloc[start:end]
        times = pd.to_datetime(predictions["timestamp"], format="%d/%m/%Y %H:%M")
        if len(predictions) != len(target) or not np.array_equal(times.to_numpy(), target["date"].to_numpy()):
            raise RuntimeError("Prediction target population does not match original source")
        truth = target["Usage_kWh"].to_numpy()
        if not np.array_equal(predictions["y_true"].to_numpy(), truth):
            raise RuntimeError("Candidate labels do not match source labels")
        scores[split] = float(np.mean(np.abs(predictions["y_pred"].to_numpy() - truth)))
    reported = node.metric.value
    node.review_verdict = None
    agent = AgentSearch("", cfg, journal)
    agent.update_data_preview()
    started = time.monotonic()
    result = ExecutionResult(term_out=list(node._term_out), exec_time=node.exec_time,
                             exc_type=node.exc_type, exc_info=node.exc_info, exc_stack=node.exc_stack)
    node = result_parse_agent.run(agent, node=node, exec_result=result)
    update_node_certification(agent, node)
    summary = {
        "stage": "automl", "slug": "steel", "passed": node.review_verdict == "reject" and node.is_valid is False and node.search_eligible is False and (dest / "llm_usage.jsonl").is_file(),
        "scope": "Actual production re-review of a saved invalid holdout-scored candidate plus independent source-aligned MAE recomputation. No model code or original search journal is changed.",
        "independent_scores": scores, "original_search_score": reported,
        "score_matches_holdout": abs(reported - scores["holdout"]) < 1e-9,
        "score_matches_development": abs(reported - scores["development"]) < 1e-9,
        "new_verdict": node.review_verdict, "is_valid": node.is_valid, "search_eligible": node.search_eligible,
        "analysis": node.parser_analysis, "seconds": time.monotonic() - started,
    }
    (dest / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(dest), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()

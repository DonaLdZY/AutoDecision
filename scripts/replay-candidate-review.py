"""Replay result review from saved candidate output in a separate workspace.

Does not rerun training or final evaluation, edit the original journal, or
promote the replayed verdict into a historical task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "core/AlgoEvolve"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, help="New independent repair containing solution.py, execution.log and execution-result.json.")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".codex-work") or output.exists():
        raise ValueError("Use a new output directory inside .codex-work.")
    sys.path.insert(0, str(ENGINE))
    from omegaconf import OmegaConf
    from config import Config
    from agents import result_parse_agent
    from engine.execution import update_node_certification
    from engine.executor import ExecutionResult
    from engine.search_node import SearchNode
    from utils.autorealize_context import build_autorealize_context_md, load_autorealize_task_summary

    original_log = args.log_dir.resolve()
    journal = json.loads((original_log / "journal.json").read_text(encoding="utf-8"))
    saved = next(n for n in journal["nodes"] if n["id"] == args.node_id)
    cfg = OmegaConf.to_object(OmegaConf.merge(OmegaConf.structured(Config), OmegaConf.load(original_log / "config.yaml")))
    original_ws = Path(cfg.workspace_dir)
    output.mkdir(parents=True)
    workspace = output / "workspace"
    repaired = args.candidate_dir.resolve() if args.candidate_dir else None
    if repaired and not repaired.is_relative_to(ROOT / ".codex-work"):
        raise ValueError("Candidate repair must be inside .codex-work.")
    shutil.copytree(original_ws / "input", workspace / "input")
    shutil.copytree(repaired or original_ws / "node_runs" / args.node_id, workspace / "node_runs" / args.node_id)
    submission = repaired / "submission/submission.csv" if repaired else original_ws / "submission" / f"submission_{args.node_id}.csv"
    if submission.exists():
        (workspace / "submission").mkdir()
        shutil.copyfile(submission, workspace / "submission" / f"submission_{args.node_id}.csv")
    cfg.workspace_dir, cfg.log_dir = workspace, output / "logs"
    cfg.log_dir.mkdir()
    private = yaml.safe_load((ROOT / "frontend/config/global_settings.yaml").read_text(encoding="utf-8-sig"))["llm"]
    for role, stage in (("autoMlCode", cfg.agent.code), ("autoMlFeedback", cfg.agent.feedback)):
        selected = private["roleModels"].get(role) or private["roleModels"]["autoMlCode"]
        model = next(m for m in private["modelLibrary"] if m["id"] == selected)
        stage.model, stage.base_url, stage.api_key = model["model"], model["baseUrl"], model["apiKey"]
        stage.enable_thinking = True
        stage.max_tokens = int(model.get("maxTokens") or 65536)
        stage.context_window_tokens = int(model.get("contextWindowTokens") or 1000000)
    context = build_autorealize_context_md(workspace / "input", write_context_file=False)
    agent = SimpleNamespace(
        cfg=cfg, acfg=cfg.agent, has_autorealize_context=True,
        autorealize_context=context, data_preview=context, coldstart_description="",
        task_desc=load_autorealize_task_summary(workspace / "input"),
        global_memory=None, metric_maximize=False, metric_maximize_reasoning="Frozen task contract",
    )
    repaired_execution = json.loads((repaired / "execution-result.json").read_text(encoding="utf-8")) if repaired else None
    code = (repaired / "solution.py").read_text(encoding="utf-8") if repaired else saved["code"]
    node = SearchNode(
        id=args.node_id, code=code, stage=saved["stage"], plan=saved.get("plan"),
        solution_interface=saved.get("solution_interface") or "prediction",
        evaluation_protocol={k: v for k, v in saved.get("evaluation_protocol", {}).items() if k.startswith("expected_")},
    )
    execution = ExecutionResult(
        term_out=(repaired / "execution.log").read_text(encoding="utf-8").splitlines(keepends=True) if repaired else saved["_term_out"],
        exec_time=repaired_execution["elapsed_seconds"] if repaired else saved["exec_time"],
        exc_type=("ExecutionFailed" if repaired_execution["returncode"] else None) if repaired else saved.get("exc_type"),
        exc_info=None if repaired else saved.get("exc_info"), exc_stack=None if repaired else saved.get("exc_stack"))
    result_parse_agent.run(agent, node, execution)
    update_node_certification(agent, node)
    result = {k: getattr(node, k) for k in (
        "id", "analysis", "llm_insight", "review_verdict", "review_reason_codes", "output_scope",
        "search_eligible", "delivery_ready", "delivery_certified", "evaluation_protocol",
    )}
    result["metric"] = node.metric.value
    result["original_journal_sha256"] = hashlib.sha256((original_log / "journal.json").read_bytes()).hexdigest()
    result["reviewed_code_sha256"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
    result["candidate_repair_dir"] = str(repaired) if repaired else None
    result["scope"] = "Saved output result review only; no training, holdout access, historical journal update or delivery certification."
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("review_verdict", "output_scope", "metric", "search_eligible", "delivery_ready", "delivery_certified")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

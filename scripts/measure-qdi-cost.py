"""Offline deterministic QDI comparison. No API calls; all execution in temp dirs.

Pass --baseline-dir pointing at the pre-edit AutoRealize source snapshot root.
The scripted responses demonstrate mechanisms, not model accuracy or actual fees.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "AutoRealize"))
from autorealize import investigation, models
from autorealize.config import AutoRealizeConfig
from autorealize.llm.client import _schema_text_for_prompt, _example_from_schema
from autorealize.prompt_cache import estimate_text_tokens
from autorealize.qdi_efficiency import compile_checks


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def scenario(module, schema_models, prompt_root, *, optimized):
    with tempfile.TemporaryDirectory(prefix="qdi_offline_") as folder:
        root = Path(folder)
        data = root / "input"
        data.mkdir()
        (data / "a.csv").write_text("id\n001\n002\n003\n", encoding="utf-8")
        # Extra cards intentionally exercise source projection on a multi-table task.
        context = {
            "context_policy": {}, "authoritative_memory": {"metric": "MAE on development rows only."},
            "constraint_memory": {"hard_rule": "Never use final holdout for search."}, "relations": [],
            "table_cards": [{"table_id": name, "source_file": name,
                "fields": [{"name": f"column_{j}", "meaning": f"Source {name} field {j}: preserve exact units and null policy."}
                           for j in range(40)]} for name in ["a.csv"] + [f"extra_{i}.csv" for i in range(7)]],
        }
        questions = [models.InvestigationQuestion(question_id="q1", question="Are identifiers unique?", candidate_files=["a.csv"]),
                     models.InvestigationQuestion(question_id="q2", question="How many distinct identifiers?", candidate_files=["a.csv"])]
        metric_question = models.InvestigationQuestion(question_id="q3", question="Which metric is required?", category="evaluation")
        check = models.QDIDeterministicCheck(kind="key_integrity", left={"file": "a.csv"}, columns=["id"])
        script = compile_checks([check], "").custom_python
        actions = []
        for q in questions:
            actions.append(models.QuestionInvestigationAction(
                action="request_checks" if optimized else "request_script",
                **({"request_checks": [check]} if optimized else {"request_script": script.model_copy(update={"question_id": q.question_id})})))
            actions.append(models.QuestionInvestigationAction(action="answer", answer="3 nonempty unique identifiers in the complete table.",
                                                              evidence=["checks/0/facts"]))
        plan = models.QuestionInvestigationPlan(questions=deepcopy(questions))
        if optimized:
            plan.direct_answers = [models.QDIExtractiveAnswer(question=metric_question,
                source_pointer="/authoritative_memory/metric", quote=context["authoritative_memory"]["metric"])]
        else:
            plan.questions.append(metric_question)
            actions.append(models.QuestionInvestigationAction(action="answer", answer=context["authoritative_memory"]["metric"],
                                                              evidence=["stable_context:/authoritative_memory/metric"]))
        calls = []
        iterator = iter(actions)
        class Prompts:
            def load(self, name):
                return (prompt_root / name).read_text(encoding="utf-8")
        class LLM:
            def ask_structured(self, model_cls, **kwargs):
                schema = getattr(schema_models, model_cls.__name__).model_json_schema()
                parts = {"static_context": kwargs.get("static_context_prompt", ""),
                         "dynamic_context": kwargs.get("dynamic_user_prompt", ""),
                         "instructions": kwargs.get("system_prompt", ""),
                         "schema": _schema_text_for_prompt(schema, compact=True),
                         "example": json.dumps(_example_from_schema(schema), ensure_ascii=False)}
                calls.append({"prompt": kwargs["prompt_name"], "estimated_tokens": {
                    key: estimate_text_tokens(text) for key, text in parts.items()}})
                return plan if model_cls.__name__ == "QuestionInvestigationPlan" else next(iterator)
        cfg = AutoRealizeConfig()
        cfg.investigation.automatic_verification_question_limit = 0
        cfg.investigation.max_questions = 3
        cfg.investigation.max_rounds_per_run = 3
        executions = []
        original = module.CrossFileInvestigationTools.execute
        def execute(self, req):
            executions.append(req.request_id)
            return original(self, req)
        with patch.object(module, "_build_investigation_context", return_value=(deepcopy(context), {})), \
             patch.object(module.CrossFileInvestigationTools, "execute", execute):
            report = module._run_question_investigator_inner(cfg=cfg, llm_client=LLM(), prompt_mgr=Prompts(),
                data_root=data, task_hint="offline", file_summaries=[], relation_hints=[], constraint_memory={},
                authoritative_memory={}, knowledge_base={}, report_dir=root / "report")
        assert len(report["answers"]) == 3
        assert not report["unresolved_questions"]
        return {"llm_calls": len(calls), "sandbox_executions": len(executions), "answers": len(report["answers"]),
                "estimated_input_tokens": sum(sum(c["estimated_tokens"].values()) for c in calls),
                "calls": calls, "cost_controls": report["progress"].get("cost_controls", {})}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    old = load("autorealize._qdi_before", args.baseline_dir / "autorealize/investigation.py")
    old_models = load("autorealize._qdi_before_models", args.baseline_dir / "autorealize/models.py")
    before = scenario(old, old_models, args.baseline_dir / "autorealize/prompts", optimized=False)
    after = scenario(investigation, models, ROOT / "core/AutoRealize/autorealize/prompts", optimized=True)
    result = {"method": "Synthetic scripted QDI scenario, real sandbox executions, no model/provider calls",
              "limitations": "Includes estimated static/dynamic instructions, pruned schema and example. Excludes wire framing, reasoning and outputs. Not a production cost or accuracy A/B.",
              "before": before, "after": after,
              "estimated_input_reduction": 1 - after["estimated_input_tokens"] / before["estimated_input_tokens"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("method", "estimated_input_reduction")}, ensure_ascii=False))
    print(json.dumps({"before": {k: before[k] for k in ("llm_calls", "sandbox_executions", "estimated_input_tokens")},
                      "after": {k: after[k] for k in ("llm_calls", "sandbox_executions", "estimated_input_tokens")}}))


if __name__ == "__main__":
    main()

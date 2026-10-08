"""Probe production QDI prompts with saved traffic evidence and explicit test gaps."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
SPEC = importlib.util.spec_from_file_location("industrial_validation", Path(__file__).with_name("validate-industrial-prompts.py"))
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)

from autorealize.config import AutoRealizeConfig
from autorealize.context_compiler import file_to_table_cards
from autorealize.llm.client import LLMClient
from autorealize.investigation import _qdi_answerer_stable_prefix
from autorealize.models import FileSummary, QuestionInvestigationAction, QuestionInvestigationPlan
from autorealize.prompt_cache import stable_dynamic_prompt
from autorealize.prompts.manager import PromptManager


def main():
    destination = validation.OUT / "optimization-validation" / ("qdi-routing-" + str(time.time_ns()))
    source = validation.OUT / "tasks/工业实例-逐门架车流预测/autorealize/realize_report/file_cognition"
    summaries = [FileSummary.model_validate_json(path.read_text(encoding="utf-8-sig")) for path in sorted(source.glob("*.json"))]
    sheet = next(card for summary in summaries for card in file_to_table_cards(summary)
                 if card.get("table_kind") == "excel_sheet")
    entry = validation.model_entry()
    cfg = AutoRealizeConfig()
    cfg.llm.model_name, cfg.llm.api_key, cfg.llm.base_url = entry["model"], entry["apiKey"], entry["baseUrl"]
    cfg.llm.reasoning_effort = "xhigh"
    cfg.llm.max_tokens = 16384
    cfg.llm.request_timeout_seconds = 600
    cfg.llm.max_retries = 1
    cfg.llm.enable_cache = False
    client, prompts = LLMClient(cfg, destination), PromptManager(cfg)
    context = {
        "probe_scope": "Isolated routing probe using a saved real table card, not a task stage or new measured business result",
        "table_cards": [sheet],
        "authoritative_memory": {"task": "预测各门架未来车流", "missing_business_definition": "业务验收中的60分钟高流量分层到底使用哪个半小时尚未定义"},
        "constraint_memory": {"must_preserve": "60分钟高流量分层口径必须明确；不能默默选择一个口径并声称源文档已确认"},
        "question_records": [],
    }
    stable, dynamic = stable_dynamic_prompt(stable=context, dynamic={"max_questions": 3, "instruction": "规划尚未解决的阻塞问题。"})
    planner_prefix = stable
    started = time.monotonic()
    plan = client.ask_structured(
        model_cls=QuestionInvestigationPlan, system_prompt=prompts.load("system/question_investigator_planner.md"),
        user_prompt=dynamic, static_context_prompt=stable, dynamic_user_prompt=dynamic,
        prompt_name="question_investigator_initial_questions",
    )
    validation.save(destination / "plan.json", plan.model_dump())
    stable, dynamic = stable_dynamic_prompt(stable=context, dynamic={
        "current_question": {"question_id": "reading_probe", "question": "当前已有证据推荐如何读取门架关系工作簿的工作表？请说明其证据范围。"},
        "initial_question": {"question_id": "reading_probe", "question": "当前已有证据推荐如何读取门架关系工作簿的工作表？请说明其证据范围。"},
        "available_actions": ["answer", "request_context", "request_script", "give_up"],
        "working_memory": {}, "pending_action_digest_requests": [], "recent_action_window": [],
    })
    stable = _qdi_answerer_stable_prefix(context)
    assert stable == planner_prefix
    action = client.ask_structured(
        model_cls=QuestionInvestigationAction, system_prompt=prompts.load("system/question_investigator_answerer.md"),
        user_prompt=dynamic, static_context_prompt=stable, dynamic_user_prompt=dynamic,
        prompt_name="question_investigator_action",
    )
    validation.save(destination / "action.json", action.model_dump())
    result = {"stage": "qdi_routing", "seconds": time.monotonic() - started, "scope": context["probe_scope"],
              "plan_questions": [item.model_dump() for item in plan.questions],
              "action": action.action, "answer": action.answer,
              "reading_evidence_reused_without_tool": action.action == "answer",
              "planner_and_answerer_prefix_identical": stable == planner_prefix,
              "business_gap_retained": any("60" in item.question for item in plan.questions),
              "passed": action.action == "answer" and any("60" in item.question for item in plan.questions)}
    validation.save(destination / "result.json", result)
    print(json.dumps({"destination": str(destination), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

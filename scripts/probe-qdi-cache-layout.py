"""Run a bounded real QDI probe for the cache-layout and usage split.

The probe uses a tiny synthetic CSV and the configured test gateway. It is
intended to verify transport, structured QDI calls, provider usage telemetry,
and the separation of provider/local/QDI caches. It is not an algorithm-quality
benchmark and never reads or modifies historical ``runs/`` data.

Credentials are read only from the process/user environment:
``AUTODECISION_TEST_LLM_API_KEY``, ``AUTODECISION_TEST_LLM_BASE_URL`` and
``AUTODECISION_TEST_LLM_MODEL``.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "AutoRealize"))

from autorealize.config import AutoRealizeConfig
from autorealize.investigation import _run_question_investigator_inner
from autorealize.llm.client import LLMClient
from autorealize.prompts.manager import PromptManager


def _small_context() -> dict:
    cards = [
        {
            "table_id": "process.csv",
            "source_file": "process.csv",
            "table_kind": "csv",
            "role": "feature_table",
            "shape": [4, 3],
            "fields": [
                {"name": "timestamp", "meaning": "采样时间", "logical_type": "datetime"},
                {"name": "steam_flow", "meaning": "蒸汽进气流量", "logical_type": "numeric"},
                {"name": "al_n", "meaning": "压滤液 Al(N) 结果", "logical_type": "numeric"},
            ],
        },
        {
            "table_id": "notes.csv",
            "source_file": "notes.csv",
            "table_kind": "csv",
            "role": "document_table",
            "shape": [2, 2],
            "fields": [
                {"name": "timestamp", "meaning": "采样时间", "logical_type": "datetime"},
                {"name": "note", "meaning": "工艺备注", "logical_type": "string"},
            ],
        },
    ]
    return {
        "schema_version": "probe.qdi-context.v1",
        "task_hint": (
            "请从本地工艺备注核实 Al(N) 的目标和蒸汽流量推荐规则，再结合 process.csv 的记录判断"
            "是否足以给出下一小时推荐。只能使用实际读取到的备注或计算结果；说明证据和限制。"
        ),
        "data_root_name": "qdi-cache-probe",
        "context_policy": {
            "files_are_table_cards": True,
            "large_objects_local_only": True,
            "authoritative_facts_source": "authoritative_memory",
            "constraint_facts_source": "constraint_memory",
        },
        "table_cards": cards,
        "relations": [],
        "constraint_memory": {"items": ["不得使用未来时刻字段构造特征。"]},
        "authoritative_memory": {"task_goal": "预测 Al(N)，推荐蒸汽流量。"},
        "source_coverage_ledger": [],
        "relation_verification_queue": [],
        "population_verification_queue": [],
        "sampled_filename_patterns": [],
        "filename_sample_groups": [],
        "entity_alias_candidates": [],
        "field_glossary": {},
        "script_investigation_policy": {"input_dir": "read-only"},
        "limits": {"max_questions": 1, "max_rounds_per_run": 2},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".codex-work" / "audit-20261024" / "qdi-cache-layout-probe",
    )
    parser.add_argument(
        "--shared-cache-dir",
        type=Path,
        default=None,
        help="Reuse a QDI node/evidence cache directory from an earlier isolated run.",
    )
    args = parser.parse_args()
    api_key = os.environ.get("AUTODECISION_TEST_LLM_API_KEY", "").strip()
    base_url = os.environ.get("AUTODECISION_TEST_LLM_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("AUTODECISION_TEST_LLM_MODEL", "deepseek-v4.1-flash").strip()
    if not api_key or not base_url:
        raise SystemExit(
            "Missing AUTODECISION_TEST_LLM_API_KEY or AUTODECISION_TEST_LLM_BASE_URL; no request sent"
        )

    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing probe output: {output}")
    output.mkdir(parents=True)
    shared_cache_dir = (
        args.shared_cache_dir.resolve()
        if args.shared_cache_dir is not None
        else output / "shared-cache"
    )

    cfg = AutoRealizeConfig.from_env()
    cfg.llm.api_key = api_key
    cfg.llm.base_url = base_url
    cfg.llm.model_name = model
    cfg.llm.temperature = 0
    cfg.llm.enable_cache = False
    cfg.llm.max_retries = 1
    cfg.llm.request_timeout_seconds = 60
    cfg.llm.max_concurrent_requests = 1
    cfg.investigation.max_questions = 1
    cfg.investigation.max_rounds_per_run = 2
    cfg.investigation.max_scripts_per_question = 1
    cfg.investigation.automatic_verification_question_limit = 0
    cfg.investigation.adaptive_budgeting = False
    cfg.investigation.allow_custom_readonly_python = True
    cfg.investigation.max_result_chars = 4000

    with tempfile.TemporaryDirectory(prefix="autodecision-qdi-probe-") as folder:
        data_root = Path(folder) / "input"
        data_root.mkdir()
        (data_root / "process.csv").write_text(
            "timestamp,steam_flow,al_n\n"
            "2026-01-01T00:00:00,10,1.20\n"
            "2026-01-01T01:00:00,11,1.30\n"
            "2026-01-01T02:00:00,12,1.26\n"
            "2026-01-01T03:00:00,11,1.22\n",
            encoding="utf-8",
        )
        (data_root / "notes.csv").write_text(
            "timestamp,note\n"
            "2026-01-01T00:00:00,"
            "Al(N) operating target <= 1.25; recommend the lowest steam_flow that keeps "
            "predicted next-hour Al(N) <= 1.25; do not use future rows.\n"
            "2026-01-01T00:00:00,"
            "Each timestamp is one hourly process measurement; the next-hour recommendation "
            "applies immediately after the latest observed timestamp.\n",
            encoding="utf-8",
        )
        client = LLMClient(cfg, output)
        context = _small_context()
        try:
            with patch(
                "autorealize.investigation._build_investigation_context",
                return_value=(deepcopy(context), {}),
            ):
                report = _run_question_investigator_inner(
                    cfg=cfg,
                    llm_client=client,
                    prompt_mgr=PromptManager(cfg),
                    data_root=data_root,
                    task_hint=context["task_hint"],
                    file_summaries=[],
                    relation_hints=[],
                    constraint_memory=context["constraint_memory"],
                    authoritative_memory=context["authoritative_memory"],
                    knowledge_base={},
                    prior_question_memory={},
                    shared_cache_dir=shared_cache_dir,
                    report_dir=output / "report",
                )
        finally:
            client.client.close()

        result = {
            "status": "completed",
            "model": model,
            "base_url": base_url,
            "synthetic_data_only": True,
            "max_questions": cfg.investigation.max_questions,
            "max_actions_per_question": cfg.investigation.max_rounds_per_run,
            "llm_usage_summary": client._usage_summary,
            "qdi_cache_metrics": (
                report.get("progress", {}).get("cost_controls", {}).get("cache_metrics", {})
                if isinstance(report, dict)
                else {}
            ),
            "report_summary": {
                "answers": len(report.get("answers", []) or []),
                "unresolved_questions": len(report.get("unresolved_questions", []) or []),
                "actions": len(report.get("action_history", []) or []),
                "action_names": [
                    str(item.get("action") or "")
                    for item in report.get("action_history", [])
                    if isinstance(item, dict)
                ],
                "action_statuses": [
                    str(item.get("status") or "")
                    for item in report.get("action_history", [])
                    if isinstance(item, dict)
                ],
                "script_attempts": len(report.get("step_results", []) or []),
                "terminal_outcome": (
                    "answered"
                    if report.get("answers")
                    else "unresolved"
                    if report.get("unresolved_questions")
                    else "no_question"
                ),
            },
        }
        (output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

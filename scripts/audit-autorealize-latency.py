"""Audit completed LLM calls and replay automatic checks from saved file profiles."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))

from autorealize.context_compiler import build_relation_verification_queue, file_to_table_cards
from autorealize.investigation import _reading_strategy_verification_questions, _relation_verification_questions
from autorealize.models import FileSummary
from autorealize.profiling.relations import detect_relations


def read_jsonl(path):
    # A live writer may leave the last line incomplete during a snapshot.
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    rows = []
    for index, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise
    return rows


def audit(root):
    calls = read_jsonl(root / "llm_usage.jsonl")
    groups = defaultdict(lambda: {"calls": 0, "request_seconds_sum": 0.0, "input_tokens": 0,
                                  "output_tokens": 0, "reasoning_tokens": 0, "cache_known_calls": 0})
    for row in calls:
        if row.get("source") != "provider":
            continue
        group = groups[row["prompt_name"]]
        group["calls"] += 1
        group["request_seconds_sum"] += float(row.get("seconds") or 0)
        group["input_tokens"] += int(row.get("prompt_tokens") or 0)
        group["output_tokens"] += int(row.get("completion_tokens") or 0)
        group["reasoning_tokens"] += int(row.get("reasoning_tokens") or 0)
        group["cache_known_calls"] += int(bool(row.get("provider_cache_tokens_known")))

    summaries = [FileSummary.model_validate_json(path.read_text(encoding="utf-8-sig"))
                 for path in sorted((root / "file_cognition").glob("*.json"))]
    cards = [card for summary in summaries for card in file_to_table_cards(summary)]
    relations = detect_relations({summary.path: summary.columns for summary in summaries}, file_summaries=summaries)
    context = {"table_cards": cards,
               "relation_verification_queue": build_relation_verification_queue([asdict(item) for item in relations])}
    revised = _relation_verification_questions(context) + _reading_strategy_verification_questions(context)
    report = json.loads((root / "question_investigation_report.json").read_text(encoding="utf-8-sig"))
    original = [item for item in report["questions"] if item["question_id"].startswith(("auto_relation_", "auto_reading_"))]
    events = read_jsonl(root / "event_stream.jsonl")
    starts = {}
    durations = {}
    for row in events:
        fields = row.get("fields", {})
        qid = fields.get("question_id")
        if not qid:
            continue
        if row["event"] == "QUESTION_STARTED":
            starts[qid] = datetime.fromisoformat(row["ts"])
        if row["event"] == "QUESTION_COMPLETED" and qid in starts:
            durations[qid] = (datetime.fromisoformat(row["ts"]) - starts[qid]).total_seconds()
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "run_report": str(root),
        "measurement_scope": "Snapshot of completed provider calls. Request sums are not wall time; reasoning tokens are included in output tokens. No end-to-end speedup measured.",
        "prompts": dict(groups), "observed_question_wall_seconds": durations,
        "original_automatic_questions": original,
        "revised_automatic_questions": [item.model_dump() for item in revised],
        "planner_questions_unchanged": [item for item in report["questions"] if not item["question_id"].startswith("auto_")],
        "source_warnings_retained": {summary.path: summary.warnings for summary in summaries},
        "cache_hit_rate": None if not any(row.get("provider_cache_tokens_known") for row in calls) else "See per-call usage; partial telemetry must not be extrapolated",
        "cache_note": "Absent provider telemetry is unknown, not a zero hit rate",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.report_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {
        "source_warnings_retained", "original_automatic_questions", "planner_questions_unchanged"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

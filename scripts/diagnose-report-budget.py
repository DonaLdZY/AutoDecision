"""Measure a saved report writer request without calling a provider."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.config import load_config
from autoreport.collector import collect_evidence
from autoreport.events import ReportEventWriter
from autoreport.context import estimate_tokens
from autoreport.prompt_context import encode_task_context
from autoreport.generator import _prepare_report_context, _base_system_prompt, _context_input_budget, _writer_stage_instruction
from autoreport import generator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--archived-autorealize", type=Path)
    parser.add_argument("--exercise-writer", action="store_true", help="Replay real saved writer inputs with a local provider stub")
    args = parser.parse_args()
    cfg = load_config(args.report / "resolved_config.yaml")
    if args.archived_autorealize:
        for evidence in cfg.evidence_paths:
            if evidence.kind == "autorealize":
                evidence.path = str(args.archived_autorealize.resolve())
    analysis = json.loads((args.report / "report_analysis.json").read_text(encoding="utf-8"))
    dest = ROOT / "runs/prompt-validation" / f"report-budget-{time.time_ns()}"
    events = ReportEventWriter(dest, print_events_to_console=False)
    bundle = collect_evidence(cfg, events)
    settings = {"context_window_tokens": cfg.llm.context_window_tokens, "max_tokens": cfg.llm.max_tokens,
                "context_headroom_ratio": cfg.llm.context_headroom_ratio}
    _prepare_report_context(cfg, settings, bundle, events, allow_partitions=True)
    prefix = settings["task_context_prefix"]
    system = _base_system_prompt(cfg)
    encoded = encode_task_context(analysis, heading="Report analysis")
    prompt = f'{encoded}\n# Latest stage instruction\n{_writer_stage_instruction(cfg)}'
    notes = analysis.get("complete_source_partition_notes", [])
    facts = {key: value for key, value in analysis.items() if key != "complete_source_partition_notes"}
    result = {"model": cfg.llm.model, "window": cfg.llm.context_window_tokens,
              "output_reserve": cfg.llm.max_tokens, "input_budget": _context_input_budget(settings),
              "system_tokens": estimate_tokens(system), "prefix_tokens": estimate_tokens(prefix),
              "analysis_tokens": estimate_tokens(encoded), "combined_request_tokens": estimate_tokens(system) + estimate_tokens(prefix + prompt),
              "core_analysis_tokens": estimate_tokens(encode_task_context(facts)),
              "note_tokens": [estimate_tokens(encode_task_context(note)) for note in notes],
              "partitions": len(settings.get("task_context_partitions", [])),
              "analysis_keys": list(analysis), "candidates": settings["report_has_executed_candidates"],
              "archived_autorealize": str(args.archived_autorealize or "")}
    if args.exercise_writer:
        settings.update(model=cfg.llm.model, base_url=cfg.llm.base_url, api_key="stub-unused",
                        temperature=0, enable_thinking=None, reasoning_effort=cfg.llm.reasoning_effort,
                        timeout=1, max_retries=1, retry_base_sleep_seconds=0, retry_max_sleep_seconds=0, usage=[])
        article = "\n\n".join("## " + title + "\n\nLocal transport fixture, not a real report."
                              for title in generator._report_section_titles(cfg))
        requests = []

        def stub(_url, payload, **kwargs):
            content = payload["messages"][1]["content"]
            size = generator._report_input_size(cfg, {**settings, "task_context_prefix": ""}, content)
            assert generator._report_input_fits(cfg, {**settings, "task_context_prefix": ""}, content)
            assert payload["max_tokens"] == 32768
            requests.append(size)
            response = json.dumps({"status": "pass", "issues": [], "edits": []}) if "# Draft report" in content else article
            return {"choices": [{"message": {"content": response}}]}

        previous = generator._post_json_with_retry
        generator._post_json_with_retry = stub
        try:
            generator._write_report_article(cfg, settings, analysis, events)
        finally:
            generator._post_json_with_retry = previous
        result["writer_replay"] = {"scope": "Actual saved input, local provider stub, no generated business report",
                                   "requests": requests, "all_requests_fit": True,
                                   "coverage": json.loads((dest / "writer-analysis-coverage.json").read_text(encoding="utf-8"))}
        raw_analyses = list((args.report / "llm-responses").glob("*analyzer*.txt"))
        if raw_analyses:
            raw = raw_analyses[-1].read_text(encoding="utf-8")
            result["malformed_saved_analysis_rejected"] = generator._extract_json_object(raw) is None
    (dest / "measurement.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"measurement": str(dest / "measurement.json"), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

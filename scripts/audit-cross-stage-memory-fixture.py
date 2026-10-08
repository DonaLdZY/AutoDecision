"""Freeze a completed compactor/retriever pair without API or active-run writes."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import MethodType

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))

from autorealize.config import AutoRealizeConfig
from autorealize.context_memory import CrossStageContextLedger
from autorealize.llm.client import LLMClient
from autorealize.models import EvaluationContractReview
from autorealize.prompt_cache import estimate_text_tokens, json_block
from autorealize.prompts.manager import PromptManager


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value):
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CapturedRequest(BaseException):
    pass


class OfflineClient(LLMClient):
    def __init__(self, config):
        self.config = config
        self.base_url = config.llm.base_url
        self.request = None
        self.cache_key = None

    def _cache_get(self, key):
        self.cache_key = key
        return None

    def _chat_completion_with_network_retry(self, *, create_kwargs, **_kwargs):
        self.request = deepcopy(create_kwargs)
        raise CapturedRequest


def capture_request(config, kwargs):
    client = OfflineClient(config)
    try:
        client.ask_structured(**kwargs)
    except CapturedRequest:
        pass
    assert client.request is not None
    assert client.request["max_tokens"] == 32768
    return {"prompt_name": kwargs["prompt_name"], "cache_key": client.cache_key,
            "request": client.request}


class HistoricalResponses:
    def __init__(self, config, traces):
        self.config = config
        self.traces = traces
        self.calls = []

    def ask_structured(self, **kwargs):
        self.calls.append(capture_request(self.config, kwargs))
        return kwargs["model_cls"].model_validate_json(self.traces[kwargs["prompt_name"]]["response"])


def corrected_body_budget(self):
    budget = max(2000, int(self.config.prompt.prompt_token_budget))
    ratio = min(0.9, max(0.4, float(self.config.context.cross_stage_headroom_ratio)))
    configured = self.config.context.cross_stage_memory_trigger_tokens
    limit = max(1000, int(configured)) if configured else max(1000, int(budget * ratio))
    if self.config.context.cross_stage_memory_limit_scope == "total":
        stable_tokens = estimate_text_tokens(self.static_context_prompt)
        return min(max(1000, limit - stable_tokens), max(1000, int(budget * ratio) - stable_tokens))
    return min(limit, max(1000, int(budget * ratio)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--payload-id", required=True)
    args = parser.parse_args()
    source = args.report_dir.resolve()
    output = args.output_dir.resolve()
    assert output != source and source not in output.parents
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "frozen"
    frozen.mkdir()
    artifact_dir = source / "context_artifacts"
    payload_file = artifact_dir / (args.payload_id + ".json")
    payload = read_json(payload_file)["payload"]
    state = read_json(source / "cross_stage_context.json")
    stage = payload["current_stage"]
    stable_id = payload["recovered_artifact_excerpts"][0]["artifact_id"]
    stable_file = artifact_dir / (stable_id + ".json")
    full_stable = read_json(stable_file)["payload"]
    compaction = next(item for item in state["compaction_history"] if item["next_stage"] == stage)
    entry_ids = compaction["compacted_artifact_ids"] + [
        item["artifact_id"] for item in payload["recent_stage_entries"]
    ]
    catalog = {item["artifact_id"]: item for item in state["artifact_catalog"]}
    entry_sources = [read_json(artifact_dir / (item + ".json")) for item in entry_ids]
    raw_config = yaml.safe_load((source / "final_config.yaml").read_text(encoding="utf-8"))
    config = AutoRealizeConfig()
    safe_config = {}
    for group in ("llm", "prompt", "context"):
        safe_config[group] = {key: value for key, value in raw_config[group].items() if key != "api_key"}
        for key, value in safe_config[group].items():
            setattr(getattr(config, group), key, value)
    config.llm.api_key = "offline-never-used"
    traces = {item["prompt_name"]: item for item in map(json.loads,
        (source / "llm_traces.jsonl").read_text(encoding="utf-8").splitlines())}
    support_names = ["cross_stage_context_compactor_1", "cross_stage_context_retriever_" + stage]
    traces = {name: traces[name] for name in support_names}
    usage = [item for item in map(json.loads,
        (source / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines())
        if item.get("prompt_name") in support_names]
    cache_keys = {item["key"] for item in map(json.loads,
        (source / "llm_cache.jsonl").read_text(encoding="utf-8").splitlines())}
    manifest = []
    for path in [payload_file, stable_file, *(artifact_dir / (item + ".json") for item in entry_ids)]:
        raw = path.read_bytes()
        (frozen / path.name).write_bytes(raw)
        manifest.append({"source": str(path), "frozen": path.name, "sha256": digest(raw)})
    write_json(frozen / "config-without-credentials.json", safe_config)
    write_json(frozen / "support-traces.json", traces)
    write_json(frozen / "support-usage.json", usage)
    write_json(frozen / "state-at-freeze.json", state)
    prompt_mgr = PromptManager(config)

    def make_ledger(directory, responses):
        ledger = CrossStageContextLedger(config=config, llm_client=responses,
            prompt_mgr=prompt_mgr, report_dir=directory, stable_context=full_stable)
        for item in entry_sources:
            source_meta = catalog[item["artifact_id"]]
            entry = ledger.add(item["source"], item["payload"], authority=source_meta["authority"],
                evidence_refs=item["payload"].get("evidence", []) if item["source"] == "problem_paradigm" else [])
            assert entry["artifact_id"] == item["artifact_id"]
        assert ledger._memory_tokens() == compaction["before_estimated_tokens"]
        assert digest(ledger.static_context_prompt)[:16] == state["stable_context_digest"]
        return ledger

    with tempfile.TemporaryDirectory(prefix="cross_stage_audit_") as scratch:
        scratch = Path(scratch)
        history = HistoricalResponses(config, traces)
        old = make_ledger(scratch / "old", history)
        before_entries = deepcopy(old.entries)
        old_stable, old_dynamic = old.prompt_parts(stage=stage,
            stage_evidence=payload["current_stage_evidence"], latest_request=payload["latest_request"],
            dynamic_title="Dynamic evaluation review state", dynamic_limit=14000)
        rebuilt = read_json(scratch / "old/context_artifacts" / payload_file.name)["payload"]
        assert rebuilt == payload
        for call in history.calls:
            assert call["cache_key"] in cache_keys, call["prompt_name"]
        no_calls = HistoricalResponses(config, {})
        candidate = make_ledger(scratch / "candidate", no_calls)
        candidate._live_memory_token_budget = MethodType(corrected_body_budget, candidate)
        candidate.prompt_parts(stage=stage, stage_evidence=payload["current_stage_evidence"],
            latest_request=payload["latest_request"], dynamic_title="Dynamic evaluation review state",
            dynamic_limit=14000)
        assert not no_calls.calls
        candidate_artifact = next(item for item in candidate.artifact_catalog
            if item["authority"] == "full_dynamic_prompt_payload")
        candidate_payload = read_json(scratch / "candidate/context_artifacts" /
            (candidate_artifact["artifact_id"] + ".json"))["payload"]
        assert not candidate_payload["recovered_artifact_excerpts"]
        assert candidate.entries == before_entries
        safe_payload = deepcopy(candidate_payload)
        safe_payload["recovered_artifact_excerpts"] = deepcopy(payload["recovered_artifact_excerpts"])
        assert safe_payload["current_stage_evidence"] == payload["current_stage_evidence"]
        assert safe_payload["latest_request"] == payload["latest_request"]
        pack = payload["current_stage_evidence"]["evaluation_evidence_pack"]
        assert entry_sources[0]["payload"] == pack["problem_paradigm"]
        assert full_stable["question_memory"] == pack["qdi_evaluation_output_constraint_conclusions"]
        assert full_stable["verified_relation_cards"][:len(pack["relations"])] == pack["relations"]
        common = {"model_cls": EvaluationContractReview,
                  "system_prompt": prompt_mgr.load("system/evaluation_contract_reviewer.md"),
                  "prompt_name": stage, "static_context_prompt": old_stable}
        requests = []
        for variant, dynamic in [("A_historical", old_dynamic), ("B_frozen_retrieval_plan",
                json_block("Dynamic evaluation review state", safe_payload, sort_keys=False))]:
            captured = capture_request(config, {**common, "user_prompt": dynamic,
                "dynamic_user_prompt": dynamic})
            write_json(output / (variant + "-request.json"), captured)
            requests.append({"variant": variant, "estimated_message_tokens": sum(
                estimate_text_tokens(message["content"]) for message in captured["request"]["messages"]),
                "request_sha256": digest(json.dumps(captured["request"], ensure_ascii=False, sort_keys=True))})
        write_json(output / "A-helper-requests.json", history.calls)
        write_json(output / "B-budget-only-UNSAFE-payload.json", candidate_payload)
        write_json(output / "B-frozen-retrieval-plan-payload.json", safe_payload)
        write_json(output / "A-before-compaction-entries.json", before_entries)
        write_json(output / "bounded-stable-context.json", old.stable_context)
        old_budget = old._live_memory_token_budget()
        new_budget = candidate._live_memory_token_budget()

    recovered_audit = []
    naive_visible = json.dumps({"stable": old.stable_context, "dynamic": candidate_payload}, ensure_ascii=False)
    for item in payload["recovered_artifact_excerpts"]:
        path = item["json_path"]
        values = full_stable
        for key in path.removeprefix("payload.").split("."):
            values = values[key]
        excerpt = item["excerpt"]
        full_records = []
        visible_files = []
        record_offset = 2
        for index, value in enumerate(values):
            indented = "\n".join("  " + line for line in json.dumps(
                value, ensure_ascii=False, sort_keys=True, indent=2).splitlines())
            if indented in excerpt:
                full_records.append({"index": index, "path": value.get("path", "")})
            if path == "payload.deterministic_data_access.files" and record_offset < len(excerpt):
                visible_record = excerpt[record_offset:record_offset + len(indented)]
                visible_files.append({"file": value["path"],
                    "source_path_visible": value["path"] in visible_record,
                    "fields": [field for field in value["important_fields"]
                        if field in visible_record and field not in naive_visible]})
            record_offset += len(indented) + 2
        recovered_audit.append({key: item[key] for key in
            ("json_path", "original_chars", "visible_chars", "has_more")})
        recovered_audit[-1]["complete_records_in_excerpt"] = full_records
        if path == "payload.deterministic_data_access.files":
            recovered_audit[-1]["visible_field_names_missing_without_retrieval"] = visible_files
    result = {
        "stage": stage, "production_modified": False, "api_calls": 0,
        "source_files": manifest, "before_memory_tokens": compaction["before_estimated_tokens"],
        "after_memory_tokens": compaction["after_estimated_tokens"],
        "old_token_budget": old_budget, "proposed_body_token_budget": new_budget,
        "stable_tokens": state["stable_context_estimated_tokens"],
        "helper_input_tokens": sum(item["prompt_tokens"] for item in usage),
        "helper_seconds": round(sum(item["seconds"] for item in usage), 4),
        "cache_hit_rate_known": all(item["provider_cache_tokens_known"] for item in usage),
        "support_cache_keys_match_actual_history": True,
        "historical_payload_reconstructed_exactly": True,
        "naive_budget_fix_disables_all_retrieval": True,
        "qdi_memory_exact_duplicate": True,
        "relations_exact_duplicate_prefix": len(pack["relations"]),
        "compacted_stage_full_payload_already_visible": "evaluation_evidence_pack.problem_paradigm",
        "table_index_sources": [item["table_id"] for item in pack["table_index"]],
        "recovered_audit": recovered_audit, "requests": requests,
        "paired_B_limit": "B reuses A's frozen retrieval plan to isolate compactor removal; validate a new retrieval gate independently before release.",
        "required_followup": [
            "Use body_after_prefix scope consistently in both token and character thresholds.",
            "Allow stage retrieval for omitted stable sections or truncated entries even when compaction_count is zero.",
            "Provide stage evidence coverage to the retriever so it can avoid exact duplicates.",
            "Keep all recovered file-reading evidence until source-aware equality proves it is redundant.",
            "Run frozen A/B with max_tokens=32768 and compare contractual facts and downstream executability.",
        ],
    }
    write_json(output / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

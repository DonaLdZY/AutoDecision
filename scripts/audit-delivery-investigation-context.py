"""Measure current QDI context and reversible encoding candidates without API calls."""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.config import AutoRealizeConfig
from autorealize.context_compiler import ArtifactStore, build_qdi_context_and_details
from autorealize.document_retrieval import LocalDocumentIndex
from autorealize.models import FileSummary
from autorealize.modules.data_cognition import DataCognitionModule
from autorealize.profiling.relations import detect_relations
from autorealize.prompt_cache import _stable_payload, estimate_text_tokens, lossless_json, stable_dynamic_prompt


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    stages = runpy.run_path(str(Path(__file__).with_name("industrial-stage-control.py")))
    task = stages["current_task"]("delivery")
    report = Path(task["run_dir"]) / "autorealize/realize_report"
    cfg = AutoRealizeConfig.from_file(report / "final_config.yaml")
    summaries = [FileSummary.model_validate_json(path.read_text(encoding="utf-8-sig"))
                 for path in sorted((report / "file_cognition").glob("*.json"))]
    authority = read(report / "authoritative_task_memory.json")
    candidates = []
    for line in (report / "llm_cache.jsonl").read_text(encoding="utf-8-sig").splitlines():
        cached = json.loads(line)
        try:
            response = json.loads(cached["response"])
        except (ValueError, TypeError):
            continue
        if isinstance(response, dict) and "items" in response and "entity_alias_candidates" in response:
            candidates.append(response)
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one current constraint extraction, found {len(candidates)}")
    constraints = candidates[0]
    relations = detect_relations({fs.path: fs.columns for fs in summaries if fs.columns}, file_summaries=summaries)
    module = DataCognitionModule(cfg, SimpleNamespace(), report)
    knowledge = module._build_meta_knowledge_base(
        file_summaries=summaries, relation_count=len(relations), constraint_memory=constraints,
        authoritative_memory=authority, directory_tree=(report / "directory_tree.txt").read_text(encoding="utf-8-sig"),
        sampled_patterns=[], filename_sample_groups=[],
    )
    data_root = report.parent / "data"
    with tempfile.TemporaryDirectory(prefix="delivery-qdi-audit-") as tmp:
        store = ArtifactStore(Path(tmp) / "artifacts")
        context, _details = build_qdi_context_and_details(
            cfg=cfg, data_root=data_root, task_hint=task["config"]["auto_realize"]["task_hint"],
            file_summaries=summaries, relation_hints=relations, constraint_memory=constraints,
            authoritative_memory=authority, knowledge_base=knowledge, artifact_store=store,
        )
        index = LocalDocumentIndex.build(data_root=data_root, store_root=Path(tmp) / "documents",
            chunk_chars=cfg.investigation.document_chunk_chars, chunk_overlap_chars=cfg.investigation.document_chunk_overlap_chars)
        context["document_manifest"] = index.manifest_for_prompt()
        context["context_policy"].update(full_document_text_local=True,
            document_retrieval_actions=["search_document", "read_document_chunks"])
        raw = _stable_payload(context)
        variants = {str(minimum): lossless_json(raw, sort_keys=False, canonical_matches=True,
                                               min_shared_chars=minimum) for minimum in (512, 256, 128, 64)}
        result = {
            "scope": "Equivalent QDI reconstruction from saved source profiles and completed constraint response, sorted by path; local-only metadata may differ from the in-flight request",
            "baseline_estimated_tokens": estimate_text_tokens(stable_dynamic_prompt(stable=context)[0]),
            "by_field": sorted([{"field": key, "chars": len(json.dumps(value, ensure_ascii=False)),
                                 "estimated_tokens": estimate_text_tokens(lossless_json(value))}
                                for key, value in context.items()], key=lambda row: -row["estimated_tokens"]),
            "reversible_encoding_candidates": [{"min_shared_chars": int(key), "chars": len(value),
                "estimated_tokens": estimate_text_tokens(value)} for key, value in variants.items()],
            "no_api_calls": True, "applied_to_running_task": False,
        }
        output = stages["batch"].OUT / "optimization-validation/delivery-qdi-context-20260908"
        output.mkdir(exist_ok=True)
        stages["batch"].save(output / "context.json", context)
        stages["batch"].save(output / "result.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Measure and compare lossless encodings of one frozen production QDI context."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.config import AutoRealizeConfig
from autorealize.context_compiler import ArtifactStore
from autorealize.investigation import _build_investigation_context, LocalDocumentIndex
from autorealize.models import FileSummary, QuestionInvestigationPlan
from autorealize.profiling.relations import RelationHint
from autorealize.prompts.manager import PromptManager
from autorealize.prompt_cache import stable_dynamic_prompt, lossless_json, _stable_payload, STABLE_CONTEXT_TITLE, estimate_text_tokens
from autorealize.review_prompt import decode_review_snapshot, encode_review_snapshot


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--call", choices=("old", "new"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = AutoRealizeConfig.from_file(args.report_root / "final_config.yaml")
    snapshot = args.out / "snapshot.json"
    if snapshot.is_file():
        context = read(snapshot)
    else:
        report = read(args.report_root / "data_cognition_report.json")
        data_root = args.report_root.parent
        context, _ = _build_investigation_context(cfg=cfg, data_root=data_root, task_hint=report["task_hint"],
            file_summaries=[FileSummary.model_validate(item) for item in report["files"]],
            relation_hints=[RelationHint(**item) for item in report["relations"]],
            constraint_memory=report["constraint_memory"], authoritative_memory=report["authoritative_memory"],
            knowledge_base=report["knowledge_base"], artifact_store=ArtifactStore(args.report_root / "context_artifacts"))
        index = LocalDocumentIndex.build(data_root=data_root, store_root=args.report_root / "document_store",
            chunk_chars=cfg.investigation.document_chunk_chars, chunk_overlap_chars=cfg.investigation.document_chunk_overlap_chars)
        context["document_manifest"] = index.manifest_for_prompt()
        context["context_policy"]["full_document_text_local"] = True
        context["context_policy"]["document_retrieval_actions"] = ["search_document", "read_document_chunks"]
        snapshot.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    old, dynamic = stable_dynamic_prompt(stable=context, dynamic={
        "instruction": "生成本次问题驱动研究的初始问题队列。只提出真正阻塞任务定义、数据读取、文件关联、输出、评估或硬约束落地的问题；不要在 planner 阶段请求脚本。把 files 中的 CSV、表格型 JSON、Excel sheet 都按 table/file card 理解；file_cognition 只是短导航，权威事实看 authoritative_memory，硬约束和业务规则看 constraint_memory。",
        "max_questions": cfg.investigation.max_questions, "previous_question_records": []},
        dynamic_title="Dynamic initial QDI planning request")
    ordered = _stable_payload(context)
    variants = {"old": old.split("\n", 1)[1],
                "refs160": lossless_json(ordered, sort_keys=False, canonical_matches=True, min_shared_chars=160),
                "refs64": lossless_json(ordered, sort_keys=False, canonical_matches=True, min_shared_chars=64),
                "line_refs": encode_review_snapshot(ordered)}
    stats = {}
    for name, encoded in variants.items():
        assert decode_review_snapshot(encoded) == context, name
        stats[name] = {"chars": len(encoded), "estimated_tokens": estimate_text_tokens(encoded), "exact_roundtrip": True}
    components = sorted([{"key": key, "chars": len(json.dumps(value, ensure_ascii=False)),
                          "estimated_tokens": estimate_text_tokens(json.dumps(value, ensure_ascii=False))}
                         for key, value in context.items()], key=lambda item: -item["chars"])
    selected = min((name for name in variants if name != "old"), key=lambda name: stats[name]["estimated_tokens"])
    result = {"variants": stats, "components": components, "selected": selected,
              "snapshot_scope": "Production context reconstructed from completed cognition; frozen identically for both comparison calls"}
    (args.out / "encoding-measurements.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if args.call:
        spec = importlib.util.spec_from_file_location("review_validation", ROOT / "scripts/validate-review-prompts.py")
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        encoded = variants["old" if args.call == "old" else selected]
        dest = args.out / args.call
        dest.mkdir(exist_ok=True)
        request = {"model_cls": QuestionInvestigationPlan, "system_prompt": PromptManager(cfg).load("system/question_investigator_planner.md"),
                   "user_prompt": dynamic, "prompt_name": "question_investigator_initial_questions",
                   "static_context_prompt": STABLE_CONTEXT_TITLE + "\n" + encoded, "dynamic_user_prompt": dynamic}
        print(json.dumps(harness.run_call(request, dest, args.report_root / "final_config.yaml"), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

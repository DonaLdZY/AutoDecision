"""Compile a reviewed cognition repair through the real task-definition module in isolation."""
import argparse
import hashlib
import importlib.util
import logging
from pathlib import Path
import shutil
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
spec = importlib.util.spec_from_file_location("industrial_repair", Path(__file__).with_name("repair-industrial-task-definition.py"))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
stages = repair.stages


def remove_generated_input_artifacts(data_root: Path, input_root: Path) -> list[str]:
    removed: list[str] = []
    for name in ("sample_submission.csv", "submission.csv"):
        copied = data_root / name
        if copied.is_file() and not (input_root / name).is_file():
            copied.unlink()
            removed.append(name)
    return removed


def load_completed_cognition(source, input_root, task_hint):
    raw = stages.read_json(source / "realize_report/data_cognition_report.json", {})
    summary = raw.get("summary", {})
    if (raw.get("task_hint") != task_hint or not raw.get("files")
            or summary.get("file_count") != len(raw["files"])
            or summary.get("relation_count") != len(raw.get("relations", []))):
        raise RuntimeError("A complete cognition checkpoint with the unchanged task hint is required")
    data_root = source / "data" if (source / "data").is_dir() else source
    hashes = {}
    for path in sorted(input_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(input_root)
        copied = data_root / relative
        if not copied.is_file() or not copied.resolve().is_relative_to(data_root.resolve()):
            raise RuntimeError(f"Original input is absent from cognition workspace: {relative}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        with copied.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise RuntimeError(f"Original input changed since cognition: {relative}")
        hashes[relative.as_posix()] = digest
    if not hashes:
        raise RuntimeError("No original inputs available for cognition reuse")
    for file in raw["files"]:
        path = data_root / file["path"]
        if not path.is_file() or not path.resolve().is_relative_to(data_root.resolve()):
            raise RuntimeError(f"Cognition references missing or external data: {file['path']}")
    return raw, data_root, hashes


def main():
    from autorealize.config import AutoRealizeConfig
    from autorealize.llm.client import LLMClient
    from autorealize.models import FileSummary
    from autorealize.modules.data_cognition import DataCognitionModule
    from autorealize.modules.task_definition import TaskDefinitionModule
    from autorealize.modules.types import DataCognitionResult, RuntimeServices
    from autorealize.profiling.relations import RelationHint
    from autorealize.prompts.manager import PromptManager
    from autorealize.report_writer import write_data_description, append_constraint_memory_section
    from autorealize.trajectory import TrajectoryLogger

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--provenance-result", type=Path)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--resume-failed-definition", action="store_true")
    parser.add_argument("--recovery-context-file", type=Path)
    parser.add_argument("--verify-excel-readers", action="store_true")
    args = parser.parse_args()
    with stages.admission_lock():
        task = stages.current_task(args.slug)
        expected_phases = (
            {"autorealize_failed", "stopped", "prepare_automl_input_failed"}
            if args.resume_failed_definition
            else {"autorealize_completed"}
        )
        if task["status"] == "running" or task["phase"] not in expected_phases:
            raise RuntimeError("Wait for the original AutoRealize stage to finish")
        source = Path(task["run_dir"]) / "autorealize"
        recovery_context = repair.load_recovery_context(args.recovery_context_file, task) if args.recovery_context_file else None
        manifest = stages.read_json(stages.batch.OUT / "manifest.json")
        input_root = Path(next(item for item in manifest["tasks"] if item["slug"] == args.slug)["payload"]["input_root"])
        source_hashes = None
        if args.resume_failed_definition:
            raw, saved_data_root, source_hashes = load_completed_cognition(source, input_root, task["config"]["auto_realize"]["task_hint"])
        else:
            if not args.provenance_result or not args.review_file:
                parser.error("Provide provenance and review files, or --resume-failed-definition")
            prior = stages.read_json(args.provenance_result)
            review = stages.read_json(args.review_file)
            directory = args.provenance_result.parent
            if not prior.get("completed") or review.get("passed") is not True or Path(prior["source"]).resolve() != source.resolve():
                raise RuntimeError("A completed source-matched provenance repair and independent passed review are required")
            if stages.read_json(source / "realize_report/data_cognition_report.json") != stages.read_json(directory / "old-cognition.json"):
                raise RuntimeError("Original cognition changed during provenance review")
            expected = stages.fingerprint([directory / "refreshed-cognition.json", directory / "original-document.json"])
            if review.get("artifact_fingerprint") != expected:
                raise RuntimeError("Provenance artifacts changed after review")
            raw = stages.read_json(directory / "refreshed-cognition.json")
        dest = stages.batch.OUT / "stage-repairs" / f"{args.slug}-{time.time_ns()}"
        candidate = dest / "autorealize"
        report_dir = candidate / "realize_report"
        report_dir.mkdir(parents=True)
        logging.basicConfig(filename=dest / "repair.log", level=logging.INFO, encoding="utf-8")
        shutil.copytree(saved_data_root if args.resume_failed_definition else input_root, candidate / "data")
        if args.resume_failed_definition:
            shutil.copytree(source / "realize_report", report_dir, dirs_exist_ok=True)
        data_root = candidate / "data"
        removed_generated_inputs = remove_generated_input_artifacts(data_root, input_root)
        if removed_generated_inputs:
            stages.batch.save(dest / "removed-generated-inputs.json", removed_generated_inputs)
        if recovery_context:
            repair.install_recovery_fixtures(recovery_context, data_root)
        # Do not feed a previous generated task description back as original authority.
        generated = data_root / "description.md"
        if generated.is_file() and (source / "description.md").is_file() and generated.read_bytes() == (source / "description.md").read_bytes():
            generated.unlink()
        cfg = AutoRealizeConfig.from_file(source / "realize_report/final_config.yaml")
        settings = yaml.safe_load((stages.batch.OUT / "settings.yaml").read_text(encoding="utf-8-sig"))
        model = next(item for item in settings["llm"]["modelLibrary"] if item["id"] == settings["llm"]["roleModels"]["autoRealize"])
        stages.validate_provider(settings)
        cfg.llm.api_key, cfg.llm.base_url, cfg.llm.model_name = model["apiKey"], model["baseUrl"], model["model"]
        configured_effort = str(model.get("reasoningEffort") or "").strip()
        cfg.llm.reasoning_effort = None if configured_effort.lower() in {"", "default"} else configured_effort
        cfg.llm.request_timeout_seconds = 900
        cfg.llm.minimum_output_tokens = cfg.llm.max_tokens = cfg.llm.structured_max_tokens = 32768
        cfg.prompt.lossless_review_prompts = True
        cfg.prompt.artifact_consistency_max_rounds = 3
        cfg.prompt.artifact_consistency_fail_on_blocking = True
        cfg.data.auto_generate_predict_split = False
        cfg.write_yaml(report_dir / "final_config.yaml")
        client = LLMClient(cfg, report_dir)
        services = RuntimeServices(client, PromptManager(cfg), None, TrajectoryLogger(report_dir))
        cognition_module = DataCognitionModule(cfg, services, report_dir)
        files = [FileSummary.model_validate(item) for item in raw["files"]]
        if args.verify_excel_readers:
            reader_spec = importlib.util.spec_from_file_location(
                "verified_excel_readers", Path(__file__).with_name("verify-delivery-read-contracts.py"),
            )
            reader_module = importlib.util.module_from_spec(reader_spec)
            reader_spec.loader.exec_module(reader_module)
            checks = reader_module.verify_profile_readers(files, input_root)
            stages.batch.save(dest / "verified-excel-readers.json", checks)
            raw["files"] = [file.model_dump() for file in files]
        relations = [RelationHint(**item) for item in raw["relations"]]
        knowledge = cognition_module._build_meta_knowledge_base(
            file_summaries=files, relation_count=len(relations), constraint_memory=raw["constraint_memory"],
            authoritative_memory=raw["authoritative_memory"], directory_tree=raw["directory_tree"],
            sampled_patterns=raw["sampled_filename_patterns"], filename_sample_groups=raw["filename_sample_groups"],
        )
        knowledge["question_investigation"] = raw["question_investigation"]
        pack = cognition_module._build_agent_context_pack(task_hint=raw["task_hint"], file_summaries=files,
            relation_hints=relations, constraint_memory=raw["constraint_memory"], authoritative_memory=raw["authoritative_memory"],
            knowledge_base=knowledge, sampled_patterns=raw["sampled_filename_patterns"],
            filename_sample_groups=raw["filename_sample_groups"], question_memory=raw["question_investigation"])
        if args.resume_failed_definition:
            knowledge, pack = raw["knowledge_base"], raw["agent_context_pack"]
        raw.update(knowledge_base=knowledge, agent_context_pack=pack)
        for name, value in (("data_cognition_report.json", raw), ("constraint_memory.json", raw["constraint_memory"]),
                            ("authoritative_task_memory.json", raw["authoritative_memory"]), ("agent_context_pack.json", pack)):
            stages.batch.save(report_dir / name, value)
        description = report_dir / "data_description.md"
        write_data_description(description, files, [], relations)
        append_constraint_memory_section(description, raw["constraint_memory"])
        original_texts = [cognition_module._read_authoritative_text(data_root / file.path) for file in files
                          if file.role.value == "task_requirement"]
        if recovery_context:
            import json
            original_texts.append("Preserved session requirements and independently verified recovery evidence:\n"
                                  + json.dumps(recovery_context, ensure_ascii=False, indent=2))
            stages.batch.save(report_dir / "supplemental-recovery-context.json", recovery_context)
        cognition = DataCognitionResult(file_summaries=files, original_requirement_texts=original_texts,
            table_columns={file.path: file.columns for file in files if file.columns}, relation_hints=relations,
            constraint_memory=raw["constraint_memory"], authoritative_memory=raw["authoritative_memory"],
            question_memory=raw["question_investigation"], knowledge_base=knowledge, agent_context_pack=pack,
            data_description_path=description)
        result = {"slug": args.slug, "source": str(source), "candidate": str(candidate),
                  "source_fingerprint": stages.fingerprint(stages.task_definition_source_artifacts(task)),
                  "passed": False, "started_at": time.time(), "original_input_hashes": source_hashes,
                  "task_hint_at_repair": task["config"]["auto_realize"]["task_hint"],
                  "scope": "Real task-definition recompilation from preserved cognition; original data probes retained"}
        stages.batch.save(dest / "result.json", result)
        print(str(dest), flush=True)
        try:
            output = TaskDefinitionModule(cfg, services, candidate, report_dir).run(data_root, raw["task_hint"], cognition)
            audit = stages.read_json(report_dir / "artifact_consistency_report.json")["final"]
            result.update(audit=audit, defects=output.defects)
            stages.verify_task_definition({"run_dir": str(dest)})
            result["passed"] = True
        except Exception as exc:
            logging.exception("Task definition recompilation failed")
            result.update(error_type=type(exc).__name__, error=str(exc).replace(model["apiKey"], "[REDACTED]"))
        finally:
            client.client.close()
        result["finished_at"] = time.time()
        if (candidate / "description.md").is_file():
            result["candidate_fingerprint"] = stages.fingerprint(stages.stage_artifacts({"run_dir": str(dest)}, "autorealize"))
        stages.batch.save(dest / "result.json", result)
        print(str(dest / "result.json"), flush=True)


if __name__ == "__main__":
    main()

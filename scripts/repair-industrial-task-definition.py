"""Repair a completed task definition with production compilers and preserved evidence."""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
SPEC = importlib.util.spec_from_file_location("industrial_stages", Path(__file__).with_name("industrial-stage-control.py"))
stages = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stages)


def load_recovery_context(path, task):
    import hashlib

    value = stages.read_json(path)
    if (not isinstance(value, dict) or value.get("schema") != "industrial.recovery_context.v1"
            or value.get("task_id") != task["id"]
            or value.get("task_hint") != task["config"]["auto_realize"]["task_hint"]):
        raise RuntimeError("Recovery context does not match the current task and unchanged user requirements")
    if not value.get("retained_user_requirements") or not value.get("evidence_files"):
        raise RuntimeError("Recovery context requires retained requirements and verifiable evidence")
    for name, expected in value["evidence_files"].items():
        with Path(name).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"Recovery evidence changed: {name}")
    return value


def install_recovery_fixtures(context, data_root):
    import hashlib

    validation = context.get("implementation_validation", {})
    fixture_dir = validation.get("fixture_source_directory")
    if not fixture_dir:
        return []
    target = data_root / "internal_validation/synthetic_delivery"
    if not target.resolve().is_relative_to(data_root.resolve()):
        raise RuntimeError("Validation fixture destination leaves task data root")
    checked = []
    for item in validation["fixture_manifest"]:
        if Path(item["name"]).name != item["name"] or not item["name"].endswith(".json"):
            raise RuntimeError("Validation fixture name must be a local JSON basename")
        source = Path(fixture_dir) / item["name"]
        destination = target / item["name"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Synthetic fixture changed after recovery review")
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Refusing to replace different existing task input with synthetic fixture")
        checked.append((source, destination))
    target.mkdir(parents=True, exist_ok=True)
    for source, destination in checked:
        shutil.copy2(source, destination)
    return [str(destination) for _, destination in checked]


def reapply_last_patch(module, desc, report_dir):
    report = stages.read_json(report_dir / "artifact_consistency_report.json", {})
    for entry in reversed(report.get("rounds", [])):
        patch = entry.get("patch", {})
        if not patch.get("revised_sections"):
            continue
        if (entry.get("patch_missing_file_references") or entry.get("candidate_new_deterministic_defects")
                or entry.get("patch_rejected") not in {None, "no_effective_section_change"}):
            raise RuntimeError("The last patch failed safety checks and cannot be replayed")
        candidate = desc
        for section, markdown in patch["revised_sections"].items():
            candidate = module._replace_h2_section(candidate, section, markdown)
        if candidate == desc:
            raise RuntimeError("The last provider patch makes no section change")
        return candidate, {"source_round": entry["round"], "patch": patch}
    raise RuntimeError("No previous provider section patch is available")


def restore_sample_sources(report_dir, sample):
    """Recover the saved provider source mapping before alias normalization."""
    import hashlib
    rows = [json.loads(line) for line in (report_dir / "llm_cache.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    matches = []
    for row in rows:
        try:
            value = json.loads(row["response"])
        except (ValueError, KeyError, TypeError):
            continue
        candidate = value.get("sample_submission_spec", {}) if isinstance(value, dict) else {}
        if (candidate.get("columns") == sample.columns and candidate.get("source") == sample.source
                and set(candidate.get("source_fields", {})) == set(sample.source_fields)):
            matches.append((row, candidate))
    if len(matches) != 1:
        raise RuntimeError("Sample restoration requires one unambiguous original provider mapping")
    row, candidate = matches[0]
    previous = dict(sample.source_fields)
    sample.source_fields = dict(candidate["source_fields"])
    return {"cache_key": row["key"], "response_sha256": hashlib.sha256(row["response"].encode("utf-8")).hexdigest(),
            "before": previous, "restored": sample.source_fields, "scope": "Source mappings only; no new provider response"}


def load_reviewed_evaluation(contract_file, review_file, cognition, original_text):
    import hashlib
    from autorealize.models import EvaluationContractReview
    from autorealize.report_writer import evaluation_contract_defects

    review = stages.read_json(review_file, {})
    evidence_path = review_file.parent / "frozen-evidence.json"
    for path, key in ((contract_file, "accepted_contract_sha256"), (evidence_path, "frozen_evidence_sha256")):
        if review.get("passed") is not True or hashlib.sha256(path.read_bytes()).hexdigest() != review.get(key):
            raise RuntimeError("Reviewed evaluator or its frozen evidence changed after acceptance")
    frozen = stages.read_json(evidence_path)
    for key in ("task_hint", "authoritative_memory", "constraint_memory", "files", "relations", "question_investigation"):
        if frozen.get(key) != cognition.get(key):
            raise RuntimeError(f"Reviewed evaluator evidence no longer matches cognition: {key}")
    if frozen.get("original_requirements_full") != original_text:
        raise RuntimeError("Reviewed evaluator original requirements changed")
    contract = EvaluationContractReview.model_validate(stages.read_json(contract_file))
    if not contract.passed or not contract.executable or evaluation_contract_defects(contract):
        raise RuntimeError("Reviewed evaluator failed executable structural validation")
    return contract


def prepare_repair(slug, feedback_file=None, *, audit_only_from=None, reapply_patch=False, repair_questions=False,
                   restore_sample=False, description_review_file=None, reuse_compiled_from=None, question_review_file=None,
                   derived_review_file=None, reviewed_evaluation_file=None, evaluation_review_file=None,
                   verify_excel_readers=False, section_fact_review_file=None, recovery_context_file=None):
    from autorealize import pipeline as legacy
    from autorealize.config import AutoRealizeConfig
    from autorealize.context_compiler import build_source_coverage_ledger
    from autorealize.llm.client import LLMClient
    from autorealize.models import ArtifactConsistencyReview, DescriptionProtocolBundle, EvaluationContractReview, FileSummary, ProblemParadigmReview, SampleSubmissionSpec
    from autorealize.modules.task_definition import TaskDefinitionModule
    from autorealize.modules.types import RuntimeServices
    from autorealize.prompts.manager import PromptManager
    from autorealize.profiling.relations import RelationHint
    from autorealize.report_writer import build_data_access_protocol
    from autorealize.trajectory import TrajectoryLogger
    import yaml

    task = stages.current_task(slug)
    if task["status"] == "running" or task["phase"] not in {
        "autorealize_completed", "autorealize_failed", "stopped", "prepare_automl_input_failed",
    }:
        raise RuntimeError("Wait for the real AutoRealize stage to finish before repair")
    previous = stages.read_json(audit_only_from) if audit_only_from else None
    feedback = (stages.read_json(feedback_file) if feedback_file else
                ["Re-audit preserved repaired artifacts after deterministic provenance corrections."] if previous else None)
    if not isinstance(feedback, list) or not feedback or not all(isinstance(item, str) for item in feedback):
        raise ValueError("Feedback must be a nonempty JSON list of specific evidence-backed defects")
    source = Path(task["run_dir"]) / "autorealize"
    recovery_context = load_recovery_context(recovery_context_file, task) if recovery_context_file else None
    copy_source = source
    if previous:
        copy_source = Path(previous["candidate"])
        if (previous.get("slug") != slug or not previous.get("finished_at")
                or not copy_source.resolve().is_relative_to((stages.batch.OUT / "stage-repairs").resolve())):
            raise RuntimeError("Resume requires a finished candidate from this task")
        if stages.fingerprint(stages.task_definition_source_artifacts(task)) != previous["source_fingerprint"]:
            raise RuntimeError("Source changed since the previous repair")
        if stages.fingerprint(stages.stage_artifacts({"run_dir": str(copy_source.parent)}, "autorealize")) != previous.get("candidate_fingerprint"):
            raise RuntimeError("Previous candidate changed after its audit")
    dest = stages.batch.OUT / "stage-repairs" / f"{slug}-{time.time_ns()}"
    candidate = dest / "autorealize"
    candidate.mkdir(parents=True)
    report_dir = candidate / "realize_report"
    source_fingerprint = stages.fingerprint(stages.task_definition_source_artifacts(task))
    reused_contract = None
    if reuse_compiled_from:
        failed = stages.read_json(reuse_compiled_from)
        failed_candidate = Path(failed["candidate"]).resolve()
        if (failed.get("slug") != slug or failed.get("source_fingerprint") != source_fingerprint
                or not failed.get("error", "").startswith("Evaluation repair rejected:")
                or not failed_candidate.is_relative_to((stages.batch.OUT / "stage-repairs").resolve())):
            raise RuntimeError("Compiled output reuse requires the unchanged source of a rejected evaluator repair")
        caches = sorted((failed_candidate / "realize_report/repair_usage").rglob("llm_cache.jsonl"))
        if len(caches) != 1:
            raise RuntimeError("Expected exactly one recorded evaluation repair session")
        cache_rows = [json.loads(line) for line in caches[0].read_text(encoding="utf-8").splitlines() if line.strip()]
        reused_contract = EvaluationContractReview.model_validate_json(cache_rows[-1]["response"])
    shutil.copytree(copy_source / "realize_report", report_dir)
    for name in ("description.md", "sample_submission.csv"):
        if (copy_source / name).exists():
            shutil.copy2(copy_source / name, candidate / name)
    stages.batch.save(dest / "feedback.json", feedback)
    logging.basicConfig(filename=dest / "repair.log", level=logging.INFO, encoding="utf-8")
    config = AutoRealizeConfig.from_file(report_dir / "final_config.yaml")
    settings = yaml.safe_load((stages.batch.OUT / "settings.yaml").read_text(encoding="utf-8-sig"))
    role_id = settings["llm"]["roleModels"]["autoRealize"]
    entry = next(item for item in settings["llm"]["modelLibrary"] if item["id"] == role_id)
    config.llm.api_key = entry["apiKey"]
    config.llm.base_url = entry["baseUrl"]
    config.llm.model_name = entry["model"]
    configured_effort = str(entry.get("reasoningEffort") or "").strip()
    config.llm.reasoning_effort = None if configured_effort.lower() in {"", "default"} else configured_effort
    config.llm.max_tokens = config.llm.structured_max_tokens = config.llm.minimum_output_tokens = 32768
    config.prompt.lossless_review_prompts = True
    config.llm.max_retries = 1
    config.llm.request_timeout_seconds = 900
    config.prompt.artifact_consistency_max_rounds = 3
    config.prompt.artifact_consistency_fail_on_blocking = True
    os.environ["AUTOREALIZE_PROMPT_CACHE_KEY_MODE"] = "enabled"
    client = LLMClient(config, report_dir / "repair_usage" / str(time.time_ns()))
    services = RuntimeServices(client, PromptManager(config), None, TrajectoryLogger(report_dir))
    module = TaskDefinitionModule(config, services, candidate, report_dir)
    data_root = source / "data" if (source / "data").is_dir() else source
    module._current_data_root = data_root
    payload = stages.read_json(report_dir / "task_definition_report.json")
    cognition = stages.read_json(report_dir / "data_cognition_report.json")
    context = payload["downstream_context"]
    prior_review = context.pop("artifact_consistency_review", None)
    if prior_review:
        stages.batch.save(dest / "prior-artifact-review.json", prior_review)
    context.pop("defects_after_gate", None)
    files = [FileSummary.model_validate(item) for item in cognition["files"]]
    if verify_excel_readers:
        reader_spec = importlib.util.spec_from_file_location("verified_excel_readers", Path(__file__).with_name("verify-delivery-read-contracts.py"))
        reader_module = importlib.util.module_from_spec(reader_spec)
        reader_spec.loader.exec_module(reader_module)
        input_root = Path(next(row for row in stages.read_json(stages.batch.OUT / "manifest.json")["tasks"]
                               if row["slug"] == slug)["payload"]["input_root"])
        checks = reader_module.verify_profile_readers(files, input_root)
        stages.batch.save(dest / "verified-excel-readers.json", checks)
        cognition["files"] = [fs.model_dump() for fs in files]
        stages.batch.save(report_dir / "data_cognition_report.json", cognition)
    relations = [RelationHint(**item) for item in cognition["relations"]]
    original_text = (report_dir / "original_requirements.txt").read_text(encoding="utf-8")
    if recovery_context:
        original_text += "\n\n## Preserved session requirements and independently verified recovery evidence\n"
        original_text += json.dumps(recovery_context, ensure_ascii=False, indent=2)
        (report_dir / "original_requirements.txt").write_text(original_text, encoding="utf-8")
        stages.batch.save(report_dir / "supplemental-recovery-context.json", recovery_context)
        context["supplemental_recovery_context"] = recovery_context
    reviewed_evaluation = None
    if reviewed_evaluation_file:
        if not previous or not evaluation_review_file:
            raise RuntimeError("Reviewed evaluator reuse requires a finished candidate and its independent review")
        reviewed_evaluation = load_reviewed_evaluation(reviewed_evaluation_file, evaluation_review_file, cognition, original_text)
    problem = ProblemParadigmReview.model_validate(payload["problem_paradigm"])
    bundle = DescriptionProtocolBundle.model_validate(payload["description_protocol_bundle"])
    bundle.data_access = build_data_access_protocol(files)
    context["data_access_protocol"] = bundle.data_access.model_dump()
    module._write_protocol_artifacts(problem_review=problem, deterministic_data_access=bundle.data_access, protocol_bundle=bundle)
    contract = EvaluationContractReview.model_validate(payload["evaluation_contract"])
    sample = SampleSubmissionSpec.model_validate(context["sample_submission_spec"])
    if restore_sample:
        stages.batch.save(dest / "restored-provider-sample.json", restore_sample_sources(report_dir, sample))
    pack = payload["automl_context_pack"]
    protocol = payload["main_task_protocol"]
    previous_report = stages.read_json(report_dir / "evaluation_contract_report.json")
    module._evaluation_contract_revision_log = previous_report["revision_log"]
    module._evaluation_reflection_log = previous_report.get("reflection_log", [])
    module._initialize_cross_stage_context(
        task_hint=payload["task_hint"], original_text=original_text, downstream_context=context,
        file_summaries=files, relations=relations, deterministic_data_access=context["data_access_protocol"],
    )
    repair_context = {"original_text": original_text, "file_summaries": files, "relations": relations}
    result = {"slug": slug, "source": str(source), "candidate": str(candidate),
              "source_fingerprint": source_fingerprint, "passed": False, "started_at": time.time(),
              "audit_only_from": str(audit_only_from) if audit_only_from else None,
              "reused_compiled_from": str(reuse_compiled_from) if reuse_compiled_from else None,
              "task_hint_at_repair": task["config"]["auto_realize"]["task_hint"],
              "scope": "Real production contract repair and final artifact audit, reusing completed data cognition"}
    stages.batch.save(dest / "result.json", result)
    try:
        desc = (candidate / "description.md").read_text(encoding="utf-8")
        if reapply_patch:
            if not previous:
                raise RuntimeError("Patch replay requires a finished audit-only source")
            desc, replay = reapply_last_patch(module, desc, report_dir)
            stages.batch.save(dest / "replayed-provider-patch.json", replay)
        desc = module.refresh_output_source_diagnostics(
            desc=desc, sample_spec=sample,
            protocol_bundle=bundle, problem_review=problem, downstream_context=context, file_summaries=files,
        )
        if description_review_file:
            review = ArtifactConsistencyReview.model_validate(stages.read_json(description_review_file))
            if not review.issues or any(issue.repair_target != "description_section" for issue in review.issues):
                raise RuntimeError("Description feedback must identify bounded prose sections, not machine rule changes")
            patch = module._build_artifact_consistency_patch(desc=desc, review=review, round_idx=0)
            allowed_sections = {issue.section for issue in review.issues}
            if not patch.revised_sections or not set(patch.revised_sections).issubset(allowed_sections):
                raise RuntimeError("Independent-feedback patch changed an unrequested section")
            for title, markdown in patch.revised_sections.items():
                desc = module._replace_h2_section(desc, title, markdown)
            if legacy._find_missing_file_references(desc, source):
                raise RuntimeError("Independent-feedback patch references missing input files")
            stages.batch.save(dest / "independent-description-review.json", review.model_dump())
            stages.batch.save(dest / "independent-description-patch.json", patch.model_dump())
        module._sync_final_description_sections(desc, context)
        if reviewed_evaluation is not None:
            desc = module._synchronize_final_evaluation_contract(
                desc=desc, repaired=reviewed_evaluation, evaluation_contract=contract,
                problem_review=problem, protocol_bundle=bundle, downstream_context=context,
                automl_context_pack=pack, main_task_protocol=protocol, repair_context=repair_context,
            )
            stages.batch.save(dest / "reused-reviewed-evaluation.json", reviewed_evaluation.model_dump())
        elif previous and not feedback_file:
            pack = module._write_automl_context_pack(protocol_bundle=bundle, file_summaries=files,
                downstream_context=context, evaluation_contract=contract, relations=relations)
            protocol = module._write_main_task_protocol(task_hint=payload["task_hint"], problem_review=problem,
                protocol_bundle=bundle, deterministic_data_access=context["data_access_protocol"],
                evaluation_contract=contract, automl_context_pack=pack, downstream_context=context)
        elif reused_contract is not None:
            desc = module._synchronize_final_evaluation_contract(
                desc=desc, repaired=reused_contract, evaluation_contract=contract,
                problem_review=problem, protocol_bundle=bundle, downstream_context=context,
                automl_context_pack=pack, main_task_protocol=protocol, repair_context=repair_context,
            )
            stages.batch.save(dest / "reused-provider-evaluation.json", reused_contract.model_dump())
        else:
            desc = module._repair_final_evaluation_contract(
                desc=desc, feedback=feedback,
                evaluation_contract=contract, problem_review=problem, protocol_bundle=bundle,
                downstream_context=context, automl_context_pack=pack, main_task_protocol=protocol,
                repair_context=repair_context,
            )
        if section_fact_review_file:
            if not previous:
                raise RuntimeError("Section fact repair requires a finished audited candidate")
            fact_review = ArtifactConsistencyReview.model_validate(stages.read_json(section_fact_review_file))
            from autorealize.artifact_contract_repair import section_fact_fields
            if not fact_review.issues or any(not section_fact_fields(context.get("description_sections", {}), [issue])
                                             for issue in fact_review.issues):
                raise RuntimeError("Section fact repair may only target audited facts_used entries")
            module._repair_final_section_facts(issues=fact_review.issues, downstream_context=context,
                evaluation_contract=contract, repair_context=repair_context)
            protocol["frozen_description_sections"] = context["description_sections"]
            pack = module._write_automl_context_pack(protocol_bundle=bundle, file_summaries=files,
                downstream_context=context, evaluation_contract=contract, relations=relations)
        if derived_review_file:
            if not previous:
                raise RuntimeError("Derived repair requires a finished audited candidate")
            derived_review = ArtifactConsistencyReview.model_validate(stages.read_json(derived_review_file))
            if not derived_review.issues or any(issue.repair_target != "machine_contract" or not
                issue.section.startswith(("description_protocol_bundle", "sample_submission_spec"))
                for issue in derived_review.issues):
                raise RuntimeError("Independent derived feedback may only target bounded derived contracts")
            module._repair_final_derived_contracts(
                review=derived_review, evaluation_contract=contract, problem_review=problem, protocol_bundle=bundle,
                sample_spec=sample, downstream_context=context, automl_context_pack=pack, main_task_protocol=protocol,
                repair_context=repair_context,
            )
        if repair_questions or question_review_file:
            if not previous:
                raise RuntimeError("Question repair requires a finished audited candidate")
            question_review = ArtifactConsistencyReview.model_validate(
                stages.read_json(question_review_file) if question_review_file else previous["audit"])
            if question_review_file and (not question_review.issues or any(
                issue.repair_target != "machine_contract" or issue.section not in {"open_questions", "execution_contract.open_questions"}
                for issue in question_review.issues)):
                raise RuntimeError("Independent question review may only target current open-question state")
            module._repair_final_open_questions(
                review=question_review,
                evaluation_contract=contract, problem_review=problem, protocol_bundle=bundle,
                downstream_context=context, automl_context_pack=pack, main_task_protocol=protocol,
                repair_context=repair_context,
            )
        ledger = build_source_coverage_ledger(file_summaries=files)
        defects = module._artifact_sanity_check(
            desc=desc, data_root=data_root, legacy=legacy, sample_spec=sample,
            evaluation_contract=contract, source_coverage_ledger=ledger,
        )
        desc, audit, defects = module._audit_and_repair_final_artifacts(
            desc=desc, data_root=data_root, legacy=legacy, problem_review=problem, protocol_bundle=bundle,
            evaluation_contract=contract, sample_spec=sample,
            submission_report=stages.read_json(report_dir / "submission_report.json"),
            automl_context_pack=pack, main_task_protocol=protocol, downstream_context=context,
            deterministic_defects=defects, source_coverage_ledger=ledger,
            evaluation_repair_context=repair_context,
        )
        context["artifact_consistency_review"] = audit.model_dump()
        context["defects_after_gate"] = list(defects)
        module._sync_final_description_sections(desc, context)
        pack = module._write_automl_context_pack(
            protocol_bundle=bundle, file_summaries=files, downstream_context=context,
            evaluation_contract=contract, relations=relations,
        )
        protocol = module._write_main_task_protocol(
            task_hint=payload["task_hint"], problem_review=problem, protocol_bundle=bundle,
            deterministic_data_access=context["data_access_protocol"], evaluation_contract=contract,
            automl_context_pack=pack, downstream_context=context,
        )
        payload.update(evaluation_contract=contract.model_dump(), automl_context_pack=pack,
                       main_task_protocol=protocol, downstream_context=context, defects_after_gate=defects,
                       description_protocol_bundle=bundle.model_dump(), problem_paradigm=problem.model_dump())
        payload["task_classification"].update(primary_metric=contract.primary_metric, metric_formula=contract.metric_formula)
        payload["plan"].update(evaluation_metric=contract.primary_metric, evaluation_formula=contract.metric_formula)
        stages.batch.save(report_dir / "task_definition_report.json", payload)
        (candidate / "description.md").write_text(desc, encoding="utf-8")
        result.update(passed=audit.passed and not defects and not any(issue.severity == "blocking" for issue in audit.issues),
                      defects=defects, audit=audit.model_dump(), finished_at=time.time())
        result["candidate_fingerprint"] = stages.fingerprint(stages.stage_artifacts({"run_dir": str(dest)}, "autorealize"))
    except Exception as exc:
        result.update(error=str(exc).replace(entry["apiKey"], "[REDACTED]"), finished_at=time.time())
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "passed": result["passed"]}, ensure_ascii=False), flush=True)
    if not result["passed"]:
        raise RuntimeError("Candidate repair requires further review; original artifacts are unchanged")


def apply_repair(result_file):
    from autorealize.report_writer import render_automl_context_markdown

    result = stages.read_json(result_file)
    if result.get("passed") is not True:
        raise RuntimeError("Only a successfully audited repair can be applied")
    task = stages.current_task(result["slug"])
    if ("task_hint_at_repair" in result
            and task["config"]["auto_realize"]["task_hint"] != result["task_hint_at_repair"]):
        raise RuntimeError("User requirements changed after the repair started")
    if task["status"] == "running" or task["phase"] not in {
        "autorealize_completed", "autorealize_failed", "stopped", "prepare_automl_input_failed",
    }:
        raise RuntimeError("The source stage is no longer available for repair")
    source = (Path(task["run_dir"]) / "autorealize").resolve()
    candidate = Path(result["candidate"]).resolve()
    if (source != Path(result["source"]).resolve() or not source.is_relative_to(stages.batch.OUT.resolve())
            or not candidate.is_relative_to((stages.batch.OUT / "stage-repairs").resolve())):
        raise RuntimeError("Repair paths do not belong to this batch")
    if stages.fingerprint(stages.task_definition_source_artifacts(task)) != result["source_fingerprint"]:
        raise RuntimeError("Source artifacts changed during repair; review the newer source")
    if stages.fingerprint(stages.stage_artifacts({"run_dir": str(candidate.parent)}, "autorealize")) != result["candidate_fingerprint"]:
        raise RuntimeError("Candidate artifacts changed after their audit")
    report = stages.read_json(candidate / "realize_report/task_definition_report.json")
    audit = stages.read_json(candidate / "realize_report/artifact_consistency_report.json")["final"]
    if report["defects_after_gate"] or audit.get("passed") is not True:
        raise RuntimeError("Candidate has unresolved defects")
    evaluation = report["evaluation_contract"]
    supplemental = candidate / "realize_report/supplemental-recovery-context.json"
    recovery_context = load_recovery_context(supplemental, task) if supplemental.is_file() else None
    for actual in (
        stages.read_json(candidate / "realize_report/evaluation_contract_report.json")["final"],
        stages.read_json(candidate / "realize_report/main_task_protocol.json")["evaluation_contract"],
        report["downstream_context"]["evaluation_contract"],
    ):
        if actual != evaluation:
            raise RuntimeError("Candidate machine contract copies disagree")
    archive = stages.batch.OUT / "stage-archives" / result["slug"] / f"before-contract-repair-{time.time_ns()}"
    archive.mkdir(parents=True)
    shutil.copytree(source / "realize_report", archive / "realize_report")
    for name in ("description.md", "sample_submission.csv"):
        if (source / name).is_file():
            shutil.copy2(source / name, archive / name)
    # Source data never moves. A failed copy cannot pass a later stage review.
    shutil.copytree(candidate / "realize_report", source / "realize_report", dirs_exist_ok=True)
    shutil.copy2(candidate / "description.md", source / "description.md")
    if recovery_context:
        install_recovery_fixtures(recovery_context, source / "data" if (source / "data").is_dir() else source)
    if (candidate / "sample_submission.csv").is_file():
        shutil.copy2(candidate / "sample_submission.csv", source / "sample_submission.csv")
    # Render the audited machine contract with the current deterministic writer.
    if report.get("automl_context_pack"):
        (source / "realize_report/automl_context.md").write_text(
            render_automl_context_markdown(report["automl_context_pack"]), encoding="utf-8",
        )
    ledger = stages.read_json(stages.LEDGER, {})
    ledger.pop(result["slug"], None)
    stages.batch.save(stages.LEDGER, ledger)
    result.update(applied_at=time.time(), archive=str(archive),
                  automl_context_rendered_from_audited_pack=bool(report.get("automl_context_pack")))
    stages.batch.save(result_file, result)
    if task["phase"] in {"autorealize_failed", "stopped"}:
        from autorealize.pipeline import AutoRealizePipeline
        AutoRealizePipeline()._flatten_data_to_root(source, source / "data", source / "realize_report")
    stages.verify_task_definition(task)
    stages.batch.save(Path(task["run_dir"]) / "task-definition-recovery.json", {
        "passed": True, "result": str(result_file.resolve()), "applied_at": result["applied_at"],
        "artifact_fingerprint": stages.fingerprint(stages.stage_artifacts(task, "autorealize")),
        "scope": "Completed production task-definition compilation and full audit from preserved cognition"})
    print(json.dumps({"applied": str(source), "archived": str(archive)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug")
    parser.add_argument("--feedback-file", type=Path)
    parser.add_argument("--apply-result", type=Path)
    parser.add_argument("--audit-only-from", type=Path)
    parser.add_argument("--reapply-last-patch", action="store_true")
    parser.add_argument("--repair-open-questions", action="store_true")
    parser.add_argument("--restore-sample-from-cache", action="store_true")
    parser.add_argument("--description-review-file", type=Path)
    parser.add_argument("--reuse-compiled-from", type=Path)
    parser.add_argument("--question-review-file", type=Path)
    parser.add_argument("--derived-review-file", type=Path)
    parser.add_argument("--reviewed-evaluation-file", type=Path)
    parser.add_argument("--evaluation-review-file", type=Path)
    parser.add_argument("--verify-excel-readers", action="store_true")
    parser.add_argument("--section-fact-review-file", type=Path)
    parser.add_argument("--recovery-context-file", type=Path)
    args = parser.parse_args()
    if args.apply_result:
        with stages.admission_lock():
            apply_repair(args.apply_result)
    elif args.slug and (args.feedback_file or args.audit_only_from):
        with stages.admission_lock():
            prepare_repair(args.slug, args.feedback_file, audit_only_from=args.audit_only_from,
                           reapply_patch=args.reapply_last_patch, repair_questions=args.repair_open_questions,
                           restore_sample=args.restore_sample_from_cache,
                           description_review_file=args.description_review_file,
                           reuse_compiled_from=args.reuse_compiled_from,
                           question_review_file=args.question_review_file, derived_review_file=args.derived_review_file,
                           reviewed_evaluation_file=args.reviewed_evaluation_file, evaluation_review_file=args.evaluation_review_file,
                           verify_excel_readers=args.verify_excel_readers,
                           section_fact_review_file=args.section_fact_review_file,
                           recovery_context_file=args.recovery_context_file)
    else:
        parser.error("Provide --slug and --feedback-file, or --apply-result")


if __name__ == "__main__":
    main()

"""Exercise the production bounded repair against the frozen, audited traffic artifacts."""
from copy import deepcopy
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.config import AutoRealizeConfig
from autorealize.artifact_contract_repair import DerivedContractRepair
from autorealize.llm.client import LLMClient
from autorealize.models import ArtifactConsistencyReview, DescriptionProtocolBundle, EvaluationContractReview, FileSummary, ProblemParadigmReview, SampleSubmissionSpec
from autorealize.modules.task_definition import TaskDefinitionModule
from autorealize.modules.types import RuntimeServices
from autorealize.prompts.manager import PromptManager
from autorealize.profiling.relations import RelationHint
from autorealize.trajectory import TrajectoryLogger


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-from", type=Path)
    args = parser.parse_args()
    dest = BATCH / "optimization-validation" / ("derived-contract-" + str(time.time_ns()))
    dest.mkdir(parents=True)
    frozen = read(BATCH / "optimization-validation/review-ab-v3/snapshot.json")
    task = deepcopy(frozen["task"])
    context = task["downstream_context"]
    cfg = AutoRealizeConfig()
    settings = yaml.safe_load((BATCH / "settings.yaml").read_text(encoding="utf-8-sig"))
    model = next(item for item in settings["llm"]["modelLibrary"] if item["id"] == settings["llm"]["roleModels"]["autoRealize"])
    assert model["model"] == "gpt-5.6-luna" and model["reasoningEffort"] == "xhigh" and model["apiKey"]
    cfg.llm.base_url, cfg.llm.api_key, cfg.llm.model_name = model["baseUrl"], model["apiKey"], model["model"]
    cfg.llm.reasoning_effort = "xhigh"
    cfg.llm.minimum_output_tokens = cfg.llm.max_tokens = cfg.llm.structured_max_tokens = 32768
    cfg.llm.request_timeout_seconds = 900
    cfg.llm.enable_cache = False
    client = LLMClient(cfg, dest)
    if args.replay_from:
        recorded = DerivedContractRepair.model_validate(read(args.replay_from / "derived_contract_repair_report.json"))
        client.ask_structured = lambda **kwargs: recorded.model_copy(deep=True)
    module = TaskDefinitionModule(cfg, RuntimeServices(client, PromptManager(cfg), None, TrajectoryLogger(dest)), dest, dest)
    bundle = DescriptionProtocolBundle.model_validate(task["description_protocol_bundle"])
    sample = SampleSubmissionSpec.model_validate(context["sample_submission_spec"])
    original_bundle, original_sample = bundle.model_dump(), sample.model_dump()
    review = ArtifactConsistencyReview.model_validate(read(BATCH / "optimization-validation/review-ab-v3/actual-new/result.json")["output"])
    review.issues = [issue for issue in review.issues if issue.artifact in {"sample_submission_spec", "description_protocol_bundle"}]
    contract = EvaluationContractReview.model_validate(read(BATCH / "optimization-validation/review-finalizer-v4/finalizer-new/result.json")["output"])
    context["evaluation_contract"] = contract.model_dump()
    result = {"passed": False, "stage": "autorealize", "started_at": time.time(), "source_snapshot": "review-ab-v3/snapshot.json",
              "replayed_provider_output": str(args.replay_from) if args.replay_from else None}
    (dest / "result.json").write_text(json.dumps(result), encoding="utf-8")
    print(str(dest), flush=True)
    try:
        module._repair_final_derived_contracts(
            review=review, evaluation_contract=contract, problem_review=ProblemParadigmReview.model_validate(task["problem_paradigm"]),
            protocol_bundle=bundle, sample_spec=sample, downstream_context=context,
            automl_context_pack=task["automl_context_pack"], main_task_protocol=task["main_task_protocol"],
            repair_context={"original_text": frozen["original"],
                            "file_summaries": [FileSummary.model_validate(item) for item in frozen["cognition"]["files"]],
                            "relations": [RelationHint(**item) for item in frozen["cognition"]["relations"]]},
        )
        checks = {"columns_unchanged": sample.columns == original_sample["columns"],
                  "source_fields_unchanged": sample.source_fields == original_sample["source_fields"],
                  "constraints_unchanged": bundle.constraints == original_bundle["constraints"],
                  "method_requirements_unchanged": bundle.required_method_families == original_bundle["required_method_families"],
                  "evaluation_unchanged": context["evaluation_contract"] == contract.model_dump(),
                  "row_rule_changed": sample.row_count_rule != original_sample["row_count_rule"],
                  "target_changed": bundle.ml_dl.target != original_bundle["ml_dl"]["target"],
                  "sample_mirror_synchronized": task["automl_context_pack"]["output_contract"]["sample_submission_spec"] == sample.model_dump()}
        result.update(passed=all(checks.values()), checks=checks, bundle=bundle.model_dump(), sample=sample.model_dump(),
                      repair=read(dest / "derived_contract_repair_report.json"),
                      scope="Production repair and exact retention checks; full task audit is still required before apply")
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc).replace(model["apiKey"], "[REDACTED]"))
    finally:
        client.client.close()
    result["finished_at"] = time.time()
    (dest / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "result": str(dest / "result.json")}), flush=True)


if __name__ == "__main__":
    main()

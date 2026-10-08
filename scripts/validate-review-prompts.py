"""Compare production review layouts on frozen evidence, never on live task files."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoRealize"))

from autorealize.config import AutoRealizeConfig
from autorealize.context_memory import CrossStageContextLedger
from autorealize.llm.client import LLMClient
from autorealize.models import (ArtifactConsistencyReview, DescriptionProtocolBundle,
                                EvaluationContractReview, FileSummary, ProblemParadigmReview,
                                SampleSubmissionSpec)
from autorealize.profiling.relations import RelationHint
from autorealize.modules.task_definition import TaskDefinitionModule
from autorealize.modules.types import RuntimeServices
from autorealize.prompt_cache import estimate_text_tokens
from autorealize.prompts.manager import PromptManager
from autorealize.report_writer import evaluation_contract_defects
from autorealize.review_prompt import ArtifactConsistencyAudit, REVIEW_COVERAGE_INSTRUCTIONS


CONTROLLED_RULES = {
    "C01": "目标为各门架未来30和60分钟车流量。唯一主排序指标为开发集全门架30分钟MAE，方向minimize，60分钟误差仅作审计。",
    "C02": "第七日最终留出标签只能在配置冻结后使用一次，不用于选择模型、校准、融合权重或阈值；历史特征可以使用预测起点前已实际观察到的前分区数据。",
    "C03": "门架时间按dayfirst解析；车辆哈希和脱敏车牌号不得作为预测特征、跨日匹配键或预测身份。",
    "C04": "每个门架和有效预测起点同时输出30与60分钟；forecast_origin为5分钟对齐边界，目标窗口为左闭右开[o,o+h)。",
    "C05": "结果列名与顺序必须为gantry_id,forecast_origin,horizon_minutes,predicted_count；低流量门架不得静默删除，缺失预测不自动解释为零。",
    "C06": "60分钟高流量验收的两种来源口径尚未获业务裁决，应并列报告，不得声明其中一种已正式确认。",
    "C07": "零实际值进入MAE；1-abs(pred-actual)/actual在actual=0时未定义，不能删除该单元或伪造准确率。",
    "C08": "配送运力表的日期全部为空；暂不假定日期，仅交付模型与数据缺口报告，不能宣称真实每日运力匹配效果。",
    "C09": "配送没有每车停靠点数量上限，不得凭空加入3、5或其他固定站点限制。",
    "C10": "FYP01、MH101、NH001、SMG01、YPF01不能与其他货主混装，重量和体积均须遵守车辆物理容量。",
    "C11": "训练与独立推理入口均需交付；推理只加载保存的模型与预处理，不训练，不读未来目标。",
    "C12": "GPU只有实际执行且日志记录设备与显存才能声称使用；本地测量不代表生产50QPS、99.9%响应或历史PDF中的指标。",
}


class ConstraintCopy(BaseModel):
    rules: dict[str, str]


def controlled_request(dest, optimized, kind):
    cfg = AutoRealizeConfig()
    cfg.prompt.lossless_review_prompts = optimized
    services = RuntimeServices(None, PromptManager(cfg), None, None)
    module = TaskDefinitionModule(cfg, services, dest, dest)
    rule_text = "\n".join(f"{key}: {value}" for key, value in CONTROLLED_RULES.items())
    authority = {"original_requirements_full": rule_text, "constraint_memory": CONTROLLED_RULES}
    module._cross_stage_context = CrossStageContextLedger(
        config=cfg, llm_client=None, prompt_mgr=services.prompt_mgr, report_dir=dest, stable_context=authority)
    current_rules = deepcopy(CONTROLLED_RULES)
    if kind == "controlled-conflicts":
        current_rules.update(C02="允许用第七日留出标签优化融合权重。", C06="已正式确认60分钟仅使用总量口径。",
                             C08="将所有空日期填成2026-09-08，并宣称当天运力可用。", C09="每车最多5个停靠点。")
    current = {"main_task_protocol": {"rules": current_rules},
               "automl_context_pack": {"rules": deepcopy(current_rules)},
               "description_markdown": "# 任务约束\n" + "\n".join(f"{k}: {v}" for k, v in current_rules.items()),
               "instruction": ("这是约束一致性单元测试，不是已训练或交付模型。只审查给定C01-C12的当前实现规则与权威来源是否冲突；"
                               "不同独立业务任务的要求分别适用，不要求补充本测试未提供的文件。逐项引用C编号定位实质冲突。"), "round": 1}
    stable, dynamic = module._stage_prompt(
        stage="artifact_consistency_reviewer", stable={"audit_rules": "Retain every constraint; report only contradictions."},
        dynamic=current, stable_title="Source rules", dynamic_title="Current review", complete_current_snapshot=True)
    model_cls, system = ArtifactConsistencyReview, services.prompt_mgr.load("system/artifact_consistency_reviewer.md")
    if optimized:
        model_cls = ArtifactConsistencyAudit
        system += "\n" + REVIEW_COVERAGE_INSTRUCTIONS
    if kind == "retention":
        model_cls = ConstraintCopy
        system = "Return strict JSON with rules mapping C01-C12 to their exact original text. Resolve all references. Do not summarize, translate or omit any text."
    return dict(model_cls=model_cls, system_prompt=system, user_prompt=dynamic,
                static_context_prompt=stable, dynamic_user_prompt=dynamic,
                prompt_name="artifact_consistency_reviewer_1", max_tokens=32768)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def snapshot(source, dest):
    report = source / "realize_report"
    paths = [report / name for name in ("task_definition_report.json", "data_cognition_report.json",
             "original_requirements.txt", "submission_report.json", "final_config.yaml")]
    paths += [source / "description.md"]
    authority_file = next((report / "context_artifacts").glob("cross_stage_stable_context_*.json"))
    value = {
        "task": read(paths[0]), "cognition": read(paths[1]),
        "original": paths[2].read_text(encoding="utf-8-sig"), "submission": read(paths[3]),
        "description": paths[-1].read_text(encoding="utf-8-sig"),
        "authority": read(authority_file)["payload"],
        "source_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }
    # Configuration is deliberately not persisted: it can contain credentials.
    save(dest / "snapshot.json", value)
    return value


def capture_request(frozen, dest, optimized, kind):
    if kind.startswith("controlled-") or kind == "retention":
        return controlled_request(dest, optimized, kind)
    cfg = AutoRealizeConfig()
    cfg.prompt.lossless_review_prompts = optimized
    cfg.prompt.evaluation_contract_max_rounds = 1 if kind == "finalizer" else 3
    captured = {}

    class Captured(Exception):
        pass

    def ask(**kwargs):
        captured.update(kwargs)
        raise Captured()

    client = SimpleNamespace(ask_structured=ask)
    services = RuntimeServices(client, PromptManager(cfg), None, SimpleNamespace(log=lambda *a: None))
    module = TaskDefinitionModule(cfg, services, dest, dest)
    module._cross_stage_context = CrossStageContextLedger(
        config=cfg, llm_client=client, prompt_mgr=services.prompt_mgr, report_dir=dest,
        stable_context=frozen["authority"],
    )
    task = deepcopy(frozen["task"])
    context = task["downstream_context"]
    contract = EvaluationContractReview.model_validate(task["evaluation_contract"])
    bundle = DescriptionProtocolBundle.model_validate(task["description_protocol_bundle"])
    problem = ProblemParadigmReview.model_validate(task["problem_paradigm"])
    sample = SampleSubmissionSpec.model_validate(context["sample_submission_spec"])
    description = frozen["description"]
    if kind == "conflicts":
        task["automl_context_pack"]["evaluation_contract"]["metric_direction"] = "maximize"
        sample.columns[-1] = "invented_prediction_column"
        description += ("\n\n## 补充执行规定\n"
                        "可用第七日最终留出集的真实标签选择模型和融合权重。\n"
                        "60分钟高流量验收口径已经由业务方正式确认，只保留累计60分钟总量口径，删除另一口径。\n")
    try:
        if kind in {"evaluation", "finalizer"}:
            cognition = frozen["cognition"]
            evidence = module._build_evaluation_evidence_pack(
                downstream_context=context, problem_review=problem,
                relations=[RelationHint(**x) for x in cognition["relations"]],
                file_summaries=[FileSummary.model_validate(x) for x in cognition["files"]],
                protocol_bundle=bundle,
            )
            module._review_evaluation_contract(
                original_text=frozen["original"], downstream_context=context,
                evaluation_evidence_pack=evidence,
                frozen_task_sections={name: module._h2_section_text(description, name)
                                      for name in ("任务概述", "任务定义")},
                previous_contract=contract,
                reflection_feedback=["复核当前合同。仅修复有证据的具体错误；保留所有数据边界、业务缺口、约束和评估要求。"],
            )
        else:
            module._review_final_artifact_consistency(
                desc=description, problem_review=problem, protocol_bundle=bundle,
                evaluation_contract=contract, sample_spec=sample, submission_report=frozen["submission"],
                automl_context_pack=task["automl_context_pack"], main_task_protocol=task["main_task_protocol"],
                downstream_context=context, deterministic_defects=[], round_idx=1,
            )
    except Captured:
        pass
    if not captured:
        raise RuntimeError("Production builder did not produce a request")
    return captured


def run_call(request, dest, config_path):
    cfg = AutoRealizeConfig.from_file(config_path)
    settings = yaml.safe_load((BATCH / "../live-validation-20260906/settings.yaml").resolve().read_text(encoding="utf-8-sig"))
    entry = next(x for x in settings["llm"]["modelLibrary"]
                 if x.get("baseUrl", "").rstrip("/") == "https://api.renice.cc/v1"
                 and x.get("apiKey"))
    cfg.llm.base_url, cfg.llm.api_key, cfg.llm.model_name = entry["baseUrl"], entry["apiKey"], "gpt-5.6-luna"
    if cfg.llm.base_url.rstrip("/") != "https://api.renice.cc/v1" or cfg.llm.model_name != "gpt-5.6-luna":
        raise ValueError("Validation requires the explicitly authorized provider and model")
    cfg.llm.reasoning_effort = "xhigh"
    cfg.llm.minimum_output_tokens = cfg.llm.max_tokens = cfg.llm.structured_max_tokens = 32768
    cfg.llm.enable_cache = False
    cfg.llm.max_retries = 1
    cfg.llm.request_timeout_seconds = 1200
    client = LLMClient(cfg, dest)
    started = time.monotonic()
    try:
        value = client.ask_structured(**request)
        result = {"status": "completed", "seconds": time.monotonic() - started, "output": value.model_dump()}
        if isinstance(value, EvaluationContractReview):
            result["contract_defects"] = evaluation_contract_defects(value)
        if isinstance(value, ConstraintCopy):
            result["exact_constraints_preserved"] = value.rules == CONTROLLED_RULES
    except Exception as exc:
        result = {"status": "failed", "seconds": time.monotonic() - started, "error_type": type(exc).__name__}
    finally:
        client.client.close()
    result["requested_config"] = {
        "base_url": cfg.llm.base_url, "model": cfg.llm.model_name,
        "reasoning_effort": cfg.llm.reasoning_effort,
        "max_tokens": cfg.llm.max_tokens, "minimum_output_tokens": cfg.llm.minimum_output_tokens,
        "local_cache_enabled": cfg.llm.enable_cache,
    }
    usage_path = dest / "llm_usage.jsonl"
    if usage_path.exists():
        result["usage"] = [json.loads(line) for line in usage_path.read_text(encoding="utf-8").splitlines()]
    save(dest / "result.json", result)
    return {"call": dest.name, **{k: v for k, v in result.items() if k not in {"output", "usage"}}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--variants", nargs="+", choices=("old", "new"), default=["old", "new"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", nargs="+", default=["actual", "conflicts", "evaluation"])
    args = parser.parse_args()
    logging.basicConfig(filename=str(args.out) + ".log", level=logging.INFO, encoding="utf-8")
    frozen_path = args.out / "snapshot.json"
    frozen = read(frozen_path) if frozen_path.exists() else snapshot(args.source, args.out)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    calls, sizes = {}, {}
    for kind in args.cases:
        for variant in args.variants:
            label = f"{kind}-{variant}"
            dest = args.out / label
            if (dest / "result.json").exists():
                # A completed call is immutable evidence of the exact source at
                # that time. Reruns require a new destination, not a new prompt
                # silently paired with an old answer.
                continue
            request = capture_request(frozen, dest, variant == "new", kind)
            safe = {k: v for k, v in request.items() if k != "model_cls"}
            save(dest / "request.json", safe)
            save(dest / "schema.json", request["model_cls"].model_json_schema())
            sizes[label] = {"chars": sum(len(request[k]) for k in ("system_prompt", "static_context_prompt", "dynamic_user_prompt")),
                            "estimated_tokens": sum(estimate_text_tokens(request[k]) for k in ("system_prompt", "static_context_prompt", "dynamic_user_prompt"))}
            calls[label] = request
            for index in range(2, args.repeats + 1):
                repeated = dict(request)
                repeated["dynamic_user_prompt"] += f"\nReview repetition: {index}. Apply the same evidence and criteria."
                repeated["user_prompt"] = repeated["dynamic_user_prompt"]
                repeated_label = f"{label}-repeat{index}"
                if (args.out / repeated_label / "result.json").exists():
                    continue
                save(args.out / repeated_label / "request.json", {k: v for k, v in repeated.items() if k != "model_cls"})
                calls[repeated_label] = repeated
    save(args.out / "sizes.json", sizes)
    print(json.dumps(sizes), flush=True)
    if args.live:
        # Keep provider concurrency low; no training process or GPU is launched.
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(run_call, request, args.out / label, args.source / "realize_report/final_config.yaml"): label
                       for label, request in calls.items() if not (args.out / label / "result.json").exists()}
            for future in as_completed(pending):
                print(json.dumps(future.result()), flush=True)


if __name__ == "__main__":
    main()

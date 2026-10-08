"""Compare evaluation-policy prompts on frozen real chemical task evidence."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.config import AutoRealizeConfig
from autorealize.llm.client import LLMClient
from autorealize.models import EvaluationContractReview
from autorealize.prompts.manager import PromptManager
from autorealize.prompt_cache import lossless_json
from autorealize.report_writer import evaluation_contract_defects

POLICY = """
离线预测任务的执行范围：
- 用户要求用已有历史数据建立预测模型、训练和独立推理代码及实验报告，且未要求现场上线或固定提前量时，可以提出有证据基础、明确披露的离线验证场景。预测时点、历史窗口、时间切分、评价指标和内部请求 schema 属可配置实验设计；不得因为没有官方模型验收方案就反复要求业务审批。原始来源没有“须批准”的要求时，不得自行添加审批门禁。
- 实验假设不等于已核验的业务事实。缺失真实日期、运力、费用、目标值、生产线关系和安全限制仍不得补造。来源冲突须保留，不把两套工艺自动认成同一对象；可以只使用真实已观测、适用于目标的来源建立实验。
- 严格保留原目标、字段、异常和重复数据的审计。已验证时间戳可作为明确披露的离线信息截止点候选；它不自动等于化验回传时间或真实上线可用时间。无可确认可用性的历史标签特征应排除，或仅在明确的敏感性实验中报告，不能宣称实时预测有效。任何特征只从截止点前实际记录派生，禁止未来匹配、当前目标派生特征和标签泄漏。
- 当前任务没有独立待预测表且用户要求可复用推理代码时，定义真实特征 schema 和可追溯的开发验证请求并测试独立加载推理；明确这不是已交付真实未来预测，不把缺少未来表视为无法训练历史模型。
- QDI 的建议、旧未决问题和先前生成合同均非原始权威。先与最新原文、全量画像和已完成调查核对；已解决问题不得继续作为阻塞。不能用长串新增业务元数据取代可运行实验设计。
- 若目标或必要输入在所有有依据的实验场景中都无法构造，则保持不可执行；不得为了产生分数改变用户的预测目标、生成模拟标签，或以软件检查分数代替模型效果。
"""


def main():
    spec = importlib.util.spec_from_file_location("offline_policy_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    source = stages.batch.OUT / "stage-repairs/chemical-1788806761192479100/autorealize/realize_report"
    dest = stages.batch.OUT / "optimization-validation" / f"chemical-offline-policy-{time.time_ns()}"
    dest.mkdir(parents=True)
    logging.basicConfig(filename=dest / "validation.log", level=logging.INFO, encoding="utf-8")
    cognition = stages.read_json(source / "data_cognition_report.json")
    evidence = {"task_hint": cognition["task_hint"], "original_requirements_full": (source / "original_requirements.txt").read_text(encoding="utf-8"),
                "authoritative_memory": cognition["authoritative_memory"], "constraint_memory": cognition["constraint_memory"],
                "files": cognition["files"], "relations": cognition["relations"],
                "question_investigation": cognition["question_investigation"],
                "previous_evaluation_contract": stages.read_json(source / "evaluation_contract_report.json")["final"]}
    # Retain the same complete source evidence for both calls, including unresolved facts.
    encoded = lossless_json(evidence)
    stages.batch.save(dest / "frozen-evidence.json", evidence)
    stages.batch.save(dest / "comparison.json", {"status": "running", "evidence_sha256": hashlib.sha256(encoded.encode()).hexdigest()})
    config = AutoRealizeConfig.from_file(source / "final_config.yaml")
    original = PromptManager(config).load("system/evaluation_contract_reviewer.md")
    (dest / "original-system.txt").write_text(original, encoding="utf-8")
    (dest / "candidate-policy.txt").write_text(POLICY, encoding="utf-8")
    settings = yaml.safe_load((stages.batch.OUT / "settings.yaml").read_text(encoding="utf-8-sig"))
    stages.validate_provider(settings)
    model = next(row for row in settings["llm"]["modelLibrary"] if row["id"] == settings["llm"]["roleModels"]["autoRealize"])

    def run(name):
        cfg = deepcopy(config)
        cfg.llm.api_key, cfg.llm.base_url, cfg.llm.model_name = model["apiKey"], model["baseUrl"], model["model"]
        cfg.llm.reasoning_effort = "xhigh"
        cfg.llm.max_tokens = cfg.llm.minimum_output_tokens = cfg.llm.structured_max_tokens = 32768
        cfg.llm.enable_cache = False
        cfg.llm.max_retries = 1
        out = dest / name
        out.mkdir()
        client = LLMClient(cfg, out)
        started = time.monotonic()
        try:
            response = client.ask_structured(model_cls=EvaluationContractReview,
                system_prompt=original + ("\n" + POLICY if name == "new" else ""),
                static_context_prompt="完整冻结来源与此前合同：\n" + encoded,
                user_prompt="复核并修复此前评估合同，保留所有真实约束和未知事实，交付与用户任务一致的可复现评估定义。不得伪造已运行实验。",
                prompt_name="evaluation_contract_offline_policy_" + name, max_tokens=32768)
            stages.batch.save(out / "contract.json", response.model_dump())
            result = {"completed": True, "contract_passed": response.passed, "executable": response.executable,
                      "defects": evaluation_contract_defects(response), "seconds": time.monotonic() - started}
        except Exception as exc:
            result = {"completed": False, "error_type": type(exc).__name__, "error": str(exc).replace(model["apiKey"], "[REDACTED]")}
        finally:
            client.client.close()
        stages.batch.save(out / "result.json", result)
        return name, result

    print(str(dest), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(run, ("old", "new")))
    stages.batch.save(dest / "comparison.json", {"status": "awaiting_independent_quality_review", "results": results})
    print(json.dumps({"comparison": str(dest / "comparison.json"), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()

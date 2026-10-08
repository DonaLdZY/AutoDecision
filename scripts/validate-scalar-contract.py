"""Live prompt regression using the configured AutoRealize provider; no task artifacts are modified."""
from __future__ import annotations

import argparse
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
from autorealize.modules.task_definition import TaskDefinitionModule
from autorealize.modules.types import RuntimeServices
from autorealize.prompts.manager import PromptManager
from autorealize.report_writer import evaluation_contract_defects
from autorealize.trajectory import TrajectoryLogger


DELIVERY = """开发城配订单与运力匹配模型。先最大化满足全部硬约束的唯一订单数 completed_orders，
订单数相同时最小化 total_cost。最终评分必须是唯一可比较数值，不允许分层或元组。
权威材料没有权重，允许定义并明确披露不改变该优先级的标量化参数。
cost(o,承运商,车型,线路) 必须按合同费率表字段独立复算：合同有效标志=是，订单日期在开始日期~结束日期内；
计费单位选择元每吨或元每箱；起运量/截止量判断档位；保底费取 max；
同区多点费率/跨区多点费率叠加；订单额外费用/运单额外费用累加；折算箱数/标箱转换率换算。
运力表的 51 行日期全部缺失，暂不假定日期，只完成模型与数据缺口报告。不得用自检通过率代替业务指标。
没有提供官方成本上界或车牌等唯一车辆编号。不得发明业务值。
这次仅验证评分合同生成，不要求执行求解或虚构实测业务分数。"""
PREDICTION = """本例是隔离的提示词回归样例，不是已有任务或实测业务数据。
使用 train.csv 的 date、sensor_a、target 预测 target。date 是已验证按天唯一的时间戳；
sensor_a 在预测时点前已观测。train.csv 的 2025 年记录用于训练，2026 年 1 月记录用于开发评估，
2026 年 2 月为独立最终留出，不参与搜索。主指标仅 RMSE，越小越好；按全部开发行计算，
输出 date,prediction，每行与开发日期一一对应。缺行、重复、非有限值为无效输出。
保留共同人口，预处理只拟合训练记录；最终评分必须单一数值，不添加额外目标或加权成本。"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["delivery", "prediction"], required=True)
    parser.add_argument("--settings", type=Path, required=True, help="Active gateway settings file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    settings = yaml.safe_load(args.settings.read_text(encoding="utf-8-sig"))
    role = settings["llm"]["roleModels"]["autoRealize"]
    entry = next(row for row in settings["llm"]["modelLibrary"] if row["id"] == role)
    cfg = AutoRealizeConfig()
    cfg.llm.model_name, cfg.llm.base_url = entry["model"], entry["baseUrl"]
    cfg.llm.api_key = entry.get("apiKey") or cfg.llm.api_key
    cfg.llm.reasoning_effort = entry.get("reasoningEffort")
    cfg.llm.minimum_output_tokens = cfg.llm.max_tokens = cfg.llm.structured_max_tokens = 32768
    cfg.llm.request_timeout_seconds = 240
    cfg.llm.max_retries = 1
    cfg.llm.enable_cache = False
    cfg.prompt.evaluation_contract_max_rounds = 2
    dest = ROOT / "runs/prompt-validation" / f"scalar-{args.case}-{time.time_ns()}"
    dest.mkdir(parents=True)
    print(json.dumps({"case": args.case, "model": cfg.llm.model_name, "output": str(dest)}, ensure_ascii=False), flush=True)
    client = LLMClient(cfg, dest)
    module = TaskDefinitionModule(cfg, RuntimeServices(client, PromptManager(cfg), None, TrajectoryLogger(dest)), dest, dest)
    original = DELIVERY if args.case == "delivery" else PREDICTION
    result = {"case": args.case, "model": cfg.llm.model_name, "max_output_tokens": 32768,
              "scope": "Isolated live contract prompt validation, no training, scoring or live task update.",
              "requirements": original, "started_at": time.time()}
    try:
        review = module._review_evaluation_contract(original_text=original, downstream_context={"task_hint": original})
        defects = evaluation_contract_defects(review)
        result.update(output=review.model_dump(), structural_defects=defects,
                      structurally_valid=not defects, rounds=module._evaluation_contract_revision_log)
    except Exception as exc:
        result.update(structurally_valid=False, error=str(exc).replace(cfg.llm.api_key, "[REDACTED]"))
    finally:
        client.client.close()
    result["seconds"] = time.time() - result["started_at"]
    (dest / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"structurally_valid": result["structurally_valid"], "result": str(dest / "result.json"),
                      "seconds": result["seconds"]}, ensure_ascii=False), flush=True)
    return 0 if result["structurally_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

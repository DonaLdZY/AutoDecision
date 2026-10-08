"""Freeze retained user scope and verified delivery evidence for real recompilation."""
import hashlib
import importlib.util
import json
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("delivery_repair", Path(__file__).with_name("repair-industrial-task-definition.py"))
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)
stages = repair.stages


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    task = stages.current_task("delivery")
    out = stages.batch.OUT / "optimization-validation"
    review = out / "delivery-current-source-review-20260908"
    manifest = stages.read_json(review / "source-manifest.json")
    evidence = {str(Path(manifest["source_root"]) / row["relative_path"]): row["sha256"] for row in manifest["files"]}
    for path in [*review.glob("*.json"), review / "acceptance-checklist.md", stages.batch.OUT / "delivery-protocol.md"]:
        evidence[str(path.resolve())] = sha(path)
    suite = out / "delivery-synthetic-acceptance-v1"
    fixtures = sorted((suite / "fixtures").glob("*.json"))
    if len(fixtures) != 34:
        raise RuntimeError("Expected the independently checked 34-fixture suite")
    for path in fixtures:
        evidence[str(path.resolve())] = sha(path)
    value = {
        "schema": "industrial.recovery_context.v1", "task_id": task["id"],
        "task_hint": task["config"]["auto_realize"]["task_hint"],
        "retained_user_requirements": [
            {"source": "Earlier explicit user reply retained in delivery-protocol.md",
             "text": "暂不假定日期，配送任务只完成模型与数据缺口报告"},
            {"source": "Current task_hint, preserved verbatim above",
             "text": "订单号区分单个订单；原始订单号仅表示历史决策，不代表最优。尽可能承运订单优先，同等承运水平下成本最小，调查仓库中转。"},
        ],
        "scope": "交付可复用求解器、冻结配置、独立加载决策代码、原始数据缺口报告和明确标注为合成测试的软件/算法比较。真实数据不补运力日期，不生成真实每日分配、运营成本、节约或达成率。",
        "verified_facts": {
            "original_readers": "24个xlsx、47个sheet已独立读取，source-manifest记录全部原始文件SHA256。各文件不同header、sheet和列名不能用统一猜测替代。",
            "orders": stages.read_json(review / "order-identity-evidence.json"),
            "capacity": "承运商每日可用车辆数据表.xlsx::Sheet1 51行日期全空；数量之和203不是203辆每日车辆。",
            "time_windows": "2104订单中71个含1899年占位时间；保留全部需求分母，不可删除异常订单抬高覆盖率。保留原始日期、时分秒、跨日与提送先后。",
            "contracts": "18个费率工作簿共7425行；4238行标记是、3187行否；其中3913个是记录不与任何合法订单交货窗口日期重叠。诊断不构成启用/映射授权。保留计费单位、费用模式、有效期、匹配维度、阶梯、保底、多点与附加费，不能取全局最小费率。",
            "vehicle_and_owner_mapping": "重量和体积同时约束；4.2M普通/电车型容量冲突不能取首行。五货主隔离 FYP01/MH101/NH001/SMG01/YPF01 保留；MH101/MHI01与NH001/NHI01映射冲突未获授权，不能模糊合并。",
            "stops": "重要补充原文：我司未做限制。不可发明固定停靠点上限。",
            "loading": "后送先装与按时间窗安排卸货可同时成立：先求可行卸货顺序，再逆序装货；本身没有冲突。多仓实例若具体不满足空载进仓或货流约束，按实例明确不可行，不要求虚构优先级裁决。",
            "transfer": "已观察订单2511030000335由KDYPS至KDYGM，KDYGM另有273个出库单，但无证据证明这些单货流相连；10条转仓计费方案仅1条标有效。保留可配置中转能力，须显式授权仓库边、费用、驻留、货流守恒、各段运力与先入后出，不假造免费无限转仓。",
            "provider_error_in_old_qdi": "auto_reading_5曾将Provider Rate limit exceeded误判为give_up；旧推断不构成数据缺失证据。后续完成的原始工作簿核验和有效QDI结果优先；未核验的业务映射仍保留缺口。",
        },
        "implementation_validation": {
            "authority": "Engineering test design for the authorized reusable-model delivery; not an official operational metric or fabricated real business data.",
            "ranking_scope": "software_contract_checks",
            "input_qualification": "真实原始输入缺日期必须status=blocked_data_gap, assignments=[], cost=null，并保存完整data_gap_report/constraint_audit；这只作资格检查，常数100不足以证明求解能力。",
            "algorithm_checks": "固定合成小实例实际调用同一个候选求解器；完整可行输入必须产生方案，不得始终blocked。按订单承运数优先、同等承运数最小成本，和独立穷举的解/界核对；不能只相信候选打印的成本。所有候选共享同一fixture集合、精确公式与资格门槛。",
            "fixture_count": 34, "algorithm_fixture_count": 27, "data_gap_fixture_count": 7,
            "fixture_directory_in_task": "internal_validation/synthetic_delivery",
            "fixture_source_directory": str((suite / "fixtures").resolve()),
            "fixture_manifest": [{"name": path.name, "sha256": sha(path)} for path in fixtures],
            "semantics": "每个JSON明确synthetic=true、车型/日期/费率/费用/时间单位、允许边与目标。合成假设只适用该fixture，不回写原始订单和运力；算法族和超参由AutoML选择。",
            "required_tests": ["新完整数据非空方案", "承运优先", "同覆盖成本", "双容量", "多日期", "精确时窗与跨日", "吨箱计费与保底", "五货主隔离", "8停靠点", "明确开关的一单中转", "真实缺日期", "冻结工件移动目录并新进程加载"],
            "metric_design": "使用明确标注的软件/算法验收指标，可比较独立重算的检查通过比例或有界质量分；完整输入的一律blocked必须失败。不能以当前真实缺日期上的常数分数作为MCTS算法比较，也不能将软件检查百分比声称真实覆盖率或成本节约。完整三小时是运行器完成条件，不是每个候选重复执行三小时的检查项。",
            "references": "Independent enumerated acceptance witnesses remain outside candidate inputs. These fixtures and reference outputs are not a system candidate or proof that any solver has passed.",
        },
        "evidence_files": evidence,
    }
    path = out / "delivery-recovery-context-20260908.json"
    stages.batch.save(path, value)
    repair.load_recovery_context(path, task)
    print(json.dumps({"context": str(path), "evidence_files_verified": len(evidence), "fixtures": len(fixtures), "task_hint_preserved": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()

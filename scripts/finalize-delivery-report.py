"""Apply evidence-checked editorial corrections to the completed system report."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.collector import collect_evidence
from autoreport.config import load_config
from autoreport.events import ReportEventWriter
from autoreport.generator import revise_existing_report


def main():
    batch = ROOT / "runs/industrial-examples-20260907"
    task = batch / "tasks/工业实例-城配订单运力匹配"
    source = task / "report"
    report = json.loads((source / "report.json").read_text(encoding="utf-8"))
    trace = json.loads((source / "report_trace.json").read_text(encoding="utf-8"))
    original = report["article_markdown"]
    edits = [
        ("# 工业实例-城配订单运力匹配：技术报告", "# 城配订单运力匹配：技术报告"),
        ("但这个等价性是**基于实际观测成本范围的分析**，不是合同已经完整冻结的保证。",
         "数学上，只要 N 为整数、B>0、C 为非负有限数，便有 0≤C/(B+C)<1；因此按实数精确计算时，增加 1 个完成订单始终优于任意成本项变化，N 相同时成本越低分数越高。这不依赖上述观测成本范围。浮点实现仍需检查精度，而数学性质本身不能证明候选成本口径一致或满足全部业务硬约束。"),
        ("`B = 1.0e6` 元由合同冻结，不交给候选自行选择。原始业务分量为 `N` 与 `C`。在本组候选实际观测范围内，`C/(B+C) < 1`，所以每个完成订单的相对增益为 1，成本项最多贡献小于 1 的惩罚。因此在本组观测范围内，排名等价于 `N` 降序、`C` 升序。但该等价性不是官方合同已经完全修正后的保证，合同内部阈值描述仍存在矛盾。",
         "`B = 1.0e6` 元是本次搜索冻结的常数，不交给候选自行选择。对于整数 N、B>0 和非负有限 C，0≤C/(B+C)<1，故精确实数排序等价于先按 N 降序，再按 C 升序；该性质不依赖观测成本范围。上游文档中的阈值论证错误与公式本身的排序性质应分开说明；业务硬约束和成本复算是否通过仍是独立问题。"),
        ("该排序行为基于实际观测成本范围，不是合同内部阈值矛盾已经解决后的保证。",
         "该优先级由整数 N、B>0 和非负有限 C 的数学条件保证，不局限于已观测成本范围；它不代表上游阈值论证、候选成本口径或业务验证已经通过。"),
        ("因此在本组候选的观测范围内", "因此在上述数学条件下"),
    ]
    checked = [{"old": old, "new": new, "expected_count": original.count(old)}
               for old, new in edits if old in original]
    if len(checked) < 4:
        raise RuntimeError("The reviewed report has changed; inspect it before applying edits")
    receipt = {"status": "revised", "source_sha256": hashlib.sha256(original.encode()).hexdigest(),
               "issues": ["Correct the scalar formula proof without treating mathematical validity as business certification.",
                          "Disclose that the live task definition differs from the frozen search version.",
                          "Remove the obsolete task-name prefix from the displayed title."], "edits": checked}
    destination = task / "stage-history" / f"report-editorial-{time.time_ns()}"
    destination.mkdir(parents=True)
    cfg = load_config(source / "resolved_config.yaml")
    cfg.output_dir = str(destination)
    settings = yaml.safe_load((batch / "settings.yaml").read_text(encoding="utf-8"))
    model = next(m for m in settings["llm"]["modelLibrary"]
                 if m["id"] == settings["llm"]["roleModels"]["autoMlFeedback"])
    cfg.llm.api_key = model["apiKey"]
    report["report_title"] = "城配订单运力匹配 工智寻优运行报告"
    events = ReportEventWriter(destination, print_events_to_console=False)
    bundle = collect_evidence(cfg, events)
    (destination / "editorial_review.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    revise_existing_report(cfg, bundle, events, report, trace, reviewed_edits=receipt)
    if json.loads((source / "report.json").read_text(encoding="utf-8"))["article_markdown"] != original:
        raise RuntimeError("The live report changed during finalization")
    previous = destination / "previous"
    previous.mkdir()
    for name in ("report.md", "report.json", "report_trace.json"):
        shutil.copy2(source / name, previous / name)
        shutil.copy2(destination / name, source / name)
    print(json.dumps({"report": str(source / "report.md"), "archive": str(previous), "edits": len(checked),
                      "search_rerun": False, "provider_rerun": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

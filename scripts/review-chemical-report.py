"""Apply independently verified chemical report corrections after its full audit."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoReport"))
from autoreport.audit_chunks import apply_audit_edits
from autoreport.config import LLMConfig, config_from_dict, dump_config, write_config_yaml
from autoreport.events import ReportEventWriter
from autoreport.generator import revise_existing_report, _validate_report_article


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--draft-only", action="store_true")
    args = parser.parse_args()
    source, dest = args.source.resolve(), args.directory.resolve()
    if dest.exists() or not all(path.is_relative_to(OUT.resolve()) for path in (source, dest)):
        raise RuntimeError("Use a completed source and a fresh reviewed directory inside this batch")
    source_result = read(source / "result.json")
    if source_result.get("passed") is not True and not args.draft_only:
        raise RuntimeError("The real full audit must complete before independent editorial review")
    stages = module("industrial-stage-control")
    task = stages.current_task("chemical")
    fingerprint = stages.fingerprint(stages.stage_artifacts(task, "automl"))
    if source_result["source_fingerprint"] != fingerprint:
        raise RuntimeError("AutoML sources changed after the real report audit")
    workspace = Path(task["auto_ml_workspace_dir"])
    exported = workspace / "best_solution"
    manifest = read(exported / "solution_manifest.json")
    code = (exported / manifest["implementation_path"]).read_text(encoding="utf-8")
    functions = {node.name: ast.get_source_segment(code, node) for node in ast.parse(code).body
        if isinstance(node, ast.FunctionDef) and node.name in {"train", "predict", "_single_window_features_from_history", "final_evaluate"}}
    assert manifest["node_id"] == "58002f37a3fd4bf88c950e4375784ecb"
    if args.draft_only:
        cfg, _, _ = module("measure-report-context").source_bundle("chemical")
        entry = module("validate-industrial-prompts").model_entry()
        cfg.llm = LLMConfig(model=entry["model"], base_url=entry["baseUrl"], api_key=entry["apiKey"],
            reasoning_effort="xhigh", max_tokens=32768, minimum_output_tokens=32768,
            request_timeout_seconds=900, max_retries=2, context_window_tokens=196608)
        report, trace = {"article_markdown": (source / "report_draft.md").read_text(encoding="utf-8"), "config": dump_config(cfg)}, {}
    else:
        report, trace = read(source / "report.json"), read(source / "report_trace.json")
    article = report["article_markdown"]
    corrections, findings = [], []

    def edit(old, new, finding, *, optional=False):
        if old == new:
            return
        if old not in article and optional:
            return
        if article.count(old) != 1:
            raise RuntimeError("Independent source edit must match exactly once: " + old[:100])
        corrections.append({"old": old, "new": new, "expected_count": 1})
        findings.append(finding)

    def subsection(number, replacement, finding):
        lines = article.splitlines(keepends=True)
        tokens = MarkdownIt("commonmark").parse(article)
        boundaries = [(token.map[0], tokens[index + 1].content) for index, token in enumerate(tokens)
            if token.type == "heading_open" and token.tag in {"h1", "h2"} and token.markup.startswith("#")]
        matches = [(index, start) for index, (start, title) in enumerate(boundaries) if title.startswith(number + " ")]
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one source subsection " + number)
        index, start = matches[0]
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(lines)
        edit("".join(lines[start:end]), replacement.rstrip() + "\n\n", finding)

    subsection("7.2", f'''## 7.2 已提供数据上的直接推理示例

以下完整示例使用本次原始设备文件和已保存的历史截止点，加载 1221 行训练加开发数据拟合的最终模型。它复现已知历史请求，不代表真实未来生产数据已经验收。

```python
from pathlib import Path
import sys
import numpy as np
import pandas as pd

WORKSPACE = Path(r"{workspace}")
sys.path.insert(0, str(WORKSPACE / "best_solution"))
import solution

raw_device = pd.read_csv(WORKSPACE / "input" / "设备.csv", encoding="utf-8-sig", sep=",")
cutoff = pd.Timestamp("2026-04-06 09:00:00")
sample_time = pd.to_datetime(raw_device["SampleTime"], errors="raise")
history = raw_device.loc[
    (sample_time > cutoff - pd.Timedelta(minutes=60)) & (sample_time <= cutoff)
].copy()
prediction = solution.predict(
    solution.default_model_path(),
    {{"prediction_cutoff": cutoff.isoformat(), "history": history}},
)
assert isinstance(prediction, np.ndarray) and prediction.shape == (1,)
assert np.isfinite(prediction).all()
result = pd.DataFrame([{{"prediction_cutoff": cutoff.isoformat(), "y_pred": float(prediction[0])}}])
print(result)
```

真实接入时由调用方提供实际设备历史和请求截止点。读取后保留原始完整 63 列及顺序；不能静默删除、重排或补造字段。接口允许更早的历史行，但仅使用左开右闭的 60 分钟窗口；请求中任何晚于截止点的设备行都会被拒绝。上面的显式窗口过滤是一种符合合同的调用方式。
''', "Replace the nonexistent deployment placeholder with a complete original-input inference example and the exact ndarray shape.")
    subsection("8.2", f'''## 8.2 公共训练入口与可复现示例

`train(data, artifact_dir)` 已确认接受本次完整输入目录路径，并在读取和审计后只使用冻结训练分区的 914 行拟合模型及稳健裁剪器。以下完整示例在新目录复现默认训练配方，再对开发集中的一个历史截止点调用推理；不执行候选搜索或最终留出评分。

```python
from pathlib import Path
import sys
import numpy as np
import pandas as pd

WORKSPACE = Path(r"{workspace}")
sys.path.insert(0, str(WORKSPACE / "best_solution"))
import solution

model_path = solution.train(
    data=WORKSPACE / "input",
    artifact_dir=Path("chemical_retrained_artifacts").resolve(),
)
raw_device = pd.read_csv(WORKSPACE / "input" / "设备.csv", encoding="utf-8-sig", sep=",")
cutoff = pd.Timestamp("2025-12-20 09:00:00")
sample_time = pd.to_datetime(raw_device["SampleTime"], errors="raise")
history = raw_device.loc[
    (sample_time > cutoff - pd.Timedelta(minutes=60)) & (sample_time <= cutoff)
].copy()
prediction = solution.predict(model_path, {{"prediction_cutoff": cutoff.isoformat(), "history": history}})
assert isinstance(prediction, np.ndarray) and prediction.shape == (1,) and np.isfinite(prediction).all()
print(model_path, float(prediction[0]))
```

完整目录应保持本次 `浓度.xls`、`设备.csv` 及冻结任务文件；代码会全量读取标签以检查资格、重复记录、窗口及切分。读取开发或留出标签作审计，不表示这些标签参与默认模型拟合。

| 模型用途 | 模型和预处理器的拟合行数 | 留出标签的使用边界 |
|---|---:|---|
| 搜索阶段及默认公共训练 | 914 | 可读取作人口与切分审计，不进入拟合或选择 |
| 已导出的最终模型 | 1221 | 训练加开发重拟合，不使用留出标签拟合 |
| 已完成最终评分 | 304 条预测 | 配置锁定后的一次评分；不用于反向选择 |

默认训练输出与最终交付模型的训练范围不同，不能用默认训练工件替代已报告最终留出分数对应的 1221 行模型。原模型与原最终评分保持冻结。
''', "Provide the independently verified directory-based training API and distinguish reading labels for auditing from fitting to them.")
    subsection("8.4", """## 8.4 训练与命令行的边界

公共 `best_solution/solution.py` 是可导入封装，直接执行它不会自动调用原实现中的训练流程。第 8.2 节的 `solution.train(data=完整输入目录, artifact_dir=新目录)` 是已独立验证的复现入口。

冻结源码还支持包含 `X`、`y`、`feature_names`、`device_schema`、`process_columns` 的预先审计训练字典；这属于源码确认的低层接口，本报告实际执行的是完整目录入口。任意自建字典必须同时满足原始特征、人口、训练范围和防泄漏合同，不能将接口支持误解为任意数据均已验收。

原运行元数据中的 `python solution.py` 是历史执行命令，不能作为当前便携封装会自动端到端训练或评分的承诺。复现默认训练不重新选择候选，不重复最终留出评分，也不覆写原始最终工件。
""", "Correct the false missing-training-input claim using the delivered train source and independently executed public API.")
    edit("- 形状：一行", "- 形状：`(1,)`", "State the actual one-dimensional numpy return shape.", optional=True)
    edit("```python\ndefault_model_path()\npredict(model_path, data)\ntrain(data, artifact_dir)\n```", "```text\ndefault_model_path()\npredict(model_path, data)\ntrain(data, artifact_dir)\n```", "Mark API signatures as reference text instead of an executable Python example.", optional=True)
    edit("| 总请求检查数 | 12 项 |", "| 与冻结预测比对的有效历史请求数 | 12 个 |", "Distinguish twelve positive prediction requests from separate malformed-input rejection checks.", optional=True)
    edit("| 独立推理检查请求总数 | 12 个（包含正常请求与拒绝情形） |", "| 与冻结预测比对的有效历史请求数 | 12 个；另有独立非法输入拒绝检查 |", "Correct the auditor's conflation of twelve successful predictions with the separate negative-input checks.", optional=True)
    edit("本次全局搜索时钟累计为 `10800.4204284` 秒，完成了配置为 10800 秒（3 小时）的全局搜索预算。搜索记录共 35 个节点（含根节点），其中 `candidate_node_count=34`、`search_candidate_count=25`、`failed_node_count=9`；这些引擎统计字段不能改写为“25 个接受候选”或“9 个拒绝候选”。第 5 节仅展示 6 个已接受且经后续行级复核可比较的候选。", "本次全局搜索时钟累计为 `10800.4204284` 秒，完成 3 小时预算。原始搜索记录共 35 个节点（含根节点）、34 个候选。逐节点核验确认 25 个节点同时满足 `search_eligible=true`、`is_buggy=false`、`is_valid=true`；另外 9 个候选被拒绝。第 5 节展示其中 6 个已接受且经后续行级复核可比较的候选。", "Use independently counted original journal flags instead of conflating the six displayed candidates with the complete search.", optional=True)
    edit("本次全局搜索时钟累计约为 `10800.42` 秒。", "本次全局搜索时钟累计为 `10800.4204284` 秒，达到 3 小时要求。搜索记录共 35 个节点（含根节点），其中 34 个候选、25 个接受候选、9 个拒绝候选；第 5 节展示的是 6 个代表性接受候选。", "Report complete search counts separately from the displayed comparison subset.", optional=True)
    edit("最终模型曾请求 GPU 执行，但 CatBoost 在解析 GPU 参数时出现错误，随后安全回退到 CPU。", "最终模型曾请求 GPU 执行，但安装的 CatBoost 拒绝解析整数 `pinned_memory_bytes=268435456`，随后回退到 CPU；该失败是参数兼容问题，并非显存不足。", "Identify the recorded parameter parsing failure instead of implying a resource OOM.", optional=True)
    edit("最佳节点处于“融合阶段”，其记录中包含多个技术来源节点。该标签只能说明代码和思路存在技术迁移或组合来源，不能自动证明最终模型是多模型融合。", "实际 MCTS 搜索执行了跨分支融合操作并产生最佳节点，来源为 `a3c73aebc04f477bb86aa31e3841dd9a`、`7a266be671cf4d42911e607d3e2f8b86`、`101999e58a1043ceafd1c8c157df5d71`。这是已执行的搜索操作，其产出的最终代码采用技术迁移与组合；最终预测器本身仍是单模型，不能因此称为加权多模型集成。", "Retain the actual executed cross-branch search operation while accurately identifying the single final predictor.", optional=True)
    edit("最佳节点记录列出了跨分支技术来源：`a3c73aebc04f477bb86aa31e3841dd9a`、`7a266be671cf4d42911e607d3e2f8b86`、`101999e58a1043ceafd1c8c157df5d71`。这说明该搜索节点继承了相应的技术来源；结合最终执行代码和最终训练配方，最终预测器本身仍是单模型，不能因此称为加权多模型集成。", "原始搜索记录确认最佳节点实际执行了 `fusion` 跨分支搜索操作，来源为 `a3c73aebc04f477bb86aa31e3841dd9a`、`7a266be671cf4d42911e607d3e2f8b86`、`101999e58a1043ceafd1c8c157df5d71`。这一搜索操作完成了技术迁移与组合；冻结执行代码和最终工件仍是单个 CatBoost 预测器，不能因此称为加权多模型集成。", "Restore the executed fusion operation established by the original selected node record, without claiming an ensemble predictor.", optional=True)
    revised = apply_audit_edits(article, {"status": "revised" if corrections else "pass", "issues": findings, "edits": corrections})
    lines = revised.splitlines(keepends=True)
    headings = [token for token in MarkdownIt("commonmark").parse(revised)
        if token.type == "heading_open" and token.level == 0 and token.markup.startswith("#")]
    primary = [token for token in headings if token.tag == "h1"]
    if len(primary) == 10:
        for token in headings:
            index = token.map[0]
            lines[index] = "#" + lines[index]
        revised = "# 压滤液铝浓度预测方案交付报告\n\n" + "".join(lines)
        findings.append("Normalize ten primary sections to H2 and subordinate headings below them so the frontend renders the actual report outline.")
    cfg, bundle, _ = module("measure-report-context").source_bundle("chemical")
    cfg = config_from_dict(report["config"])
    cfg.task_name, cfg.report_title, cfg.output_dir = "压滤液铝浓度预测", "压滤液铝浓度预测方案交付报告", str(dest)
    entry = module("validate-industrial-prompts").model_entry()
    cfg.llm.api_key = entry["apiKey"]
    report.update(task_name=cfg.task_name, report_title=cfg.report_title, config=dump_config(cfg))
    trace["task_name"] = cfg.task_name
    _validate_report_article(cfg, revised, require_outline=True)
    reviewed = {"source_sha256": hashlib.sha256(article.encode("utf-8")).hexdigest(), "status": "revised",
        "issues": findings, "edits": [{"old": article, "new": revised, "expected_count": 1}],
        "atomic_content_edits": corrections, "heading_edits": "One level deeper for parsed Markdown headings, plus an explicit task title"}
    dest.mkdir(parents=True)
    save(dest / "independent-editorial-edits.json", reviewed)
    journal = read(Path(task["auto_ml_log_dir"]) / "journal.json")
    node_flags = [{key: node.get(key) for key in ("id", "stage", "search_eligible", "is_buggy", "is_valid", "fusion_sources", "evaluation_protocol")} for node in journal["nodes"]]
    assert len(node_flags) == 35 and sum(node["search_eligible"] is True and node["is_buggy"] is False and node["is_valid"] is True for node in node_flags) == 25
    save(dest / "independent-source-evidence.json", {"source_fingerprint": fingerprint,
        "implementation_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(), "verified_function_sources": functions,
        "original_journal_node_flags": node_flags,
        "independent_verification": read(workspace / "final_evaluation/independent-verification.json")})
    if args.draft_only:
        (dest / "report_draft.md").write_text(revised, encoding="utf-8")
        shutil.copy2(source / "report_analysis.json", dest / "report_analysis.json")
        shutil.copy2(source / "llm_usage.jsonl", dest / "llm_usage.jsonl")
        save(dest / "result.json", {"passed": False, "installation_allowed": False, "slug": "chemical",
            "source_fingerprint": fingerprint, "output_limit": 32768, "draft_independently_edited": True,
            "original_production_directory": str(source), "findings_corrected": findings,
            "scope": "Independently corrected draft derived from the real writer; a complete provider audit and exact example verification are still required"})
        print(json.dumps({"directory": str(dest), "passed": False, "draft_ready_for_audit": True}))
        return
    value = revise_existing_report(cfg, bundle, ReportEventWriter(dest, print_events_to_console=False), report, trace, reviewed_edits=reviewed)
    write_config_yaml(cfg, dest / "resolved_config.yaml")
    unchanged = fingerprint == stages.fingerprint(stages.stage_artifacts(task, "automl"))
    result = {"passed": unchanged, "installation_allowed": False, "source_fingerprint": fingerprint,
        "source_unchanged": unchanged, "source_directory": str(source), "findings_corrected": findings,
        "sections": len(value["sections"]), "scope": "Full provider audit followed by independently grounded editorial corrections; exact example execution and final acceptance still required"}
    save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), "passed": unchanged, "sections": len(value["sections"])}))


if __name__ == "__main__":
    main()

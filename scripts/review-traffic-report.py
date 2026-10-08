"""Apply evidence-backed independent edits after the real full traffic report audit."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoReport"))
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
    import joblib
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    source, dest = args.source.resolve(), args.directory.resolve()
    if dest.exists() or not all(path.is_relative_to(OUT.resolve()) for path in (source, dest)):
        raise RuntimeError("A fresh reviewed report directory inside this batch is required")
    source_result = read(source / "result.json")
    if source_result.get("passed") is not True:
        raise RuntimeError("The real writer and full audit must complete first")
    stages = module("industrial-stage-control")
    task = stages.current_task("traffic")
    fingerprint = stages.fingerprint(stages.stage_artifacts(task, "automl"))
    if fingerprint != source_result["source_fingerprint"]:
        raise RuntimeError("AutoML artifacts changed after the production report generation")
    workspace = Path(task["auto_ml_workspace_dir"])
    exported = workspace / "best_solution"
    manifest = read(exported / "solution_manifest.json")
    implementation = exported / manifest["implementation_path"]
    code = implementation.read_text(encoding="utf-8")
    functions = {node.name: ast.get_source_segment(code, node) for node in ast.parse(code).body
                 if isinstance(node, ast.FunctionDef) and node.name in {"final_evaluate", "_coerce_fixed_dataset", "train", "predict", "infer_new_data", "main"}}
    model_relative = (exported / "model_path.txt").read_text(encoding="utf-8").strip()
    model_path = exported / model_relative
    model = joblib.load(model_path)
    assert model["training_window"] == {"start": "2025-11-01 00:00:00", "end": "2025-11-07 00:00:00", "origin_count": 1717}
    assert model["ensemble_config"]["poisson_weights"] == {"30": 0.48, "60": 0.84}
    diagnostics_path = workspace / "final_evaluation/artifacts/final_evaluation/holdout_per_gantry_diagnostics.csv"
    diagnostics = pd.read_csv(diagnostics_path, dtype={"gantry_id": str})
    assert len(diagnostics) == 318 and diagnostics["gantry_id"].nunique() == 159
    assert diagnostics["sample_count"].eq(277).all()
    evidence = {"source_fingerprint": fingerprint, "function_source": functions,
        "model_path": str(model_path), "model_size_bytes": model_path.stat().st_size,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "model_metadata": {key: model[key] for key in ("training_window", "ensemble_config", "fit_seconds")},
        "manifest": manifest, "independent_verification": read(workspace / "final_evaluation/independent-verification.json"),
        "final_per_gantry_diagnostics": {"path": str(diagnostics_path), "rows": len(diagnostics),
            "gantries": diagnostics["gantry_id"].nunique(), "samples_per_gantry_horizon": 277,
            "sha256": hashlib.sha256(diagnostics_path.read_bytes()).hexdigest()}}
    cfg, bundle, _ = module("measure-report-context").source_bundle("traffic")
    cfg.task_name, cfg.output_dir = "门架车流预测", str(dest)
    report, trace = read(source / "report.json"), read(source / "report_trace.json")
    article = report["article_markdown"]
    _validate_report_article(cfg, article, require_outline=True)
    edits, findings = [], []

    def edit(old, new, finding):
        if old == new:
            return
        if article.count(old) != 1:
            raise RuntimeError("Independent exact edit must match once: " + old[:90])
        edits.append({"old": old, "new": new, "expected_count": 1})
        findings.append(finding)

    def subsection(number, replacement, finding):
        pattern = rf"(?ms)^### {re.escape(number)} [^\n]*\n.*?(?=^###? |\Z)"
        matches = re.findall(pattern, article)
        if len(matches) != 1:
            raise RuntimeError("Expected one subsection: " + number)
        edit(matches[0], replacement.rstrip() + "\n\n", finding)

    subsection("4.6", f"""### 4.6 搜索模型、最终重训模型与验证范围

搜索阶段模型只使用 `[2025-11-01, 2025-11-06)` 的标签拟合基础专家和滚动 OOF 融合权重，共 1,429 个共同起点。选定配置冻结后，实际 `final_evaluate()` 以 `[2025-11-01, 2025-11-07)` 的前六日数据重新拟合基础专家，共 1,717 个共同起点；融合配方与已选权重保持冻结，第七日标签未参与重新选择。

| 项目 | 最终保存工件中的记录 |
|---|---|
| 模型工件大小 | {model_path.stat().st_size:,} 字节 |
| 特征数 | 92 |
| 最终基础专家训练窗口 | `[2025-11-01 00:00:00, 2025-11-07 00:00:00)` |
| 最终训练共同起点数 | 1,717 |
| Poisson 专家融合权重 | 30 分钟 0.48；60 分钟 0.84 |
| 对数 L1 专家融合权重 | 30 分钟 0.52；60 分钟 0.16 |
| 最终基础专家拟合耗时 | 30 分钟约 31.02 秒；60 分钟约 29.01 秒 |

后续独立验证记录的“搜索与最终模型文件未改变”，表示验证过程没有改写各自已存在的工件，不表示搜索模型与最终模型字节相同，也不表示未进行前六日重训。现有 `train()` 的默认复现范围仍是前五日拟合集，不能把其默认输出当成六日重训后的最终模型。
""", "Correct the false no-refit claim using actual final_evaluate source and saved final model metadata; distinguish subsequent immutable verification.")
    unknown_weight = "当前记录未提供两个跨度最终选中权重的具体数值，因此不能编造其值。"
    if unknown_weight in article:
        edit(unknown_weight, "保存工件中的 Poisson 权重分别为 30 分钟 0.48、60 分钟 0.84，对数 L1 权重为对应补数。", "The selected weights exist in the saved model and must not be called unknown.")
    if "| 搜索候选数 | 16 |" in article:
        edit("| 搜索候选数 | 16 |", "| 搜索候选总数 | 24 |\n| 有已接受有效分数的候选数 | 16 |", "Distinguish all 24 candidates from 16 accepted scored candidates.")
    missing_diagnostics = "当前材料只确认候选工件中存在 `development_per_gantry_diagnostics.csv`，未提供其中的逐门架数值；因此不编造逐门架 MAE、RMSE 或误差分布。"
    if missing_diagnostics in article:
        edit(missing_diagnostics, "最终逐门架诊断已保存在 `final_evaluation/artifacts/final_evaluation/holdout_per_gantry_diagnostics.csv`（路径相对于 7.1 节工作目录），共 318 行，即 159 门架 × 2 跨度，每行 277 个起点。文件包含逐门架 MAE、RMSE、误差分位数和回退覆盖计数；完整 88,086 行最终预测保存在同目录的 `holdout_predictions.csv`。", "Verify and expose the existing final per-gantry diagnostics and full prediction artifacts rather than calling their values unavailable.")
    subsection("7.1", f"""### 7.1 已存在的可加载工件

以下路径以本次 AutoML 工作目录为根目录：

```text
{workspace}
```

| 工件 | 相对上述根目录的实际路径 |
|---|---|
| 公共 Python 封装 | `best_solution/solution.py` |
| 冻结实现文件 | `best_solution/{manifest['implementation_path']}` |
| 最终模型工件 | `best_solution/{Path(model_relative).as_posix()}` |
| 模型路径记录 | `best_solution/model_path.txt` |
| 导出清单 | `best_solution/solution_manifest.json` |
| 搜索阶段选定配方 | `final_evaluation/artifacts/selected_recipe.json` |
| 最终评估结果 | `final_evaluation/result.json` |
| 完整最终预测 | `final_evaluation/artifacts/final_evaluation/holdout_predictions.csv` |
| 最终逐门架诊断 | `final_evaluation/artifacts/final_evaluation/holdout_per_gantry_diagnostics.csv` |
| 最终模型与推理独立复核 | `final_evaluation/independent-verification.json` |
| 训练与开发推理复现记录 | `best_solution/inference-verification.json` |

模型路径中嵌套的 `final_evaluation/artifacts` 是实际导出布局，不能自行省略。通过 `solution.default_model_path()` 获取默认工件路径。公开入口有 `predict(model_path, data)` 和 `train(data, artifact_dir)`，封装还通过 `__getattr__` 提供 `infer_new_data(model_path, input_dir, output_dir, forecast_origins)`。
""", "Replace guessed model paths with the exact exported manifest path and clearly anchored real files.")
    subsection("7.2", f'''### 7.2 Python 方式加载和预测

以下示例使用当前已提供的原始事件 CSV 和三个已保存的最终预测起点，加载冻结模型，返回 954 行预测。替换为业务新数据时，应提供真实输入路径和请求起点；本例复现不代表未知业务新数据已经验收。

```python
from pathlib import Path
import sys
import numpy as np
import pandas as pd

WORKSPACE = Path(r"{workspace}")
sys.path.insert(0, str(WORKSPACE / "best_solution"))
import solution

model_path = solution.default_model_path()
input_dir = WORKSPACE / "input"
events = pd.read_csv(
    input_dir / "tmp_gantry_trade_info_split1_20251224_7d_hechi_result.csv",
    encoding="utf-8-sig",
    usecols=["门架id", "门架时间"],
    dtype={{"门架id": "string", "门架时间": "string"}},
    on_bad_lines="error",
)
forecast_origins = [
    "2025-11-07 00:00:00",
    "2025-11-07 11:30:00",
    "2025-11-07 23:00:00",
]
moments = pd.to_datetime(events["门架时间"], dayfirst=True, errors="raise")
events = events.loc[moments < pd.Timestamp(forecast_origins[-1])].copy()
prediction = solution.predict(
    model_path,
    {{"events": events, "forecast_origins": forecast_origins}},
)
print(prediction.head())
```

`predict()` 返回 `pandas.DataFrame`，列顺序为 `gantry_id, forecast_origin, horizon_minutes, predicted_count`。原始事件可以包含比某个较早请求起点更晚的记录，接口会为每个起点严格截取其可见历史；恰等于该起点的事件不能进入该起点特征。事件时间本身不必整除 5 分钟，请求预测起点必须对齐 5 分钟边界。调用方仍需确定共同起点、分区边界和门架映射，不能将分区外目标加入评分。
''', "Replace fabricated business input paths with a concrete reproducible example; correct event-time versus forecast-origin alignment and per-origin causal filtering.")
    subsection("7.3", '''### 7.3 使用目录式独立推理入口

在上一段导入和变量定义后执行：

```python
output_dir = Path("traffic_inference_output").resolve()
output = solution.infer_new_data(
    model_path=model_path,
    input_dir=input_dir,
    output_dir=output_dir,
    forecast_origins=forecast_origins,
)
print(output)
```

该入口读取固定原始 CSV 文件名，按每个起点截取因果历史，在新输出目录实际保存以下文件：

```text
submission_0dbdc708fc074653a2b0490009760a40.csv
fallback_audit.csv
inference_causal_audit.json
inference_run_audit.json
```

预测 CSV 默认文件名来自实现，尚不能称为业务方确认的官方文件名。本例中的目录写出与 API 返回会独立核对，预测时不执行训练。
''', "Provide a concrete output-directory invocation linked to the verified input and prediction variables.")
    subsection("7.4", f'''### 7.4 命令行推理入口

冻结实现 `best_solution/{manifest['implementation_path']}` 的 `main()` 提供 `--mode infer`、`--model-path`、`--input-dir`、`--output-dir`、`--origins-csv` 参数。起点 CSV 必须包含 `forecast_origin` 列。公共 `solution.py` 仅作为可导入封装，直接执行该包装文件不会自动运行实现的命令行入口。

本报告已执行复现的交付路径是上述 Python API 与目录推理接口。命令行入口存在的依据是冻结源码，未将未经单独执行的命令行示例称为已验收业务流程。已有 954 行迁移推理复核、原始事件与面板等价检查、合成未来事件排除检查共同限定软件验证范围；真实新业务数据仍需满足原任务输入与输出合同。
''', "Remove an unverified command with a nonexistent model path while retaining the actual CLI entrypoint and its validation scope.")
    subsection("7.5", '''### 7.5 结果返回后的校验

在以上两段示例之后执行，检查数据类型、列、完整键集合、非负有限值，以及目录输出与 API 返回的一致性：

```python
expected_columns = [
    "gantry_id", "forecast_origin", "horizon_minutes", "predicted_count",
]
assert prediction.columns.tolist() == expected_columns
values = prediction["predicted_count"].to_numpy(dtype=float)
assert np.isfinite(values).all() and (values >= 0).all()
keys = ["gantry_id", "forecast_origin", "horizon_minutes"]
assert not prediction.duplicated(keys).any()
assert len(prediction) == 159 * len(forecast_origins) * 2
assert prediction["gantry_id"].nunique() == 159
assert set(prediction["horizon_minutes"]) == {{30, 60}}

def align(frame):
    frame = frame.copy()
    frame["gantry_id"] = frame["gantry_id"].astype(str)
    frame["forecast_origin"] = pd.to_datetime(frame["forecast_origin"])
    return frame.set_index(keys)["predicted_count"].sort_index()

saved = pd.read_csv(
    output_dir / "submission_0dbdc708fc074653a2b0490009760a40.csv",
    dtype={{"gantry_id": str}},
)
pd.testing.assert_series_equal(
    align(saved), align(prediction), check_exact=False, rtol=1e-10, atol=1e-8,
)
```

本例的 159 门架数量来自冻结工件，业务接入时必须核对完整冻结门架 ID 集合、请求起点、输入映射与输出文件合同。回退记录保留在独立文件，不加入四列主结果表。
'''.replace("{{", "{").replace("}}", "}"), "Strengthen the executable output check to reject infinity and compare persisted predictions with API values.")
    subsection("8.2", f'''### 8.2 已提供的训练入口

`train(data, artifact_dir)` 实际接受固定数据目录，也接受包含 `panel`、`timeline`、`gantry_ids`、`fit_origins` 的已核验字典。以下完整示例从本次固定数据目录重新训练前五日搜索配方；它不执行候选搜索或最终留出评分，输出不是六日重训后的最终模型。

```python
from pathlib import Path
import sys

WORKSPACE = Path(r"{workspace}")
sys.path.insert(0, str(WORKSPACE / "best_solution"))
import solution

artifact_path = solution.train(
    data=WORKSPACE / "input",
    artifact_dir=Path("traffic_retrained_artifacts").resolve(),
)
print(artifact_path)
```

固定目录必须包含本次精确命名、物理字段和时间范围的车流 CSV 与关系工作簿。该入口可读取目录，但不保证任意业务 CSV 都满足合同。训练只在前五日标签上拟合基础模型与滚动 OOF 权重，保存模型、配方、门架及特征元数据和拟合审计；后续开发预测的独立复现检查不改变原始模型或最终评估。

原始执行代码保留于 `node_runs/0dbdc708fc074653a2b0490009760a40/runfile_0.py`，路径相对于 7.1 节定义的工作目录。
''', "Replace undefined prepared_fixed_dataset with the actual supported fixed-directory training API and clarify its five-day scope.")
    dest.mkdir(parents=True)
    reviewed = {"source_sha256": hashlib.sha256(article.encode("utf-8")).hexdigest(),
                "status": "revised", "issues": findings, "edits": edits}
    save(dest / "independent-editorial-edits.json", reviewed)
    save(dest / "independent-source-evidence.json", evidence)
    revised = revise_existing_report(cfg, bundle, ReportEventWriter(dest, print_events_to_console=False),
                                    report, trace, reviewed_edits=reviewed)
    _validate_report_article(cfg, revised["article_markdown"], require_outline=True)
    unchanged = fingerprint == stages.fingerprint(stages.stage_artifacts(task, "automl"))
    result = {"passed": unchanged, "installation_allowed": False, "source_unchanged": unchanged,
        "source_fingerprint": fingerprint, "source_directory": str(source), "required_outline_validated": True,
        "report_fingerprints": {name: hashlib.sha256((dest / name).read_bytes()).hexdigest()
                                for name in ("report.md", "report.json", "report_trace.json")},
        "scope": "Real full-source provider audit followed by evidence-backed independent exact edits. Runnable example verification and final factual review remain required before installation.",
        "findings_corrected": findings}
    save(dest / "result.json", result)
    print(json.dumps({"directory": str(dest), "passed": result["passed"], "installation_allowed": False}))


if __name__ == "__main__":
    main()

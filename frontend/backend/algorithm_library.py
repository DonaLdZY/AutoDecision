"""Reusable algorithm-package library.

A completed task distills its delivered solution into an on-disk package card
(``runs/algorithm-library/<package_id>/package_card.json``).  A new task can
then match its data signature against these cards and either reuse a package
directly (retrain only) or warm-start the search with the package solution.

The Studio package catalog remains the place for user-published, callable
models.  This library is an internal, read-only reuse index and deliberately
does not register anything in that catalog.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_ROOT = Path(os.environ.get("AUTODECISION_ALGORITHM_LIBRARY", str(APP_ROOT / "runs" / "algorithm-library"))).expanduser()
logger = logging.getLogger(__name__)

CARD_FILENAME = "package_card.json"
_SKIP_NAMES = {"__pycache__", "*.pyc", "runtime"}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    temporary.replace(path)


def _normal(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _numeric(value: str) -> float | None:
    try:
        number = float(str(value).strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        return columns, [{key: (row.get(key) or "") for key in columns} for row in reader]


def _profile(columns: list[str], rows: list[dict[str, str]], excluded: set[str]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for column in columns:
        if column in excluded:
            continue
        values = [row.get(column, "") for row in rows]
        present = [value for value in values if str(value).strip() != ""]
        numbers = [_numeric(value) for value in present]
        numeric = bool(present) and all(number is not None for number in numbers)
        entry: dict[str, Any] = {
            "name": column,
            "type": "number" if numeric else "string",
            "missing_rate": round(1 - len(present) / max(1, len(values)), 4),
        }
        if numeric:
            entry["range"] = [min(numbers), max(numbers)]
        fields.append(entry)
    return fields


def task_signature(autorealize_dir: Path) -> dict[str, Any]:
    autorealize_dir = Path(autorealize_dir)
    train_columns, train_rows = _table(autorealize_dir / "train.csv")
    predict_columns, predict_rows = _table(autorealize_dir / "predict.csv")
    extra = [column for column in train_columns if column not in predict_columns]
    target = extra[-1] if extra else ""
    paradigm = read_json(autorealize_dir / "realize_report" / "problem_paradigm_report.json", {}) or {}
    context = read_json(autorealize_dir / "realize_report" / "automl_context_pack.json", {}) or {}
    contract = (read_json(autorealize_dir / "realize_report" / "evaluation_contract_report.json", {}) or {}).get("final") or {}
    structure = str(paradigm.get("problem_structure") or context.get("problem_structure") or "").strip()
    family = "decision" if any(word in structure.lower() for word in ("optimization", "decision", "reinforcement")) else (
        "prediction" if structure else ""
    )
    target_values = [str(row.get(target, "")).strip() for row in train_rows] if target else []
    observed = {value for value in target_values if value}
    binary = bool(observed) and observed <= {"0", "1", "0.0", "1.0", "true", "false"}
    if binary:
        target_type = "classification"
        positives = sum(1 for value in target_values if value.lower() in {"1", "1.0", "true"})
        positive_rate = round(positives / max(1, len([value for value in target_values if value])), 6)
    elif observed:
        target_type = "regression"
        positive_rate = None
    else:
        target_type = ""
        positive_rate = None
    metric = str(contract.get("primary_metric") or "").strip()
    direction = str(contract.get("metric_direction") or "").strip()
    return {
        "problem_family": family,
        "target_type": target_type,
        "metric": metric,
        "metric_key": metric_key(metric),
        "direction": direction,
        "target_column": target,
        "row_count": len(train_rows),
        "positive_rate": positive_rate,
        "fields": _profile(predict_columns, predict_rows, {target}),
    }


def metric_key(text: str) -> str:
    value = str(text or "").lower()
    if "average precision" in value or "平均精度" in value or re.search(r"\bap\b", value):
        return "average_precision"
    if "roc" in value or "auc" in value:
        return "auc"
    if "accuracy" in value or "准确率" in value:
        return "accuracy"
    if "f1" in value:
        return "f1"
    if "rmse" in value or "均方根误差" in value:
        return "rmse"
    if "mae" in value or "平均绝对误差" in value:
        return "mae"
    return _normal(value)[:80]


def _field_map(signature: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {_normal(field.get("name", "")): field for field in signature.get("fields") or []}


def hard_mismatch(new: dict[str, Any], old: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key, label in (("problem_family", "问题族"), ("target_type", "目标类型"), ("metric_key", "评价指标"), ("direction", "指标方向")):
        left, right = str(new.get(key) or ""), str(old.get(key) or "")
        if left and right and left != right:
            reasons.append(f"{label}不一致：{left} != {right}")
    old_fields = _field_map(old)
    new_fields = _field_map(new)
    missing = [field["name"] for key, field in old_fields.items() if key not in new_fields]
    if missing:
        reasons.append("缺少输入字段：" + "、".join(missing[:6]) + (" 等" if len(missing) > 6 else ""))
    for key, field in old_fields.items():
        current = new_fields.get(key)
        if current and field.get("type") and current.get("type") and field["type"] != current["type"]:
            reasons.append(f"字段类型不一致：{field['name']} {field['type']} != {current['type']}")
    return reasons


def similarity(new: dict[str, Any], old: dict[str, Any], weights: dict[str, float]) -> tuple[float, dict[str, float]]:
    new_fields, old_fields = _field_map(new), _field_map(old)
    shared = set(new_fields) & set(old_fields)
    union = set(new_fields) | set(old_fields)
    field_score = len(shared) / max(1, len(union))
    overlaps = []
    for key in shared:
        left, right = new_fields[key], old_fields[key]
        if left.get("type") == right.get("type") == "number":
            a = left.get("range") or [0, 0]
            b = right.get("range") or [0, 0]
            low, high = max(a[0], b[0]), min(a[1], b[1])
            span = max(a[1], b[1]) - min(a[0], b[0])
            overlaps.append(max(0.0, high - low) / span if span else 1.0)
        else:
            overlaps.append(1.0)
    range_score = sum(overlaps) / len(overlaps) if overlaps else 0.0
    new_rows, old_rows = new.get("row_count") or 0, old.get("row_count") or 0
    row_score = min(new_rows, old_rows) / max(1, max(new_rows, old_rows)) if new_rows and old_rows else 0.0
    new_rate, old_rate = new.get("positive_rate"), old.get("positive_rate")
    positive_score = 1 - abs(float(new_rate) - float(old_rate)) / max(0.001, max(float(new_rate), float(old_rate))) if new_rate is not None and old_rate is not None else 0.0
    parts = {"fields": field_score, "ranges": range_score, "rows": row_score, "positives": positive_score}
    total = sum(parts[name] * weights.get(name, 0.0) for name in parts)
    return round(max(0.0, min(1.0, total)), 4), {name: round(value, 4) for name, value in parts.items()}


def load_cards() -> list[dict[str, Any]]:
    cards = []
    if not LIBRARY_ROOT.is_dir():
        return cards
    for path in sorted(LIBRARY_ROOT.glob(f"*/{CARD_FILENAME}")):
        card = read_json(path, {})
        if isinstance(card, dict) and card.get("package_id"):
            card["_card_path"] = str(path)
            card["_package_dir"] = str(path.parent)
            cards.append(card)
    return cards


def _workspace_file(task: Any, filename: str) -> Path | None:
    run_dir = Path(task.run_dir).expanduser().resolve() if getattr(task, "run_dir", "") else None
    if run_dir is None:
        return None
    hits = sorted(run_dir.glob(f"automl/workspaces/*/{filename}"))
    return hits[0] if hits else None


def _delivered_dir(task: Any, facts: dict[str, Any]) -> tuple[Path | None, str]:
    workspace = Path(task.auto_ml_workspace_dir).expanduser().resolve() if getattr(task, "auto_ml_workspace_dir", "") else None
    if workspace is None:
        manifest = _workspace_file(task, "solution_manifest.json")
        workspace = manifest.parent.parent if manifest else None
    if workspace is None:
        return None, ""
    relative = str(((facts.get("交付物") or {}) if isinstance(facts.get("交付物"), dict) else {}).get("交付目录") or "").strip()
    if relative:
        candidate = (workspace / relative).resolve()
        if candidate.is_dir():
            return candidate, relative
    candidate = workspace / "best_solution"
    return (candidate, "best_solution") if candidate.is_dir() else (None, "")


def _journal_node(log_dir: Path | None, node_id: str) -> dict[str, Any] | None:
    if log_dir is None:
        return None
    journal = read_json(log_dir / "journal.json", {}) or {}
    for node in journal.get("nodes") or []:
        if isinstance(node, dict) and str(node.get("id")) == node_id:
            return node
    return None


def distill_task_package(task: Any, *, version: str = "") -> dict[str, Any]:
    """Write one package card for a completed task. Never raise to the caller."""
    run_dir = Path(task.run_dir).expanduser().resolve() if getattr(task, "run_dir", "") else None
    if run_dir is None or not run_dir.is_dir():
        return {"status": "skipped", "reason": "任务没有运行目录"}
    report_dir = Path(task.report_dir).expanduser().resolve() if getattr(task, "report_dir", "") else run_dir / "report"
    facts = read_json(report_dir / "producer_facts.json", {}) or {}
    if not isinstance(facts, dict) or not facts:
        return {"status": "skipped", "reason": "没有生产者版事实数据，无法完成先验知识检查"}
    competition = facts.get("算法竞争") if isinstance(facts.get("算法竞争"), dict) else {}
    reselection = competition.get("改选说明") if isinstance(competition.get("改选说明"), dict) else {}
    chosen = reselection.get("改用方案编号", competition.get("胜出编号"))
    try:
        chosen = int(chosen)
    except (TypeError, ValueError):
        return {"status": "skipped", "reason": "没有可确认的交付方案编号"}
    candidates = {int(row.get("编号")): row for row in competition.get("候选") or [] if isinstance(row, dict) and str(row.get("编号", "")).isdigit()}
    delivered = candidates.get(chosen) or {}
    if delivered.get("借用已知规则"):
        return {"status": "skipped", "reason": f"交付方案 #{chosen} 引用了已知名称或阈值"}
    prior = facts.get("先验知识检查") if isinstance(facts.get("先验知识检查"), dict) else {}
    if f"#{chosen}" in {str(key) for key in (prior.get("明细") or {})}:
        return {"status": "skipped", "reason": f"交付方案 #{chosen} 引用了已知名称或阈值"}
    source_dir, relative = _delivered_dir(task, facts)
    if source_dir is None or not (source_dir / "solution.py").is_file():
        return {"status": "skipped", "reason": "找不到交付方案目录"}
    manifest = read_json(source_dir / "solution_manifest.json", {}) or {}
    log_dir = Path(task.auto_ml_log_dir).expanduser().resolve() if getattr(task, "auto_ml_log_dir", "") else None
    if log_dir is None:
        hits = sorted(run_dir.glob("automl/logs/*/journal.json"))
        log_dir = hits[0].parent if hits else None
    node = _journal_node(log_dir, str(manifest.get("node_id") or ""))
    package_id = str(task.id)
    target_dir = LIBRARY_ROOT / package_id
    temporary = LIBRARY_ROOT / f".{package_id}.{os.getpid()}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    shutil.copytree(source_dir, temporary / "solution", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runtime"))
    autorealize_dir = run_dir / "autorealize"
    signature = task_signature(autorealize_dir)
    warning = facts.get("预警效果") if isinstance(facts.get("预警效果"), dict) else {}
    single = warning.get("单一指标说明") if isinstance(warning.get("单一指标说明"), dict) else {}
    card = {
        "schema_version": "autodecision.algorithm_library.card.v1",
        "package_id": package_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {
            "task_id": str(task.id),
            "task_name": str(task.task_name),
            "run_dir": str(run_dir),
            "report_dir": str(report_dir),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "version": version,
        },
        "solution": {
            "directory": "solution",
            "node_id": str(manifest.get("node_id") or ""),
            "node_number": chosen,
            "method_family": str(competition.get("胜出方法") or manifest.get("method_family") or ""),
            "kind": str(manifest.get("kind") or ""),
            "entrypoint": str(manifest.get("entrypoint") or ""),
            "artifact_path": str(manifest.get("artifact_path") or ""),
            "source_relative_dir": relative,
            "journal_node": node or {},
        },
        "signature": signature,
        "scores": {
            "development": competition.get("系统选中方案的自报验证成绩"),
            "verification": competition.get("系统选中方案的验收集成绩"),
            "verification_source": "统一复算（保管的答案）",
            "single_metric": single.get("验收集平均精度"),
            "single_metric_name": single.get("指标"),
            "reuse_check": facts.get("交付物", {}).get("复用核对") if isinstance(facts.get("交付物"), dict) else {},
        },
        "experience": {
            "winning_method_family": str(competition.get("胜出方法") or manifest.get("method_family") or ""),
            "composite_metrics": (facts.get("发现") or {}).get("最终方案自己构造的组合指标（摘自代码）") if isinstance(facts.get("发现"), dict) else [],
            "failed_families": _failed_families(log_dir),
            "prior_knowledge": {
                "checked": prior.get("检查的方案数"),
                "flagged": prior.get("引用了已知名称或阈值的方案数"),
                "reselection": reselection,
            },
        },
    }
    write_json(temporary / CARD_FILENAME, card)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    temporary.replace(target_dir)
    logger.info("Distilled algorithm package card %s from task %s", target_dir, task.id)
    return {"status": "created", "package_id": package_id, "card": str(target_dir / CARD_FILENAME)}


def _failed_families(log_dir: Path | None) -> list[dict[str, Any]]:
    if log_dir is None:
        return []
    journal = read_json(log_dir / "journal.json", {}) or {}
    counts: dict[str, dict[str, Any]] = {}
    for node in journal.get("nodes") or []:
        if not isinstance(node, dict) or node.get("stage") == "root":
            continue
        failed = node.get("is_buggy") is True or node.get("runtime_ok") is False or node.get("valid") is False
        if not failed:
            continue
        family = str(node.get("method_family") or "unknown")
        row = counts.setdefault(family, {"method_family": family, "count": 0, "reason": ""})
        row["count"] += 1
        if not row["reason"]:
            row["reason"] = str(node.get("exc_type") or node.get("exc_info") or node.get("stage") or "")[:240]
    return sorted(counts.values(), key=lambda row: -row["count"])


def _weights(config: Any) -> dict[str, float]:
    return {
        "fields": float(getattr(config, "reuse_field_weight", 0.5)),
        "ranges": float(getattr(config, "reuse_range_weight", 0.25)),
        "rows": float(getattr(config, "reuse_row_weight", 0.15)),
        "positives": float(getattr(config, "reuse_positive_weight", 0.10)),
    }


def decide_reuse(task: Any, autorealize_dir: Path) -> dict[str, Any]:
    """Match the new task against the library and persist the decision."""
    config = task.config.auto_ml
    mode = str(getattr(config, "reuse_package_mode", "auto") or "auto")
    run_dir = Path(task.run_dir).expanduser().resolve()
    decision: dict[str, Any] = {
        "schema_version": "autodecision.reuse_decision.v1",
        "task_id": str(task.id),
        "task_name": str(task.task_name),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": mode,
        "signature": task_signature(autorealize_dir),
        "action": "normal",
        "reason": "",
        "package_id": "",
        "score": None,
        "thresholds": {
            "direct": float(getattr(config, "reuse_direct_threshold", 0.85)),
            "hot_start": float(getattr(config, "reuse_hot_start_threshold", 0.6)),
            "score_tolerance": float(getattr(config, "reuse_score_tolerance", 0.10)),
            "hot_start_step_ratio": float(getattr(config, "reuse_hot_start_step_ratio", 0.30)),
        },
        "estimated_saved_calls": 0,
    }
    path = run_dir / "reuse_decision.json"
    if mode == "off":
        decision["reason"] = "任务配置关闭了算法包复用"
        write_json(path, decision)
        return decision
    weights = _weights(config)
    ranked = []
    for card in load_cards():
        mismatch = hard_mismatch(decision["signature"], card.get("signature") or {})
        if mismatch:
            ranked.append({"package_id": card.get("package_id"), "score": None, "rejected": mismatch})
            continue
        score, parts = similarity(decision["signature"], card.get("signature") or {}, weights)
        ranked.append({"package_id": card.get("package_id"), "score": score, "parts": parts, "card": card})
    decision["candidates"] = [
        {key: value for key, value in row.items() if key != "card"} for row in ranked
    ]
    eligible = [row for row in ranked if row.get("score") is not None]
    if not eligible:
        rejected = [row for row in ranked if row.get("rejected")]
        decision["rejections"] = rejected[:5]
        first = rejected[0]["rejected"] if rejected else []
        decision["reason"] = "库中没有满足硬条件的算法包" + ("：" + "；".join(first[:3]) if first else "")
        write_json(path, decision)
        return decision
    best = max(eligible, key=lambda row: row["score"])
    decision["package_id"] = str(best["package_id"])
    decision["score"] = best["score"]
    direct, hot = decision["thresholds"]["direct"], decision["thresholds"]["hot_start"]
    if best["score"] < hot:
        decision["reason"] = f"最高相似度 {best['score']} 低于热启动阈值 {hot}"
        write_json(path, decision)
        return decision
    if mode == "hot_start_only":
        decision["reason"] = "任务配置只允许热启动"
        action = "hot_start"
    elif best["score"] >= direct:
        action = "direct_reuse"
        decision["reason"] = f"相似度 {best['score']} 达到直接复用阈值 {direct}"
    else:
        action = "hot_start"
        decision["reason"] = f"相似度 {best['score']} 位于热启动区间"
    decision["action"] = action
    decision["card"] = best["card"]
    if action == "hot_start":
        hot_paths = prepare_hot_start(decision, Path(best["card"]["_package_dir"]) / "solution", run_dir, config)
        decision["hot_start"] = hot_paths
        decision["estimated_saved_calls"] = max(0, int(getattr(config, "steps", 50)) - int(hot_paths["steps"]))
    else:
        decision["estimated_saved_calls"] = int(getattr(config, "steps", 50))
    decision.pop("card", None)
    write_json(path, decision)
    return decision


def prepare_hot_start(decision: dict[str, Any], solution_dir: Path, run_dir: Path, config: Any) -> dict[str, Any]:
    solution_code = (solution_dir / "solution.py").read_text(encoding="utf-8", errors="ignore")
    directory = run_dir / "reuse" / "coldstart"
    directory.mkdir(parents=True, exist_ok=True)
    exp_id = str(decision.get("task_name") or "")
    task_json = directory / "tasks.json"
    model_json = directory / "models.json"
    write_json(task_json, {"__package_reuse__": "Others"})
    write_json(
        model_json,
        {
            "Others": {
                f"复用算法包 {decision.get('package_id', '')}": {
                    "Description": (
                        "该方案来自库中相似任务的交付算法包。把它作为参考实现，沿用其数据读取、"
                        "特征处理与验证顺序；若数据结构不一致必须调整，并在交付说明中写明。"
                    ),
                    "Code_template": solution_code,
                    "Copy_exact": False,
                }
            }
        },
    )
    ratio = float(getattr(config, "reuse_hot_start_step_ratio", 0.30))
    steps = max(1, int(int(getattr(config, "steps", 50)) * ratio))
    return {
        "task_json_path": str(task_json),
        "model_json_path": str(model_json),
        "steps": steps,
        "package_solution": str(solution_dir / "solution.py"),
    }


_DIRECT_SCRIPT = r"""
import importlib.util, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

package, inputs, artifacts, out_csv, out_json = map(Path, sys.argv[1:6])
sys.path.insert(0, str(package))
spec = importlib.util.spec_from_file_location("reused_solution", package / "solution.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
train = pd.read_csv(inputs / "train.csv")
predict = pd.read_csv(inputs / "predict.csv")
sample = pd.read_csv(inputs / "sample_submission.csv")
artifacts.mkdir(parents=True, exist_ok=True)
result = module.train({"train": train, "predict": predict, "sample_submission": sample}, artifacts) or {}
models = sorted(artifacts.glob("*.joblib"))
if not models:
    raise RuntimeError("train() did not write a joblib artifact")
probabilities = module.predict(str(models[0]), {"predict": predict})
columns = list(sample.columns)
submission = pd.DataFrame({columns[0]: predict.iloc[:, 0].to_numpy(), columns[-1]: np.asarray(probabilities, dtype=float)})
submission.to_csv(out_csv, index=False, encoding="utf-8-sig")
out_json.write_text(json.dumps({"dev_score": result.get("dev_ap"), "model_file": models[0].name,
    "diagnostics": {key: value for key, value in result.items() if isinstance(value, (str, int, float, bool)) or value is None}},
    ensure_ascii=False), encoding="utf-8")
"""


def run_direct_reuse(card: dict[str, Any], task: Any, autorealize_dir: Path, workspace: Path, log_dir: Path, tolerance: float) -> dict[str, Any]:
    """Retrain the package on the new task data and score it on the dev split."""
    package_dir = Path(card["_package_dir"]) / "solution"
    workspace.mkdir(parents=True, exist_ok=True)
    best = workspace / "best_solution"
    if best.exists():
        shutil.rmtree(best)
    shutil.copytree(package_dir, best, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runtime"))
    inputs = workspace / "input"
    if inputs.exists():
        shutil.rmtree(inputs)
    shutil.copytree(autorealize_dir, inputs, ignore=shutil.ignore_patterns("realize_report", "__pycache__", "*.pyc"))
    artifacts = best / "model_artifacts" / "working" / "artifact"
    artifacts.mkdir(parents=True, exist_ok=True)
    out_csv = workspace / "best_solution" / "submission.csv"
    out_json = workspace / "reuse_result.json"
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _DIRECT_SCRIPT, str(best), str(inputs), str(artifacts), str(out_csv), str(out_json)],
            cwd=workspace, capture_output=True, text=True, timeout=1800,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"复用训练异常：{exc}"}
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-6:]
        return {"ok": False, "reason": "复用训练失败：" + " | ".join(tail)}
    result = read_json(out_json, {}) or {}
    dev_score = result.get("dev_score")
    if not isinstance(dev_score, (int, float)) or not math.isfinite(float(dev_score)):
        return {"ok": False, "reason": "复用训练没有返回开发集分数"}
    dev_score = float(dev_score)
    scores = card.get("scores") or {}
    baseline = scores.get("single_metric")
    recorded = scores.get("development")
    recorded = float(recorded) if isinstance(recorded, (int, float)) else None
    baseline = float(baseline) if isinstance(baseline, (int, float)) else None
    # Package cards store scores on the producer report's percentage scale; a
    # solution may return the same metric as a 0-1 fraction.
    if dev_score <= 1 and any(value is not None and value > 1 for value in (baseline, recorded)):
        dev_score *= 100
    if baseline is not None and dev_score < baseline:
        return {"ok": False, "reason": f"复用后开发集分数 {dev_score} 低于单一指标对照 {baseline}"}
    if recorded is not None and dev_score < recorded * (1 - tolerance):
        return {"ok": False, "reason": f"复用后开发集分数 {dev_score} 低于记录成绩 {recorded} 的容忍范围"}
    manifest = read_json(best / "solution_manifest.json", {}) or {}
    artifact_rel = str(manifest.get("artifact_path") or "")
    model_file = artifacts / str(result.get("model_file") or "")
    if artifact_rel and model_file.is_file():
        target = best / artifact_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(model_file, target)
    (best / "metric.txt").write_text(str(dev_score), encoding="utf-8")
    _write_reuse_journal(workspace, log_dir, best, manifest, card, dev_score)
    return {"ok": True, "dev_score": dev_score, "reason": "复用成功", "score": dev_score}


def _write_reuse_journal(workspace: Path, log_dir: Path, best: Path, manifest: dict[str, Any], card: dict[str, Any], dev_score: float) -> None:
    node = dict((card.get("solution") or {}).get("journal_node") or {})
    node.update({
        "stage": node.get("stage") or "draft",
        "method_family": node.get("method_family") or str(manifest.get("method_family") or "unknown"),
        "metric": {"value": dev_score, "maximize": True},
        "is_buggy": False,
        "is_valid": True,
        "runtime_ok": True,
        "search_eligible": True,
        "contract_valid": True,
        "artifact_ready": True,
        "delivery_ready": True,
        "delivery_certified": True,
        "certification_source": "package_reuse",
        "code": (best / "solution.py").read_text(encoding="utf-8", errors="ignore"),
        "parent": None,
        "children": [],
        "reuse_package_id": str(card.get("package_id") or ""),
        "reuse_package_task_id": str((card.get("source") or {}).get("task_id") or ""),
    })
    root = {
        "id": "package-reuse-root",
        "stage": "root",
        "step": 0,
        "code": "",
        "plan": "(package reuse)",
        "parent": None,
        "children": [node.get("id")],
        "metric": {"value": None, "maximize": True},
        "is_buggy": None,
        "is_valid": None,
        "runtime_ok": False,
        "search_eligible": False,
        "method_family": "unknown",
    }
    journal = {
        "nodes": [root, node],
        "node2parent": {str(node.get("id")): root["id"]},
        "node2best_local_node": {root["id"]: node.get("id")},
        "reuse_package_id": str(card.get("package_id") or ""),
    }
    write_json(log_dir / "journal.json", journal)
    write_json(log_dir / "filtered_journal.json", journal)
    write_json(log_dir / "run_status.json", {"status": "completed", "termination_reason": "package_reuse"})
    write_json(log_dir / "llm_usage_summary.json", {"calls": 0, "package_reuse": True})
    (log_dir / "best_solution.py").write_text((best / "solution.py").read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

"""Requirement degradation for tasks blocked at the AutoML input gate.

When task definition cannot produce an executable contract (missing materials,
conflicting requirement documents, unconverged review), the planner narrows the
task to what the supplied data can support. Every relaxed requirement is kept in
a ledger (``degradation.json`` in the task root) so research status, producer
consent and the final report all read the same record instead of model prose.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = "autodecision.degradation.v1"
LEDGER_NAME = "degradation.json"
DECLARATION_NAME = "degradation_declaration.md"
DECLARATION_MARKER = "<!-- autodecision:degradation-declaration -->"

POLICIES = ("auto", "ask", "strict")
CATEGORIES = ("材料缺失", "需求冲突", "口径不明", "范围过大", "审查未收敛")
ACTIONS = ("舍弃", "收窄", "按证据裁决", "采用假设")
MAX_ITEMS = 12
BRIEF_LIMIT = 30
INTERNAL_CATEGORY = "审查未收敛"  # system-side wording fixes, not a change the producer must weigh
HEDGES = ("如有需要", "视情况", "待确认", "酌情")

# Ledger states. ``proposed`` waits for producer consent; ``applied`` means the
# degraded definition passed the gate. Terminal failures keep the plan for review.
PROPOSED, APPLYING, APPLIED, REJECTED = "proposed", "applying", "applied", "rejected"
PLANNING_FAILED, FAILED_AFTER = "planning_failed", "failed_after_degradation"
INFEASIBLE = "infeasible"


class DegradationError(RuntimeError):
    pass


def ledger_path(task_root: Path) -> Path:
    return Path(task_root) / LEDGER_NAME


def read_ledger(task_root: Path) -> dict[str, Any] | None:
    path = ledger_path(task_root)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_ledger(task_root: Path, ledger: dict[str, Any]) -> None:
    ledger["updated_at"] = time.time()
    path = ledger_path(task_root)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _clip(value: Any, limit: int) -> str:
    text = str(value if value is not None else "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


_CONFLICT_RE = re.compile(r"Unresolved authority conflict:\s*(\{.*\})\s*$")


def _conflict_source(value: Any) -> dict[str, str]:
    # AutoRealize writes either {"source_path", "evidence", ...} or a plain string.
    if isinstance(value, dict):
        return {k: _clip(value.get(k), 300) for k in ("source_path", "evidence")}
    return {"source_path": "", "evidence": _clip(value, 300)}


def _authority_conflicts(blockers: list[str]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in blockers:
        match = _CONFLICT_RE.search(str(item))
        if not match:
            continue
        try:
            conflict = json.loads(match.group(1))
        except ValueError:
            continue
        if not isinstance(conflict, dict):
            conflict = {"description": conflict}
        key = str(conflict.get("conflict_id") or len(found))
        found[key] = {
            "conflict_id": key,
            "description": _clip(conflict.get("description"), 400),
            "source_a": _conflict_source(conflict.get("source_a")),
            "source_b": _conflict_source(conflict.get("source_b")),
        }
    return list(found.values())


def _final_section(document: Any) -> dict[str, Any]:
    final = document.get("final") if isinstance(document, dict) else None
    return final if isinstance(final, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _strip_source(issue: str) -> str:
    # Gate messages repeat the same finding once per artifact file.
    return re.sub(r"^[\w.]+\.json:\s*", "", str(issue)).strip()


def collect_evidence(*, autorealize_dir: Path, gate: dict[str, Any], task_hint: str, input_root: Path) -> dict[str, Any]:
    report_dir = Path(autorealize_dir) / "realize_report"
    hard = [str(x) for x in gate.get("hard_blocking_issues", [])]
    review = [str(x) for x in gate.get("review_issues", [])]
    blockers: list[str] = []
    for item in hard + review:
        text = _strip_source(item)
        if text.startswith("Unresolved authority conflict"):
            continue
        if text and text not in blockers:
            blockers.append(_clip(text, 400))

    contract = _final_section(_read_json(report_dir / "evaluation_contract_report.json"))
    consistency = _final_section(_read_json(report_dir / "artifact_consistency_report.json"))
    cognition = _read_json(report_dir / "data_cognition_report.json")
    cognition = cognition if isinstance(cognition, dict) else {}

    files = []
    for entry in _as_list(cognition.get("files"))[:30]:
        if isinstance(entry, dict):
            files.append({"path": entry.get("path"), "role": entry.get("role"), "summary": _clip(entry.get("summary"), 360)})
    columns = cognition.get("table_columns") or {}
    if isinstance(columns, dict):
        columns = {str(k): [str(c) for c in (v or [])][:80] for k, v in list(columns.items())[:20] if isinstance(v, list)}
    else:
        columns = {}
    input_files = sorted(
        str(p.relative_to(input_root)) for p in Path(input_root).rglob("*") if p.is_file() and not p.name.startswith(".")
    )[:200] if Path(input_root).is_dir() else []

    return {
        "original_task_hint": _clip(task_hint, 3000),
        "gate_findings": blockers[:30],
        "authority_conflicts": _authority_conflicts(hard + review),
        "evaluation_contract": {
            "passed": contract.get("passed"),
            "executable": contract.get("executable"),
            "primary_metric": _clip(contract.get("primary_metric"), 300),
            "prediction_unit": _clip(contract.get("prediction_unit"), 400),
            "metric_formula": _clip(contract.get("metric_formula"), 800),
            "issues": [_clip(x, 400) for x in _as_list(contract.get("issues"))][:15],
            "fixes": [_clip(x, 300) for x in _as_list(contract.get("fixes"))][:15],
            "assumptions": [_clip(x, 300) for x in _as_list(contract.get("assumptions"))][:12],
            "residual_issues": [_clip(x, 300) for x in _as_list(contract.get("residual_issues"))][:12],
        },
        "consistency_review": {
            "passed": consistency.get("passed"),
            "summary": _clip(consistency.get("summary"), 600),
            "issues": [
                {"severity": i.get("severity"), "category": i.get("category"), "message": _clip(i.get("message"), 400)}
                if isinstance(i, dict) else {"severity": "", "category": "", "message": _clip(i, 400)}
                for i in _as_list(consistency.get("issues"))
            ][:12],
        },
        "data": {"input_files": input_files, "file_cognition": files, "table_columns": columns},
    }


SYSTEM_PROMPT = """你是 AutoDecision 的需求降级规划助手。原任务在进入算法搜索前被输入审查拦下。你的工作：在不改变核心目标的前提下，把任务收窄成用现有数据就能执行、能评估的版本，并逐条说明放弃或改动了哪些要求。
规则：
1. 核心目标（预测、优化或诊断的对象和方向）必须保留。只能做四件事：舍弃做不到的附加要求、收窄范围、在冲突中按证据裁决、对不明确的口径采用明确假设。
2. 只能使用 data 中列出的文件和字段，不得编造数据、外部材料、指标数值或业务结论。
3. 只降级确实做不到的部分。data 里已有、能完成的分析（例如已提供的天气、浓度、进料等字段，以及需求方关心的“哪些因素影响结果”）必须保留，不能因为复杂或审查没收敛就砍掉。「范围过大」只用于缺少外部材料、工程部署、上线运维这类离线数据无法支撑的要求。
4. 每一条被舍弃、收窄、裁决或假设的要求都写进 items。每条写清：原要求、做不到的原因、依据（引用审查原文或文件名）、降级做法、对结论适用范围的影响；再写一句给生产者看的 brief（30 字以内，用业务语言，不出现文件名、字段名、代码和公式，例如「不做路段和节假日准确率」「工艺按硫酸铝处理」）。
5. degraded_goal 是交给数据分析 agent 的完整任务说明（中文，800 字以内），必须写明：预测或优化的对象与粒度、唯一的评估指标及计算方式、数据切分方式、唯一的输出文件名与列、明确不做的内容、采用的裁决和假设。写具体、可直接执行，不要出现“如有需要”“视情况”“待确认”。
6. 审查报告中本系统自己生成的文件之间不一致（文件名、指标名、行单位不统一）不属于用户需求问题：在 degraded_goal 里直接规定唯一的文件名、指标名和行单位来消除歧义，并以「审查未收敛」类记入 items。
7. 需求文档之间互相矛盾时，按证据裁决（哪份文档更详细、哪项与数据字段一致），记为「需求冲突」类。
8. 如果连核心目标都无法用现有数据完成，feasible 写 false，并在 infeasible_reason 说明原因。
只输出一个 JSON 对象：{"feasible":true,"core_goal":"一句话核心目标","degraded_goal":"","items":[{"category":"材料缺失|需求冲突|口径不明|范围过大|审查未收敛","brief":"","original":"","reason":"","evidence":"","action":"舍弃|收窄|按证据裁决|采用假设","degraded":"","impact":""}],"infeasible_reason":""}"""


def _extract_json(content: str) -> Any:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip() if "\n" in text else ""
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def validate_plan(raw: Any, evidence: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return a normalized plan plus problems; an empty problem list means usable."""

    problems: list[str] = []
    if not isinstance(raw, dict):
        return {}, ["输出必须是 JSON 对象"]
    feasible = raw.get("feasible")
    if not isinstance(feasible, bool):
        problems.append("feasible 必须是布尔值")
    plan: dict[str, Any] = {
        "feasible": feasible is True,
        "core_goal": _clip(raw.get("core_goal"), 200),
        "degraded_goal": str(raw.get("degraded_goal") or "").strip(),
        "infeasible_reason": _clip(raw.get("infeasible_reason"), 600),
        "items": [],
    }
    if feasible is False:
        if not plan["infeasible_reason"]:
            problems.append("feasible=false 时必须写 infeasible_reason")
        return plan, problems

    if len(plan["core_goal"]) < 4:
        problems.append("core_goal 不能为空")
    goal = plan["degraded_goal"]
    if not 30 <= len(goal) <= 1500:
        problems.append(f"degraded_goal 长度应在 30 到 1500 字之间，当前 {len(goal)}")
    for word in HEDGES:
        if word in goal:
            problems.append(f"degraded_goal 不能出现「{word}」，口径要写死")

    items = raw.get("items")
    if not isinstance(items, list) or not items:
        problems.append("items 至少要有一条：被拦下的任务一定有要求被改动")
        items = []
    if len(items) > MAX_ITEMS:
        problems.append(f"items 最多 {MAX_ITEMS} 条，请合并同类项")
    for index, item in enumerate(items[:MAX_ITEMS], start=1):
        if not isinstance(item, dict):
            problems.append(f"items 第 {index} 条不是对象")
            continue
        row = {key: _clip(item.get(key), 400) for key in ("category", "original", "reason", "evidence", "action", "degraded", "impact")}
        row["brief"] = str(item.get("brief") or "").strip()
        if not row["brief"]:
            problems.append(f"items 第 {index} 条缺少 brief")
        elif len(row["brief"]) > BRIEF_LIMIT:
            problems.append(f"items 第 {index} 条 brief 超过 {BRIEF_LIMIT} 字（{len(row['brief'])} 字），请压短")
        if row["category"] not in CATEGORIES:
            problems.append(f"items 第 {index} 条 category 只能是 {'/'.join(CATEGORIES)}")
        if row["action"] not in ACTIONS:
            problems.append(f"items 第 {index} 条 action 只能是 {'/'.join(ACTIONS)}")
        missing = [key for key in ("original", "reason", "degraded", "impact") if not row[key]]
        if missing:
            problems.append(f"items 第 {index} 条缺少 {', '.join(missing)}")
        plan["items"].append(row)

    categories = {row["category"] for row in plan["items"]}
    if evidence.get("authority_conflicts") and "需求冲突" not in categories:
        problems.append("审查里有需求文档冲突，items 必须包含「需求冲突」类并写明裁决依据")
    contract = evidence.get("evaluation_contract") or {}
    if contract.get("executable") is False and not categories & {"材料缺失", "范围过大", "口径不明"}:
        problems.append("评估合同不可执行，items 必须说明缺了什么材料或砍掉了哪些范围")
    return plan, problems


def request_plan(evidence: dict[str, Any], call_model: Callable[[str, str], str], *, max_attempts: int = 3) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Ask the model for a plan, feeding validation problems back until it passes."""

    attempts: list[dict[str, Any]] = []
    feedback: list[str] = []
    for attempt in range(1, max_attempts + 1):
        payload = {"evidence": evidence}
        if feedback:
            payload["previous_problems"] = feedback
        try:
            content = call_model(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
            plan, problems = validate_plan(_extract_json(content), evidence)
        except Exception as exc:  # transport, JSON and shape errors are all retryable here
            plan, problems = {}, [f"{type(exc).__name__}: {_clip(exc, 200)}"]
        attempts.append({"attempt": attempt, "problems": problems})
        if not problems:
            return plan, attempts
        feedback = problems
    raise DegradationError("降级规划没有通过校验：" + "；".join(feedback))


def degraded_task_hint(original: str, plan: dict[str, Any], approver: str) -> str:
    # Keep the statement short: task definition restates every requirement in
    # structured memory, so a long hint makes each downstream call slower. The
    # full original/changed/impact text lives in the ledger and the report.
    lines = []
    if str(original or "").strip():
        lines += [str(original).strip(), ""]
    lines += ["# 已批准的降级任务口径（以此为准）", plan["degraded_goal"], "", "## 降级要点"]
    for index, item in enumerate(plan["items"], start=1):
        lines.append(f"{index}. {item.get('brief') or _clip(item.get('degraded'), 80)}")
    lines += [
        "",
        f"以上降级已由{approver}批准。原需求文档中与上述口径冲突或超出范围的内容不再作为本任务的验收要求，"
        "但必须在最终报告中如实声明未满足，不得声称已满足。",
    ]
    return "\n".join(lines)


def new_ledger(*, task_id: str, policy: str, gate: dict[str, Any], original_task_hint: str,
               plan: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    now = time.time()
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "policy": policy,
        "status": PROPOSED,
        "created_at": now,
        "updated_at": now,
        "trigger": {
            "hard_blocking_issues": [_clip(x, 600) for x in gate.get("hard_blocking_issues", [])][:30],
            "review_issues": [_clip(x, 600) for x in gate.get("review_issues", [])][:30],
        },
        "original_task_hint": original_task_hint,
        "plan": plan,
        "planning_attempts": attempts,
        "approval": None,
        "outcome": None,
    }


def approve(ledger: dict[str, Any], *, by: str, conversation_id: str = "") -> dict[str, Any]:
    if ledger.get("status") != PROPOSED:
        raise DegradationError(f"降级清单状态为 {ledger.get('status')}，不能再批准")
    ledger["approval"] = {"by": by, "at": time.time(), "conversation_id": conversation_id or None}
    ledger["status"] = APPLYING
    refresh_hint(ledger)
    return ledger


def refresh_hint(ledger: dict[str, Any]) -> str:
    """(Re)build the degraded statement from the approved plan, e.g. before a retry."""
    approver = "研究计划的自动降级设置" if (ledger.get("approval") or {}).get("by") == "auto" else "生产者"
    ledger["degraded_task_hint"] = degraded_task_hint(ledger.get("original_task_hint", ""), ledger["plan"], approver)
    return ledger["degraded_task_hint"]


def reject(ledger: dict[str, Any], *, conversation_id: str = "") -> dict[str, Any]:
    if ledger.get("status") != PROPOSED:
        raise DegradationError(f"降级清单状态为 {ledger.get('status')}，不能再拒绝")
    ledger["status"] = REJECTED
    ledger["approval"] = {"by": "producer", "at": time.time(), "conversation_id": conversation_id or None, "approved": False}
    return ledger


def archive_definition(task_root: Path) -> Path | None:
    """Move the blocked task definition aside so the degraded run starts clean."""

    source = Path(task_root) / "autorealize"
    if not source.exists():
        return None
    target = Path(task_root) / "stage-history" / f"autorealize-before-degradation-{time.strftime('%Y%m%d-%H%M%S')}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return target


def summary(ledger: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ledger:
        return None
    plan = ledger.get("plan") or {}
    items = plan.get("items") or []
    approval = ledger.get("approval") or {}
    return {
        "status": ledger.get("status"),
        "policy": ledger.get("policy"),
        "count": len(items),
        "core_goal": plan.get("core_goal") or "",
        "items": [{key: i.get(key) for key in ("category", "action", "brief", "original", "degraded", "impact")} for i in items],
        "approved_by": approval.get("by") if approval.get("approved", True) else None,
        "decided_at": approval.get("at"),
        "conversation_id": approval.get("conversation_id"),
        "infeasible_reason": plan.get("infeasible_reason") or "",
        "outcome": ledger.get("outcome"),
    }


_GENERIC_REVIEW_LINES = (
    "review retries exhausted",
    "final artifact consistency review has not passed",
    "final artifact review retries exhausted",
    "execution contract remains blocked by final review",
    "evaluation contract has not passed executable validation",
)


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip() or "—"


def render_declaration(ledger: dict[str, Any], review_gate: dict[str, Any] | None = None) -> str:
    plan = ledger.get("plan") or {}
    approval = ledger.get("approval") or {}
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(approval.get("at") or time.time()))
    how = ("按研究计划的「自动降级」设置执行" if approval.get("by") == "auto"
           else f"生产者于 {when} 同意后执行")
    lines = [
        DECLARATION_MARKER,
        "## 降级声明",
        "",
        f"本研究未能满足原需求的全部要求，已按下列降级口径执行（{how}）。本报告的结论只在降级后的口径内成立，"
        "表中各项原要求均**未满足**。",
        "",
        f"**降级后的核心目标**：{_cell(plan.get('core_goal'))}",
        "",
        "| # | 类别 | 原要求 | 原因 | 降级做法 | 对结论的影响 |",
        "|---|---|---|---|---|---|",
    ]
    for index, item in enumerate(plan.get("items") or [], start=1):
        lines.append(
            f"| {index} | {_cell(item.get('category'))}·{_cell(item.get('action'))} | {_cell(item.get('original'))} | "
            f"{_cell(item.get('reason'))} | {_cell(item.get('degraded'))} | {_cell(item.get('impact'))} |"
        )
    residual: list[str] = []
    for raw in (review_gate or {}).get("review_issues") or []:
        text = _strip_source(raw)
        # Keep concrete findings once; drop the generic "review exhausted" status lines.
        text = re.sub(r"^Final artifact consistency:\s*", "", text)
        if not text or text.lower().startswith(_GENERIC_REVIEW_LINES) or text in residual:
            continue
        residual.append(text)
    if residual and (review_gate or {}).get("review_bypass_active"):
        lines += ["", "### 降级后仍未解决的审查问题", ""]
        lines += [f"- {_cell(x)}" for x in residual[:15]]
    return "\n".join(lines) + "\n"


def append_declaration(report_dir: Path, ledger: dict[str, Any], review_gate: dict[str, Any] | None = None) -> bool:
    """Write the declaration file and append it once to report.md."""

    report_dir = Path(report_dir)
    if ledger.get("status") != APPLIED or not report_dir.is_dir():
        return False
    declaration = render_declaration(ledger, review_gate)
    (report_dir / DECLARATION_NAME).write_text(declaration, encoding="utf-8")
    report = report_dir / "report.md"
    if not report.is_file():
        return False
    text = report.read_text(encoding="utf-8")
    if DECLARATION_MARKER in text:
        text = text.split(DECLARATION_MARKER, 1)[0].rstrip() + "\n"
    report.write_text(text.rstrip() + "\n\n" + declaration, encoding="utf-8")
    return True

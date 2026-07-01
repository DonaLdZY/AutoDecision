from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .collector import EvidenceBundle, EvidenceItem
from .config import AutoReportConfig, dump_config
from .events import ReportEventWriter


NETWORK_RETRY_MAX_ATTEMPTS = 5
NETWORK_RETRY_MAX_SLEEP_SECONDS = 30.0


def generate_report(cfg: AutoReportConfig, bundle: EvidenceBundle, events: ReportEventWriter) -> dict[str, Any]:
    events.log("autoreport.generator", "ACTIVATED", task_name=cfg.task_name)
    settings = _validate_llm_config(cfg)
    briefing = _build_llm_briefing(cfg, bundle)
    article_md = _generate_article_with_llm(cfg, settings, briefing, events)
    article_md = _normalize_article_markdown(cfg, article_md)
    sections = _sections_from_markdown(article_md)

    payload = {
        "schema_version": "autoreport.report.v3",
        "task_name": cfg.task_name,
        "report_title": cfg.report_title or f"{cfg.task_name} 方案交付报告",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": dump_config(cfg),
        "summary": {
            "evidence_paths": len(bundle.roots),
            "evidence_items": len(bundle.items),
            "warnings": len(bundle.warnings),
            "kind_counts": bundle.derived.get("kind_counts", {}),
            "solution_evidence": _solution_evidence_summary_for_payload(bundle),
            "llm_model": settings["model"],
            "llm_base_url": settings["base_url"],
        },
        "sections": sections,
        "article_markdown": article_md,
        "evidence_index": [asdict(item) for item in bundle.items],
        "warnings": bundle.warnings,
    }

    out_dir = Path(cfg.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(article_md, encoding="utf-8")
    events.log("autoreport.generator", "GENERATED_FILE", file="report.json")
    events.log("autoreport.generator", "GENERATED_FILE", file="report.md")
    events.log("autoreport.generator", "COMPLETED", sections=len(sections), llm_model=settings["model"])
    return payload


def render_markdown(report: dict[str, Any]) -> str:
    article = str(report.get("article_markdown") or "").strip()
    if article:
        return article + "\n"
    title = str(report.get("report_title") or "AutoDecision 方案交付报告")
    lines = [f"# {title}", ""]
    for section in report.get("sections", []) or []:
        lines.append(f"## {section.get('title', '')}")
        lines.append("")
        lines.append(str(section.get("content", "")).strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _validate_llm_config(cfg: AutoReportConfig) -> dict[str, Any]:
    if not cfg.use_llm:
        raise ValueError("AutoReport 必须启用 LLM：请将 config.use_llm 设置为 true。")
    llm = dict(cfg.llm or {})
    model = str(llm.get("model") or llm.get("model_name") or "").strip()
    base_url = str(llm.get("base_url") or llm.get("baseUrl") or "").strip()
    api_key = str(llm.get("api_key") or llm.get("apiKey") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not model:
        raise ValueError("AutoReport LLM 配置缺少 model。")
    if not base_url:
        raise ValueError("AutoReport LLM 配置缺少 base_url。")
    if not api_key:
        raise ValueError("AutoReport LLM 配置缺少 api_key，且环境变量 DEEPSEEK_API_KEY 不存在。")
    base_url = _normalize_base_url(model, base_url)
    return {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "timeout": int(llm.get("timeout") or llm.get("request_timeout_seconds") or 180),
        "max_tokens": int(llm.get("max_tokens") or llm.get("maxTokens") or 8192),
        "temperature": float(llm.get("temperature", 0.25)),
    }


def _normalize_base_url(model: str, base_url: str) -> str:
    base = base_url.rstrip("/")
    if model.strip().lower().startswith("deepseek") and base in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
        return "https://api.deepseek.com/beta"
    return base


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _generate_article_with_llm(
    cfg: AutoReportConfig,
    settings: dict[str, Any],
    briefing: str,
    events: ReportEventWriter,
) -> str:
    system_prompt = """
你是 AutoDecision 的方案交付报告撰写专家。你的目标不是介绍 AutoDecision、AutoML 或搜索系统如何工作，
而是基于证据写一份能说服使用者“这个搜出来的方案有效、可复用、可交付”的报告。

硬性要求：
- 报告主语必须是最终方案/求解器/模型本身，不是 AutoML 流程。
- 不要写“AutoML 如何搜索”“系统工作流介绍”这类宣传章节；可以只把自动搜索作为证据来源。
- 必须解释最终方案的方法设计细节：数据如何读取、特征/状态/候选如何构造、核心算法如何决策、如何校验和评分。
- 必须写清如何复用代码：使用哪些文件、输入目录格式、如何运行、是否有 predict()、输出文件在哪里、输出格式是什么。
- 必须与其它搜索到的方法对比：其它方法的指标、失败原因、缺陷、为什么最终方案更好。证据不足时要明确“证据未显示”。
- 必须给出验证证据和限制：metric、score components、产物文件、已知风险、下一步改进。
- 禁止大段复制日志、源码、JSON；只引用关键路径、关键数字和短证据。
- 不得编造证据中没有的指标、字段、文件、函数或结论。
""".strip()
    language_hint = "中文" if cfg.language.lower().startswith("zh") else "English"
    user_prompt = f"""
请为任务 `{cfg.task_name}` 写一份面向 `{cfg.audience}` 读者的方案交付报告，使用{language_hint}，输出完整 Markdown。

推荐内容框架：
1. 摘要与可交付结论：一句话说清最终方案是否可用、核心指标、交付物和主要风险。
2. 问题与验收口径：任务要解决什么，最终方案按什么指标/约束验收。
3. 最终方案方法设计：详细说明数据读取、预处理、候选/动作/特征、模型或求解算法、评分/约束校验、输出构造。
4. 代码复用与部署方式：列出 `solution.py`、模型/求解器 artifact、输入目录结构、运行命令、`predict()` 或可复用函数、输出文件格式。
5. 验证结果与交付物：写清 metric、score components、输出文件、运行时间、成功/失败证据。
6. 与其它搜索方案的对比：用表格比较候选方案/节点，说明其它方案差在哪里，最终方案具体改进了什么。
7. 风险、限制与下一步改进：不要粉饰；把仍可能影响落地的问题写清楚。
8. 交付检查清单：使用者拿到报告后如何确认能跑、能验、能交付。

写作重点：
- 这是“方案有效性与复用说明”报告，不是 AutoML 系统说明书。
- 如果证据里有其它候选方案的 `llm_insight`、错误、metric、submission/metrics 输出，要用来写对比。
- 如果最终方案没有 `predict()` 或没有 artifact，要写成复用限制和补齐建议，而不是假装存在。
- 如果优化/RL/决策任务没有传统预测接口，也可以说明如何调用 solver/main/score/validate 来复用。

以下是压缩后的证据简报：

{briefing}
""".strip()

    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": settings["temperature"],
        "max_tokens": settings["max_tokens"],
        "stream": False,
    }
    events.log(
        "autoreport.generator",
        "LLM_REQUEST",
        model=settings["model"],
        base_url=settings["base_url"],
        briefing_chars=len(briefing),
    )
    raw = _post_json_with_retry(
        _chat_completions_url(settings["base_url"]),
        payload,
        api_key=settings["api_key"],
        timeout=settings["timeout"],
        events=events,
    )
    content = _extract_chat_content(raw)
    if not content.strip():
        raise RuntimeError("AutoReport LLM 返回空内容，无法生成报告。")
    events.log("autoreport.generator", "LLM_COMPLETED", chars=len(content))
    return content


def _post_json_with_retry(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: int,
    events: ReportEventWriter,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, NETWORK_RETRY_MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1, timeout)) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code}: {detail[:500]}")
            retryable = exc.code in {429, 500, 502, 503, 504}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            retryable = _is_retryable_error(exc)
        events.log(
            "autoreport.generator",
            "LLM_RECONNECTING",
            attempt=attempt,
            max_attempts=NETWORK_RETRY_MAX_ATTEMPTS,
            retryable=retryable,
            error=str(last_error)[:240],
        )
        if (not retryable) or attempt >= NETWORK_RETRY_MAX_ATTEMPTS:
            raise RuntimeError(_format_llm_network_error(last_error, url))
        time.sleep(min(NETWORK_RETRY_MAX_SLEEP_SECONDS, 5.0 * attempt))
    raise RuntimeError(_format_llm_network_error(last_error, url))


def _is_retryable_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        key in msg
        for key in [
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "connection refused",
            "10061",
            "actively refused",
            "积极拒绝",
            "temporary failure",
            "temporarily unavailable",
            "bad gateway",
            "502",
            "503",
            "504",
            "rate limit",
            "too many requests",
            "getaddrinfo",
            "11001",
            "name resolution",
            "temporary failure in name resolution",
            "nodename nor servname",
            "name or service not known",
        ]
    )


def _format_llm_network_error(exc: Exception | None, url: str) -> str:
    msg = str(exc or "unknown error")
    if "getaddrinfo" in msg.lower() or "name resolution" in msg.lower():
        return (
            "AutoReport LLM 请求失败：DNS 解析失败，无法解析模型服务域名。"
            f"请检查 LLM base_url、系统 DNS、代理/VPN 或内网防火墙。url={url}; error={msg}"
        )
    return f"AutoReport LLM 请求失败: {msg}"


def _extract_chat_content(raw: dict[str, Any]) -> str:
    choices = raw.get("choices") or []
    if not choices:
        return ""
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(x for x in parts if x)
    if content is not None:
        return str(content)
    return str(first.get("text") or "")


def _build_llm_briefing(cfg: AutoReportConfig, bundle: EvidenceBundle) -> str:
    max_chars = int((cfg.llm or {}).get("max_prompt_chars") or cfg.max_report_chars_per_section or 60000)
    parts: list[str] = []

    def add(title: str, text: str, limit: int = 8000) -> None:
        text = str(text or "").strip()
        if not text:
            return
        parts.append(f"## {title}\n{_clip(text, limit)}")

    roots = "\n".join(
        f"- {root.get('label')} ({root.get('kind')}): exists={root.get('exists')} path={root.get('path')}"
        for root in bundle.roots
    )
    add("证据入口", roots, 5000)
    if bundle.warnings:
        add("证据告警", "\n".join(f"- {x}" for x in bundle.warnings), 5000)

    add(
        "报告目标与写作边界",
        "\n".join(
            [
                "- 报告用于说服使用者：最终方案有效、可复用、可交付。",
                "- 不介绍 AutoML/AutoDecision 内部流程，只把搜索过程当作候选方案证据。",
                "- 必须说明最终方案方法设计、代码复用方式、输入输出格式、验证证据、与其它候选方法的差异。",
                "- 证据不足的地方必须明确写风险或未知，不得编造。",
            ]
        ),
        3000,
    )

    solution_evidence = bundle.derived.get("solution_evidence") or {}
    prompt_solution_evidence = _solution_evidence_for_prompt(solution_evidence)
    add("方案证据总包", json.dumps(prompt_solution_evidence, ensure_ascii=False, indent=2, default=str), 32000)

    add("任务定义 description.md", bundle.derived.get("description", ""), 12000)
    add("数据认知 data_description.md", bundle.derived.get("data_description", ""), 9000)
    add("样例提交预览", json.dumps(bundle.derived.get("sample_submission_preview") or [], ensure_ascii=False, indent=2), 3000)

    selected = _select_context_items(bundle)
    context_lines = []
    for item in selected:
        name = Path(item.path).name
        context_lines.append(f"### {name}\npath: {item.path}\nkind: {item.kind}\n")
        if item.json_summary:
            context_lines.append("json_summary:\n" + json.dumps(item.json_summary, ensure_ascii=False, indent=2, default=str)[:3000])
        elif item.table_preview:
            context_lines.append("table_preview:\n" + json.dumps(item.table_preview, ensure_ascii=False, indent=2, default=str)[:3000])
        else:
            context_lines.append(_clip(item.text_excerpt, 3000))
    add("关键证据摘录", "\n\n".join(context_lines), 18000)

    evidence_index = "\n".join(f"- [{item.kind}] {item.path}" for item in bundle.items[:160])
    add("证据索引", evidence_index, 12000)
    return _clip("\n\n".join(parts), max_chars)


def _select_context_items(bundle: EvidenceBundle) -> list[EvidenceItem]:
    priority_names = {
        "description.md",
        "data_description.md",
        "automl_context.md",
        "autorealize_context.md",
        "metrics.json",
        "model_artifacts_manifest.md",
        "node_summary_compact.json",
        "journal.json",
        "filtered_journal.json",
        "metric.txt",
        "best_solution.py",
        "solution.py",
        "submission.csv",
        "assignments.csv",
        "unassigned_orders.csv",
    }
    scored: list[tuple[int, str, EvidenceItem]] = []
    for item in bundle.items:
        name = Path(item.path).name.lower()
        score = 100
        if name in priority_names:
            score -= 60
        if item.kind == "solution":
            score -= 35
        elif item.kind == "runtime_trace":
            score -= 15
        elif item.kind == "data_cognition":
            score -= 20
        elif item.kind == "task_definition":
            score -= 25
        if any(part in item.path.lower().replace("\\", "/") for part in ["best_solution", "top_solution", "/submission/"]):
            score -= 20
        scored.append((score, item.path.lower(), item))
    return [item for _, _, item in sorted(scored, key=lambda row: (row[0], row[1]))[:32]]


def _normalize_article_markdown(cfg: AutoReportConfig, article: str) -> str:
    text = article.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if not text.startswith("#"):
        title = cfg.report_title or f"{cfg.task_name} 方案交付报告"
        text = f"# {title}\n\n{text}"
    return text.strip() + "\n"


def _sections_from_markdown(markdown: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_title = "导言"
    current_lines: list[str] = []
    heading_seen = False

    def flush() -> None:
        nonlocal current_title, current_lines
        content = "\n".join(current_lines).strip()
        if not content and current_title == "导言":
            return
        sections.append(
            {
                "id": f"section_{len(sections) + 1}",
                "title": current_title,
                "content": content,
                "evidence": [],
            }
        )
        current_lines = []

    for line in markdown.splitlines():
        if line.startswith("# "):
            current_lines.append(line)
            continue
        if line.startswith("## "):
            if heading_seen or current_lines:
                flush()
            heading_seen = True
            current_title = line.lstrip("#").strip()
            continue
        current_lines.append(line)
    flush()
    return sections


def _solution_evidence_for_prompt(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    best = evidence.get("best_solution") if isinstance(evidence.get("best_solution"), dict) else {}
    candidate = evidence.get("candidate_comparison") if isinstance(evidence.get("candidate_comparison"), dict) else {}
    reusable = evidence.get("reusable_code_interface") if isinstance(evidence.get("reusable_code_interface"), dict) else {}
    code_excerpt = str(best.get("code_excerpt") or "")
    best_compact = {
        "metric": best.get("metric"),
        "metric_text": str(best.get("metric_text") or "")[:2000],
        "metric_path": best.get("metric_path"),
        "node_id": best.get("node_id"),
        "solution_path": best.get("solution_path"),
        "code_functions": best.get("code_functions"),
        "code_excerpt_head": code_excerpt[:4500],
        "model_artifacts_manifest": str(best.get("model_artifacts_manifest") or "")[:2500],
        "model_artifacts_manifest_path": best.get("model_artifacts_manifest_path"),
    }
    return {
        "best_solution": best_compact,
        "reusable_code_interface": reusable,
        "candidate_comparison": {
            "node_count": candidate.get("node_count"),
            "maximize": candidate.get("maximize"),
            "method_signals": candidate.get("method_signals"),
            "successful_metric_nodes": candidate.get("successful_metric_nodes", [])[:12],
            "failed_nodes": candidate.get("failed_nodes", [])[:8],
            "failure_patterns": candidate.get("failure_patterns", [])[:10],
        },
        "top_solutions": (evidence.get("top_solutions") or [])[:8],
        "delivery_artifacts": (evidence.get("delivery_artifacts") or [])[:30],
        "available_evidence_files": evidence.get("available_evidence_files") or {},
    }


def _solution_evidence_summary_for_payload(bundle: EvidenceBundle) -> dict[str, Any]:
    evidence = bundle.derived.get("solution_evidence") if isinstance(bundle.derived, dict) else {}
    if not isinstance(evidence, dict):
        return {}
    candidate = evidence.get("candidate_comparison") if isinstance(evidence.get("candidate_comparison"), dict) else {}
    best = evidence.get("best_solution") if isinstance(evidence.get("best_solution"), dict) else {}
    return {
        "best_metric": (best.get("metric") or {}).get("metric") if isinstance(best.get("metric"), dict) else None,
        "best_solution_path": best.get("solution_path"),
        "top_solution_count": len(evidence.get("top_solutions") or []),
        "candidate_node_count": candidate.get("node_count"),
        "successful_metric_node_count": len(candidate.get("successful_metric_nodes") or []),
        "failure_pattern_count": len(candidate.get("failure_patterns") or []),
        "delivery_artifact_count": len(evidence.get("delivery_artifacts") or []),
        "has_predict": (evidence.get("reusable_code_interface") or {}).get("has_predict") if isinstance(evidence.get("reusable_code_interface"), dict) else None,
    }


def _clip(text: str, limit: int = 1800) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n...(已截断)"

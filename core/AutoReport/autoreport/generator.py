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
        "schema_version": "autoreport.report.v2",
        "task_name": cfg.task_name,
        "report_title": cfg.report_title or f"{cfg.task_name} AutoDecision 方案报告",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": dump_config(cfg),
        "summary": {
            "evidence_paths": len(bundle.roots),
            "evidence_items": len(bundle.items),
            "warnings": len(bundle.warnings),
            "kind_counts": bundle.derived.get("kind_counts", {}),
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
    title = str(report.get("report_title") or "AutoDecision 方案报告")
    lines = [f"# {title}", ""]
    for section in report.get("sections", []) or []:
        lines.append(f"## {section.get('title', '')}")
        lines.append("")
        lines.append(str(section.get("content", "")).strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _validate_llm_config(cfg: AutoReportConfig) -> dict[str, Any]:
    if not cfg.use_llm:
        raise ValueError("AutoReport 必须启用 LLM：请将 config.use_llm 设为 true。")
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
    system_prompt = (
        "你是 AutoDecision 的首席方案报告撰写专家。你的任务不是粘贴日志或证据，"
        "而是基于证据写一篇给人看的完整方案文章。你必须综合 AutoRealize 的数据理解、"
        "任务定义、AutoML/MLEvolve/ML-Master 的搜索轨迹、最终方案、指标、风险与复现建议。"
        "不要编造证据中没有的信息；缺失的信息要明确说“当前证据未显示”。"
        "报告主体必须是连贯的人类可读 Markdown 文章，不允许把原始日志、长代码、JSON 原样堆砌为正文。"
    )
    language_hint = "中文" if cfg.language.lower().startswith("zh") else "English"
    user_prompt = f"""
请为任务 `{cfg.task_name}` 写一篇面向 `{cfg.audience}` 读者的 AutoDecision 方案报告。

写作要求：
1. 使用{language_hint}，输出完整 Markdown。
2. 必须像一篇方案文章，而不是证据清单。请解释：这个任务要解决什么问题、数据说明了什么、系统如何把任务形式化、AutoML 如何搜索方案、最后方案是什么、指标怎么看、如何复现交付、还存在哪些风险。
3. 可以引用关键文件名或路径作为依据，但不要把日志、代码、JSON、description 原文大段复制进正文。
4. 如果自动建模失败或最优方案证据不足，要写清楚失败阶段、可能原因和下一步排查路径。
5. 建议章节结构：
   - 摘要
   - 业务问题与赛题定义
   - 数据资产与关键约束
   - AutoDecision 工作流说明
   - 自动建模搜索过程
   - 最终方案、指标与可交付物
   - 复现步骤
   - 风险、限制与后续改进

以下是经过压缩的证据简报，请据此综合撰写：

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

    add("AutoRealize 任务定义 description.md", bundle.derived.get("description", ""), 14000)
    add("AutoRealize 数据总认知 data_description.md", bundle.derived.get("data_description", ""), 14000)
    add("样例提交预览", json.dumps(bundle.derived.get("sample_submission_preview") or [], ensure_ascii=False, indent=2), 3000)
    add("最优指标文本", bundle.derived.get("best_metric_text", ""), 4000)
    add("最优方案代码摘录", bundle.derived.get("best_solution_code", ""), 6000)

    selected = _select_context_items(bundle)
    context_lines = []
    for item in selected:
        name = Path(item.path).name
        context_lines.append(f"### {name}\npath: {item.path}\nkind: {item.kind}\n")
        if item.json_summary:
            context_lines.append("json_summary:\n" + json.dumps(item.json_summary, ensure_ascii=False, indent=2)[:3000])
        elif item.table_preview:
            context_lines.append("table_preview:\n" + json.dumps(item.table_preview, ensure_ascii=False, indent=2)[:3000])
        else:
            context_lines.append(_clip(item.text_excerpt, 3000))
    add("关键证据摘录", "\n\n".join(context_lines), 24000)

    evidence_index = "\n".join(f"- [{item.kind}] {item.path}" for item in bundle.items[:120])
    add("证据索引", evidence_index, 10000)
    return _clip("\n\n".join(parts), max_chars)


def _select_context_items(bundle: EvidenceBundle) -> list[EvidenceItem]:
    priority_names = {
        "data_cognition_report.json",
        "constraint_memory.json",
        "run_summary.json",
        "current_state.json",
        "event_stream.jsonl",
        "journal.json",
        "metric.txt",
        "ml-master.log",
        "mlevolve.log",
        "best_solution.py",
        "solution.py",
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
            score -= 25
        elif item.kind == "data_cognition":
            score -= 20
        elif item.kind == "task_definition":
            score -= 15
        scored.append((score, item.path.lower(), item))
    return [item for _, _, item in sorted(scored, key=lambda row: (row[0], row[1]))[:28]]


def _normalize_article_markdown(cfg: AutoReportConfig, article: str) -> str:
    text = article.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if not text.startswith("#"):
        title = cfg.report_title or f"{cfg.task_name} AutoDecision 方案报告"
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


def _clip(text: str, limit: int = 1800) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n...(已截断)"

"""Probe test models in priority order, falling back only when needed.

By default the first responsive model wins, so later providers do not incur
test calls. Use --mode all only when explicitly comparing every configured
model. Credentials stay outside the product's persisted model settings.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

import requests


def _registry_env(name: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""


def _user_env(name: str, scope: str) -> str:
    if scope == "current-user":
        value = _registry_env(name)
        if value:
            return value
    return os.environ.get(name, "").strip()


def _providers(scope: str) -> tuple[str, list[tuple[str, str, str]]]:
    base = _user_env("AUTODECISION_TEST_LLM_BASE_URL", scope).rstrip("/")
    shared_base = base or _user_env("AUTODECISION_TEST_LLM_FALLBACK_BASE_URL", scope).rstrip("/")
    return shared_base, [
        (
            _user_env("AUTODECISION_TEST_LLM_MODEL", scope) or "deepseek-v4.1-flash",
            "AUTODECISION_TEST_LLM_API_KEY",
            shared_base,
        ),
        (
            _user_env("AUTODECISION_TEST_LLM_FALLBACK_MODEL", scope) or "glm-5.3-flash",
            "AUTODECISION_TEST_LLM_FALLBACK_API_KEY",
            _user_env("AUTODECISION_TEST_LLM_FALLBACK_BASE_URL", scope).rstrip("/") or shared_base,
        ),
        (
            _user_env("AUTODECISION_TEST_LLM_BACKUP_MODEL", scope) or "gpt-6-luna",
            "AUTODECISION_TEST_LLM_BACKUP_API_KEY",
            _user_env("AUTODECISION_TEST_LLM_BACKUP_BASE_URL", scope).rstrip("/") or shared_base,
        ),
    ]


def probe(model: str, key_name: str, base_url: str, timeout: float, scope: str) -> dict[str, object]:
    if not base_url:
        return {"model": model, "status": "missing_base_url"}
    key = _user_env(key_name, scope)
    if not key:
        return {"model": model, "status": "missing_key"}
    started = time.perf_counter()
    try:
        response = requests.post(
            base_url + "/chat/completions",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply exactly OK."}],
                "max_tokens": 12,
            },
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return {"model": model, "error": type(exc).__name__}

    elapsed = round(time.perf_counter() - started, 3)
    result: dict[str, object] = {"model": model, "http": response.status_code, "seconds": elapsed}
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.ok:
        choices = body.get("choices") if isinstance(body, dict) else []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        usage = body.get("usage") if isinstance(body, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        result.update(
            has_reply=bool(content),
            reply_is_ok=str(content or "").strip().upper() == "OK",
            usage={
                field: usage[field]
                for field in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage.get(field), (int, float))
            },
        )
        result["available"] = bool(content)
    else:
        error = body.get("error") if isinstance(body, dict) else {}
        code = (error.get("code") or error.get("type")) if isinstance(error, dict) else None
        result["error_code"] = str(code)[:80] if code else "http_error"
        result["available"] = False
    response.close()
    return result


def run_probes(
    providers: list[tuple[str, str, str]],
    timeout: float,
    scope: str,
    *,
    mode: str = "preferred",
    probe_fn=probe,
) -> list[dict[str, object]]:
    results = []
    selected = False
    for model, key_name, base_url in providers:
        if selected and mode == "preferred":
            results.append({"model": model, "status": "skipped_after_success"})
            continue
        result = probe_fn(model, key_name, base_url, timeout, scope)
        results.append(result)
        selected = selected or bool(result.get("available"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--mode",
        choices=("preferred", "all"),
        default="preferred",
        help="Stop at the first available model, or probe every model for an explicit comparison.",
    )
    parser.add_argument(
        "--env-scope",
        choices=("current-user", "process"),
        default="current-user" if sys.platform == "win32" else "process",
        help="Credential source; Windows defaults to the current-user environment to avoid stale shell values.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON receipt path")
    args = parser.parse_args()

    base_url, providers = _providers(args.env_scope)
    if not base_url:
        raise SystemExit("AUTODECISION_TEST_LLM_BASE_URL is not configured; no request sent")
    models = run_probes(providers, args.timeout, args.env_scope, mode=args.mode)
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "order": [model for model, _, _ in providers],
        "env_scope": args.env_scope,
        "mode": args.mode,
        "models": models,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    attempted = [item for item in models if item.get("status") != "skipped_after_success"]
    if args.mode == "all":
        return 0 if attempted and all(item.get("available") for item in attempted) else 1
    return 0 if any(item.get("available") for item in attempted) else 1


if __name__ == "__main__":
    raise SystemExit(main())

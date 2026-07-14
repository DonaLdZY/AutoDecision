#!/usr/bin/env python3
"""Audit release-candidate files across AutoDecision's four Git repositories."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml


ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = (
    ROOT,
    ROOT / "core" / "AutoRealize",
    ROOT / "core" / "MLEvolve-Alter",
    ROOT / "core" / "AutoReport",
)

TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".csv",
    ".env",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".gitmodules",
    "Dockerfile",
    "requirements",
}
STRICT_JSON_EXCLUDES = {
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
}

SECRET_PATTERNS = (
    ("OpenAI-compatible API key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\((?P<target>[^)]+)\)")


def git_files(repository: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    relative_paths = [
        Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]
    return [repository / path for path in relative_paths]


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_text_file(path: Path) -> bool:
    name = path.name
    return (
        name in TEXT_FILENAMES
        or path.suffix.lower() in TEXT_EXTENSIONS
    )


def forbidden_runtime_reason(path: Path, repository: Path) -> str | None:
    relative = path.relative_to(repository).as_posix()
    parts = relative.split("/")
    name = parts[-1]
    if name == ".env" or name.startswith(".env."):
        return "environment/secret file"
    if any(part in {".dev-state", ".state", "runs", "__pycache__"} for part in parts):
        return "runtime output"
    if path.suffix.lower() in {".pyc", ".pyo"}:
        return "Python bytecode"
    return None


def validate_markdown_links(path: Path, text: str, errors: list[str]) -> None:
    for match in MARKDOWN_LINK.finditer(text):
        target = match.group("target").strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target = unquote(target.split("#", 1)[0])
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            errors.append(f"{display_path(path)}: broken relative link: {target}")


def audit_file(path: Path, repository: Path, errors: list[str], counts: dict[str, int]) -> None:
    reason = forbidden_runtime_reason(path, repository)
    if reason:
        errors.append(f"{display_path(path)}: forbidden {reason}")
        return
    if not path.is_file() or not is_text_file(path):
        return

    counts["text"] += 1
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        errors.append(f"{display_path(path)}: not valid UTF-8: {exc}")
        return

    for label, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"{display_path(path)}:{line}: possible {label}")

    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        counts["yaml"] += 1
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            errors.append(f"{display_path(path)}: invalid YAML: {exc}")
    elif suffix == ".json" and path.name not in STRICT_JSON_EXCLUDES:
        counts["json"] += 1
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{display_path(path)}: invalid JSON: {exc}")
    elif suffix == ".md":
        counts["markdown"] += 1
        validate_markdown_links(path, text, errors)


def main() -> int:
    errors: list[str] = []
    counts = {"files": 0, "text": 0, "yaml": 0, "json": 0, "markdown": 0}
    seen: set[Path] = set()

    for repository in REPOSITORIES:
        if not (repository / ".git").exists():
            errors.append(f"{display_path(repository)}: Git repository/submodule is not initialized")
            continue
        try:
            candidates = git_files(repository)
        except subprocess.CalledProcessError as exc:
            errors.append(f"{display_path(repository)}: git ls-files failed: {exc}")
            continue
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            counts["files"] += 1
            audit_file(path, repository, errors, counts)

    if errors:
        print("Repository audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        "Repository audit passed: "
        f"{counts['files']} release-candidate files, {counts['text']} UTF-8 text files, "
        f"{counts['yaml']} YAML files, {counts['json']} strict JSON files, "
        f"{counts['markdown']} Markdown files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

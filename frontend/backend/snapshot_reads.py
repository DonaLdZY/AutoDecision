"""Read-only, revision-aware cache for local UI artifacts.

Only the latest revision of a path is retained. The byte budget bounds retained
source text; large journals are read without caching. Callers must not mutate
returned JSON values.
"""
from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
import threading
from typing import Any

_MAX_BYTES = 32 * 1024 * 1024
_MAX_ENTRIES = 64
_cache: OrderedDict[tuple[str, str], tuple[tuple[int, int], Any, int]] = OrderedDict()
_lock = threading.RLock()
_retained_bytes = 0


def _read(path: Path, kind: str, default: Any) -> Any:
    global _retained_bytes
    key = (str(path.resolve()), kind)
    try:
        info = path.stat()
        revision = (info.st_mtime_ns, info.st_size)
        with _lock:
            cached = _cache.get(key)
            if cached and cached[0] == revision:
                _cache.move_to_end(key)
                return cached[1]
        text = path.read_text(encoding="utf-8-sig")
        value = json.loads(text) if kind == "json" else text
        after = path.stat()
        # Never cache a partial revision while another process is writing.
        if (after.st_mtime_ns, after.st_size) != revision:
            return default
        with _lock:
            previous = _cache.pop(key, None)
            if previous:
                _retained_bytes -= previous[2]
            if info.st_size <= _MAX_BYTES:
                _cache[key] = (revision, value, info.st_size)
                _retained_bytes += info.st_size
            while _cache and (_retained_bytes > _MAX_BYTES or len(_cache) > _MAX_ENTRIES):
                _, removed = _cache.popitem(last=False)
                _retained_bytes -= removed[2]
        return value
    except (OSError, ValueError, UnicodeError):
        return default


def json_artifact(path: Path, default: Any = None) -> Any:
    return _read(path, "json", default)


def text_artifact(path: Path) -> str:
    return _read(path, "text", "")

"""Offline lossless record-table encoding experiment; never changes live prompts."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.prompt_cache import _stable_payload, estimate_text_tokens, lossless_json
from autorealize.review_prompt import decode_review_snapshot

MARKER = "$record_table"
POLICY = (
    "A sole $record_table object encodes an ordered list of complete records. "
    "Its schemas are lists of exact object keys. Each row starts with its zero-based schema index, "
    "followed by all values for that schema in order. Reconstruct each row by pairing those keys "
    "with those values. Missing keys remain missing; null, false, zero and empty values are distinct. "
    "Row order, field names, all values and all constraints are preserved. "
    "First resolve the ordinary lossless $prompt_ref aliases. This is input encoding only, not output format."
)


def pack(value):
    if isinstance(value, dict):
        return {key: pack(item) for key, item in value.items()}
    if not isinstance(value, list):
        return value
    converted = [pack(item) for item in value]
    if len(value) < 4 or not all(isinstance(item, dict) for item in value):
        return converted
    schemas, indices, rows = [], {}, []
    for item in converted:
        keys = tuple(item)
        if keys not in indices:
            indices[keys] = len(schemas)
            schemas.append(list(keys))
        rows.append([indices[keys], *item.values()])
    table = {MARKER: {"schemas": schemas, "rows": rows}}
    return table if len(dumps(table)) + 100 < len(dumps(converted)) else converted


def unpack(value):
    if isinstance(value, dict) and set(value) == {MARKER}:
        table = value[MARKER]
        result = []
        for row in table["rows"]:
            keys = table["schemas"][row[0]]
            if len(row) != len(keys) + 1:
                raise ValueError("Record length does not match schema")
            result.append({key: unpack(cell) for key, cell in zip(keys, row[1:], strict=True)})
        return result
    if isinstance(value, list):
        return [unpack(item) for item in value]
    if isinstance(value, dict):
        return {key: unpack(item) for key, item in value.items()}
    return value


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def encode(value):
    literal = dumps(value)
    if any('"' + marker + '"' in literal for marker in (MARKER, "$prompt_ref")):
        return literal
    candidate = dumps({"_record_table_encoding": POLICY, "data": pack(value)})
    candidate = lossless_json(json.loads(candidate), sort_keys=False, canonical_matches=True, min_shared_chars=160)
    decoded = decode_review_snapshot(candidate)
    recovered = unpack(decoded["data"])
    if dumps(recovered) != literal:
        raise ValueError("Record encoding changed original values or order")
    return candidate if len(candidate) < len(literal) else literal


def main():
    directory = ROOT / "runs/industrial-examples-20260907/optimization-validation/delivery-qdi-context-20260908"
    context = _stable_payload(json.loads((directory / "context.json").read_text(encoding="utf-8-sig")))
    original = lossless_json(context, sort_keys=False)
    candidate = encode(context)
    fixtures = [
        [{"alpha": 0, "beta": None, "gamma": False, "description": "preserve this repeated schema"},
         {"alpha": 1, "beta": "", "gamma": True, "description": "preserve this repeated schema"},
         {"alpha": "0", "beta": [], "gamma": {}, "description": "preserve this repeated schema"},
         {"alpha": 0.0, "beta": "\r\n", "gamma": "false", "description": "preserve this repeated schema"}] * 3,
        [{"a": i, "b": i + 1} if i % 2 else {"b": i, "c": None} for i in range(20)],
        {MARKER: {"original_source": "literal marker remains literal"}},
    ]
    for fixture in fixtures:
        encode(fixture)
    (directory / "record-table-candidate.txt").write_text(candidate, encoding="utf-8")
    result = {"scope": "Offline serialization and type/order roundtrip only; provider output quality not tested, not released",
              "source_estimated_tokens": estimate_text_tokens(original),
              "candidate_estimated_tokens": estimate_text_tokens(candidate),
              "source_chars": len(original), "candidate_chars": len(candidate),
              "full_context_roundtrip": True, "edge_cases": len(fixtures),
              "live_prompt_changed": False}
    (directory / "record-table-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

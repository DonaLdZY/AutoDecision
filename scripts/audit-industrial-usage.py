"""Aggregate provider usage and verify lossless prompt reductions on saved artifacts."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.prompt_cache import lossless_json


def aggregate(root):
    stages = []
    seen_request_ids = set()
    seen_legacy_calls = set()
    sources = [(path, [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()])
               for path in root.rglob("llm_usage.jsonl")]
    for path in root.rglob("report_trace.json"):
        sources.append((path, json.loads(path.read_text(encoding="utf-8-sig")).get("llm_usage", [])))
    for path in root.rglob("calls.json"):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            rows = [{"prompt_name": "provider_probe", **item["usage"]} for item in payload
                    if isinstance(item, dict) and isinstance(item.get("usage"), dict)]
        else:
            rows = payload.get("usage", []) if isinstance(payload, dict) else []
        if isinstance(rows, list):
            sources.append((path, rows))
    for path, rows in sources:
        result = {"path": str(path.relative_to(root)), "provider_calls": 0, "local_cache_hits": 0,
                  "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
                  "cached_input_tokens": 0, "cache_known_input_tokens": 0}
        by_prompt = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        for row in rows:
            request_id = row.get("request_id")
            if request_id and request_id in seen_request_ids:
                continue
            if request_id:
                seen_request_ids.add(request_id)
            elif row.get("ts") is not None or row.get("timestamp") is not None:
                # Archived task/repair copies contain identical legacy rows.
                # Untimestamped probes remain separate potentially paid calls.
                identity = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if identity in seen_legacy_calls:
                    continue
                seen_legacy_calls.add(identity)
            if row.get("source") in {"local_cache", "cache"}:
                result["local_cache_hits"] += 1
                continue
            prompt = int(row.get("prompt_tokens") or 0)
            output = int(row.get("completion_tokens") or 0)
            details = row.get("prompt_tokens_details") or {}
            cached = row.get("prompt_cache_hit_tokens")
            known = row.get("provider_cache_tokens_known")
            if cached is None:
                cached = details.get("cached_tokens")
            if known is None:
                known = cached is not None
            result["provider_calls"] += 1
            result["input_tokens"] += prompt
            result["output_tokens"] += output
            result["reasoning_tokens"] += int(row.get("reasoning_tokens") or
                (row.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
            result["cached_input_tokens"] += int(cached or 0) if known else 0
            result["cache_known_input_tokens"] += prompt if known else 0
            item = by_prompt[str(row.get("prompt_name") or row.get("component") or "unknown")]
            item["calls"] += 1
            item["input_tokens"] += prompt
            item["output_tokens"] += output
        result["top_prompts"] = sorted(by_prompt.items(), key=lambda pair: -pair[1]["input_tokens"])[:10]
        stages.append(result)
    fields = ("provider_calls", "local_cache_hits", "input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "cache_known_input_tokens")
    totals = {key: sum(row[key] for row in stages) for key in fields}
    prompt = totals["input_tokens"]
    known = totals["cache_known_input_tokens"]
    cached = totals["cached_input_tokens"]
    totals["input_share_of_tokens"] = prompt / max(1, prompt + totals["output_tokens"])
    totals["cache_telemetry_coverage"] = known / prompt if prompt else None
    totals["cache_hit_ratio"] = cached / prompt if prompt and known == prompt else None
    totals["known_cache_hit_ratio"] = cached / known if known else None
    totals["observed_cache_hit_ratio_lower_bound"] = cached / prompt if prompt else None
    return {"root": str(root), "totals": totals, "stages": stages,
            "cost_note": "Renice prices are not configured. Tokens are measured; currency cost is unknown. Missing cache metadata is not a zero hit rate. Failures without returned usage may still be billable and are not included in these token totals."}


def verify_lossless(root):
    measurements = []
    for path in root.glob("autorealize/realize_report/context_artifacts/*.json"):
        source = json.loads(path.read_text(encoding="utf-8"))
        original = json.dumps(source, ensure_ascii=False, indent=2, sort_keys=True)
        compact = lossless_json(source)
        envelope = json.loads(compact)

        def resolve(value):
            if isinstance(value, dict) and set(value) == {"$prompt_ref"}:
                node = envelope
                for segment in value["$prompt_ref"].split("/")[1:]:
                    key = segment.replace("~1", "/").replace("~0", "~")
                    node = node[int(key)] if isinstance(node, list) else node[key]
                return resolve(node)
            if isinstance(value, dict):
                return {key: resolve(item) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            return value

        decoded = resolve(envelope["data"]) if "_prompt_encoding" in envelope else envelope
        assert decoded == source, path
        measurements.append({"file": path.name, "original_chars": len(original), "compact_chars": len(compact), "exact_round_trip": True})
    return {"artifacts_checked": len(measurements), "original_chars": sum(row["original_chars"] for row in measurements),
            "compact_chars": sum(row["compact_chars"] for row in measurements),
            "largest_artifacts": sorted(measurements, key=lambda row: -row["original_chars"])[:10]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "runs/Live validation - store sales")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/industrial-examples-20260907/prior-cost-audit.json")
    parser.add_argument("--verify-lossless", action="store_true")
    args = parser.parse_args()
    result = aggregate(args.root)
    if args.verify_lossless:
        result["lossless_check"] = verify_lossless(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"totals": result["totals"], "lossless_check": result.get("lossless_check"), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Probe the authorized provider and record actual usage without exposing secrets."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import yaml
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "industrial-examples-20260907"


def main():
    settings = yaml.safe_load((ROOT / "runs/live-validation-20260906/settings.yaml").read_text(encoding="utf-8"))
    models = settings["llm"]["modelLibrary"]
    entry = next(item for item in models if item.get("apiKey"))
    secret = entry["apiKey"]
    client = OpenAI(base_url="https://api.renice.cc/v1", api_key=secret, timeout=240, max_retries=0)
    if "--comparison" in sys.argv:
        sys.path.insert(0, str(ROOT / "core/AutoRealize"))
        from autorealize.prompt_cache import lossless_json
        rules = {
            "C01": "FYP01/业务006, MH101/业务009, NH001/业务101, SMG01/业务014, YPF01/业务015 cannot share a vehicle with other owners.",
            "C02": "There is no delivery-stop-count cap. Never impose an invented limit of three, five or any other fixed number of stops.",
            "C03": "Carrier and vehicle-type availability is bounded by the exact daily capacity table. A missing capacity date is unknown, not unlimited.",
            "C04": "Total physical cargo weight and volume must both respect vehicle capacity. Standard-box billing quantity is not physical capacity.",
            "C05": "Enforce supplied pickup and delivery windows, address vehicle restrictions, empty warehouse entry and compatible loading order.",
            "C06": "Unknown tariff costs are not zero. Unconfirmed hired vehicles must not count as confirmed feasible available supply.",
            "C07": "Minimize hard violations first, maximize served priority orders second, minimize comparable verified cost third. Compare all algorithms with identical constraints and order coverage.",
            "C08": "Do not claim source targets of 3-8% cost savings or at least 95% on-time delivery as measured without matched operational evidence.",
        }
        context = {"rules": rules, "duplicate_handoff": rules, "duplicate_audit": rules,
                   "late_amendment": "C02 applies without exceptions in this experiment."}
        results = []
        for name, prompt in (("original", json.dumps(context, ensure_ascii=False, indent=2)), ("lossless", lossless_json(context))):
            started = time.monotonic()
            response = client.chat.completions.create(model="gpt-5.6-luna", reasoning_effort="xhigh", max_completion_tokens=8192,
                response_format={"type": "json_object"}, messages=[
                    {"role": "system", "content": "Read all task constraints, resolving input references exactly. Return JSON only."},
                    {"role": "user", "content": prompt},
                    {"role": "user", "content": 'Return {"rules":{...}} containing every C01-C08 rule and its EXACT original text, including any long tail constraints. No summaries.'}])
            content = response.choices[0].message.content or ""
            actual = json.loads(content).get("rules")
            results.append({"variant": name, "passed_exact_constraints": actual == rules, "input_chars": len(prompt),
                            "usage": response.usage.model_dump() if response.usage else {}, "seconds": round(time.monotonic()-started, 2),
                            "returned_rules": actual})
            print(json.dumps({key: val for key, val in results[-1].items() if key != "returned_rules"}), flush=True)
            (OUT / "constraint-comparison.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if not all(row["passed_exact_constraints"] for row in results):
            raise RuntimeError("Constraint equivalence probe failed")
        return
    stable = "Industrial task constraints. " + "\n".join(
        f"Constraint {i}: retain source evidence and physical column names; use training-only preprocessing; report feasibility separately from score."
        for i in range(90))
    rows = []
    for index in range(3):
        started = time.monotonic()
        try:
            result = client.chat.completions.create(
                model="gpt-5.6-luna", reasoning_effort="xhigh", max_completion_tokens=4096,
                prompt_cache_key="industrial-probe-20260907-v1",
                messages=[{"role": "system", "content": "Return valid JSON. Respect every supplied constraint."},
                          {"role": "user", "content": stable},
                          {"role": "user", "content": f'Return {{"status":"ready","probe":{index}}}.'}],
                response_format={"type": "json_object"},
            )
            text = result.choices[0].message.content or ""
            row = {"probe": index, "model_requested": "gpt-5.6-luna", "model_returned": result.model,
                   "reasoning_effort_requested": "xhigh", "passed": json.loads(text).get("status") == "ready",
                   "response": text, "usage": result.usage.model_dump() if result.usage else {},
                   "seconds": round(time.monotonic() - started, 2)}
        except Exception as exc:
            row = {"probe": index, "passed": False, "error": str(exc).replace(secret, "[REDACTED]")[:1500],
                   "seconds": round(time.monotonic() - started, 2)}
        rows.append(row)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "provider-probe.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if not row["passed"]:
            break


if __name__ == "__main__":
    main()

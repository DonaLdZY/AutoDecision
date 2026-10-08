"""Rebuild the current authority request without sending it or altering task state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.config import AutoRealizeConfig
from autorealize.llm.client import LLMClient, _prompt_part_stats
from autorealize.models import FileSummary
from autorealize.modules.data_cognition import DataCognitionModule


class CapturedRequest(Exception):
    pass


def main():
    stages = runpy.run_path(str(Path(__file__).with_name("industrial-stage-control.py")))
    task = stages["current_task"]("delivery")
    report = Path(task["run_dir"]) / "autorealize/realize_report"
    cfg = AutoRealizeConfig.from_file(report / "final_config.yaml")
    cfg.llm.api_key = "offline-capture-no-network"
    summaries = [FileSummary.model_validate_json(path.read_text(encoding="utf-8-sig"))
                 for path in sorted((report / "file_cognition").glob("*.json"))]
    captured = {}
    with tempfile.TemporaryDirectory(prefix="delivery-authority-audit-") as temporary:
        client = LLMClient(cfg, Path(temporary))

        def capture(**kwargs):
            captured.update(kwargs)
            raise CapturedRequest()

        client._chat_completion_with_network_retry = capture
        module = DataCognitionModule(cfg, SimpleNamespace(llm_client=client), report)
        try:
            module._extract_authoritative_memory(
                data_root=Path(task["config"]["input_root"]),
                task_hint=task["config"]["auto_realize"]["task_hint"],
                file_summaries=summaries,
            )
        except CapturedRequest:
            pass
        finally:
            client.client.close()
    if not captured:
        raise RuntimeError("No authority request was captured")
    kwargs = captured["create_kwargs"]
    parts, total = _prompt_part_stats([
        {"name": f"message_{i}", **message} for i, message in enumerate(kwargs["messages"])
    ])
    result = {
        "scope": "Offline exact request reconstruction from current hint and saved source profiles; token counts are estimates, not billed usage",
        "task_id": task["id"], "phase": task["phase"],
        "prompt_name": captured["prompt_name"], "model": kwargs["model"],
        "reasoning_effort": kwargs.get("reasoning_effort"),
        "max_tokens": kwargs.get("max_tokens"),
        "estimated_input_tokens": total, "message_parts": parts,
        "request_sha256": hashlib.sha256(json.dumps(kwargs["messages"], ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "file_profiles": len(summaries),
        "provider_usage_known": False, "cache_hit_ratio": None,
    }
    output = stages["batch"].OUT / "optimization-validation/delivery-authority-request-20260908.json"
    stages["batch"].save(output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

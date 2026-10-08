"""Restore the explicitly confirmed provider without resetting tasks or resources."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import time

import yaml

SPEC = importlib.util.spec_from_file_location("industrial_batch", Path(__file__).with_name("industrial-examples.py"))
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)


def main():
    settings_path = batch.OUT / "settings.yaml"
    current = yaml.safe_load(settings_path.read_text(encoding="utf-8-sig"))
    previous = yaml.safe_load((batch.ROOT / "runs/live-validation-20260906/settings.yaml").read_text(encoding="utf-8-sig"))
    credential = next(item["apiKey"] for item in previous["llm"]["modelLibrary"]
                      if str(item.get("baseUrl", "")).rstrip("/") == "https://api.renice.cc/v1"
                      and str(item.get("apiKey", "")).startswith("sk-"))
    archive = batch.OUT / "stage-archives" / ("provider-settings-" + str(time.time_ns()))
    archive.mkdir(parents=True)
    (archive / "previous-settings.yaml").write_bytes(settings_path.read_bytes())
    model = {"id": "industrial-text", "name": "工业实例文本模型", "model": "gpt-5.6-luna",
             "apiKey": credential, "baseUrl": "https://api.renice.cc/v1", "thinkingMode": "default",
             "reasoningEffort": "xhigh", "maxTokens": 32768, "contextWindowTokens": 131072}
    vision = {**model, "id": "industrial-vision", "name": "工业文档视觉模型", "model": "glm-5.3-flash", "reasoningEffort": "default"}
    llm = current.setdefault("llm", {})
    llm["modelLibrary"] = [item for item in llm.get("modelLibrary", []) if item.get("id") not in {model["id"], vision["id"]}] + [model, vision]
    llm.setdefault("roleModels", {}).update(autoRealize=model["id"], autoMlCode=model["id"], autoMlFeedback=model["id"], autoRealizeVision=vision["id"])
    current["python"] = {**current.get("python", {}), "executable": sys.executable}
    current["coreServices"] = {**current.get("coreServices", {}),
                               "autoRealizeBaseUrl": "http://127.0.0.1:18101",
                               "algoEvolveBaseUrl": "http://127.0.0.1:18103",
                               "autoReportBaseUrl": "http://127.0.0.1:18104"}
    batch.request("/api/settings/global", current, method="PUT")
    saved = yaml.safe_load(settings_path.read_text(encoding="utf-8-sig"))
    chosen = next(item for item in saved["llm"]["modelLibrary"] if item["id"] == model["id"])
    assert all(chosen[key] == model[key] for key in ("model", "apiKey", "baseUrl", "reasoningEffort"))
    assert all(saved["llm"]["roleModels"][role] == model["id"] for role in ("autoRealize", "autoMlCode", "autoMlFeedback"))
    batch.save(batch.OUT / "optimization-validation/provider-restoration.json", {
        "passed": True, "authorization": "User reconfirmed Renice / gpt-5.6-luna / xhigh",
        "model": chosen["model"], "reasoning_effort": chosen["reasoningEffort"], "archive": str(archive),
        "scope": "Global provider and running local service routes; no task, resource or existing process restart",
    })
    print("Restored Renice / gpt-5.6-luna / xhigh for all text roles; saved credentials verified without disclosure.")


if __name__ == "__main__":
    main()

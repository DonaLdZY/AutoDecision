"""Apply the user's short Chinese inputs to the three unstarted examples."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import time

SPEC = importlib.util.spec_from_file_location("industrial_batch", Path(__file__).with_name("industrial-examples.py"))
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)


def main():
    state = batch.load_state()
    tasks = {item["id"]: item for item in batch.request("/api/tasks")}
    manifest = json.loads((batch.OUT / "manifest.json").read_text(encoding="utf-8"))
    selected = {slug: tasks[state["tasks"][slug]["id"]] for slug in batch.SHORT_TASK_HINTS}
    if any(task["status"] != "idle" or task.get("run_dir") for task in selected.values()):
        raise RuntimeError("Short inputs may only replace idle, unstarted examples")
    archive = batch.OUT / "stage-archives" / ("short-inputs-" + str(time.time_ns()))
    archive.mkdir(parents=True)
    batch.save(archive / "previous-manifest.json", manifest)
    results = []
    for slug, task in selected.items():
        original = task["config"]
        hint = batch.SHORT_TASK_HINTS[slug]
        protocol_path = batch.OUT / (slug + "-protocol.md")
        if protocol_path.exists():
            (archive / protocol_path.name).write_bytes(protocol_path.read_bytes())
        batch.save(archive / (slug + "-previous-config.json"), original)
        config = deepcopy(original)
        config["auto_realize"]["task_hint"] = hint
        updated = batch.request("/api/tasks/" + task["id"], config, method="PUT")
        if updated["config"] != config:
            raise RuntimeError(f"{slug}: saved config differs from requested config")
        protocol_path.write_text(hint + "\n", encoding="utf-8")
        entry = next(item for item in manifest["tasks"] if item["slug"] == slug)
        entry["payload"] = config
        batch.save(batch.OUT / "manifest.json", manifest)
        results.append({"slug": slug, "task_id": task["id"], "task_hint": hint,
                        "previous_chars": len(original["auto_realize"]["task_hint"]), "chars": len(hint),
                        "only_task_hint_changed": True,
                        "search_seconds": config["auto_ml"]["time_limit_secs"]})
    result = {"passed": True, "scope": "User input only; no stages started or restarted",
              "archive_policy": "Historical agent-written protocols, not authority or additional input for the new short-input runs",
              "archive": str(archive), "tasks": results}
    batch.save(batch.OUT / "optimization-validation/short-task-inputs.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

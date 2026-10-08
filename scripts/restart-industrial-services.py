"""Reload idle guarded services without modifying task configuration or artifacts."""
import importlib.util
import json
from pathlib import Path
import time

import psutil

SPEC = importlib.util.spec_from_file_location("industrial_batch", Path(__file__).with_name("industrial-examples.py"))
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)


def main():
    if any(task["status"] == "running" for task in batch.request("/api/tasks")):
        raise RuntimeError("Wait for active service stages before reloading")
    state = batch.load_state()
    supervisor = psutil.Process(state["pid"])
    command = supervisor.cmdline()
    script = str((batch.ROOT / "scripts/industrial-examples.py").resolve())
    if script not in command or "run" not in command:
        raise RuntimeError("Saved PID does not own this batch supervisor")
    children = supervisor.children(recursive=True)
    if any(child.name().lower() != "conhost.exe" and "uvicorn" not in child.cmdline() for child in children):
        raise RuntimeError("Supervisor still has a non-service child; inspect before reloading")
    if any(task["status"] == "running" for task in batch.request("/api/tasks")):
        raise RuntimeError("A stage started during reload validation")
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    try:
        supervisor.terminate()
    except psutil.NoSuchProcess:
        pass
    _, alive = psutil.wait_procs([*children, supervisor], timeout=8)
    for child in alive:
        child.kill()
    psutil.wait_procs(alive, timeout=5)
    batch.launch()
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if batch.request("/api/health"):
                print(json.dumps({"reloaded": True, "task_artifacts_preserved": True}))
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Reload did not reach a healthy gateway; inspect service logs")


if __name__ == "__main__":
    main()

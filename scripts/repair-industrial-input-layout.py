"""Verify and replace old input directory symlinks with recursively discoverable files."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from utils import copytree
from utils.accelerator_runtime import ExecutionSlotPool


@contextmanager
def exclusive_execution_slots(directory, count):
    pool = ExecutionSlotPool(directory, count)
    deadline = time.monotonic() + 55
    leases = []
    try:
        while time.monotonic() < deadline:
            leases = []
            for index in range(count):
                stream = pool._try_acquire(index)
                if stream is None:
                    break
                leases.append(stream)
            if len(leases) == count:
                yield
                return
            pool.release(leases)
            leases = []
            time.sleep(.25)
        raise RuntimeError("Training is still active; retry layout application at a later execution boundary")
    finally:
        pool.release(leases)


def inventory(root):
    files = {}
    def visit(directory, relative, ancestors):
        resolved = directory.resolve()
        if resolved in ancestors:
            raise RuntimeError("Cyclic input directory link")
        for entry in resolved.iterdir():
            name = relative / entry.name
            path = entry.resolve()
            if path.is_dir():
                visit(path, name, ancestors | {resolved})
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            files[name.as_posix()] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    visit(root, Path(), set())
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--apply-result", type=Path)
    parser.add_argument("--live-under-execution-lock", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("input_repair_stages", Path(__file__).with_name("industrial-stage-control.py"))
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task(args.slug)
    source = (Path(task["auto_ml_workspace_dir"]) / "input").resolve()
    if not source.is_relative_to(stages.batch.OUT.resolve()):
        raise RuntimeError("Input directory is outside the active batch")
    if args.apply_result:
        record = stages.read_json(args.apply_result)
        candidate = Path(record["candidate"])
        if record.get("passed") is not True or Path(record["source"]).resolve() != source:
            raise RuntimeError("A source-matched verified layout is required")
        if task["status"] == "running" and not args.live_under_execution_lock:
            raise RuntimeError("Stop the search and wait for the durable checkpoint before replacing its input")
        status = stages.read_json(Path(task["auto_ml_log_dir"]) / "run_status.json", {})
        if not args.live_under_execution_lock and status.get("status") != "interrupted_resumable":
            raise RuntimeError("A resumable checkpoint is required")
        if inventory(source) != record["files"] or inventory(candidate) != record["files"]:
            raise RuntimeError("Input files changed after layout verification")
        if not candidate.resolve().is_relative_to(args.apply_result.parent.resolve()):
            raise RuntimeError("Candidate input must remain inside its reviewed repair directory")
        profile = stages.read_json(stages.batch.OUT / "runtime-resource-profile.json")
        with exclusive_execution_slots(stages.batch.OUT / "execution-slots", profile["gpu_execution_slots"]):
            archive = source.with_name(f"input-before-layout-repair-{time.time_ns()}")
            source.rename(archive)
            try:
                candidate.rename(source)
            except Exception:
                archive.rename(source)
                raise
        record.update(applied_at=time.time(), archive=str(archive))
        stages.batch.save(args.apply_result, record)
        print(json.dumps({"applied": True, "archive": str(archive)}))
        return
    dest = stages.batch.OUT / "optimization-validation" / f"{args.slug}-input-layout-{time.time_ns()}"
    candidate = dest / "input"
    candidate.mkdir(parents=True)
    expected = inventory(source)
    copytree(source, candidate, use_symlinks=True)
    actual = inventory(candidate)
    discovered = {path.relative_to(candidate).as_posix() for path in candidate.rglob("*") if path.is_file()}
    confined = all(path.resolve().is_relative_to(candidate.resolve()) for path in candidate.rglob("*"))
    result = {"slug": args.slug, "source": str(source), "candidate": str(candidate), "files": expected,
              "passed": actual == expected and discovered == set(expected) and confined,
              "all_bytes_equal": actual == expected, "recursive_discovery_complete": discovered == set(expected),
              "resolved_paths_within_input": confined, "file_count": len(expected),
              "scope": "Filesystem layout verification; no candidate code, dataset values, evaluator or search duration changed"}
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "passed": result["passed"], "files": len(expected)}))


if __name__ == "__main__":
    main()

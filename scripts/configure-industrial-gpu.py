"""Apply the user's resource allocation to a reviewed concurrent example batch."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import psutil

SPEC = importlib.util.spec_from_file_location("industrial_batch", Path(__file__).with_name("industrial-examples.py"))
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slugs", nargs="+", default=["ai4i"], choices=["ai4i", "traffic", "chemical", "deposition", "delivery"])
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if len(set(args.slugs)) != len(args.slugs) or not 1 <= len(args.slugs) <= 4 or not 1 <= args.workers <= 8:
        raise ValueError("Use one to four distinct tasks and one to eight Workers; executions remain globally limited")
    state = batch.load_state()
    tasks = batch.request("/api/tasks")
    if any(task["status"] == "running" for task in tasks):
        raise RuntimeError("Stop active stages before changing resource allocation")
    guardian = psutil.Process(state["pid"])
    if "industrial-examples.py" not in " ".join(guardian.cmdline()):
        raise RuntimeError("Guardian identity mismatch")
    owned_rss = sum(p.memory_info().rss for p in [guardian, *guardian.children(recursive=True)])
    free_gib = psutil.virtual_memory().available / batch.GIB
    total_limit = min(26, int(free_gib + owned_rss / batch.GIB - 2))
    if total_limit < 10:
        raise RuntimeError("Insufficient host memory for the larger GPU profile")
    task_limit = min(10, total_limit - 2)
    profile = {"authorization": "explicit_user_update", "created_at": time.time(), "active_slugs": args.slugs,
               "cpu_cores": 18, "task_memory_gib": task_limit,
               "services_and_tasks_hard_limit_gib": total_limit,
               "minimum_free_gib_to_start": 5, "emergency_free_gib": 2,
               "gpu_free_reserve_gib": 1, "torch_memory_fraction": .3,
               "gpu_execution_slots": 2, "workers_per_task": args.workers, "simultaneous_tasks": min(3, len(args.slugs)),
               "measured_available_gib": free_gib, "measured_guardian_tree_rss_gib": owned_rss / batch.GIB}
    override = {"authorization": "explicit_user_update", "scope": "Runtime resources only",
                "user_instruction": "Run examples concurrently with more Workers. Keep only one to two GiB system RAM headroom and use GPU resources freely within available memory.",
                "cpu_threads_per_execution": 4, "cpu_cores_per_task": 8, "task_process_tree_ram_gib": task_limit,
                "gpu": "NVIDIA RTX 5070 Ti, CUDA device 0, approximately 16 GiB total VRAM",
                "workers": f"{args.workers} generation/review Workers per task. Up to {min(3, len(args.slugs))} tasks may run concurrently. Cross-process OS locks allow at most two candidate executions across the whole batch.",
                "gpu_limits": "Keep 1 GiB globally free VRAM and 2 GiB system RAM headroom. PyTorch allocator is capped at 30% of total device memory per execution. For CatBoost GPU start with devices='0', gpu_ram_part=0.20, pinned_memory_size='256mb', bounded depth/iterations and thread_count<=4. Check BOTH host memory and VRAM before larger allocations; Windows can charge CUDA allocations to the host Job Object budget. Do not spawn nested parallel GPU fits. Release tensors/models between fits. Shared execution admission and monitoring can stop a candidate on memory pressure; this is not a universal CUDA hard allocation quota.",
                "algorithm_choice": "Use proven installed libraries and GPU training where useful. LightGBM CPU and other CPU baselines remain valid. Consider a supported GPU candidate; report actual device use and failures, never imply GPU merely from availability.",
                "unchanged_requirements": "All original business, feature-source, split, metric, leakage, deliverable and independent inference constraints remain mandatory. Search duration is 10800 actual seconds. Never evaluate holdout during search. Do not introduce scores or candidates from previous failed trials."}
    resources = {"cpu_cores": 8, "memory_limit_gb": task_limit, "accelerator_mode": "selected",
                 "accelerator_device_ids": ["cuda:0"], "monitor_interval_seconds": .5}
    manifest = json.loads((batch.OUT / "manifest.json").read_text(encoding="utf-8"))
    for slug in args.slugs:
        task = next(row for row in tasks if row["id"] == state["tasks"][slug]["id"])
        config = task["config"]
        config["resources"] = resources.copy()
        config["auto_ml"].update(skip_code_review=False, parallel_search_num=args.workers)
        config["auto_realize"]["llm_concurrency"] = args.workers
        root = Path(task["run_dir"]) if task.get("run_dir") else Path(config["output_root"]) / config["task_name"]
        root.mkdir(parents=True, exist_ok=True)
        target = root / "runtime_resource_override.json"
        update = override.copy()
        if target.is_file():
            update["supersedes_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        if not task.get("run_dir") and slug not in batch.SHORT_TASK_HINTS:
            # New intent recognition gets the same explicit resource amendment.
            config["auto_realize"]["task_hint"] += "\n\nLatest user-authorized runtime resource update (overrides earlier resource statements only):\n" + json.dumps(update, sort_keys=True)
        batch.request("/api/tasks/" + task["id"], config, method="PUT")
        batch.save(target, update)
        entry = next(row for row in manifest["tasks"] if row["slug"] == slug)["payload"]
        entry["resources"] = resources.copy()
        entry["auto_ml"]["parallel_search_num"] = args.workers
        entry["auto_realize"] = config["auto_realize"]
    batch.save(batch.OUT / "runtime-resource-profile.json", profile)
    manifest["active_resource_profile"] = profile
    batch.save(batch.OUT / "manifest.json", manifest)
    print(json.dumps(profile))


if __name__ == "__main__":
    main()

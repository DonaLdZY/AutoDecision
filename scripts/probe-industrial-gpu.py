"""Exercise the real candidate runtime on bounded synthetic CUDA workloads."""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from engine.executor import Interpreter
from utils.accelerator_runtime import nvidia_memory
from utils.resource_limits import WindowsJobMemoryLimiter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parallel", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    directory = ROOT / "runs/industrial-examples-20260907/optimization-validation" / f"gpu-runtime-{time.time_ns()}"
    directory.mkdir(parents=True)
    limit_gib = 12 if args.parallel == 2 else 8
    if psutil.virtual_memory().available < (limit_gib + 2) * 1024**3:
        raise RuntimeError("Insufficient host headroom for the bounded runtime probe")
    limiter = WindowsJobMemoryLimiter(limit_gib * 1024 ** 3)
    limiter.attach(os.getpid())
    os.environ.update(CUDA_VISIBLE_DEVICES="0", ALGOEVOLVE_GPU_EXECUTION_SLOTS=str(args.parallel),
                      ALGOEVOLVE_EXECUTION_POOL_PATH=str(directory / "execution-slots"),
                      ALGOEVOLVE_HOST_FREE_RESERVE_GIB="2",
                      ALGOEVOLVE_GPU_FREE_RESERVE_GIB="1", ALGOEVOLVE_TORCH_MEMORY_FRACTION=".3",
                      OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4", MKL_NUM_THREADS="4")
    before = nvidia_memory()
    code = '''from __future__ import annotations
import json
import numpy as np
import torch
from catboost import CatBoostClassifier
assert torch.cuda.is_available()
torch.manual_seed(42)
x = torch.randn(1024, 1024, device="cuda")
z = x @ x.T
torch.cuda.synchronize()
assert torch.isfinite(z).all().item()
del x, z
torch.cuda.empty_cache()
rng = np.random.default_rng(42)
features = rng.normal(size=(1024, 6)).astype(np.float32)
labels = (features[:, 0] + features[:, 1] > 0).astype(int)
model = CatBoostClassifier(iterations=30, depth=4, task_type="GPU", devices="0",
                          gpu_ram_part=.20, pinned_memory_size="256mb",
                          thread_count=4, verbose=False, random_seed=42)
model.fit(features, labels)
probabilities = model.predict_proba(features)[:, 1]
assert np.isfinite(probabilities).all()
assert np.unique(probabilities).size > 10
model.save_model("gpu_probe.cbm")
print(json.dumps({"torch_cuda": torch.version.cuda, "device": torch.cuda.get_device_name(0),
                  "catboost_task_type": model.get_all_params()["task_type"],
                  "cuda_tensor_finite": True, "rows": len(probabilities),
                  "torch_peak_allocated": torch.cuda.max_memory_allocated()}))
'''
    started = time.monotonic()
    def execute(index):
        working = directory / f"execution-{index}"
        working.mkdir()
        runner = Interpreter(working, timeout=120, max_parallel_run=1)
        started_at = time.time()
        execution = runner.run(code, "gpu_probe")
        return {"started_at": started_at, "finished_at": time.time(), **execution.to_dict()}
    with ThreadPoolExecutor(max_workers=args.parallel) as workers:
        executions = list(workers.map(execute, range(args.parallel)))
    result = {"stage": "automl", "slug": "ai4i", "passed": all(row["exc_type"] is None for row in executions),
              "scope": "Synthetic runtime check only; no AI4I training, scoring or holdout access",
              "parallel_executions": args.parallel, "executions": executions, "before": before, "after": nvidia_memory(),
              "seconds": time.monotonic() - started, "host_guard": limiter.describe(),
              "host_peak_bytes": limiter.peak_memory_bytes()}
    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(directory), **result}, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

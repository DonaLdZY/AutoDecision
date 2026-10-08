"""Review one proven pre-input failure, then run the unchanged frozen final entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from engine.executor import Interpreter
from engine.final_evaluation import finalize_selected_candidate
from engine.search_node import Journal
from utils.resource_limits import WindowsJobMemoryLimiter
from utils.serialize import load_json

NODE = "d37ff52bb9ff4782bec6aefcf8ede5c0"
CODE_SHA = "25b91164a8e22b7c6b11559dbdb11635e0fcde847ccd0d8f4fcfb59fd025304b"
DATA_SHA = "9b1cee6f9cb9cd9df2b95814ca90a9a2ff15b7f5f1fba0fae3c643e82072eacc"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    import psutil
    if psutil.virtual_memory().available < 13 * 1024 ** 3:
        raise RuntimeError("Final verification requires at least 13 GiB available memory")
    limiter = WindowsJobMemoryLimiter(4 * 1024 ** 3)
    limiter.attach(os.getpid())
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[:4])
    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4",
                      MKL_NUM_THREADS="4", PYTHONUTF8="1")

    task = json.loads((OUT / "batch-state.json").read_text(encoding="utf-8"))["tasks"]["steel"]
    assert task["status"] == "completed" and task["phase"] == "automl_completed"
    logs, workspace = Path(task["auto_ml_log_dir"]), Path(task["auto_ml_workspace_dir"])
    search = json.loads((logs / "search_state.json").read_text(encoding="utf-8"))
    assert search["cumulative_search_elapsed_seconds"] >= 10800
    node = next(node for node in load_json(logs / "journal.json", Journal).nodes if node.id == NODE)
    assert node.search_eligible and hashlib.sha256(node.code.encode("utf-8")).hexdigest() == CODE_SHA
    active_final = workspace / "final_evaluation"
    original = active_final
    dest = OUT / "optimization-validation/steel-final-input-recovery"
    if not original.exists():
        previous_review = json.loads((dest / "review.json").read_text(encoding="utf-8"))
        original = Path(previous_review["original_attempt_archive"])
        assert original.resolve().is_relative_to((OUT / "stage-archives/steel").resolve())
    state = json.loads((original / "status.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed" and state["exception_type"] == "PermissionError"
    assert state["selection"]["node_id"] == NODE and state["selection"]["code_sha256"] == CODE_SHA
    executed_code = (original / "selected_solution.py").read_text(encoding="utf-8")
    expected_code = Interpreter.isolate_model_path(None, Interpreter.isolate_submission_path(None, node.code, NODE), NODE)
    assert executed_code == expected_code
    assert hashlib.sha256(executed_code.encode("utf-8")).hexdigest() == state["executed_code_sha256"]
    assert "_sha256_file" in (original / "execution.log").read_text(encoding="utf-8")
    for name in ("holdout_evaluation.json", "holdout_predictions.csv", "holdout_locked_fit", "full_history_refit"):
        assert not (original / "artifacts" / name).exists(), f"Possible prior final evaluation: {name}"
    input_root = (workspace / "input").resolve()
    data = input_root / "Steel_industry_data.csv"
    assert digest(data) == DATA_SHA
    probe = dest / "preinput-reproduction"
    probe.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original / "selected_solution.py", probe / "solution.py")
    shutil.copytree(original / "artifacts", probe / "artifacts", dirs_exist_ok=True)
    code = """import importlib.util, json, os, sys
from pathlib import Path
input_root = Path(INPUT_ROOT).resolve()
opened = []
def audit(event, values):
    if event != 'open' or not isinstance(values[0], (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(values[0])).resolve()
    if path == input_root:
        opened.append({'path': str(path), 'kind': 'directory'})
    elif path.is_relative_to(input_root):
        opened.append({'path': str(path), 'kind': 'source_file'})
        raise AssertionError('Attempt to read actual data during pre-input failure verification')
sys.addaudithook(audit)
spec = importlib.util.spec_from_file_location('frozen_failure_probe', 'solution.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    module.final_evaluate(input_root, Path('artifacts'))
except PermissionError as error:
    assert Path(error.filename).resolve() == input_root
else:
    raise AssertionError('Original directory-open failure did not reproduce')
assert opened == [{'path': str(input_root), 'kind': 'directory'}], opened
result = {'passed': True, 'same_frozen_code': True, 'original_error_reproduced': True,
          'input_open_attempts': opened, 'source_file_read_attempts': 0,
          'no_data_read_verified': True, 'holdout_evaluated': False}
Path('result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
"""
    execution = subprocess.run([sys.executable, "-c", f"INPUT_ROOT = {str(input_root)!r}\n" + code],
                               cwd=probe, capture_output=True, text=True, encoding="utf-8", timeout=60)
    (probe / "execution.log").write_text(execution.stdout + execution.stderr, encoding="utf-8")
    if execution.returncode:
        raise RuntimeError(execution.stdout + execution.stderr)
    review = json.loads((probe / "result.json").read_text(encoding="utf-8"))
    review.update(node_id=NODE, source_code_sha256=CODE_SHA, source_data_sha256=DATA_SHA,
                  original_status_sha256=digest(original / "status.json"),
                  original_execution_sha256=digest(original / "execution.log"),
                  original_executed_code_sha256=state["executed_code_sha256"],
                  original_executed_file_sha256=digest(original / "selected_solution.py"),
                  search_elapsed_seconds=search["cumulative_search_elapsed_seconds"],
                  selected_recipe_sha256=digest(original / "artifacts/selected_recipe.json"),
                  scope="Manual forensic review of this exact failed input-directory invocation. This does not authorize repeating any evaluation which accessed data or changing the frozen model.")
    if original != active_final:
        review["original_attempt_archive"] = str(original)
    save(dest / "review.json", review)
    if not args.execute:
        print(json.dumps({"review": str(dest / "review.json"), "passed": True, "final_evaluation_executed": False}))
        return

    unchanged = {path: digest(path) for path in (logs / "journal.json", logs / "search_state.json", data)}
    cfg = SimpleNamespace(workspace_dir=workspace, log_dir=logs, start_cpu_id=0, cpu_number=4,
                          agent=SimpleNamespace(search=SimpleNamespace(parallel_search_num=1)))
    runner = Interpreter(workspace, timeout=900, max_parallel_run=1, isolate_node_workspaces=True, cfg=cfg)
    if original == active_final:
        archive = OUT / "stage-archives/steel" / f"final-evaluation-preinput-{time.time_ns()}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        assert original.resolve().is_relative_to(OUT.resolve()) and archive.resolve().is_relative_to(OUT.resolve())
        original.rename(archive)
    else:
        archive = original
        assert not active_final.exists(), "A replacement final invocation has already started"
    review["original_attempt_archive"] = str(archive)
    save(dest / "review.json", review)
    try:
        result = finalize_selected_candidate(cfg, node, runner, input_path=data, prior_attempt_review=review)
    finally:
        runner.terminate_all_subprocesses()
    assert all(digest(path) == checksum for path, checksum in unchanged.items())
    save(dest / "execution-result.json", {"status": result["status"], "node_id": NODE,
         "search_and_source_unchanged": True, "resource_guard": limiter.describe(),
         "peak_memory_bytes": limiter.peak_memory_bytes(), "final_evaluation": result})
    print(json.dumps({"status": result["status"], "node_id": NODE, "search_and_source_unchanged": True,
                      "peak_memory_bytes": limiter.peak_memory_bytes(), "evidence": str(dest / "execution-result.json")}))
    if result["status"] != "completed":
        raise RuntimeError("Frozen final evaluation did not complete; preserve its new once-only state for review")


if __name__ == "__main__":
    main()

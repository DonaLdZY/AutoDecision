"""Reproduce a failed candidate's network operations without reading task data."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AlgoEvolve"))
from engine.executor import Interpreter
from utils.resource_limits import WindowsJobMemoryLimiter


def main():
    spec = importlib.util.spec_from_file_location("gpu_probe_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("traffic")
    node_id = "6855ad467b394ea18de6a8ec8d8a25ea"
    journal = stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")
    node = next(row for row in journal["nodes"] if row["id"] == node_id)
    tree = ast.parse(node["code"])
    names = {"CausalResidualTCNBlock", "SharedCausalTCNAttention"}
    classes = [value for value in tree.body if isinstance(value, ast.ClassDef) and value.name in names]
    assert len(classes) == 2
    selected = []
    parameters = None
    for value in tree.body:
        if not isinstance(value, ast.Assign) or len(value.targets) != 1 or not isinstance(value.targets[0], ast.Name):
            continue
        name = value.targets[0].id
        if name in {"SEQUENCE_CHANNEL_NAMES", "CALENDAR_FEATURE_NAMES", "SEQUENCE_STEPS"}:
            ast.literal_eval(value.value)
            selected.append(value)
        if name == "RECIPE":
            parameters = next(ast.literal_eval(v) for k, v in zip(value.value.keys, value.value.values)
                              if isinstance(k, ast.Constant) and k.value == "model_parameters")
    assert len(selected) == 3 and parameters is not None
    code = "import json, traceback, gc\nimport torch\nimport torch.nn as nn\nimport torch.nn.functional as F\n"
    code += ast.unparse(ast.Module(body=selected + classes, type_ignores=[])) + "\n"
    code += "MODEL_PARAMETERS = " + repr(parameters) + "\n"
    code += '''torch.set_num_threads(4)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
torch.manual_seed(20251101)
outcomes = []
for batch_size in (4, 64, 768):
    stage = "allocate"
    try:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        model = SharedCausalTCNAttention(159, MODEL_PARAMETERS, [1., 1.]).cuda()
        sequence = torch.randn(batch_size, SEQUENCE_STEPS, len(SEQUENCE_CHANNEL_NAMES), device="cuda")
        sequence[:, :, 2] = 1
        calendar = torch.randn(batch_size, len(CALENDAR_FEATURE_NAMES), device="cuda")
        gantries = torch.arange(batch_size, device="cuda") % 159
        stage = "forward"
        outputs = model(sequence, calendar, gantries)
        torch.cuda.synchronize()
        stage = "backward"
        loss = sum(value.square().mean() for value in outputs)
        loss.backward()
        torch.cuda.synchronize()
        outcomes.append({"batch": batch_size, "passed": bool(torch.isfinite(loss)),
                         "peak_allocated": torch.cuda.max_memory_allocated(),
                         "free_bytes": torch.cuda.mem_get_info()[0]})
        del model, sequence, calendar, gantries, outputs, loss
        gc.collect()
    except Exception as exc:
        outcomes.append({"batch": batch_size, "passed": False, "stage": stage,
                         "error_type": type(exc).__name__, "error": str(exc),
                         "traceback": traceback.format_exc(),
                         "peak_allocated": torch.cuda.max_memory_allocated()})
        break
with open("network_probe.json", "w", encoding="utf-8") as stream:
    json.dump({"torch": torch.__version__, "cuda": torch.version.cuda, "outcomes": outcomes,
               "task_data_accessed": False, "task_score_produced": False}, stream, indent=2)
print(json.dumps(outcomes))
'''
    dest = stages.batch.OUT / "optimization-validation" / f"traffic-network-probe-{time.time_ns()}"
    dest.mkdir(parents=True)
    guard = WindowsJobMemoryLimiter(8 * 1024**3)
    guard.attach(os.getpid())
    os.environ.update(CUDA_VISIBLE_DEVICES="0", CUDA_LAUNCH_BLOCKING="1",
        ALGOEVOLVE_GPU_EXECUTION_SLOTS="2", ALGOEVOLVE_EXECUTION_POOL_PATH=str(stages.batch.OUT / "execution-slots"),
        ALGOEVOLVE_HOST_FREE_RESERVE_GIB="2", ALGOEVOLVE_GPU_FREE_RESERVE_GIB="1",
        ALGOEVOLVE_TORCH_MEMORY_FRACTION=".30", OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4", MKL_NUM_THREADS="4")
    (dest / "probe.py").write_text(code, encoding="utf-8")
    runner = Interpreter(dest, timeout=120, max_parallel_run=1)
    execution = runner.run(code, "network_probe")
    result = {"source_node": node_id, "source_code_sha256": hashlib.sha256(node["code"].encode()).hexdigest(),
              "execution": execution.to_dict(), "probe": stages.read_json(dest / "network_probe.json"),
              "scope": "Exact candidate network classes, synthetic tensors, shared execution admission; no task data or metric"}
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

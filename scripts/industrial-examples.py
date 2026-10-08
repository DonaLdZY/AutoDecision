"""Run the six authorized industrial examples with a bounded service process tree."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import psutil
import yaml


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT.parent / "AutoDecision_Sample"
OUT = ROOT / "runs/industrial-examples-20260907"
GATEWAY = "http://127.0.0.1:18080"
GIB = 1024 ** 3
SERVICES = (
    ("realize", "core/AutoRealize", "autorealize.service_api:app", 18101, "/health"),
    ("search", "core/AlgoEvolve", "service_api:app", 18103, "/health"),
    ("report", "core/AutoReport", "service_api:app", 18104, "/health"),
    ("gateway", "frontend/backend", "app:app", 18080, "/api/health"),
)

COMMON = """Read every supplied business requirement and supplementary document. Preserve all hard constraints and their source references in description.md and automl_context. Treat contradictions explicitly. Do not claim unavailable production capabilities have been validated.
Deliver a reusable training/config-selection entrypoint, saved model/preprocessing or solver configuration, and an independent inference entrypoint accepting NEW data and an output directory. Default retraining must reproduce the selected configuration and seed. No training during prediction. Include dependencies, exact commands, split IDs, validation predictions, model comparisons, baseline, feasibility checks, and machine-readable metrics. Keep final holdout separate from search selection and ensemble weights. Never fabricate metrics or use a different split to improve reported scores.
Resource budget: CPU only, maximum 4 CPU threads per task across its generated fit processes, 8 GiB RAM for the complete task process tree, two search Workers. Use chunked readers for large tables, bounded solver/training iterations, sparse graph features where appropriate. Installed pandas, numpy, scipy, scikit-learn, lightgbm, catboost, joblib, openpyxl, xlrd and ortools are available. No external pretrained downloads. Prefer established libraries for optimization. A search node may spend up to 900 seconds executing. Each task must accumulate 10800 seconds of actual AutoML search, excluding interruption and repair downtime. The runner stops search admission at that cumulative budget; persist and report actual elapsed time. Budget exhaustion or shutdown overhead does not invalidate previously valid candidates or replace their scores with zero.
"""

SHORT_TASK_HINTS = {
    "chemical": "请根据提供的化工生产数据和相关文档，建立预测压滤液 Al(N) 结果值的模型，交付可复用的训练与推理代码、模型和效果报告。",
    "deposition": "请阅读沉积工艺数据及说明文档，建立预测不同沉积策略下局部冷却温度变化的模型，交付可复用的训练与推理代码、模型和效果报告。",
    "delivery": "请根据订单、运力和业务文档，建立订单与每日运力匹配的决策模型。运力日期缺失时暂不假定日期，本次只交付可复用模型和数据缺口报告。",
}


def task_hint(slug: str, protocol: str) -> str:
    return SHORT_TASK_HINTS.get(slug, protocol.strip() + "\n\n" + COMMON.strip())


def task_specs():
    deposition = next(SAMPLES.glob("Data_for_*"))
    return [
        ("steel", "钢厂用电预测", SAMPLES / "steel+industry+energy+consumption", """
Predict Usage_kWh for the next 15-minute period in Steel_industry_data.csv using only information available before that target period. This has 35040 rows and a date column in day-first format. Sort and validate timestamps. Target-period reactive energy, CO2, power factors and Load_Type are unavailable predictors; only lagged observations and calendar fields known in advance are allowed. Do not merely reconstruct same-period consumption from derived energy proxies.
Freeze oldest 60% of timestamps for fit, next 20% for development/search, final 20% for a one-time untouched holdout; purge any training labels crossing a boundary. Use rolling one-step forecasts with previously observed actual history, never future observations. Primary search metric MAE in kWh, also RMSE, daily aggregate errors, persistence and previous-day seasonal baselines. Output timestamp and predicted Usage_kWh; saved inference must predict the next unseen timestamp from supplied history. Refit selected configuration on all available history only after honest holdout evaluation.
"""),
        ("ai4i", "设备故障识别", SAMPLES / "ai4i+2020+predictive+maintenance+dataset", """
Model the probability of Machine failure using Type, Air temperature [K], Process temperature [K], Rotational speed [rpm], Torque [Nm], Tool wear [min]. Exclude UDI and Product ID from model features and exclude TWF,HDF,PWF,OSF,RNF, which disclose failure modes. UDI is output identity only. This is a synthetic dataset of 10000 operating states, not a prospective remaining-life or advance-warning dataset; no failure horizon or production deployment claim is justified.
Freeze a stratified 60/20/20 train/development/holdout split: sklearn train_test_split(test_size=0.2,stratify=y,random_state=20260907), followed by train_test_split on the remaining 80% with test_size=0.25,stratify=remaining_y,random_state=20260907. Save UDI membership. Primary search metric average_precision_score (PR-AUC/AP, maximize); report ROC-AUC, precision, recall, F1 and confusion matrix. Select any decision threshold and calibration with training/development only. Include dummy prevalence, logistic regression and tree boosting baselines. Report class counts and holdout confidence limitations. Output UDI,failure_probability,predicted_failure for new unlabeled states.
"""),
        ("traffic", "逐门架车流预测", SAMPLES / "车流预测", """
Predict traffic for EVERY gantry from the raw passage records and gantry relationship workbook, including low-volume gantries through a documented fallback if needed. The CSV has 1620906 records with 门架id,门架时间,脱敏车牌号,车型. Verify day-first timestamps and the actual seven-day coverage. Build configurable aggregation and directed topology mapping; use 5-minute bins as the example input and forecast total passage counts over the next 30 and 60 minutes for each gantry. Vehicle hashes are not predictor identities.
Freeze the first five complete days for fitting, sixth day for search/development, seventh day for untouched holdout, purging origins whose future targets cross a boundary. Every feature uses observations at or before the forecast origin. Primary search metric MAE of next-30-minute counts over all gantries; report RMSE, 60-minute error, per-gantry error and zero-volume handling. Preserve the source acceptance formula 1-abs(pred-actual)/actual: 30-minute mean accuracy >=90% when half-hour volume >100 and >=95% when >200; 60-minute thresholds >=85% and >=90% on the specified high-volume strata. Define the 60-minute stratum explicitly and report counts. Zero actuals are undefined for this ratio; do not clip negative accuracy or hide empty strata. Preserve holiday targets and explain that one week cannot validate holiday generalization.
Compare persistence, seasonal and learned temporal models, include a topology-aware graph/attention candidate or document any inability to execute the source-required architecture. Do not silently remove that requirement when choosing a CPU model. Output gantry_id,forecast_origin,horizon_minutes,predicted_count. Benchmark local preprocessing/inference and distinguish these measurements from source 50-QPS end-to-end SLA, <=3-second/100000-row ingestion, recovery, high availability, online learning and patent/publication deliverables, which remain separate production obligations.
"""),
        ("chemical", "压滤液铝浓度预测", SAMPLES / "化学工厂", SHORT_TASK_HINTS["chemical"]),
        ("deposition", "沉积工艺冷却曲线预测", deposition, SHORT_TASK_HINTS["deposition"]),
        ("delivery", "城配订单运力匹配", SAMPLES / "城市配送智能", SHORT_TASK_HINTS["delivery"]),
    ]


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def request(path, payload=None, *, base=GATEWAY, method=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    old = yaml.safe_load((ROOT / "runs/live-validation-20260906/settings.yaml").read_text(encoding="utf-8"))
    key = next(item["apiKey"] for item in old["llm"]["modelLibrary"] if item.get("apiKey"))
    model = {"id": "industrial-text", "name": "工业实例文本模型", "model": "gpt-5.6-luna",
             "apiKey": key, "baseUrl": "https://api.renice.cc/v1", "thinkingMode": "default",
             "reasoningEffort": "xhigh", "maxTokens": 32768, "contextWindowTokens": 131072}
    vision = {**model, "id": "industrial-vision", "name": "工业文档视觉模型", "model": "glm-5.3-flash", "reasoningEffort": "default"}
    old["python"] = {"executable": sys.executable}
    old["llm"] = {"modelLibrary": [model, vision], "roleModels": {
        "autoRealize": model["id"], "autoMlCode": model["id"], "autoMlFeedback": model["id"],
        "autoRealizeVision": vision["id"], "embedding": ""}, "vllm": {"enabled": True}}
    old["coreServices"] = {"autoRealizeBaseUrl": "http://127.0.0.1:18101", "algoEvolveBaseUrl": "http://127.0.0.1:18103",
                           "autoReportBaseUrl": "http://127.0.0.1:18104", "requestTimeoutSecs": 30}
    settings_path = OUT / "settings.yaml"
    if not settings_path.exists():
        settings_path.write_text(yaml.safe_dump(old, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.chmod(settings_path, 0o600)
    tasks = []
    for slug, name, source, protocol in task_specs():
        payload = {"task_name": name, "input_root": str(source), "output_root": str(OUT / "tasks"), "output_language": "zh",
            "auto_realize": {"task_hint": task_hint(slug, protocol), "enable_vllm": False,
                "llm_concurrency": 2, "llm_timeout": 600, "llm_file_cognition_mode": "documents_only",
                "prompt_token_budget": 24000, "enable_question_investigator": True,
                "investigation_max_questions": 6 if slug in {"traffic", "chemical", "delivery"} else 3,
                "investigation_max_rounds_per_question": 2, "investigation_max_scripts_per_question": 2,
                "investigation_script_timeout_secs": 180, "artifact_consistency_max_rounds": 2},
            "auto_ml": {"steps": 1000, "time_limit_secs": 10800, "parallel_search_num": 2,
                "initial_drafts": 3, "search_num_drafts": 6, "search_num_improves": 5,
                "use_global_memory": False, "use_coldstart": False, "use_optimization_experience_library": False,
                "exec_timeout_secs": 900, "code_request_timeout_secs": 900, "feedback_request_timeout_secs": 600,
                "code_generation_max_retries": 3, "feedback_generation_max_retries": 3,
                "auto_install_missing_dependencies": False, "fusion_vs_evolution_prob": 0.35,
                "search_fusion_min_remaining_seconds": 600, "search_fusion_min_successful_nodes": 2,
                "search_fusion_min_branches": 2},
            "auto_report": {"enabled": True, "detail_level": "detailed", "comparison_candidate_limit": 6,
                "max_retrieval_rounds": 2, "enable_report_audit": True},
            "resources": {"cpu_cores": 4, "memory_limit_gb": 8, "accelerator_mode": "none", "monitor_interval_seconds": 0.5}}
        tasks.append({"slug": slug, "payload": payload})
        (OUT / (slug + "-protocol.md")).write_text("# " + name + "\n\n" + payload["auto_realize"]["task_hint"], encoding="utf-8")
    save(OUT / "manifest.json", {"model": model["model"], "reasoning_effort": "xhigh", "tasks": tasks,
        "resource_policy": {"simultaneous_tasks": 1, "workers_per_task": 2, "task_memory_gib": 8,
            "services_and_tasks_hard_limit_gib": 10, "minimum_free_gib_to_start": 13, "emergency_free_gib": 4,
            "cpu_only": True, "search_seconds_per_task": 10800}})
    print(json.dumps({"prepared": [item["slug"] for item in tasks], "model": model["model"], "output": str(OUT)}, ensure_ascii=False))


def load_state():
    path = OUT / "batch-state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"tasks": {}, "events": []}


def log_event(state, kind, **data):
    row = {"time": time.time(), "kind": kind, **data}
    state["events"] = (state.get("events", []) + [row])[-200:]
    print(json.dumps(row, ensure_ascii=False), flush=True)
    save(OUT / "batch-state.json", state)


def service_environment():
    env = os.environ.copy()
    env.update({"AUTODECISION_GLOBAL_SETTINGS_PATH": str(OUT / "settings.yaml"),
        "AUTODECISION_PYTHON_EXECUTABLE": sys.executable, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "NUMEXPR_NUM_THREADS": "2",
        "AUTOREALIZE_PROMPT_CACHE_KEY_MODE": "enabled", "ALGOEVOLVE_PROMPT_CACHE_KEY_MODE": "enabled",
        "AUTOREPORT_PROMPT_CACHE_KEY_MODE": "enabled",
        "AUTOREPORT_LLM_REQUEST_TIMEOUT_SECONDS": "600", "AUTOREPORT_LLM_MAX_RETRIES": "3"})
    profile = OUT / "runtime-resource-profile.json"
    if profile.is_file():
        policy = json.loads(profile.read_text(encoding="utf-8"))
        env.update({"CUDA_VISIBLE_DEVICES": "0", "ALGOEVOLVE_GPU_EXECUTION_SLOTS": str(policy["gpu_execution_slots"]),
                    "ALGOEVOLVE_EXECUTION_POOL_PATH": str(OUT / "execution-slots"),
                    "ALGOEVOLVE_HOST_FREE_RESERVE_GIB": str(policy["emergency_free_gib"]),
                    "ALGOEVOLVE_GPU_FREE_RESERVE_GIB": str(policy["gpu_free_reserve_gib"]),
                    "ALGOEVOLVE_TORCH_MEMORY_FRACTION": str(policy["torch_memory_fraction"])})
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[name] = str(policy["cpu_cores"])
    return env


def guard():
    if os.name != "nt":
        raise RuntimeError("This launch profile requires Windows Job Object support.")
    spec = importlib.util.spec_from_file_location("industrial_resource_limits", ROOT / "core/AlgoEvolve/utils/resource_limits.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    profile = OUT / "runtime-resource-profile.json"
    policy = json.loads(profile.read_text(encoding="utf-8")) if profile.is_file() else {}
    limiter = module.WindowsJobMemoryLimiter(int(policy.get("services_and_tasks_hard_limit_gib", 10) * GIB))
    limiter.attach(os.getpid())
    proc = psutil.Process()
    proc.cpu_affinity(proc.cpu_affinity()[:policy.get("cpu_cores", 6)])
    proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    return limiter


def run():
    state = load_state()
    state["pid"] = os.getpid()
    # Bound every service, investigation script and generated model before any launch.
    limiter = guard()
    state["memory_guard"] = limiter.describe()
    save(OUT / "batch-state.json", state)
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    profile_path = OUT / "runtime-resource-profile.json"
    policy = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
    children = []
    for name, directory, app, port, health in SERVICES:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} already in use; refusing to use an unguarded service.")
        stream = (OUT / (name + "-service.log")).open("a", encoding="utf-8")
        child = subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT / directory, env=service_environment(), stdout=stream, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        children.append((name, child))
        deadline = time.monotonic() + 75
        while True:
            if child.poll() is not None:
                raise RuntimeError(f"{name} exited during startup; inspect its service log")
            try:
                request(health, base=f"http://127.0.0.1:{port}")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        state.setdefault("services", {})[name] = {"pid": child.pid, "port": port}
    log_event(state, "services_ready")
    for spec in manifest["tasks"]:
        slug = spec["slug"]
        if slug not in state["tasks"]:
            task = request("/api/tasks", spec["payload"])
            state["tasks"][slug] = {"id": task["id"], "status": "queued"}
            log_event(state, "task_registered", slug=slug, task_id=task["id"])
    while not (OUT / "STOP").exists():
        state["updated_at"] = time.time()
        state["available_memory_gib"] = round(psutil.virtual_memory().available / GIB, 3)
        state["peak_guarded_memory_gib"] = round(limiter.peak_memory_bytes() / GIB, 3)
        dead = [name for name, child in children if child.poll() is not None]
        if dead:
            log_event(state, "service_failed", services=dead)
            raise RuntimeError("Guarded service exited")
        try:
            remote = {item["id"]: item for item in request("/api/tasks")}
            active = []
            for slug, item in state["tasks"].items():
                current = remote.get(item["id"], {})
                if item["status"] == "queued" and current.get("status") == "idle":
                    continue
                previous = (item.get("status"), item.get("phase"))
                item.update({key: current.get(key) for key in ("status", "phase", "last_error", "run_dir", "auto_ml_log_dir", "auto_ml_workspace_dir", "report_dir")})
                if item["status"] == "running":
                    active.append(item)
                if previous != (item.get("status"), item.get("phase")):
                    log_event(state, "task_transition", slug=slug, status=item["status"], phase=item["phase"], error=item.get("last_error"))
            if active and state["available_memory_gib"] < policy.get("emergency_free_gib", 4):
                for item in active:
                    request("/api/tasks/stop", {"task_id": item["id"], "confirm": True})
                state["admission_paused"] = True
                log_event(state, "memory_pressure_stopped_tasks", available_gib=state["available_memory_gib"])
            state["batch_status"] = "running_stage" if active else "stage_review_required"
            save(OUT / "batch-state.json", state)
        except Exception as exc:
            log_event(state, "poll_error", error=str(exc)[:1200])
        time.sleep(10)
    for item in state["tasks"].values():
        if item["status"] == "running":
            request("/api/tasks/stop", {"task_id": item["id"], "confirm": True})
    log_event(state, "stopping_guarded_services")
    for _, child in reversed(children):
        child.terminate()
    for _, child in children:
        child.wait(timeout=30)
    # Keep the job handle live until the guarded process itself exits.


def launch():
    state = load_state()
    pid = state.get("pid")
    if pid and psutil.pid_exists(pid):
        command = " ".join(psutil.Process(pid).cmdline())
        if "industrial-examples.py" in command and "run" in command:
            raise RuntimeError(f"The batch guardian is already running as PID {pid}")
    stream = (OUT / "batch.log").open("a", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run"], cwd=ROOT,
        env=service_environment(), stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    print(json.dumps({"guardian_pid": process.pid, "state": str(OUT / "batch-state.json")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "launch", "run", "status", "sync-delivery", "sync-task"))
    parser.add_argument("--slug", choices=("steel", "ai4i", "traffic", "chemical", "deposition", "delivery"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "launch":
        launch()
    elif args.command == "run":
        run()
    elif args.command in {"sync-delivery", "sync-task"}:
        slug = "delivery" if args.command == "sync-delivery" else args.slug
        if not slug:
            parser.error("sync-task requires --slug")
        state = load_state()
        item = state["tasks"][slug]
        current = next(task for task in request("/api/tasks") if task["id"] == item["id"])
        if current["status"] == "running":
            raise RuntimeError(f"{slug} task is running; do not change its inputs")
        manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
        spec = next(item for item in manifest["tasks"] if item["slug"] == slug)
        task = request("/api/tasks/" + item["id"], spec["payload"], method="PUT")
        print(json.dumps({"task_id": task["id"], "slug": slug, "updated": True}))
    else:
        state = load_state()
        state.pop("events", None)
        print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

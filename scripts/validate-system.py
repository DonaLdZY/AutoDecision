"""Run a real, isolated Studio lifecycle without persisting provider credentials.

The input repository is only a source of files. Every launch creates a new task;
receipts and stage outputs are evidence, not the input repository itself.
"""
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
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / ".codex-work/audit-20261029"
BASE = "http://127.0.0.1:18081"

HOUSE_HINT = """预测 Kaggle House Prices 的 SalePrice，交付可独立加载的房价预测算法包及中文报告。
输入 train.csv 为1460条有标签记录，test.csv 为1459条无标签记录，Id为标识列。读取 description.md 和 data_description.txt，核对实际数据；sample_submission.csv仅是提交格式样例，不是真值。
统一评价合同：主要指标 RMSE(log(pred),log(actual))，越小越好（自然对数，非原价RMSE，也不要替换成log1p指标）。预测必须为正的有限数，保留全部冻结评价人口；禁止因失败、缺失、非有限数而删行缩小分母。
固定随机划分：先对train.csv的行索引用train_test_split(test_size=0.2,random_state=42)冻结留出，再对剩余索引用train_test_split(test_size=0.25,random_state=42)划分训练和开发，约60/20/20。记录三组Id与行数，所有候选完全相同。test.csv不作训练标签，也不作有真值评估。所有缺失填补、编码、缩放、目标变换和特征选择仅在训练拟合；搜索/早停只用开发集；冻结获选方案后由引擎final_evaluate(data,artifact_dir)进行一次留出评估。
先得到能运行的稳健基线，再比较改进。可选择线性、树、boosting、神经网络等，不强制某个模型。资源4 CPU/8GiB/无GPU，单候选360秒，总搜索1800秒。数据很小，不需要大规模参数搜索或外部下载；允许已安装的sklearn/lightgbm/catboost/xgboost/torch。控制线程总数与worker资源。
训练保存预处理和冻结模型；推理入口predict(model_path,data)接受与test.csv列结构一致的pandas DataFrame（允许包含Id），返回Id及正的有限SalePrice预测。推理只加载模型，不重新训练，不读取原训练表，不依赖机器绝对路径。保存依赖、调用示例、可重训命令及输入输出说明。
final_evaluate(data,artifact_dir)从传入artifact_dir加载获选配置、冻结划分和模型，返回非空有限metrics、inference_checks及相对model_path；逐行预测与真值可核对，不能读取其他候选目录或重训。主报告区分开发集与留出结果、外部test提交和业务验收；对没有实测的内容明确说明。"""


def request(path, payload=None, method=None, timeout=60):
    req = urllib.request.Request(
        BASE + path,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_audit(value):
    path = value.resolve()
    if not any(path.is_relative_to(parent.resolve()) for parent in (ROOT / ".codex-work", ROOT / "runs")):
        raise ValueError("Audit output must stay in this repository's .codex-work or runs.")
    return path


def redact(value):
    if isinstance(value, dict):
        return {k: ("[runtime environment]" if "key" in k.lower() and ("api" in k.lower() or "secret" in k.lower()) else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def gateway(audit, *, foreground=False, provider="preferred"):
    audit.mkdir(parents=True, exist_ok=True)
    receipt = audit / "gateway.json"
    if receipt.exists():
        raise RuntimeError("Gateway receipt exists. Inspect the existing service before starting another.")
    settings = yaml.safe_load((ROOT / "frontend/config/global_settings.yaml").read_text(encoding="utf-8-sig"))
    llm = settings["llm"]
    model_id = llm["roleModels"]["autoMlCode"]
    model = dict(next(m for m in llm["modelLibrary"] if m["id"] == model_id))
    key = os.environ.get("AUTODECISION_TEST_LLM_API_KEY") or model.get("apiKey")
    if provider == "fallback":
        key = os.environ.get("AUTODECISION_TEST_LLM_FALLBACK_API_KEY")
        model.update(model=os.environ.get("AUTODECISION_TEST_LLM_FALLBACK_MODEL") or "glm-5.3-flash",
                     baseUrl=os.environ.get("AUTODECISION_TEST_LLM_FALLBACK_BASE_URL") or model["baseUrl"],
                     thinkingMode="enabled")
        # Only the isolated, credential-free settings copy receives this choice.
        llm["modelLibrary"] = [model if item["id"] == model_id else item for item in llm["modelLibrary"]]
    if not key:
        raise RuntimeError("The selected private model has no runtime credential.")
    env = os.environ.copy()
    env.update({
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "AUTODECISION_STATE_DIR": str(audit / "state"),
        "AUTODECISION_GLOBAL_SETTINGS_PATH": str(audit / "settings-without-credentials.yaml"),
        "AUTODECISION_TEST_LLM_OVERRIDE": "true",
        "AUTODECISION_TEST_LLM_BASE_URL": model["baseUrl"],
        "AUTODECISION_TEST_LLM_MODEL": model["model"],
        "AUTODECISION_TEST_LLM_API_KEY": str(key),
        "AUTODECISION_TEST_LLM_MAX_TOKENS": str(model.get("maxTokens") or 32768),
        "AUTODECISION_TEST_LLM_CONTEXT_WINDOW_TOKENS": str(model.get("contextWindowTokens") or 1000000),
        "AUTODECISION_TEST_LLM_THINKING_MODE": "enabled",
    })

    def remove_keys(value):
        if isinstance(value, dict):
            return {k: "" if ("key" in k.lower() and ("api" in k.lower() or "secret" in k.lower())) else remove_keys(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remove_keys(v) for v in value]
        return value

    settings = remove_keys(settings)
    settings["python"]["executable"] = sys.executable
    Path(env["AUTODECISION_GLOBAL_SETTINGS_PATH"]).write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    with (audit / "gateway.stdout.log").open("a", encoding="utf-8") as out, (audit / "gateway.stderr.log").open("a", encoding="utf-8") as err:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "18081"],
                                cwd=ROOT / "frontend/backend", env=env, stdout=out, stderr=err,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    write_json(receipt, {"pid": proc.pid, "base": BASE, "started_at": time.time(), "model": redact(model), "provider": provider,
                         "settings_source_sha256": digest(ROOT / "frontend/config/global_settings.yaml")})
    print(json.dumps({"pid": proc.pid, "base": BASE, "model": model["model"]}))
    if foreground:
        proc.wait()


def restart_gateway(audit, *, foreground=False, provider="preferred"):
    """Restart only this harness's idle Gateway, preserving its state and receipt."""
    import psutil

    receipt = audit / "gateway.json"
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    if saved.get("base") != BASE:
        raise RuntimeError("Receipt does not identify the isolated test Gateway.")
    try:
        process = psutil.Process(int(saved["pid"]))
    except psutil.NoSuchProcess:
        process = None
    if process is not None:
        command = process.cmdline()
        if "uvicorn" not in command or "18081" not in command or "app:app" not in command:
            raise RuntimeError("Recorded PID is no longer the isolated Gateway.")
        if any(task["status"] == "running" for task in request("/api/tasks")):
            raise RuntimeError("A task is running; finish or stop it before restarting the test Gateway.")
    else:
        # Do not mistake a stale receipt for permission to replace a different
        # service now listening at this port.
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 18081)) == 0:
                raise RuntimeError("The receipt process is gone but the test port is occupied.")
    history = audit / "gateway-history"
    history.mkdir(exist_ok=True)
    shutil.copyfile(receipt, history / f"{saved['pid']}-{time.time_ns()}.json")
    if process is not None:
        process.terminate()
        process.wait(timeout=15)
    receipt.unlink()
    gateway(audit, foreground=foreground, provider=provider)


def launch(audit, name, search_seconds):
    run = audit / name
    if run.exists():
        raise RuntimeError(f"Refusing to reuse run output: {run}")
    source = ROOT.parent / "AutoDecision_Sample/kaggle/house-prices-advanced-regression-techniques"
    run.mkdir(parents=True)
    inputs = run / "input"
    inputs.mkdir()
    names = ["train.csv", "test.csv", "sample_submission.csv", "description.md", "data_description.txt"]
    for name_ in names:
        shutil.copyfile(source / name_, inputs / name_)
    write_json(run / "input-manifest.json", {n: {"bytes": (inputs / n).stat().st_size, "sha256": digest(inputs / n)} for n in names})
    # Store fingerprints only, not source diffs which might contain old secrets.
    paths = []
    for parent in ["frontend/backend", "core/AutoRealize/autorealize", "core/AlgoEvolve", "core/AutoReport/autoreport"]:
        paths.extend(p for p in (ROOT / parent).rglob("*.py") if "__pycache__" not in p.parts and "tests" not in p.parts)
    paths.extend((ROOT / "core/AlgoEvolve/config/config.yaml", ROOT / "scripts/validate-system.py"))
    write_json(run / "source-manifest.json", {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in sorted(set(paths))})
    project = request("/api/studio/projects", {"name": f"房价 · {name}", "input_root": str(inputs), "description": "Kaggle 房价原始输入的隔离研发验证"})
    payload = {
        "task_name": f"house-prices-{name}", "input_root": str(inputs), "output_root": str(run / "tasks"), "output_language": "zh",
        "auto_realize": {"task_hint": HOUSE_HINT.replace("总搜索1800秒", f"总搜索{search_seconds}秒"),
                         "llm_file_cognition_mode": "documents_only", "llm_concurrency": 2, "llm_timeout": 240,
                         "investigation_max_questions": 5, "investigation_max_rounds_per_question": 3,
                         "investigation_max_scripts_per_question": 2, "investigation_script_timeout_secs": 60,
                         "prompt_token_budget": 24000, "review_gate_policy": "strict"},
        "auto_ml": {"steps": 128, "time_limit_secs": search_seconds, "parallel_search_num": 2,
                    "initial_drafts": 2, "search_num_drafts": 4, "exec_timeout_secs": 360,
                    "use_global_memory": False, "use_coldstart": False, "use_optimization_experience_library": False,
                    "auto_install_missing_dependencies": False, "code_request_timeout_secs": 300,
                    "feedback_request_timeout_secs": 240, "code_generation_max_retries": 3, "feedback_generation_max_retries": 3,
                    "fast_first_draft_skip_pre_review": False, "web_research_enabled": True,
                    "web_research_query": "Kaggle House Prices log RMSE missing categorical features baseline"},
        "auto_report": {"enabled": True, "audience": "delivery", "detail_level": "detailed", "enable_report_audit": True},
        "resources": {"cpu_cores": 4, "memory_limit_gb": 8, "accelerator_mode": "none"},
    }
    task = request(f"/api/studio/projects/{project['id']}/tasks", payload)
    write_json(run / "receipt.json", {"project_id": project["id"], "task_id": task["id"], "created_at": time.time(),
                                     "base": BASE, "payload": payload})
    response = request("/api/tasks/start", {"task_id": task["id"]})
    print(json.dumps({k: response.get(k) for k in ["id", "status", "phase", "last_error"]}, ensure_ascii=False))


def status(audit, name):
    run = audit / name
    receipt = json.loads((run / "receipt.json").read_text(encoding="utf-8"))
    task = next(t for t in request("/api/tasks") if t["id"] == receipt["task_id"])
    brief = {k: task.get(k) for k in ["id", "status", "phase", "run_dir", "auto_ml_log_dir", "auto_ml_workspace_dir", "report_dir", "last_error"]}
    brief["elapsed_seconds"] = round(time.time() - receipt["created_at"], 1)
    if task.get("auto_ml_log_dir"):
        logs = Path(task["auto_ml_log_dir"])
        if (logs / "run_status.json").is_file():
            s = json.loads((logs / "run_status.json").read_text(encoding="utf-8"))
            brief["search"] = {k: s.get(k) for k in ["status", "elapsed_seconds", "completed_steps", "active_searches", "stop_reason"]}
        if (logs / "journal.json").is_file():
            j = json.loads((logs / "journal.json").read_text(encoding="utf-8"))
            nodes = j.get("nodes", []) if isinstance(j, dict) else j
            brief["candidates"] = [{k: n.get(k) for k in ["id", "stage", "is_buggy", "metric", "search_eligible"]} for n in nodes]
    write_json(run / "status-latest.json", brief)
    print(json.dumps(brief, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["gateway", "restart-gateway", "launch", "status"])
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--name", default="house-r1")
    parser.add_argument("--search-seconds", type=int, default=1800)
    parser.add_argument("--foreground", action="store_true", help="Keep Gateway attached to a managed exec session.")
    parser.add_argument("--provider", choices=["preferred", "fallback"], default="preferred",
                        help="Explicit isolated test-model fallback; never edits the user's private settings.")
    args = parser.parse_args()
    audit = safe_audit(args.audit)
    {"gateway": lambda: gateway(audit, foreground=args.foreground, provider=args.provider), "restart-gateway": lambda: restart_gateway(audit, foreground=args.foreground, provider=args.provider),
     "launch": lambda: launch(audit, args.name, args.search_seconds),
     "status": lambda: status(audit, args.name)}[args.action]()


if __name__ == "__main__":
    main()

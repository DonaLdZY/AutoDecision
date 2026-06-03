from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
import locale
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


APP_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = APP_ROOT / "core"
AUTOREALIZE_DIR = CORE_DIR / "AutoRealize"
ML_MASTER_DIR = CORE_DIR / "ML-Master-Alter"
MLEVOLVE_DIR = CORE_DIR / "MLEvolve-Alter"
DEFAULT_RUNS_DIR = AUTOREALIZE_DIR / "runs"
PROJECT_RUNS_DIR = APP_ROOT / "runs"
STATE_DIR = Path(__file__).resolve().parent / ".state"
TASKS_FILE = STATE_DIR / "tasks.json"
GLOBAL_SETTINGS_FILE = STATE_DIR / "global_settings.json"
DEFAULT_GLOBAL_SETTINGS_FILE = Path(__file__).resolve().parent / "default_global_settings.json"
NETWORK_RETRY_MAX_ATTEMPTS = 5


def now_ts() -> float:
    return time.time()


def safe_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rel_str(path: Path, base: Path) -> str:
    return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")


@dataclass
class RuntimeHandle:
    process: subprocess.Popen[str] | None
    started_at: float
    source: str = "local"
    remote_base_url: str | None = None
    remote_job_id: str | None = None


class AutoRealizeConfigPayload(BaseModel):
    run_data_cognition: bool = True
    run_task_definition: bool = True
    run_data_cleaning: bool = False
    no_knowledge: bool = False
    no_telemetry: bool = False
    no_llm_cache: bool = False
    enable_vllm: bool = True
    offline: bool = False
    auto_generate_predict_split: bool = False
    parallel_cleaning: bool = True
    task_hint: str = ""
    llm_timeout: float = 180.0
    llm_concurrency: int = 4
    llm_enable_thinking: bool | None = None
    llm_reasoning_effort: str | None = None
    llm_structured_disable_thinking: bool = True
    cognition_workers: int = 4
    cleaning_workers: int = 2


class AutoMLConfigPayload(BaseModel):
    engine: str = "ml_master"
    enabled: bool = True
    steps: int = 50
    time_limit_secs: int = 3600
    parallel_search_num: int = 1
    k_fold_validation: int = 1
    check_format: bool = False
    expose_prediction: bool = True
    steerable_reasoning: bool = False
    search_num_drafts: int = 5
    search_num_bugs: int = 1
    search_num_improves: int = 3
    search_max_debug_depth: int = 20
    search_back_debug_depth: int = 3
    metric_improvement_threshold: float = 0.0001
    invalid_metric_upper_bound: int = 100
    max_improve_failure: int = 3
    decay_type: str = "piecewise"
    exploration_constant: float = 1.414
    lower_bound: float = 0.5
    goal: str = ""
    eval: str = ""
    initial_drafts: int = 3
    preprocess_data: bool = True
    copy_data: bool = False
    data_preview: bool = True
    use_diff_mode: bool = True
    check_data_leakage: bool = True
    use_global_memory: bool = True
    memory_similarity_threshold: float = 0.7
    memory_embedding_backend: str = "openai"
    memory_embedding_model: str = ""
    memory_embedding_device: str = "cuda"
    memory_embedding_model_path: str = "BAAI/bge-base-en-v1.5"
    use_coldstart: bool = True
    use_grading_server: bool = False
    exec_timeout_secs: int = 32400


class TaskConfigPayload(BaseModel):
    task_name: str = Field(min_length=1)
    input_root: str = ""
    output_root: str = str(PROJECT_RUNS_DIR)
    auto_realize: AutoRealizeConfigPayload = Field(default_factory=AutoRealizeConfigPayload)
    auto_ml: AutoMLConfigPayload = Field(default_factory=AutoMLConfigPayload)


class TaskModel(BaseModel):
    id: str
    task_name: str
    input_root: str
    output_root: str
    created_at: float
    updated_at: float
    status: str
    phase: str
    config: TaskConfigPayload
    run_dir: str | None = None
    run_started_at: float | None = None
    auto_ml_log_dir: str | None = None
    auto_ml_workspace_dir: str | None = None
    last_error: str | None = None


class StartTaskRequest(BaseModel):
    task_id: str


class StopTaskRequest(BaseModel):
    task_id: str
    confirm: bool = False


class RerunAutoMLRequest(BaseModel):
    task_id: str
    confirm: bool = False


class FullRerunTaskRequest(BaseModel):
    task_id: str
    confirm: bool = False


class ResumeTaskRequest(BaseModel):
    task_id: str


class GlobalSettingsModel(BaseModel):
    python: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    coreServices: dict[str, Any] = Field(default_factory=dict)
    mlevolve: dict[str, Any] = Field(default_factory=dict)


class PickDirectoryRequest(BaseModel):
    initial_path: str = ""
    title: str = "Select Directory"


class PythonEnvModel(BaseModel):
    path: str
    version: str
    source: str
    exists: bool = True


class TaskStore:
    def __init__(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskModel] = {}
        self._handles: dict[str, RuntimeHandle] = {}
        self._load()
        self._reconcile_stale_running_on_boot()

    def _load(self) -> None:
        raw = safe_read_json(TASKS_FILE, {"tasks": []})
        tasks: dict[str, TaskModel] = {}
        for item in raw.get("tasks", []):
            try:
                task = TaskModel.model_validate(item)
                tasks[task.id] = task
            except Exception:
                continue
        self._tasks = tasks

    def _persist(self) -> None:
        write_json(TASKS_FILE, {"tasks": [t.model_dump() for t in self._tasks.values()]})

    def _reconcile_stale_running_on_boot(self) -> None:
        """
        Recover from abnormal shutdown/restart:
        persisted task status may be `running`, but in-memory runtime handles are gone.
        """
        with self._lock:
            changed = False
            for task in self._tasks.values():
                if task.status == "running":
                    task.status = "failed"
                    task.phase = "interrupted"
                    if not task.last_error:
                        task.last_error = "Task interrupted by backend restart or abnormal shutdown."
                    task.updated_at = now_ts()
                    changed = True
            if changed:
                self._persist()

    def reconcile_stale_running(self) -> None:
        """
        Runtime guard for zombie running tasks:
        if a task is `running` but no runtime handle exists, mark it interrupted.
        """
        with self._lock:
            changed = False
            for task_id, task in self._tasks.items():
                if task.status != "running":
                    continue
                if task_id in self._handles:
                    continue
                # Startup is asynchronous. Give freshly-started tasks a grace period
                # before treating missing handles as stale.
                started_at = float(task.run_started_at or 0.0)
                if started_at > 0 and (now_ts() - started_at) < 20:
                    continue
                task.status = "failed"
                task.phase = "interrupted"
                if not task.last_error:
                    task.last_error = "Task runtime handle missing; marked interrupted."
                task.updated_at = now_ts()
                changed = True
            if changed:
                self._persist()

    def list_tasks(self) -> list[TaskModel]:
        self.reconcile_stale_running()
        with self._lock:
            return sorted(self._tasks.values(), key=lambda x: x.created_at)

    def get(self, task_id: str) -> TaskModel:
        self.reconcile_stale_running()
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="task not found")
            return task

    def create(self, payload: TaskConfigPayload) -> TaskModel:
        with self._lock:
            if not payload.output_root.strip():
                payload.output_root = str(PROJECT_RUNS_DIR)
            task_id = uuid.uuid4().hex
            ts = now_ts()
            task = TaskModel(
                id=task_id,
                task_name=payload.task_name,
                input_root=payload.input_root,
                output_root=payload.output_root,
                created_at=ts,
                updated_at=ts,
                status="idle",
                phase="config",
                config=payload,
            )
            self._tasks[task.id] = task
            self._persist()
            return task

    def update(self, task_id: str, payload: TaskConfigPayload) -> TaskModel:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="task not found")
            if task.status == "running":
                raise HTTPException(status_code=400, detail="running task cannot be edited")
            if not payload.output_root.strip():
                payload.output_root = str(PROJECT_RUNS_DIR)
            task.task_name = payload.task_name
            task.input_root = payload.input_root
            task.output_root = payload.output_root
            task.updated_at = now_ts()
            task.config = payload
            self._tasks[task.id] = task
            self._persist()
            return task

    def delete(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if task.status == "running":
                raise HTTPException(status_code=400, detail="running task cannot be deleted")
            del self._tasks[task_id]
            self._persist()

    def set_status(
        self,
        task_id: str,
        *,
        status: str,
        phase: str | None = None,
        run_dir: str | None = None,
        run_started_at: float | None = None,
        auto_ml_log_dir: str | None = None,
        auto_ml_workspace_dir: str | None = None,
        last_error: str | None = None,
    ) -> TaskModel:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="task not found")
            task.status = status
            if phase is not None:
                task.phase = phase
            if run_dir is not None:
                task.run_dir = run_dir
            if run_started_at is not None:
                task.run_started_at = run_started_at
            if auto_ml_log_dir is not None:
                task.auto_ml_log_dir = auto_ml_log_dir
            if auto_ml_workspace_dir is not None:
                task.auto_ml_workspace_dir = auto_ml_workspace_dir
            if last_error is not None:
                task.last_error = last_error
            task.updated_at = now_ts()
            self._tasks[task_id] = task
            self._persist()
            return task

    def reset_runtime(self, task_id: str, *, status: str = "idle", phase: str = "config", last_error: str | None = None) -> TaskModel:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="task not found")
            task.status = status
            task.phase = phase
            task.run_dir = None
            task.run_started_at = None
            task.auto_ml_log_dir = None
            task.auto_ml_workspace_dir = None
            task.last_error = last_error
            task.updated_at = now_ts()
            self._tasks[task_id] = task
            self._persist()
            return task

    def attach_handle(self, task_id: str, handle: RuntimeHandle) -> None:
        with self._lock:
            self._handles[task_id] = handle

    def pop_handle(self, task_id: str) -> RuntimeHandle | None:
        with self._lock:
            return self._handles.pop(task_id, None)

    def get_handle(self, task_id: str) -> RuntimeHandle | None:
        with self._lock:
            return self._handles.get(task_id)


store = TaskStore()
app = FastAPI(title="AutoDecision Local API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_global_settings() -> dict[str, Any]:
    defaults = safe_read_json(DEFAULT_GLOBAL_SETTINGS_FILE, {})
    current = safe_read_json(GLOBAL_SETTINGS_FILE, {})
    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(current, dict):
        current = {}

    merged: dict[str, Any] = {}
    py_merged = {**defaults.get("python", {}), **current.get("python", {})}
    merged["python"] = {
        "executable": str(py_merged.get("executable", "python")),
    }
    merged["resource"] = {**defaults.get("resource", {}), **current.get("resource", {})}
    llm_defaults = defaults.get("llm", {})
    llm_current = current.get("llm", {})
    merged["llm"] = {
        **llm_defaults,
        **llm_current,
        "codeModel": {**llm_defaults.get("codeModel", {}), **llm_current.get("codeModel", {})},
        "feedbackModel": {**llm_defaults.get("feedbackModel", {}), **llm_current.get("feedbackModel", {})},
        "vllm": {**llm_defaults.get("vllm", {}), **llm_current.get("vllm", {})},
    }
    core_defaults = defaults.get("coreServices", {})
    core_current = current.get("coreServices", {})
    merged["coreServices"] = {**core_defaults, **core_current}
    mlevolve_defaults = defaults.get("mlevolve", {})
    mlevolve_current = current.get("mlevolve", {})
    merged["mlevolve"] = {**mlevolve_defaults, **mlevolve_current}
    write_json(GLOBAL_SETTINGS_FILE, merged)
    return merged


def get_global_settings() -> GlobalSettingsModel:
    return GlobalSettingsModel.model_validate(ensure_global_settings())


def save_global_settings(payload: GlobalSettingsModel) -> None:
    raw = payload.model_dump()
    py = raw.get("python", {}) if isinstance(raw, dict) else {}
    raw["python"] = {"executable": str((py or {}).get("executable", "python"))}
    write_json(GLOBAL_SETTINGS_FILE, raw)


def _validate_start(task: TaskModel) -> tuple[Path, Path]:
    if not task.input_root.strip():
        raise HTTPException(status_code=400, detail="请先配置输入文件夹(input_root)再启动任务")

    input_root = Path(task.input_root).expanduser().resolve()
    output_root = Path(task.output_root).expanduser().resolve()
    run_dir = output_root / task.task_name

    if not input_root.exists():
        raise HTTPException(status_code=400, detail=f"input_root does not exist: {input_root}")
    if run_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"任务开始失败：输出目录已存在同名文件夹 `{run_dir}`，请重命名任务。",
        )
    return input_root, output_root


def _task_layout(task: TaskModel, output_root: Path | None = None) -> dict[str, Path]:
    root_base = output_root if output_root is not None else Path(task.output_root).expanduser().resolve()
    task_root = root_base / task.task_name
    ar_dir = task_root / "autorealize"
    automl_root = task_root / "automl"
    automl_logs_root = automl_root / "logs"
    automl_workspaces_root = automl_root / "workspaces"
    return {
        "task_root": task_root,
        "autorealize_dir": ar_dir,
        "automl_root": automl_root,
        "automl_logs_root": automl_logs_root,
        "automl_workspaces_root": automl_workspaces_root,
    }


def _resolve_autorealize_dir(task: TaskModel) -> Path:
    if not task.run_dir:
        raise HTTPException(status_code=400, detail="task has no run_dir; cannot rerun AutoML")
    run_dir = Path(task.run_dir).expanduser().resolve()
    ar_dir = run_dir / "autorealize"
    if not ar_dir.exists() or not ar_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"AutoRealize output not found: {ar_dir}")
    return ar_dir


def _validate_automl_rerun(task: TaskModel) -> tuple[Path, Path, Path, Path, Path]:
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task is running; cannot rerun AutoML")
    if task.status != "failed":
        raise HTTPException(status_code=400, detail="only failed tasks can rerun AutoML")
    if task.phase not in {"automl_failed", "report_failed", "failed"}:
        raise HTTPException(status_code=400, detail=f"current phase `{task.phase}` does not support AutoML-only rerun")
    if not task.config.auto_ml.enabled:
        raise HTTPException(status_code=400, detail="AutoML is disabled in task config")

    autorealize_dir = _resolve_autorealize_dir(task)
    required_files = [
        autorealize_dir / "description.md",
        autorealize_dir / "sample_submission.csv",
    ]
    missing = [str(p) for p in required_files if not p.exists()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"AutoRealize outputs are incomplete; missing files: {missing}",
        )

    layout = _task_layout(task)
    automl_logs_root = layout["automl_logs_root"]
    automl_workspaces_root = layout["automl_workspaces_root"]
    ml_log_dir = automl_logs_root / task.task_name
    ml_ws_dir = automl_workspaces_root / task.task_name
    return autorealize_dir, automl_logs_root, automl_workspaces_root, ml_log_dir, ml_ws_dir


def _candidate_full_rerun_dirs(task: TaskModel) -> list[Path]:
    dirs: list[Path] = []
    try:
        configured_root = Path(task.output_root).expanduser().resolve() / task.task_name
        dirs.append(configured_root)
    except Exception:
        pass
    if task.run_dir:
        try:
            dirs.append(Path(task.run_dir).expanduser().resolve())
        except Exception:
            pass

    seen: set[str] = set()
    unique: list[Path] = []
    for p in dirs:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _is_safe_task_output_dir(task: TaskModel, path: Path) -> bool:
    try:
        output_root = Path(task.output_root).expanduser().resolve()
        candidate = path.expanduser().resolve()
        candidate.relative_to(output_root)
    except Exception:
        return False
    return candidate.name == task.task_name


def _prepare_full_rerun(task: TaskModel) -> None:
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task is running; cannot fully rerun")
    if not task.input_root.strip():
        raise HTTPException(status_code=400, detail="请先配置输入文件夹(input_root)再完全重跑任务")
    if not task.task_name.strip():
        raise HTTPException(status_code=400, detail="请先配置任务名(task_name)再完全重跑任务")


def _rmtree_onerror(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        pass
    try:
        func(path)
    except Exception:
        raise exc_info[1]


def _remove_tree_with_retries(target: Path, retries: int = 5, sleep_secs: float = 0.6) -> None:
    last_error: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            shutil.rmtree(target, onerror=_rmtree_onerror)
            return
        except Exception as e:
            last_error = e
            time.sleep(sleep_secs)
    if last_error is not None:
        raise last_error


def _full_rerun_task_thread(task_id: str) -> None:
    task = store.get(task_id)
    targets = _candidate_full_rerun_dirs(task)
    for target in targets:
        if not target.exists():
            continue
        if not _is_safe_task_output_dir(task, target):
            store.set_status(
                task_id,
                status="failed",
                phase="failed",
                last_error=f"Refused to delete unsafe task directory: {target}",
            )
            return
        try:
            _remove_tree_with_retries(target)
        except Exception as e:
            store.set_status(
                task_id,
                status="failed",
                phase="failed",
                last_error=f"完全重跑前清理旧结果失败: {e}。如果是 Windows 文件占用，请关闭该文件的预览器/PDF阅读器/资源管理器预览后重试。",
            )
            return

    store.reset_runtime(task_id, status="idle", phase="config", last_error=None)
    _start_task_thread(task_id)


def _build_automl_paths(
    task: TaskModel,
    automl_logs_root: Path,
    automl_workspaces_root: Path,
    run_suffix: str | None = None,
) -> tuple[str, Path, Path]:
    exp_name = task.task_name if not run_suffix else f"{task.task_name}__{run_suffix}"
    ml_log_dir = automl_logs_root / exp_name
    ml_ws_dir = automl_workspaces_root / exp_name
    return exp_name, ml_log_dir, ml_ws_dir


def _write_autorealize_config(task: TaskModel, gs: GlobalSettingsModel) -> Path:
    template_path = AUTOREALIZE_DIR / "tmp_default_config_check.json"
    cfg = safe_read_json(template_path, {})
    ar = task.config.auto_realize
    cfg.setdefault("switches", {})
    cfg.setdefault("llm", {})
    cfg.setdefault("vllm", {})
    cfg.setdefault("parallel", {})
    cfg.setdefault("telemetry", {})
    cfg.setdefault("knowledge", {})

    cfg["switches"]["run_data_cognition"] = ar.run_data_cognition
    cfg["switches"]["run_task_definition"] = ar.run_task_definition
    cfg["switches"]["run_data_cleaning"] = ar.run_data_cleaning
    cfg["llm"]["request_timeout_seconds"] = ar.llm_timeout
    cfg["llm"]["max_concurrent_requests"] = ar.llm_concurrency
    cfg["llm"]["enable_thinking"] = ar.llm_enable_thinking
    cfg["llm"]["reasoning_effort"] = ar.llm_reasoning_effort
    cfg["llm"]["structured_disable_thinking"] = ar.llm_structured_disable_thinking
    cfg["parallel"]["cognition_max_workers"] = ar.cognition_workers
    cfg["parallel"]["cleaning_max_workers"] = ar.cleaning_workers
    cfg["parallel"]["enable_parallel_cleaning"] = ar.parallel_cleaning
    cfg["telemetry"]["enabled"] = not ar.no_telemetry
    cfg["knowledge"]["enabled"] = not ar.no_knowledge
    cfg["llm"]["enable_cache"] = not ar.no_llm_cache

    llm = gs.llm
    code_model = llm.get("codeModel", {})
    vllm = llm.get("vllm", {})
    if code_model.get("baseUrl"):
        cfg["llm"]["base_url"] = code_model.get("baseUrl")
    if code_model.get("model"):
        cfg["llm"]["model_name"] = code_model.get("model")
    if code_model.get("apiKey"):
        cfg["llm"]["api_key"] = code_model.get("apiKey")
    if "enableThinking" in code_model:
        cfg["llm"]["enable_thinking"] = code_model.get("enableThinking")
    if code_model.get("reasoningEffort"):
        cfg["llm"]["reasoning_effort"] = code_model.get("reasoningEffort")
    if "structuredDisableThinking" in code_model:
        cfg["llm"]["structured_disable_thinking"] = bool(code_model.get("structuredDisableThinking"))

    cfg["vllm"]["enabled"] = bool(ar.enable_vllm)
    if vllm.get("baseUrl"):
        cfg["vllm"]["base_url"] = vllm.get("baseUrl")
    if vllm.get("model"):
        cfg["vllm"]["model_name"] = vllm.get("model")
    if vllm.get("apiKey"):
        cfg["vllm"]["api_key"] = vllm.get("apiKey")

    out = STATE_DIR / f"{task.id}.autorealize.config.json"
    write_json(out, cfg)
    return out


def _automl_engine(task: TaskModel) -> str:
    raw = str(getattr(task.config.auto_ml, "engine", "ml_master") or "ml_master").strip().lower()
    if raw in {"mlevolve", "ml-evolve", "ml_evolve"}:
        return "mlevolve"
    return "ml_master"


def _build_ml_master_command(
    task: TaskModel,
    gs: GlobalSettingsModel,
    autorealize_dir: Path,
    automl_logs_root: Path,
    automl_workspaces_root: Path,
    exp_name: str | None = None,
) -> list[str]:
    am = task.config.auto_ml
    llm = gs.llm
    code_model = llm.get("codeModel", {})
    feedback_model = llm.get("feedbackModel", {})
    py = gs.python.get("executable", "python")

    exp_name = exp_name or task.task_name

    def _as_cli_str(value: Any, default: str = "") -> str:
        # Use JSON string encoding so OmegaConf.from_cli receives a real string
        # even when value is empty; avoid parsing empty override as None.
        v = default if value is None else str(value)
        return json.dumps(v, ensure_ascii=False)

    cmd = [
        py,
        "main_mcts.py",
        f"data_dir={str(autorealize_dir)}",
        f"dataset_dir={str(autorealize_dir.parent)}",
        "template_file=./instruction/instruction_template.txt",
        f"exp_name={exp_name}",
        "start_cpu_id=0",
        f"cpu_number={int(gs.resource.get('cpuLimit', 4))}",
        f"agent.steps={am.steps}",
        f"agent.time_limit={am.time_limit_secs}",
        f"agent.k_fold_validation={am.k_fold_validation}",
        f"agent.check_format={'true' if am.check_format else 'false'}",
        f"agent.expose_prediction={'true' if am.expose_prediction else 'false'}",
        f"agent.steerable_reasoning={'true' if am.steerable_reasoning else 'false'}",
        f"agent.search.parallel_search_num={am.parallel_search_num}",
        f"agent.search.num_drafts={am.search_num_drafts}",
        f"agent.search.num_bugs={am.search_num_bugs}",
        f"agent.search.num_improves={am.search_num_improves}",
        f"agent.search.max_debug_depth={am.search_max_debug_depth}",
        f"agent.search.back_debug_depth={am.search_back_debug_depth}",
        f"agent.search.metric_improvement_threshold={am.metric_improvement_threshold}",
        f"agent.search.invalid_metric_upper_bound={am.invalid_metric_upper_bound}",
        f"agent.search.max_improve_failure={am.max_improve_failure}",
        f"agent.decay.decay_type={am.decay_type}",
        f"agent.decay.exploration_constant={am.exploration_constant}",
        f"agent.decay.lower_bound={am.lower_bound}",
        f"agent.code.model={_as_cli_str(code_model.get('model', 'deepseek-v4-pro'), 'deepseek-v4-pro')}",
        f"agent.code.temp=0.5",
        f"agent.code.base_url={_as_cli_str(code_model.get('baseUrl', 'https://api.deepseek.com'), 'https://api.deepseek.com')}",
        f"agent.code.api_key={_as_cli_str(code_model.get('apiKey', ''), '')}",
        f"agent.feedback.model={_as_cli_str(feedback_model.get('model', 'deepseek-v4-pro'), 'deepseek-v4-pro')}",
        f"agent.feedback.temp=0.5",
        f"agent.feedback.base_url={_as_cli_str(feedback_model.get('baseUrl', 'https://api.deepseek.com'), 'https://api.deepseek.com')}",
        f"agent.feedback.api_key={_as_cli_str(feedback_model.get('apiKey', ''), '')}",
        f"log_dir={str(automl_logs_root)}",
        f"workspace_dir={str(automl_workspaces_root)}",
    ]
    if am.goal:
        cmd.append(f"goal={_as_cli_str(am.goal)}")
    if am.eval:
        cmd.append(f"eval={_as_cli_str(am.eval)}")
    return cmd


def _build_mlevolve_command(
    task: TaskModel,
    gs: GlobalSettingsModel,
    autorealize_dir: Path,
    automl_logs_root: Path,
    automl_workspaces_root: Path,
    exp_name: str | None = None,
) -> list[str]:
    am = task.config.auto_ml
    llm = gs.llm
    global_mlevolve = gs.mlevolve or {}
    code_model = llm.get("codeModel", {})
    feedback_model = llm.get("feedbackModel", {})
    py = gs.python.get("executable", "python")

    exp_name = exp_name or task.task_name

    def _as_cli_str(value: Any, default: str = "") -> str:
        v = default if value is None else str(value)
        return json.dumps(v, ensure_ascii=False)

    cmd = [
        py,
        "run.py",
        f"data_dir={str(autorealize_dir)}",
        f"dataset_dir={str(autorealize_dir.parent)}",
        f"desc_file={_as_cli_str(str(autorealize_dir / 'description.md'))}",
        f"exp_id={_as_cli_str(task.task_name)}",
        f"exp_name={_as_cli_str(exp_name)}",
        f"log_dir={str(automl_logs_root)}",
        f"workspace_dir={str(automl_workspaces_root)}",
        f"preprocess_data={'true' if am.preprocess_data else 'false'}",
        f"copy_data={'true' if am.copy_data else 'false'}",
        f"start_cpu_id=0",
        f"cpu_number={int(gs.resource.get('cpuLimit', 4))}",
        f"torch_hub_dir={_as_cli_str(global_mlevolve.get('torchHubDir', getattr(am, 'torch_hub_dir', '')))}",
        f"pretrain_model_dir={_as_cli_str(global_mlevolve.get('pretrainModelDir', getattr(am, 'pretrain_model_dir', '')))}",
        f"use_grading_server={'true' if am.use_grading_server else 'false'}",
        f"exec.timeout={am.exec_timeout_secs}",
        "exec.agent_file_name=runfile.py",
        f"agent.steps={am.steps}",
        f"agent.time_limit={am.time_limit_secs}",
        f"agent.initial_drafts={am.initial_drafts}",
        "agent.seed=42",
        f"agent.data_preview={'true' if am.data_preview else 'false'}",
        f"agent.code.model={_as_cli_str(code_model.get('model', 'deepseek-v4-pro'), 'deepseek-v4-pro')}",
        "agent.code.temp=0.5",
        f"agent.code.base_url={_as_cli_str(code_model.get('baseUrl', 'https://api.deepseek.com'), 'https://api.deepseek.com')}",
        f"agent.code.api_key={_as_cli_str(code_model.get('apiKey', ''), '')}",
        "agent.code.enable_thinking=false",
        "agent.code.reasoning_effort=high",
        f"agent.feedback.model={_as_cli_str(feedback_model.get('model', 'deepseek-v4-pro'), 'deepseek-v4-pro')}",
        "agent.feedback.temp=0.5",
        f"agent.feedback.base_url={_as_cli_str(feedback_model.get('baseUrl', 'https://api.deepseek.com'), 'https://api.deepseek.com')}",
        f"agent.feedback.api_key={_as_cli_str(feedback_model.get('apiKey', ''), '')}",
        "agent.feedback.enable_thinking=false",
        "agent.feedback.reasoning_effort=high",
        f"agent.check_data_leakage={'true' if am.check_data_leakage else 'false'}",
        f"agent.use_diff_mode={'true' if am.use_diff_mode else 'false'}",
        "agent.fusion_vs_evolution_prob=0.3",
        "agent.branch_fusion_trigger_prob=1.0",
        "agent.max_fusion_drafts=2",
        f"agent.use_global_memory={'true' if am.use_global_memory else 'false'}",
        f"agent.memory_similarity_threshold={am.memory_similarity_threshold}",
        f"agent.memory_embedding_backend={_as_cli_str(am.memory_embedding_backend, 'openai')}",
        f"agent.memory_embedding_api_key={_as_cli_str(global_mlevolve.get('embeddingApiKey', getattr(am, 'memory_embedding_api_key', '')))}",
        f"agent.memory_embedding_base_url={_as_cli_str(global_mlevolve.get('embeddingBaseUrl', getattr(am, 'memory_embedding_base_url', '')))}",
        f"agent.memory_embedding_model={_as_cli_str(global_mlevolve.get('embeddingModel', getattr(am, 'memory_embedding_model', '')))}",
        f"agent.memory_embedding_device={_as_cli_str(am.memory_embedding_device, 'cuda')}",
        f"agent.memory_embedding_model_path={_as_cli_str(am.memory_embedding_model_path, 'BAAI/bge-base-en-v1.5')}",
        f"agent.search.parallel_search_num={am.parallel_search_num}",
        "agent.search.num_gpus=1",
        f"agent.search.num_drafts={am.search_num_drafts}",
        f"agent.search.num_bugs={am.search_num_bugs}",
        f"agent.search.num_improves={am.search_num_improves}",
        "agent.search.topk_max_improves=10",
        f"agent.search.max_debug_depth={am.search_max_debug_depth}",
        f"agent.search.back_debug_depth={am.search_back_debug_depth}",
        "agent.search.debug_prob=1",
        f"agent.search.metric_improvement_threshold={am.metric_improvement_threshold}",
        f"agent.search.max_improve_failure={am.max_improve_failure}",
        "agent.search.branch_stagnation_threshold=3",
        "agent.search.topk_stagnation_threshold=6",
        "agent.search.stagnation_window=4",
        "agent.search.top_candidates_size=20",
        "agent.search.explore_switch_start=0.5",
        "agent.search.explore_switch_end=0.7",
        "agent.search.min_exploration_weight=0.2",
        "agent.search.topk_early_k=5",
        "agent.search.topk_early_max_per_branch=3",
        "agent.search.topk_late_k=3",
        "agent.search.topk_late_max_per_branch=2",
        "agent.search.force_backprop_late_threshold=0.80",
        "agent.search.force_backprop_late_prob=0.5",
        "agent.search.force_backprop_mid_threshold=0.4",
        "agent.search.force_backprop_mid_modulo=3",
        "agent.search.recent_best_window=4",
        "agent.search.fusion_min_time_hours=6",
        "agent.search.fusion_max_time_hours=10",
        "agent.search.fusion_min_successful_nodes=2",
        "agent.search.fusion_min_branches=2",
        f"agent.decay.exploration_constant={am.exploration_constant}",
        f"agent.decay.lower_bound={am.lower_bound}",
        "agent.decay.alpha=0.01",
        "agent.decay.phase_ratios=[0.3,0.7]",
        f"coldstart.use_coldstart={'true' if am.use_coldstart else 'false'}",
    ]
    if am.goal:
        cmd.append(f"goal={_as_cli_str(am.goal)}")
    if am.eval:
        cmd.append(f"eval={_as_cli_str(am.eval)}")
    return cmd


def _json_post(base_url: str, path: str, payload: dict[str, Any], timeout_secs: int = 15) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, NETWORK_RETRY_MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url=url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=max(1, timeout_secs)) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            retryable = e.code in {429, 500, 502, 503, 504}
            if (not retryable) or attempt >= NETWORK_RETRY_MAX_ATTEMPTS:
                raise RuntimeError(f"HTTP {e.code} {url}: {detail}")
            time.sleep(min(8.0, 1.5 ** (attempt - 1)))
            continue
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            retryable = any(
                x in msg
                for x in [
                    "timed out",
                    "timeout",
                    "connection refused",
                    "connection reset",
                    "connection aborted",
                    "bad gateway",
                    "temporary failure",
                    "503",
                    "502",
                    "504",
                ]
            )
            if (not retryable) or attempt >= NETWORK_RETRY_MAX_ATTEMPTS:
                raise RuntimeError(f"POST {url} failed: {e}")
            time.sleep(min(8.0, 1.5 ** (attempt - 1)))
    raise RuntimeError(f"POST {url} failed: {last_error}")


def _json_get(base_url: str, path: str, timeout_secs: int = 15) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    last_error: Exception | None = None
    for attempt in range(1, NETWORK_RETRY_MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url=url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=max(1, timeout_secs)) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            retryable = e.code in {429, 500, 502, 503, 504}
            if (not retryable) or attempt >= NETWORK_RETRY_MAX_ATTEMPTS:
                raise RuntimeError(f"HTTP {e.code} {url}: {detail}")
            time.sleep(min(8.0, 1.5 ** (attempt - 1)))
            continue
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            retryable = any(
                x in msg
                for x in [
                    "timed out",
                    "timeout",
                    "connection refused",
                    "connection reset",
                    "connection aborted",
                    "bad gateway",
                    "temporary failure",
                    "503",
                    "502",
                    "504",
                ]
            )
            if (not retryable) or attempt >= NETWORK_RETRY_MAX_ATTEMPTS:
                raise RuntimeError(f"GET {url} failed: {e}")
            time.sleep(min(8.0, 1.5 ** (attempt - 1)))
    raise RuntimeError(f"GET {url} failed: {last_error}")


def _service_base_urls(gs: GlobalSettingsModel) -> tuple[str, str, str, int]:
    core = gs.coreServices or {}
    ar_base = str(core.get("autoRealizeBaseUrl") or "http://127.0.0.1:18101").strip().rstrip("/")
    ml_base = str(core.get("autoMlBaseUrl") or "http://127.0.0.1:18102").strip().rstrip("/")
    mlevolve_base = str(core.get("mlevolveBaseUrl") or "http://127.0.0.1:18103").strip().rstrip("/")
    timeout_secs = int(core.get("requestTimeoutSecs") or 10)
    return ar_base, ml_base, mlevolve_base, timeout_secs


def _poll_remote_job(base_url: str, job_id: str, timeout_secs: int = 15) -> dict[str, Any]:
    while True:
        status = _json_get(base_url, f"/jobs/{job_id}", timeout_secs=timeout_secs)
        state = str(status.get("status") or "")
        if state in {"completed", "failed", "stopped"}:
            return status
        time.sleep(1.0)


def _autorealize_outputs_ready(autorealize_dir: Path) -> bool:
    required = [
        autorealize_dir / "description.md",
        autorealize_dir / "sample_submission.csv",
        autorealize_dir / "realize_report" / "data_description.md",
    ]
    return all(p.exists() for p in required)


def _run_autorealize_stage(
    *,
    task_id: str,
    task: TaskModel,
    gs: GlobalSettingsModel,
    input_root: Path,
    run_dir: Path,
    ar_base: str,
    req_timeout: int,
) -> bool:
    ar_cfg_path = _write_autorealize_config(task, gs)
    py = str(gs.python.get("executable", "python"))
    code_model = (gs.llm or {}).get("codeModel", {}) or {}

    store.set_status(
        task_id,
        status="running",
        phase="autorealize",
        run_dir=str(run_dir),
        run_started_at=now_ts(),
        last_error=None,
    )
    ar_start_payload = {
        "task_id": task_id,
        "input_root": str(input_root),
        "output_root": str(run_dir),
        "run_name": "autorealize",
        "task_hint": task.config.auto_realize.task_hint,
        "config_path": str(ar_cfg_path),
        "python_executable": py,
        "working_dir": str(AUTOREALIZE_DIR),
        "offline": bool(task.config.auto_realize.offline),
        "auto_generate_predict_split": bool(task.config.auto_realize.auto_generate_predict_split),
        "env_overrides": {"DEEPSEEK_API_KEY": str(code_model.get("apiKey") or "")},
    }
    try:
        ar_start = _json_post(ar_base, "/jobs/start", ar_start_payload, timeout_secs=req_timeout)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="autorealize_failed", last_error=f"AutoRealize service start failed: {e}")
        return False
    ar_job_id = str(ar_start.get("job_id") or "")
    if not ar_job_id:
        store.set_status(task_id, status="failed", phase="autorealize_failed", last_error="AutoRealize service returned empty job_id")
        return False
    store.attach_handle(
        task_id,
        RuntimeHandle(
            process=None,
            source="autorealize_service",
            remote_base_url=ar_base,
            remote_job_id=ar_job_id,
            started_at=now_ts(),
        ),
    )
    try:
        ar_status = _poll_remote_job(ar_base, ar_job_id, timeout_secs=req_timeout)
    except Exception as e:
        store.pop_handle(task_id)
        store.set_status(task_id, status="failed", phase="autorealize_failed", last_error=f"AutoRealize service poll failed: {e}")
        return False
    store.pop_handle(task_id)
    ar_state = str(ar_status.get("status") or "")
    if ar_state != "completed":
        store.set_status(
            task_id,
            status="failed",
            phase="autorealize_failed",
            last_error=str(ar_status.get("last_error") or f"AutoRealize job status: {ar_state}"),
        )
        return False
    return True


def _start_task_thread(task_id: str) -> None:
    try:
        task = store.get(task_id)
        gs = get_global_settings()
        ar_base, ml_base, mlevolve_base, req_timeout = _service_base_urls(gs)
        input_root, output_root = _validate_start(task)
        run_started_at = now_ts()
        layout = _task_layout(task, output_root)
        run_dir = layout["task_root"]
        autorealize_dir = layout["autorealize_dir"]
        automl_logs_root = layout["automl_logs_root"]
        automl_workspaces_root = layout["automl_workspaces_root"]
        ml_exp_name, ml_log_dir, ml_ws_dir = _build_automl_paths(
            task,
            automl_logs_root=automl_logs_root,
            automl_workspaces_root=automl_workspaces_root,
        )

        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            autorealize_dir.mkdir(parents=True, exist_ok=True)
            automl_logs_root.mkdir(parents=True, exist_ok=True)
            automl_workspaces_root.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            store.set_status(
                task_id,
                status="failed",
                phase="start_failed",
                last_error=f"任务开始失败：输出目录已存在同名文件夹 `{run_dir}`，请重命名任务。",
            )
            return

        env = os.environ.copy()
        llm = gs.llm
        code_model = llm.get("codeModel", {})
        if code_model.get("apiKey"):
            env["DEEPSEEK_API_KEY"] = str(code_model["apiKey"])

        store.set_status(task_id, status="running", phase="autorealize", run_dir=str(run_dir), run_started_at=run_started_at, last_error=None)
        ok_ar = _run_autorealize_stage(
            task_id=task_id,
            task=task,
            gs=gs,
            input_root=input_root,
            run_dir=run_dir,
            ar_base=ar_base,
            req_timeout=req_timeout,
        )
        if not ok_ar:
            return

        if not task.config.auto_ml.enabled:
            store.set_status(task_id, status="completed", phase="completed")
            return

        ok = _run_automl_stage(
            task_id=task_id,
            task=task,
            gs=gs,
            autorealize_dir=autorealize_dir,
            automl_logs_root=automl_logs_root,
            automl_workspaces_root=automl_workspaces_root,
            exp_name=ml_exp_name,
            ml_log_dir=ml_log_dir,
            ml_ws_dir=ml_ws_dir,
            env=env,
            ml_service_base=ml_base,
            mlevolve_service_base=mlevolve_base,
            req_timeout=req_timeout,
        )
        if not ok:
            return

        store.set_status(task_id, status="completed", phase="completed")
    except HTTPException as e:
        # Background thread exceptions were previously swallowed by Python's
        # threading runtime; surface them in task status for the UI.
        detail = getattr(e, "detail", None)
        msg = str(detail) if detail is not None else str(e)
        store.set_status(task_id, status="failed", phase="start_failed", last_error=msg)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="start_failed", last_error=f"任务启动异常: {e}")


def _run_automl_stage(
    *,
    task_id: str,
    task: TaskModel,
    gs: GlobalSettingsModel,
    autorealize_dir: Path,
    automl_logs_root: Path,
    automl_workspaces_root: Path,
    exp_name: str,
    ml_log_dir: Path,
    ml_ws_dir: Path,
    env: dict[str, str],
    ml_service_base: str,
    mlevolve_service_base: str,
    req_timeout: int,
) -> bool:
    engine = _automl_engine(task)
    if engine == "mlevolve":
        ml_cmd = _build_mlevolve_command(
            task,
            gs,
            autorealize_dir=autorealize_dir,
            automl_logs_root=automl_logs_root,
            automl_workspaces_root=automl_workspaces_root,
            exp_name=exp_name,
        )
        service_base = mlevolve_service_base
        working_dir = str(MLEVOLVE_DIR)
        graceful_shutdown_buffer_secs = 600
    else:
        ml_cmd = _build_ml_master_command(
            task,
            gs,
            autorealize_dir=autorealize_dir,
            automl_logs_root=automl_logs_root,
            automl_workspaces_root=automl_workspaces_root,
            exp_name=exp_name,
        )
        service_base = ml_service_base
        working_dir = str(ML_MASTER_DIR)
        graceful_shutdown_buffer_secs = 600

    store.set_status(
        task_id,
        status="running",
        phase="automl",
        auto_ml_log_dir=str(ml_log_dir),
        auto_ml_workspace_dir=str(ml_ws_dir),
        last_error=None,
    )
    try:
        ml_start = _json_post(
            service_base,
            "/jobs/start",
            {
                "task_id": task_id,
                "python_executable": str(gs.python.get("executable", "python")),
                "working_dir": working_dir,
                "env_overrides": {"DEEPSEEK_API_KEY": str((gs.llm.get("codeModel", {}) or {}).get("apiKey") or "")},
                "args": ml_cmd[2:],
                "log_dir": str(automl_logs_root if engine == 'mlevolve' else ml_log_dir),
                "workspace_dir": str(automl_workspaces_root if engine == 'mlevolve' else ml_ws_dir),
                "graceful_shutdown_buffer_secs": graceful_shutdown_buffer_secs,
            },
            timeout_secs=req_timeout,
        )
    except Exception as e:
        store.set_status(task_id, status="failed", phase="automl_failed", last_error=f"AutoML service start failed: {e}")
        return False

    ml_job_id = str(ml_start.get("job_id") or "")
    if not ml_job_id:
        store.set_status(task_id, status="failed", phase="automl_failed", last_error="AutoML service returned empty job_id")
        return False
    store.attach_handle(
        task_id,
        RuntimeHandle(
            process=None,
            source=f"{engine}_service",
            remote_base_url=service_base,
            remote_job_id=ml_job_id,
            started_at=now_ts(),
        ),
    )
    returned_log_dir = str(ml_start.get("log_dir") or "").strip()
    returned_ws_dir = str(ml_start.get("workspace_dir") or "").strip()
    if returned_log_dir or returned_ws_dir:
        store.set_status(
            task_id,
            status="running",
            phase="automl",
            auto_ml_log_dir=returned_log_dir or str(ml_log_dir),
            auto_ml_workspace_dir=returned_ws_dir or str(ml_ws_dir),
            last_error=None,
        )
    try:
        ml_status = _poll_remote_job(service_base, ml_job_id, timeout_secs=req_timeout)
    except Exception as e:
        store.pop_handle(task_id)
        store.set_status(task_id, status="failed", phase="automl_failed", last_error=f"AutoML service poll failed: {e}")
        return False
    store.pop_handle(task_id)
    ml_state = str(ml_status.get("status") or "")
    ml_stdout = str(ml_status.get("stdout_tail") or "")
    ml_stderr = str(ml_status.get("stderr_tail") or "")
    ml_code = ml_status.get("exit_code")
    if ml_code is None and ml_state == "completed":
        ml_code = 0
    try:
        ml_log_dir.mkdir(parents=True, exist_ok=True)
        if ml_stdout:
            (ml_log_dir / "_frontend_stdout.log").write_text(ml_stdout[-200000:], encoding="utf-8", errors="ignore")
        if ml_stderr:
            (ml_log_dir / "_frontend_stderr.log").write_text(ml_stderr[-200000:], encoding="utf-8", errors="ignore")
    except Exception:
        pass
    if ml_state != "completed" or ml_code != 0:
        err_hint = ""
        tail = (ml_stderr or ml_stdout or str(ml_status.get("last_error") or "")).strip()
        if tail:
            err_hint = tail.splitlines()[-1][:180]
        msg = f"AutoML exited with code {ml_code if ml_code is not None else '?'}"
        if err_hint:
            msg = f"{msg}: {err_hint}"
        store.set_status(task_id, status="failed", phase="automl_failed", last_error=msg)
        return False
    return True


def _rerun_automl_thread(task_id: str) -> None:
    task = store.get(task_id)
    gs = get_global_settings()
    _ar_base, ml_base, mlevolve_base, req_timeout = _service_base_urls(gs)
    autorealize_dir, automl_logs_root, automl_workspaces_root, _old_ml_log_dir, _old_ml_ws_dir = _validate_automl_rerun(task)
    run_suffix = time.strftime("%Y%m%d_%H%M%S")
    ml_exp_name, ml_log_dir, ml_ws_dir = _build_automl_paths(
        task,
        automl_logs_root=automl_logs_root,
        automl_workspaces_root=automl_workspaces_root,
        run_suffix=run_suffix,
    )

    try:
        automl_logs_root.mkdir(parents=True, exist_ok=True)
        automl_workspaces_root.mkdir(parents=True, exist_ok=True)
        ml_log_dir.mkdir(parents=True, exist_ok=False)
        ml_ws_dir.mkdir(parents=True, exist_ok=False)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="automl_failed", last_error=f"prepare AutoML rerun failed: {e}")
        return

    env = os.environ.copy()
    llm = gs.llm
    code_model = llm.get("codeModel", {})
    if code_model.get("apiKey"):
        env["DEEPSEEK_API_KEY"] = str(code_model["apiKey"])

    store.set_status(
        task_id,
        status="running",
        phase="automl",
        run_started_at=now_ts(),
        auto_ml_log_dir=str(ml_log_dir),
        auto_ml_workspace_dir=str(ml_ws_dir),
        last_error=None,
    )

    ok = _run_automl_stage(
        task_id=task_id,
        task=task,
        gs=gs,
        autorealize_dir=autorealize_dir,
        automl_logs_root=automl_logs_root,
        automl_workspaces_root=automl_workspaces_root,
        exp_name=ml_exp_name,
        ml_log_dir=ml_log_dir,
        ml_ws_dir=ml_ws_dir,
        env=env,
        ml_service_base=ml_base,
        mlevolve_service_base=mlevolve_base,
        req_timeout=req_timeout,
    )
    if not ok:
        return
    store.set_status(task_id, status="completed", phase="completed")


def _resume_task_thread(task_id: str) -> None:
    task = store.get(task_id)
    if task.status == "running":
        store.set_status(task_id, status="failed", phase="resume_failed", last_error="任务当前仍在运行，无法继续")
        return

    gs = get_global_settings()
    ar_base, ml_base, mlevolve_base, req_timeout = _service_base_urls(gs)

    if not task.input_root.strip() or not task.output_root.strip():
        store.set_status(task_id, status="failed", phase="resume_failed", last_error="缺少输入或输出目录配置，无法继续")
        return

    input_root = Path(task.input_root).expanduser().resolve()
    output_root = Path(task.output_root).expanduser().resolve()
    layout = _task_layout(task, output_root)
    run_dir = layout["task_root"]
    autorealize_dir = layout["autorealize_dir"]
    automl_logs_root = layout["automl_logs_root"]
    automl_workspaces_root = layout["automl_workspaces_root"]

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        autorealize_dir.mkdir(parents=True, exist_ok=True)
        automl_logs_root.mkdir(parents=True, exist_ok=True)
        automl_workspaces_root.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="resume_failed", last_error=f"继续任务准备目录失败: {e}")
        return

    env = os.environ.copy()
    llm = gs.llm
    code_model = llm.get("codeModel", {})
    if code_model.get("apiKey"):
        env["DEEPSEEK_API_KEY"] = str(code_model["apiKey"])

    # Resume strategy:
    # 1) If AutoRealize outputs are not complete, rerun AutoRealize.
    # 2) If AutoML disabled, finish.
    # 3) If AutoML outputs exist, continue AutoML in-place with same exp_name.
    # 4) Else start a new AutoML run.
    if not _autorealize_outputs_ready(autorealize_dir):
        ok_ar = _run_autorealize_stage(
            task_id=task_id,
            task=task,
            gs=gs,
            input_root=input_root,
            run_dir=run_dir,
            ar_base=ar_base,
            req_timeout=req_timeout,
        )
        if not ok_ar:
            return
    else:
        store.set_status(task_id, status="running", phase="autorealize", run_dir=str(run_dir), run_started_at=now_ts(), last_error=None)

    if not task.config.auto_ml.enabled:
        store.set_status(task_id, status="completed", phase="completed", run_dir=str(run_dir), last_error=None)
        return

    resume_log_dir = Path(task.auto_ml_log_dir).expanduser().resolve() if task.auto_ml_log_dir else None
    resume_ws_dir = Path(task.auto_ml_workspace_dir).expanduser().resolve() if task.auto_ml_workspace_dir else None
    can_resume_automl = (
        resume_log_dir is not None
        and resume_ws_dir is not None
        and resume_log_dir.exists()
        and resume_ws_dir.exists()
    )

    if can_resume_automl:
        exp_name = resume_log_dir.name
        ml_log_dir = resume_log_dir
        ml_ws_dir = resume_ws_dir
    else:
        exp_name, ml_log_dir, ml_ws_dir = _build_automl_paths(
            task,
            automl_logs_root=automl_logs_root,
            automl_workspaces_root=automl_workspaces_root,
            run_suffix=time.strftime("%Y%m%d_%H%M%S"),
        )
        try:
            ml_log_dir.mkdir(parents=True, exist_ok=False)
            ml_ws_dir.mkdir(parents=True, exist_ok=False)
        except Exception as e:
            store.set_status(task_id, status="failed", phase="automl_failed", last_error=f"继续任务准备 AutoML 目录失败: {e}")
            return

    store.set_status(
        task_id,
        status="running",
        phase="automl",
        run_dir=str(run_dir),
        run_started_at=now_ts(),
        auto_ml_log_dir=str(ml_log_dir),
        auto_ml_workspace_dir=str(ml_ws_dir),
        last_error=None,
    )
    ok = _run_automl_stage(
        task_id=task_id,
        task=task,
        gs=gs,
        autorealize_dir=autorealize_dir,
        automl_logs_root=automl_logs_root,
        automl_workspaces_root=automl_workspaces_root,
        exp_name=exp_name,
        ml_log_dir=ml_log_dir,
        ml_ws_dir=ml_ws_dir,
        env=env,
        ml_service_base=ml_base,
        mlevolve_service_base=mlevolve_base,
        req_timeout=req_timeout,
    )
    if not ok:
        return
    store.set_status(task_id, status="completed", phase="completed", run_dir=str(run_dir), last_error=None)


def _open_directory(path: Path) -> tuple[bool, str | None]:
    try:
        if not path.exists() or not path.is_dir():
            return False, "path_not_directory"
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            subprocess.Popen(["explorer", str(path)])
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return False, "xdg-open_not_found"
            subprocess.Popen([opener, str(path)])
        return True, None
    except Exception as e:
        return False, str(e)


def _parse_jsonl_local(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    except Exception:
        return []
    return rows


def _render_directory_tree_local(root: Path, max_nodes: int = 6000) -> str:
    if not root.exists() or not root.is_dir():
        return ""
    lines = [root.name or str(root)]
    count = 0

    def walk(node: Path, depth: int) -> None:
        nonlocal count
        if count >= max_nodes:
            return
        try:
            children = sorted(node.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except Exception:
            return
        for c in children:
            if count >= max_nodes:
                break
            suffix = "/" if c.is_dir() else ""
            lines.append(f"{'  ' * depth}- {c.name}{suffix}")
            count += 1
            if c.is_dir():
                walk(c, depth + 1)

    walk(root, 0)
    if count >= max_nodes:
        lines.append("... (truncated)")
    return "\n".join(lines)


def _load_file_cognition_index_local(report_dir: Path, max_items: int = 500) -> dict[str, Any]:
    out: dict[str, Any] = {}
    folder = report_dir / "file_cognition"
    if not folder.exists() or not folder.is_dir():
        return out
    files = sorted(folder.glob("*.json"), key=lambda x: x.name.lower())
    for f in files[:max_items]:
        payload = safe_read_json(f, {})
        if not isinstance(payload, dict):
            continue
        source = str(payload.get("path", "")).replace("\\", "/").strip()
        if not source:
            continue
        md_text = ""
        md_path = f.with_suffix(".md")
        if md_path.exists():
            md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        out[source] = {
            "json": payload,
            "markdown": md_text[:50000],
        }
    return out


def _candidate_task_run_dirs(task: TaskModel) -> list[Path]:
    seen: set[str] = set()
    dirs: list[Path] = []

    def _add(path_like: Path) -> None:
        try:
            p = path_like.expanduser().resolve()
        except Exception:
            return
        k = str(p)
        if k in seen:
            return
        seen.add(k)
        dirs.append(p)

    if task.run_dir:
        _add(Path(task.run_dir))
    if task.output_root and task.task_name:
        _add(Path(task.output_root) / task.task_name)
    if task.task_name:
        _add(PROJECT_RUNS_DIR / task.task_name)
        _add(DEFAULT_RUNS_DIR / task.task_name)

    return [x for x in dirs if x.exists() and x.is_dir()]


def _build_local_autorealize_snapshot(task: TaskModel) -> dict[str, Any]:
    run_dir: Path | None = None
    report_dir: Path | None = None
    autorealize_dir: Path | None = None
    for candidate in _candidate_task_run_dirs(task):
        cand_report = candidate / "autorealize" / "realize_report"
        cand_ar = candidate / "autorealize"
        if not cand_report.exists():
            # old layout fallback
            cand_report = candidate / "realize_report"
            cand_ar = candidate
        if cand_report.exists():
            run_dir = candidate
            report_dir = cand_report
            autorealize_dir = cand_ar
            break
    if run_dir is None or report_dir is None or autorealize_dir is None:
        return {}

    out: dict[str, Any] = {
        "run_dir": str(run_dir),
        "report_dir": str(report_dir),
    }
    out["current_state"] = safe_read_json(report_dir / "current_state.json", {})
    out["frontend_manifest"] = safe_read_json(report_dir / "frontend_manifest.json", {})
    out["run_summary"] = safe_read_json(report_dir / "run_summary.json", {})
    out["data_cognition_report"] = safe_read_json(report_dir / "data_cognition_report.json", {})
    out["events"] = _parse_jsonl_local(report_dir / "event_stream.jsonl", limit=400)
    dir_tree_file = report_dir / "directory_tree.txt"
    out["directory_tree_text"] = dir_tree_file.read_text(encoding="utf-8", errors="ignore") if dir_tree_file.exists() else ""
    out["output_tree_text"] = _render_directory_tree_local(autorealize_dir)
    desc_file = autorealize_dir / "description.md"
    out["description_text"] = desc_file.read_text(encoding="utf-8", errors="ignore") if desc_file.exists() else ""
    data_desc_file = report_dir / "data_description.md"
    out["data_description_text"] = data_desc_file.read_text(encoding="utf-8", errors="ignore") if data_desc_file.exists() else ""
    out["file_cognition_index"] = _load_file_cognition_index_local(report_dir)
    return out


def _pick_local_automl_log_dir(task: TaskModel) -> Path | None:
    if task.auto_ml_log_dir:
        p = Path(task.auto_ml_log_dir).expanduser().resolve()
        if p.exists() and p.is_dir():
            return p
    for run_dir in _candidate_task_run_dirs(task):
        logs_root = run_dir / "automl" / "logs"
        if not logs_root.exists() or not logs_root.is_dir():
            continue
        candidates = [x for x in logs_root.iterdir() if x.is_dir()]
        if not candidates:
            continue
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    return None


def _pick_local_automl_workspace_dir(task: TaskModel, exp_name: str | None) -> Path | None:
    if task.auto_ml_workspace_dir:
        p = Path(task.auto_ml_workspace_dir).expanduser().resolve()
        if p.exists() and p.is_dir():
            return p
    for run_dir in _candidate_task_run_dirs(task):
        ws_root = run_dir / "automl" / "workspaces"
        if not ws_root.exists() or not ws_root.is_dir():
            continue
        if exp_name:
            p = ws_root / exp_name
            if p.exists() and p.is_dir():
                return p
        candidates = [x for x in ws_root.iterdir() if x.is_dir()]
        if not candidates:
            continue
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    return None


def _build_local_automl_snapshot(task: TaskModel) -> dict[str, Any]:
    log_dir = _pick_local_automl_log_dir(task)
    if log_dir is None:
        return {}
    ws_dir = _pick_local_automl_workspace_dir(task, exp_name=log_dir.name)
    journal = safe_read_json(log_dir / "journal.json", {})
    nodes: list[dict[str, Any]] = []
    best_id = None
    if isinstance(journal, dict) and journal:
        j_nodes = journal.get("nodes", [])
        node2parent = journal.get("node2parent", {})
        best_metric = None
        best_maximize = True
        global_maximize: bool | None = None
        for n in j_nodes:
            metric_obj = n.get("metric") or {}
            m = metric_obj.get("maximize") if isinstance(metric_obj, dict) else None
            if isinstance(m, bool):
                global_maximize = m
                break
        for n in j_nodes:
            metric_obj = n.get("metric") or {}
            metric_val = None
            maximize = global_maximize
            if isinstance(metric_obj, dict):
                raw_val = metric_obj.get("value")
                try:
                    metric_val = None if raw_val is None else float(raw_val)
                except Exception:
                    metric_val = None
                m = metric_obj.get("maximize")
                if isinstance(m, bool):
                    maximize = m
            elif isinstance(metric_obj, (int, float)):
                metric_val = float(metric_obj)
            if metric_val is not None:
                if best_metric is None:
                    best_metric = metric_val
                    best_id = n.get("id")
                    best_maximize = True if maximize is None else maximize
                else:
                    if best_maximize:
                        if metric_val > best_metric:
                            best_metric = metric_val
                            best_id = n.get("id")
                    else:
                        if metric_val < best_metric:
                            best_metric = metric_val
                            best_id = n.get("id")
            node_id = n.get("id")
            term_out = n.get("_term_out")
            result = "".join(term_out) if isinstance(term_out, list) else str(term_out or "")
            nodes.append(
                {
                    "id": node_id,
                    "parent_id": node2parent.get(node_id),
                    "stage": n.get("stage"),
                    "plan": n.get("plan"),
                    "code": n.get("code"),
                    "result": result,
                    "insight": n.get("analysis"),
                    "metric": metric_val,
                    "maximize": maximize,
                    "is_buggy": n.get("is_buggy"),
                    "is_valid": n.get("is_valid"),
                    "visits": n.get("visits"),
                    "total_reward": n.get("total_reward"),
                    "uct": n.get("_uct"),
                    "finish_time": n.get("finish_time"),
                    "exec_time": n.get("exec_time"),
                    "branch_id": n.get("branch_id"),
                    "from_topk": n.get("from_topk"),
                }
            )
    engine = _automl_engine(task)
    out: dict[str, Any] = {
        "engine": engine,
        "log_dir": str(log_dir),
        "workspace_dir": str(ws_dir) if ws_dir is not None else "",
        "events": _parse_jsonl_local(log_dir / "event_stream.jsonl", limit=400),
        "nodes": nodes,
        "best_node_id": best_id,
        "ml_log": (log_dir / "ml-master.log").read_text(encoding="utf-8", errors="ignore")[-60000:] if (log_dir / "ml-master.log").exists() else "",
        "frontend_stdout": (log_dir / "_frontend_stdout.log").read_text(encoding="utf-8", errors="ignore")[-60000:] if (log_dir / "_frontend_stdout.log").exists() else "",
        "frontend_stderr": (log_dir / "_frontend_stderr.log").read_text(encoding="utf-8", errors="ignore")[-60000:] if (log_dir / "_frontend_stderr.log").exists() else "",
        "service_stdout": (log_dir / "_service_stdout.log").read_text(encoding="utf-8", errors="ignore")[-60000:] if (log_dir / "_service_stdout.log").exists() else "",
        "service_stderr": (log_dir / "_service_stderr.log").read_text(encoding="utf-8", errors="ignore")[-60000:] if (log_dir / "_service_stderr.log").exists() else "",
    }
    if ws_dir is not None:
        best_solution_code = ws_dir / "best_solution" / "solution.py"
        best_metric_text = ws_dir / "best_solution" / "metric.txt"
        out["best_solution_code"] = best_solution_code.read_text(encoding="utf-8", errors="ignore")[-200000:] if best_solution_code.exists() else ""
        out["best_metric_text"] = best_metric_text.read_text(encoding="utf-8", errors="ignore")[-20000:] if best_metric_text.exists() else ""
    return out


def _read_autorealize_snapshot(task: TaskModel) -> dict[str, Any]:
    if not task.run_dir:
        return {}
    gs = get_global_settings()
    ar_base, _ml_base, _mlevolve_base, req_timeout = _service_base_urls(gs)
    try:
        payload = {"run_dir": str(task.run_dir)}
        return _json_post(ar_base, "/snapshot", payload, timeout_secs=req_timeout)
    except Exception:
        local = _build_local_autorealize_snapshot(task)
        if local:
            return local
        raise


def _read_automl_snapshot(task: TaskModel) -> dict[str, Any]:
    gs = get_global_settings()
    _ar_base, ml_base, mlevolve_base, req_timeout = _service_base_urls(gs)
    engine = _automl_engine(task)
    payload = {
        "log_dir": str(task.auto_ml_log_dir or ""),
        "workspace_dir": str(task.auto_ml_workspace_dir or ""),
        "run_dir": str(task.run_dir or ""),
        "task_name": str(task.task_name or ""),
    }
    try:
        base_url = mlevolve_base if engine == "mlevolve" else ml_base
        return _json_post(base_url, "/snapshot", payload, timeout_secs=req_timeout)
    except Exception:
        local = _build_local_automl_snapshot(task)
        if local:
            return local
        raise


def _pick_dir_tkinter(initial_path: str, title: str) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askdirectory(
        title=title or "Select Directory",
        initialdir=initial_path or None,
        mustexist=True,
    )
    root.destroy()
    if selected:
        return selected
    return None


def _pick_dir_macos_osascript(initial_path: str, title: str) -> str | None:
    prompt = title.replace('"', "'")
    if initial_path and Path(initial_path).exists():
        script = (
            f'set theFolder to choose folder with prompt "{prompt}" default location POSIX file "{initial_path}"\n'
            "POSIX path of theFolder"
        )
    else:
        script = (
            f'set theFolder to choose folder with prompt "{prompt}"\n'
            "POSIX path of theFolder"
        )
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode == 0:
        out = proc.stdout.strip()
        return out or None
    return None


def _run_powershell_hidden(command: str, timeout: int = 900) -> tuple[int, str, str]:
    candidates: list[str] = []
    ps_exe = shutil.which("powershell")
    if ps_exe:
        candidates.append(ps_exe)
    pwsh = shutil.which("pwsh")
    if pwsh:
        candidates.append(pwsh)
    if not candidates:
        candidates.append("powershell")

    last_rc = 1
    last_out = ""
    last_err = "powershell not available"
    for exe in candidates:
        try:
            run_kwargs: dict[str, Any] = {
                "args": [exe, "-NoLogo", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", command],
                "capture_output": True,
                "text": False,
                "timeout": timeout,
            }
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                run_kwargs["startupinfo"] = startupinfo
                run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.run(**run_kwargs)
            stdout_b = proc.stdout or b""
            stderr_b = proc.stderr or b""
            # Robust decode for Windows locale output to avoid UnicodeDecodeError.
            enc_candidates: list[str] = []
            pref = locale.getpreferredencoding(False)
            if pref:
                enc_candidates.append(pref)
            enc_candidates.extend(["utf-8", "utf-8-sig", "gbk", "cp936", "cp1252", "latin1"])

            def _decode(data: bytes) -> str:
                for enc in enc_candidates:
                    try:
                        return data.decode(enc)
                    except Exception:
                        continue
                return data.decode("utf-8", errors="ignore")

            out = _decode(stdout_b)
            err = _decode(stderr_b)
            return proc.returncode, out, err
        except Exception as e:
            last_rc = 1
            last_out = ""
            last_err = str(e)
            continue
    return last_rc, last_out, last_err


def _extract_picker_output(raw: str) -> tuple[str | None, str]:
    lines = [x.strip() for x in (raw or "").splitlines() if x.strip()]
    for line in reversed(lines):
        if line.startswith("__PICKED_PATH__"):
            return line.replace("__PICKED_PATH__", "", 1).strip(), "selected"
        if line == "__CANCELLED__":
            return None, "cancelled"
    # Backward compatibility for older scripts that only print a path.
    if lines:
        return lines[-1], "selected"
    return None, "cancelled"


def _pick_dir_windows_shell(title: str) -> tuple[str | None, str]:
    desc = title.replace("'", " ").replace('"', " ")
    ps = (
        "$ErrorActionPreference='Stop';"
        "$shell=New-Object -ComObject Shell.Application;"
        f"$folder=$shell.BrowseForFolder(0,'{desc}',0x41,0);"
        "if($folder -ne $null -and $folder.Self -and $folder.Self.Path){"
        "  Write-Output ('__PICKED_PATH__' + $folder.Self.Path)"
        "}else{"
        "  Write-Output '__CANCELLED__'"
        "}"
    )
    rc, out, _err = _run_powershell_hidden(ps, timeout=900)
    if rc != 0:
        return None, "unavailable"
    value, status = _extract_picker_output(out)
    if status == "selected" and value:
        return value, "selected"
    return None, "cancelled"


def _pick_dir_windows_modern(initial_path: str, title: str) -> tuple[str | None, str]:
    safe_title = title.replace("'", " ").replace('"', " ")
    init = initial_path.strip()
    if not init or not Path(init).exists():
        init = str(Path.home())
    init_ps = str(Path(init)).replace("'", "''")
    ps = (
        "$ErrorActionPreference='Stop';"
        "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
        "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$d.Description='{safe_title}';"
        f"$d.SelectedPath='{init_ps}';"
        "$d.ShowNewFolderButton=$true;"
        "try{$d.AutoUpgradeEnabled=$true}catch{};"
        "$r=$d.ShowDialog();"
        "if($r -eq [System.Windows.Forms.DialogResult]::OK -and $d.SelectedPath){"
        "  Write-Output ('__PICKED_PATH__' + $d.SelectedPath)"
        "}else{"
        "  Write-Output '__CANCELLED__'"
        "}"
    )
    rc, out, _err = _run_powershell_hidden(ps, timeout=900)
    if rc != 0:
        return None, "unavailable"
    value, status = _extract_picker_output(out)
    if status == "selected" and value:
        return value, "selected"
    return None, "cancelled"


def _pick_dir_linux_zenity(initial_path: str, title: str) -> str | None:
    cmd = ["zenity", "--file-selection", "--directory", "--title", title]
    if initial_path:
        cmd.extend(["--filename", initial_path if initial_path.endswith("/") else f"{initial_path}/"])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if proc.returncode == 0:
        out = proc.stdout.strip()
        return out or None
    return None


def _pick_directory_native(initial_path: str, title: str) -> tuple[str | None, str, str]:
    # 1) OS-specific first (more stable in service/threaded contexts)
    if sys.platform == "darwin":
        try:
            picked = _pick_dir_macos_osascript(initial_path=initial_path, title=title)
            if picked:
                return picked, "osascript", "selected"
        except Exception:
            pass
        return None, "osascript", "cancelled_or_unavailable"
    elif os.name == "nt":
        picked, status = _pick_dir_windows_modern(initial_path=initial_path, title=title)
        if picked:
            return picked, "windows-folderbrowser", "selected"
        if status == "cancelled":
            return None, "windows-folderbrowser", "cancelled"
        # fallback on shell picker only when primary native API unavailable
        picked2, status2 = _pick_dir_windows_shell(title=title)
        if picked2:
            return picked2, "windows-shell-browse", "selected"
        if status2 == "cancelled":
            return None, "windows-shell-browse", "cancelled"
        return None, "none", "cancelled_or_unavailable"
    else:
        try:
            picked = _pick_dir_linux_zenity(initial_path=initial_path, title=title)
            if picked:
                return picked, "zenity", "selected"
        except Exception:
            pass

    # 2) tkinter fallback (non-Windows only)
    if os.name != "nt":
        try:
            picked = _pick_dir_tkinter(initial_path=initial_path, title=title)
            if picked:
                return picked, "tkinter", "selected"
        except Exception:
            pass

    return None, "none", "cancelled_or_unavailable"


def _normalize_selected_directory(path: str) -> str | None:
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return None
    p = Path(raw).expanduser()
    candidates = [p]

    # Some IFileDialog-based folder pickers may return an artificial file token.
    lowered_name = p.name.lower()
    if lowered_name in {"select folder", "[select this folder]"}:
        candidates.append(p.parent)

    for c in candidates:
        try:
            if c.exists() and c.is_dir():
                return str(c.resolve())
        except Exception:
            continue

    # If path does not exist but parent exists, treat as file-token path and use parent.
    try:
        parent = p.parent
        if parent.exists() and parent.is_dir():
            return str(parent.resolve())
    except Exception:
        pass
    return None


def _python_executable_names() -> list[str]:
    if os.name == "nt":
        return ["python.exe", "python3.exe", "python.bat", "python3.bat"]
    return ["python", "python3"]


def _collect_conda_candidates() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    names = _python_executable_names()
    conda_exe = os.environ.get("CONDA_EXE", "").strip()
    if conda_exe:
        try:
            proc = subprocess.run(
                [conda_exe, "info", "--envs", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                payload = json.loads(proc.stdout)
                for env_dir in payload.get("envs", []):
                    p = Path(env_dir)
                    for n in names:
                        exe = p / ("Scripts" if os.name == "nt" else "bin") / n
                        if exe.exists():
                            out.append((exe, "conda"))
        except Exception:
            pass

    home = Path.home()
    conda_roots = [
        home / "anaconda3",
        home / "miniconda3",
        home / "mambaforge",
        home / "miniforge3",
    ]
    if os.name == "nt":
        user = os.environ.get("USERPROFILE", "")
        if user:
            conda_roots.extend(
                [
                    Path(user) / "anaconda3",
                    Path(user) / "miniconda3",
                    Path(user) / "mambaforge",
                    Path(user) / "miniforge3",
                ]
            )
    for root in conda_roots:
        if not root.exists():
            continue
        for n in names:
            base_exe = root / ("python.exe" if os.name == "nt" else "bin/python")
            if base_exe.exists():
                out.append((base_exe, "conda-base"))
                break
        envs_dir = root / "envs"
        if not envs_dir.exists():
            continue
        for env_dir in envs_dir.iterdir():
            if not env_dir.is_dir():
                continue
            for n in names:
                exe = env_dir / ("Scripts" if os.name == "nt" else "bin") / n
                if exe.exists():
                    out.append((exe, "conda"))
                    break
    return out


def _collect_pyenv_candidates() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    pyenv_root = os.environ.get("PYENV_ROOT", "").strip()
    if pyenv_root:
        root = Path(pyenv_root)
    else:
        root = Path.home() / (".pyenv-win" if os.name == "nt" else ".pyenv")
    versions_dir = root / "versions"
    if not versions_dir.exists():
        return out
    for d in versions_dir.iterdir():
        if not d.is_dir():
            continue
        if os.name == "nt":
            exe = d / "python.exe"
            if exe.exists():
                out.append((exe, "pyenv"))
        else:
            exe = d / "bin" / "python"
            if exe.exists():
                out.append((exe, "pyenv"))
    return out


def _collect_venv_candidates() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    roots = [APP_ROOT, Path.cwd()]
    candidates = [".venv", "venv", "env"]
    for r in roots:
        for name in candidates:
            d = r / name
            if not d.exists():
                continue
            exe = d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if exe.exists():
                out.append((exe, "venv"))
    return out


def _collect_path_candidates() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    names = _python_executable_names()
    for cmd in ["python", "python3"]:
        p = shutil.which(cmd)
        if p:
            out.append((Path(p), "path"))

    path_entries = [x for x in os.environ.get("PATH", "").split(os.pathsep) if x]
    for entry in path_entries:
        d = Path(entry)
        if not d.exists() or not d.is_dir():
            continue
        for n in names:
            exe = d / n
            if exe.exists():
                out.append((exe, "path"))
    return out


def _probe_python_version(exe: Path) -> str:
    try:
        proc = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=4)
        text = (proc.stdout or proc.stderr or "").strip()
        return text or "Python (?)"
    except Exception:
        return "Python (?)"


def discover_python_environments(current: str = "") -> list[PythonEnvModel]:
    seen: set[str] = set()
    out: list[PythonEnvModel] = []

    raw: list[tuple[Path, str]] = []
    if sys.executable:
        raw.append((Path(sys.executable), "runtime"))
    raw.extend(_collect_path_candidates())
    raw.extend(_collect_conda_candidates())
    raw.extend(_collect_pyenv_candidates())
    raw.extend(_collect_venv_candidates())

    if current.strip():
        raw.append((Path(current.strip()), "configured"))

    for p, source in raw:
        try:
            rp = p.expanduser().resolve()
        except Exception:
            rp = p
        key = str(rp).lower()
        if key in seen:
            continue
        seen.add(key)
        exists = rp.exists()
        version = _probe_python_version(rp) if exists else "Not Found"
        out.append(
            PythonEnvModel(
                path=str(rp),
                version=version,
                source=source,
                exists=exists,
            )
        )

    source_rank = {
        "configured": 0,
        "runtime": 1,
        "venv": 2,
        "conda": 3,
        "conda-base": 4,
        "pyenv": 5,
        "path": 6,
    }
    out.sort(key=lambda x: (source_rank.get(x.source, 99), x.path.lower()))
    return out


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings/global")
def get_settings() -> dict[str, Any]:
    return get_global_settings().model_dump()


@app.put("/api/settings/global")
def put_settings(payload: GlobalSettingsModel) -> dict[str, str]:
    save_global_settings(payload)
    return {"status": "ok"}


@app.get("/api/tasks")
def list_tasks() -> list[dict[str, Any]]:
    return [x.model_dump() for x in store.list_tasks()]


@app.post("/api/tasks")
def create_task(payload: TaskConfigPayload) -> dict[str, Any]:
    task = store.create(payload)
    return task.model_dump()


@app.put("/api/tasks/{task_id}")
def update_task(task_id: str, payload: TaskConfigPayload) -> dict[str, Any]:
    task = store.update(task_id, payload)
    return task.model_dump()


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str) -> dict[str, str]:
    store.delete(task_id)
    return {"status": "ok"}


@app.post("/api/tasks/start")
def start_task(payload: StartTaskRequest) -> dict[str, Any]:
    task = store.get(payload.task_id)
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task already running")
    thread = threading.Thread(target=_start_task_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id}


@app.post("/api/tasks/rerun-automl")
def rerun_automl(payload: RerunAutoMLRequest) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for rerun automl")
    task = store.get(payload.task_id)
    _validate_automl_rerun(task)
    thread = threading.Thread(target=_rerun_automl_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id, "mode": "automl_only"}


@app.post("/api/tasks/rerun-full")
def rerun_full(payload: FullRerunTaskRequest) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for full rerun")
    task = store.get(payload.task_id)
    _prepare_full_rerun(task)
    thread = threading.Thread(target=_full_rerun_task_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id, "mode": "full_rerun"}


@app.post("/api/tasks/resume")
def resume_task(payload: ResumeTaskRequest) -> dict[str, Any]:
    task = store.get(payload.task_id)
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task already running")
    thread = threading.Thread(target=_resume_task_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id, "mode": "resume"}


@app.post("/api/tasks/stop")
def stop_task(payload: StopTaskRequest) -> dict[str, str]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for stop")
    task = store.get(payload.task_id)
    handle = store.get_handle(payload.task_id)
    if handle is None:
        # Handle stale UI state after restart/abnormal termination.
        if task.status == "running":
            store.set_status(task.id, status="stopped", phase="stopped", last_error="Stopped (recovered from stale running state)")
            return {"status": "stopped"}
        raise HTTPException(status_code=400, detail="task is not running")
    if handle.remote_base_url and handle.remote_job_id:
        try:
            _json_post(handle.remote_base_url, "/jobs/stop", {"job_id": handle.remote_job_id}, timeout_secs=8)
        except Exception:
            pass
    elif handle.process is not None:
        proc = handle.process
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[arg-type]
            else:
                proc.terminate()
        except Exception:
            proc.terminate()
    store.pop_handle(payload.task_id)
    store.set_status(task.id, status="stopped", phase="stopped", last_error="Stopped by user")
    return {"status": "stopped"}


@app.get("/api/tasks/{task_id}/snapshot")
def task_snapshot(task_id: str) -> dict[str, Any]:
    task = store.get(task_id)
    ar: dict[str, Any] = {}
    ml: dict[str, Any] = {}
    snapshot_errors: dict[str, str] = {}
    try:
        ar = _read_autorealize_snapshot(task)
    except Exception as e:
        snapshot_errors["auto_realize"] = str(e)
    try:
        ml = _read_automl_snapshot(task)
    except Exception as e:
        snapshot_errors["auto_ml"] = str(e)
    return {
        "task": task.model_dump(),
        "auto_realize": ar,
        "auto_ml": ml,
        "snapshot_errors": snapshot_errors,
    }


@app.get("/api/fs/list")
def list_dir(path: str) -> dict[str, Any]:
    raw = (path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    if os.name == "nt" and len(raw) == 2 and raw[1] == ":":
        raw = f"{raw}\\"
    try:
        p = Path(raw).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not p.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="path is not directory")
    children = []
    try:
        for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            try:
                is_dir = c.is_dir()
            except Exception:
                continue
            children.append(
                {
                    "name": c.name,
                    "path": str(c),
                    "is_dir": is_dir,
                }
            )
    except PermissionError:
        raise HTTPException(status_code=403, detail="permission denied")
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"list failed: {e}")

    children.sort(key=lambda x: (not bool(x["is_dir"]), str(x["name"]).lower()))
    return {"path": str(p), "children": children}


@app.get("/api/fs/roots")
def list_roots() -> dict[str, Any]:
    roots: list[str] = []
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            if Path(drive).exists():
                roots.append(drive)
    else:
        roots.append("/")
    return {"roots": roots}


@app.post("/api/fs/pick-directory")
def pick_directory(payload: PickDirectoryRequest) -> dict[str, Any]:
    initial_path = payload.initial_path.strip()
    title = payload.title.strip() or "Select Directory"
    picked, method, status = _pick_directory_native(initial_path=initial_path, title=title)
    normalized = _normalize_selected_directory(picked or "")
    if normalized:
        return {"ok": True, "path": normalized, "method": method, "reason": "selected", "raw_path": picked}
    reason = status
    if status == "selected" and picked:
        reason = "invalid_selection"
    return {"ok": False, "path": None, "method": method, "reason": reason, "raw_path": picked}


@app.post("/api/fs/open-directory")
def open_directory(path: str) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    ok, err = _open_directory(p)
    if not ok:
        raise HTTPException(status_code=400, detail=f"open directory failed: {err}")
    return {"ok": True, "path": str(p)}


@app.get("/api/python/environments")
def list_python_environments(current: str = "") -> list[dict[str, Any]]:
    gs = get_global_settings()
    current_exe = current.strip() or str(gs.python.get("executable", "")).strip()
    envs = discover_python_environments(current=current_exe)
    return [x.model_dump() for x in envs]



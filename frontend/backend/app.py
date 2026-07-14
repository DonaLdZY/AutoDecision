from __future__ import annotations

import csv
import hmac
import json
import os
import re
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
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parent
APP_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = APP_ROOT / "core"
AUTOREALIZE_DIR = CORE_DIR / "AutoRealize"
MLEVOLVE_DIR = CORE_DIR / "MLEvolve-Alter"
AUTOREPORT_DIR = CORE_DIR / "AutoReport"
PROJECT_RUNS_DIR = APP_ROOT / "runs"
DEFAULT_RUNS_DIR = PROJECT_RUNS_DIR
LEGACY_AUTOREALIZE_RUNS_DIR = AUTOREALIZE_DIR / "runs"
LEGACY_BACKEND_RUNS_DIR = BACKEND_DIR / "runs"
STATE_DIR = BACKEND_DIR / ".state"
TASKS_FILE = STATE_DIR / "tasks.json"
GLOBAL_SETTINGS_FILE = Path(
    os.environ.get(
        "AUTODECISION_GLOBAL_SETTINGS_PATH",
        str(APP_ROOT / "frontend" / "config" / "global_settings.yaml"),
    )
).expanduser()
if not GLOBAL_SETTINGS_FILE.is_absolute():
    GLOBAL_SETTINGS_FILE = (APP_ROOT / GLOBAL_SETTINGS_FILE).resolve()
LEGACY_GLOBAL_SETTINGS_FILE = STATE_DIR / "global_settings.json"
NETWORK_RETRY_MAX_ATTEMPTS = 5
SERVICE_POLL_RECONNECT_MAX_ATTEMPTS = 5
SERVICE_POLL_RECONNECT_BASE_SLEEP_SECS = 5.0
SERVICE_POLL_RECONNECT_MAX_SLEEP_SECS = 30.0
SERVICE_START_READY_TIMEOUT_SECS = 30.0
SERVICE_START_READY_POLL_SECS = 0.5
_UNSET = object()
DIRECTORY_PICKER_LOCK = threading.Lock()
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)
MLEVOLVE_SECRET_CONFIG_KEYS = {
    "agent.code.api_key",
    "agent.feedback.api_key",
    "agent.memory_embedding_api_key",
}


def resolve_output_root(value: str | None) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return PROJECT_RUNS_DIR.resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = APP_ROOT / path
    return path.resolve()


def normalize_output_root(value: str | None) -> str:
    raw = str(value or "").strip()
    normalized_raw = raw.replace("\\", "/").rstrip("/")
    if not raw or normalized_raw in {"runs", "./runs"}:
        return str(PROJECT_RUNS_DIR.resolve())
    resolved = resolve_output_root(raw)
    legacy_defaults = {
        str(LEGACY_BACKEND_RUNS_DIR.resolve()).lower(),
        str(LEGACY_AUTOREALIZE_RUNS_DIR.resolve()).lower(),
    }
    if str(resolved).lower() in legacy_defaults:
        return str(PROJECT_RUNS_DIR.resolve())
    return str(resolved)


def now_ts() -> float:
    return time.time()


def safe_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def safe_read_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or default
    except Exception:
        return default


def read_mlevolve_pending_nodes(log_dir: Path) -> list[dict[str, Any]]:
    payload = safe_read_json(log_dir / "pending_nodes.json", {})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("nodes")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        node_id = str(row.get("id") or "").strip()
        if not node_id:
            continue
        row = dict(row)
        row["id"] = node_id
        row["pending_execution"] = bool(
            row.get("pending_execution") or row.get("status") in {"generating", "pending_execution", "executing"}
        )
        out.append(row)
    return out


def safe_read_text_tail(path: Path, limit: int = 60000, *, byte_multiplier: int = 4) -> str:
    """Read only the tail of a potentially huge UTF-8-ish text file."""
    if limit <= 0 or not path.exists() or not path.is_file():
        return ""
    try:
        byte_limit = max(limit, limit * max(1, byte_multiplier))
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - byte_limit))
            data = f.read()
        return data.decode("utf-8", errors="ignore")[-limit:]
    except Exception:
        return ""


def safe_read_tail_lines(path: Path, limit: int = 400, *, byte_limit: int = 512_000) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - byte_limit))
            data = f.read()
        return data.decode("utf-8", errors="ignore").splitlines()[-limit:]
    except Exception:
        return []


def _restrict_sensitive_file(path: Path) -> None:
    """Apply owner-only POSIX permissions where the host supports them."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows ACLs are inherited from the containing profile directory.
        # chmod is still attempted, but it is not a substitute for OS account isolation.
        pass


def write_json(path: Path, payload: Any, *, sensitive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if sensitive:
        _restrict_sensitive_file(path)


def write_yaml(path: Path, payload: Any, *, sensitive: bool = False) -> None:
    """Atomically write a human-readable YAML configuration file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# AutoDecision 前端全局设置。此文件由 Gateway 自动生成和维护。\n"
        "# 文件可能包含明文 API Key，已被 Git 忽略，请勿提交或分享。\n"
    )
    text = header + yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    if sensitive:
        _restrict_sensitive_file(temp_path)
    os.replace(temp_path, path)
    if sensitive:
        _restrict_sensitive_file(path)


def write_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _restrict_sensitive_file(path)


def _allowed_origins_from_env() -> list[str]:
    raw = os.environ.get("AUTODECISION_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_ALLOWED_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def normalize_automl_config_payload(config: Any) -> Any:
    """Migrate legacy AutoML engine selections to the only supported engine."""
    try:
        config.auto_ml.engine = "mlevolve"
        config.auto_ml.enabled = True
    except Exception:
        pass
    return config


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
    enable_question_investigator: bool = True
    enable_fewshot: bool = False
    generate_sample_submission: bool = True
    prefer_original_description: bool = True
    direct_automl_from_description: bool = False
    no_knowledge: bool = False
    no_telemetry: bool = False
    no_llm_cache: bool = False
    enable_vllm: bool = True
    offline: bool = False
    auto_generate_predict_split: bool = False
    parallel_cleaning: bool = True
    task_hint: str = ""
    llm_timeout: float = 180.0
    llm_concurrency: int = 100
    llm_enable_thinking: bool | None = None
    llm_reasoning_effort: str | None = None
    llm_structured_disable_thinking: bool = True
    cognition_workers: int = 100
    cleaning_workers: int = 2


class AutoMLConfigPayload(BaseModel):
    engine: str = "mlevolve"
    enabled: bool = True
    steps: int = 50
    time_limit_secs: int = 10800
    parallel_search_num: int = 4
    k_fold_validation: int = 1
    check_format: bool = False
    expose_prediction: bool = True
    generate_submission: bool = True
    steerable_reasoning: bool = False
    search_num_drafts: int = 8
    search_num_bugs: int = 1
    search_num_improves: int = 5
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


class AutoReportConfigPayload(BaseModel):
    enabled: bool = True
    audience: str = "technical"
    language: str = "zh-CN"
    include_raw_logs: bool = True
    include_code_excerpt: bool = True
    use_llm: bool = True


class TaskResourceConfigPayload(BaseModel):
    cpu_cores: int = Field(default=4, ge=1, le=4096)
    memory_limit_gb: float = Field(default=8.0, ge=0, le=1048576)
    accelerator_mode: Literal["all", "selected", "none"] = "all"
    accelerator_device_ids: list[str] = Field(default_factory=list)
    monitor_interval_seconds: float = Field(default=0.5, ge=0.1, le=10.0)


class TaskConfigPayload(BaseModel):
    task_name: str = Field(min_length=1)
    input_root: str = ""
    output_root: str = str(PROJECT_RUNS_DIR)
    auto_realize: AutoRealizeConfigPayload = Field(default_factory=AutoRealizeConfigPayload)
    auto_ml: AutoMLConfigPayload = Field(default_factory=AutoMLConfigPayload)
    auto_report: AutoReportConfigPayload = Field(default_factory=AutoReportConfigPayload)
    resources: TaskResourceConfigPayload = Field(default_factory=TaskResourceConfigPayload)


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
    report_dir: str | None = None
    last_error: str | None = None


class StartTaskRequest(BaseModel):
    task_id: str


class StopTaskRequest(BaseModel):
    task_id: str
    confirm: bool = False


class RerunAutoMLRequest(BaseModel):
    task_id: str
    confirm: bool = False


class StartDirectAutoMLRequest(BaseModel):
    task_id: str
    confirm: bool = False


class RerunAutoRealizeRequest(BaseModel):
    task_id: str
    confirm: bool = False


class RerunAutoReportRequest(BaseModel):
    task_id: str
    confirm: bool = False


class FullRerunTaskRequest(BaseModel):
    task_id: str
    confirm: bool = False


class ResumeTaskRequest(BaseModel):
    task_id: str


class GlobalSettingsModel(BaseModel):
    python: dict[str, Any] = Field(default_factory=dict)
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
        changed = False
        for item in raw.get("tasks", []):
            try:
                task = TaskModel.model_validate(item)
                normalized_output_root = normalize_output_root(task.output_root)
                if task.output_root != normalized_output_root:
                    task.output_root = normalized_output_root
                    task.config.output_root = normalized_output_root
                    task.updated_at = now_ts()
                    changed = True
                if str(task.config.auto_ml.engine or "").lower() != "mlevolve" or not task.config.auto_ml.enabled:
                    normalize_automl_config_payload(task.config)
                    task.updated_at = now_ts()
                    changed = True
                tasks[task.id] = task
            except Exception:
                continue
        self._tasks = tasks
        if changed:
            self._persist()

    def _persist(self) -> None:
        write_json(TASKS_FILE, {"tasks": [t.model_dump() for t in self._tasks.values()]}, sensitive=True)

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
            normalize_automl_config_payload(payload)
            payload.output_root = normalize_output_root(payload.output_root)
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
            normalize_automl_config_payload(payload)
            payload.output_root = normalize_output_root(payload.output_root)
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
        report_dir: str | None = None,
        last_error: Any = _UNSET,
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
            if report_dir is not None:
                task.report_dir = report_dir
            if last_error is not _UNSET:
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
            task.report_dir = None
            task.last_error = last_error
            task.updated_at = now_ts()
            self._tasks[task_id] = task
            self._persist()
            return task

    def clear_output_paths(self, task_id: str, *, auto_ml: bool = False, report: bool = False) -> TaskModel:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="task not found")
            if auto_ml:
                task.auto_ml_log_dir = None
                task.auto_ml_workspace_dir = None
            if report:
                task.report_dir = None
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
_allowed_origins = _allowed_origins_from_env()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials="*" not in _allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_optional_api_token(request: Request, call_next):
    """Protect the Gateway when an operator explicitly configures a bearer token."""
    expected = os.environ.get("AUTODECISION_API_TOKEN", "").strip()
    if (
        expected
        and request.method.upper() != "OPTIONS"
        and request.url.path.startswith("/api")
        and request.url.path != "/api/health"
    ):
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip(), expected):
            return JSONResponse(status_code=401, content={"detail": "invalid or missing API token"})
    return await call_next(request)


def _default_global_settings() -> dict[str, Any]:
    return {
        # Persist the exact interpreter that launched Gateway. When the service
        # runs inside Conda this keeps task subprocesses in the same environment
        # instead of falling back to macOS /usr/bin/python3.
        "python": {
            "executable": os.environ.get("AUTODECISION_PYTHON_EXECUTABLE", sys.executable),
        },
        "llm": {
            "modelLibrary": [
                {
                    "id": "default-code",
                    "name": "默认编码模型",
                    "model": "deepseek-v4-pro",
                    "baseUrl": "https://api.deepseek.com",
                    "apiKey": "",
                    "thinkingMode": "default",
                    "reasoningEffort": "default",
                    "maxTokens": 0,
                },
                {
                    "id": "default-autorealize",
                    "name": "默认 AutoRealize 模型",
                    "model": "deepseek-v4-pro",
                    "baseUrl": "https://api.deepseek.com",
                    "apiKey": "",
                    "thinkingMode": "default",
                    "reasoningEffort": "default",
                    "maxTokens": 0,
                },
                {
                    "id": "default-feedback",
                    "name": "默认反馈模型",
                    "model": "deepseek-v4-pro",
                    "baseUrl": "https://api.deepseek.com",
                    "apiKey": "",
                    "thinkingMode": "default",
                    "reasoningEffort": "default",
                    "maxTokens": 0,
                },
                {
                    "id": "default-vllm",
                    "name": "默认视觉模型",
                    "model": "glm-4.6v-flashx",
                    "baseUrl": "https://open.bigmodel.cn/api/paas/v4/",
                    "apiKey": "",
                    "thinkingMode": "default",
                    "reasoningEffort": "default",
                    "maxTokens": 0,
                },
                {
                    "id": "default-embedding",
                    "name": "默认向量化模型",
                    "model": "text-embedding-v4",
                    "baseUrl": "",
                    "apiKey": "",
                    "thinkingMode": "default",
                    "reasoningEffort": "default",
                    "maxTokens": 0,
                },
            ],
            "roleModels": {
                "autoRealize": "default-autorealize",
                "autoRealizeVision": "default-vllm",
                "autoMlCode": "default-code",
                "autoMlFeedback": "default-feedback",
                "embedding": "default-embedding",
            },
            "vllm": {"enabled": True},
        },
        "coreServices": {
            "autoRealizeBaseUrl": "http://127.0.0.1:18101",
            "mlevolveBaseUrl": "http://127.0.0.1:18103",
            "autoReportBaseUrl": "http://127.0.0.1:18104",
            "requestTimeoutSecs": 10,
        },
        "mlevolve": {
            "torchHubDir": "",
            "pretrainModelDir": "",
            "embeddingBaseUrl": "",
            "embeddingApiKey": "",
            "embeddingModel": "",
        },
    }


def _load_persisted_global_settings() -> tuple[dict[str, Any], bool]:
    current = safe_read_yaml(GLOBAL_SETTINGS_FILE, {})
    if isinstance(current, dict) and current:
        return current, False
    if not GLOBAL_SETTINGS_FILE.exists():
        legacy = safe_read_json(LEGACY_GLOBAL_SETTINGS_FILE, {})
        if isinstance(legacy, dict) and legacy:
            return legacy, True
    return {}, False


def ensure_global_settings() -> dict[str, Any]:
    defaults = _default_global_settings()
    current, migrated_legacy = _load_persisted_global_settings()
    if not isinstance(current, dict):
        current = {}

    merged: dict[str, Any] = {}
    py_merged = {**defaults.get("python", {}), **current.get("python", {})}
    merged["python"] = {
        "executable": str(py_merged.get("executable", "python")),
    }
    llm_defaults = defaults.get("llm", {})
    llm_current = current.get("llm", {})
    core_defaults = defaults.get("coreServices", {})
    core_current = current.get("coreServices", {})
    merged["coreServices"] = {**core_defaults, **core_current}
    merged["coreServices"].pop("autoMlBaseUrl", None)
    merged["coreServices"]["mlevolveBaseUrl"] = str(
        merged["coreServices"].get("mlevolveBaseUrl") or "http://127.0.0.1:18103"
    )
    mlevolve_defaults = defaults.get("mlevolve", {})
    mlevolve_current = current.get("mlevolve", {})
    merged["mlevolve"] = {**mlevolve_defaults, **mlevolve_current}
    model_library, role_models = _normalize_model_library(llm_defaults, llm_current, merged["mlevolve"])
    llm_base = {**llm_defaults, **llm_current}
    llm_base["modelLibrary"] = model_library
    llm_base["roleModels"] = role_models
    auto_ml_code_model = _selected_model(llm_base, "autoMlCode")
    auto_ml_feedback_model = _selected_model(llm_base, "autoMlFeedback", fallback_role="autoMlCode")
    autorealize_model = _selected_model(llm_base, "autoRealize", fallback_role="autoMlCode")
    vllm_model = _selected_model(llm_base, "autoRealizeVision")
    embedding_model = _selected_model(llm_base, "embedding")
    llm_base["codeModel"] = _role_model_to_legacy(auto_ml_code_model, structured_disable=True)
    llm_base["autoRealizeModel"] = _role_model_to_legacy(autorealize_model, structured_disable=True)
    llm_base["feedbackModel"] = _role_model_to_legacy(auto_ml_feedback_model)
    llm_base["vllm"] = {
        "enabled": bool((llm_current.get("vllm") or llm_defaults.get("vllm") or {}).get("enabled", True)),
        "model": str(vllm_model.get("model") or ""),
        "baseUrl": str(vllm_model.get("baseUrl") or ""),
        "apiKey": str(vllm_model.get("apiKey") or ""),
    }
    merged["llm"] = llm_base
    if embedding_model:
        merged["mlevolve"]["embeddingModel"] = str(embedding_model.get("model") or merged["mlevolve"].get("embeddingModel") or "")
        merged["mlevolve"]["embeddingBaseUrl"] = str(embedding_model.get("baseUrl") or merged["mlevolve"].get("embeddingBaseUrl") or "")
        merged["mlevolve"]["embeddingApiKey"] = str(embedding_model.get("apiKey") or merged["mlevolve"].get("embeddingApiKey") or "")
    write_yaml(GLOBAL_SETTINGS_FILE, merged, sensitive=True)
    if migrated_legacy:
        try:
            LEGACY_GLOBAL_SETTINGS_FILE.unlink()
        except OSError:
            pass
    return merged


def _redact_global_settings_for_client(settings: dict[str, Any]) -> dict[str, Any]:
    """Return settings metadata without sending stored provider keys to the browser."""
    redacted = json.loads(json.dumps(settings, ensure_ascii=False, default=str))
    llm = redacted.get("llm") if isinstance(redacted.get("llm"), dict) else {}
    library = llm.get("modelLibrary") if isinstance(llm.get("modelLibrary"), list) else []
    for item in library:
        if not isinstance(item, dict):
            continue
        key = str(item.get("apiKey") or "")
        item["apiKeyConfigured"] = bool(key)
        item["apiKey"] = ""
    for model_key in ("codeModel", "autoRealizeModel", "feedbackModel", "vllm"):
        model = llm.get(model_key)
        if isinstance(model, dict):
            key = str(model.get("apiKey") or "")
            model["apiKeyConfigured"] = bool(key)
            model["apiKey"] = ""
    mlevolve = redacted.get("mlevolve") if isinstance(redacted.get("mlevolve"), dict) else {}
    embedding_key = str(mlevolve.get("embeddingApiKey") or "")
    mlevolve["embeddingApiKeyConfigured"] = bool(embedding_key)
    mlevolve["embeddingApiKey"] = ""
    return redacted


def _deep_merge_settings(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def _non_empty_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _is_generic_python_executable(value: Any) -> bool:
    text = _non_empty_text(value).lower()
    return text in {"", "python", "python3", "py"}


def _thinking_mode_from_legacy(value: Any) -> str:
    if value is True:
        return "enabled"
    if value is False:
        return "disabled"
    text = str(value or "").strip().lower()
    if text in {"enabled", "disabled"}:
        return text
    return "default"


def _legacy_enable_thinking(mode: Any) -> bool | None:
    text = str(mode or "").strip().lower()
    if text == "enabled":
        return True
    if text == "disabled":
        return False
    return None


def _normal_reasoning_effort(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"low", "medium", "high", "xhigh", "max"} else "default"


def _normal_max_tokens(value: Any) -> int | None:
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return None
    return tokens if tokens > 0 else None


def _role_model_to_legacy(model: dict[str, Any], *, structured_disable: bool | None = None) -> dict[str, Any]:
    out = {
        "model": str(model.get("model") or ""),
        "baseUrl": str(model.get("baseUrl") or ""),
        "apiKey": str(model.get("apiKey") or ""),
        "enableThinking": _legacy_enable_thinking(model.get("thinkingMode")),
        "reasoningEffort": None if _normal_reasoning_effort(model.get("reasoningEffort")) == "default" else _normal_reasoning_effort(model.get("reasoningEffort")),
        "maxTokens": _normal_max_tokens(model.get("maxTokens", model.get("max_tokens"))) or 0,
    }
    if structured_disable is not None:
        out["structuredDisableThinking"] = bool(structured_disable)
    return out


def _legacy_model_to_library_item(
    *,
    item_id: str,
    name: str,
    model: dict[str, Any] | None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = {**(defaults or {}), **(model or {})}
    return {
        "id": item_id,
        "name": name,
        "model": str(merged.get("model") or ""),
        "baseUrl": str(merged.get("baseUrl") or ""),
        "apiKey": str(merged.get("apiKey") or ""),
        "thinkingMode": _thinking_mode_from_legacy(merged.get("enableThinking")),
        "reasoningEffort": _normal_reasoning_effort(merged.get("reasoningEffort")),
        "maxTokens": _normal_max_tokens(merged.get("maxTokens", merged.get("max_tokens"))) or 0,
    }


def _normalize_model_library(llm_defaults: dict[str, Any], llm_current: dict[str, Any], mlevolve_merged: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    raw_library: list[Any] = []
    current_library_explicit = isinstance(llm_current.get("modelLibrary"), list)
    current_library = llm_current.get("modelLibrary") if current_library_explicit else []
    has_current_library = any(isinstance(item, dict) for item in current_library)
    if current_library_explicit:
        # Once the user has saved a model library, it is the source of truth.
        # Do not merge defaults back in, otherwise deleted default-* entries
        # reappear the next time global settings are loaded.
        raw_library.extend(current_library)
    elif isinstance(llm_defaults.get("modelLibrary"), list):
        raw_library.extend(llm_defaults.get("modelLibrary") or [])

    by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_library:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()
        if not item_id:
            continue
        by_id[item_id] = {
            "id": item_id,
            "name": str(raw.get("name") or raw.get("remark") or raw.get("model") or item_id),
            "model": str(raw.get("model") or raw.get("modelName") or ""),
            "baseUrl": str(raw.get("baseUrl") or raw.get("base_url") or ""),
            "apiKey": str(raw.get("apiKey") or raw.get("api_key") or ""),
            "thinkingMode": _thinking_mode_from_legacy(raw.get("thinkingMode", raw.get("enableThinking"))),
            "reasoningEffort": _normal_reasoning_effort(raw.get("reasoningEffort")),
            "maxTokens": _normal_max_tokens(raw.get("maxTokens", raw.get("max_tokens"))) or 0,
        }

    legacy_specs = [
        ("default-code", "默认编码模型", llm_current.get("codeModel"), llm_defaults.get("codeModel")),
        ("default-autorealize", "默认 AutoRealize 模型", llm_current.get("autoRealizeModel"), llm_defaults.get("autoRealizeModel") or llm_defaults.get("codeModel")),
        ("default-feedback", "默认反馈模型", llm_current.get("feedbackModel"), llm_defaults.get("feedbackModel")),
        ("default-vllm", "默认视觉模型", llm_current.get("vllm"), llm_defaults.get("vllm")),
    ]
    if not current_library_explicit:
        for item_id, name, current_model, default_model in legacy_specs:
            if item_id not in by_id:
                by_id[item_id] = _legacy_model_to_library_item(
                    item_id=item_id,
                    name=name,
                    model=current_model if isinstance(current_model, dict) else {},
                    defaults=default_model if isinstance(default_model, dict) else {},
                )
            elif not has_current_library and isinstance(current_model, dict):
                # Old settings files do not have modelLibrary yet. In that case the
                # default library entry exists, but user-edited legacy fields
                # (especially API keys/Base URLs) must win during one-time migration.
                by_id[item_id] = _legacy_model_to_library_item(
                    item_id=item_id,
                    name=name,
                    model=current_model,
                    defaults=default_model if isinstance(default_model, dict) else {},
                )

    embedding_defaults = {
        "model": str(mlevolve_merged.get("embeddingModel") or ""),
        "baseUrl": str(mlevolve_merged.get("embeddingBaseUrl") or ""),
        "apiKey": str(mlevolve_merged.get("embeddingApiKey") or ""),
    }
    if (not current_library_explicit and "default-embedding" not in by_id) or (
        not current_library_explicit
        and not has_current_library
        and any(str(embedding_defaults.get(key) or "").strip() for key in ("model", "baseUrl", "apiKey"))
    ):
        by_id["default-embedding"] = _legacy_model_to_library_item(
            item_id="default-embedding",
            name="默认向量化模型",
            model=embedding_defaults,
            defaults={},
        )

    role_defaults = llm_defaults.get("roleModels") if isinstance(llm_defaults.get("roleModels"), dict) else {}
    role_current = llm_current.get("roleModels") if isinstance(llm_current.get("roleModels"), dict) else {}
    first_model_id = next(iter(by_id.keys()), "")
    roles = {
        "autoRealize": str(role_current.get("autoRealize") or (role_defaults.get("autoRealize") if not current_library_explicit else "") or "default-autorealize"),
        "autoRealizeVision": str(role_current.get("autoRealizeVision") or (role_defaults.get("autoRealizeVision") if not current_library_explicit else "") or "default-vllm"),
        "autoMlCode": str(role_current.get("autoMlCode") or (role_defaults.get("autoMlCode") if not current_library_explicit else "") or "default-code"),
        "autoMlFeedback": str(role_current.get("autoMlFeedback") or (role_defaults.get("autoMlFeedback") if not current_library_explicit else "") or "default-feedback"),
        "embedding": str(role_current.get("embedding") or (role_defaults.get("embedding") if not current_library_explicit else "") or "default-embedding"),
    }
    for role, item_id in list(roles.items()):
        if item_id not in by_id:
            fallback = {
                "autoRealize": "default-autorealize",
                "autoRealizeVision": "default-vllm",
                "autoMlCode": "default-code",
                "autoMlFeedback": "default-feedback",
                "embedding": "default-embedding",
            }[role]
            roles[role] = fallback if fallback in by_id else first_model_id

    return list(by_id.values()), roles


def _selected_model(llm: dict[str, Any], role: str, fallback_role: str | None = None) -> dict[str, Any]:
    library = llm.get("modelLibrary") if isinstance(llm.get("modelLibrary"), list) else []
    roles = llm.get("roleModels") if isinstance(llm.get("roleModels"), dict) else {}
    item_id = str(roles.get(role) or (roles.get(fallback_role) if fallback_role else "") or "").strip()
    for item in library:
        if isinstance(item, dict) and str(item.get("id") or "") == item_id:
            return item
    legacy_key = {
        "autoRealize": "autoRealizeModel",
        "autoRealizeVision": "vllm",
        "autoMlCode": "codeModel",
        "autoMlFeedback": "feedbackModel",
        "embedding": "",
    }.get(role, "")
    if legacy_key:
        return llm.get(legacy_key, {}) if isinstance(llm.get(legacy_key), dict) else {}
    return {}


def _model_cli_value(model: dict[str, Any], key: str, default: str = "") -> str:
    value = model.get(key)
    if value not in (None, ""):
        return str(value)
    return "" if default is None else str(default)


def _model_thinking_cli(model: dict[str, Any]) -> str:
    mode = str(model.get("thinkingMode") or "").strip().lower()
    if not mode and "enableThinking" in model:
        mode = _thinking_mode_from_legacy(model.get("enableThinking"))
    if mode == "enabled":
        return "true"
    if mode == "disabled":
        return "false"
    return "null"


def _model_reasoning_cli(model: dict[str, Any]) -> str:
    effort = _normal_reasoning_effort(model.get("reasoningEffort"))
    return "null" if effort == "default" else effort


def _model_max_tokens_cli(model: dict[str, Any]) -> str | None:
    tokens = _normal_max_tokens(model.get("maxTokens", model.get("max_tokens")))
    return str(tokens) if tokens is not None else None


def _preserve_sensitive_settings(merged: dict[str, Any], existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing_python = (existing.get("python") or {}) if isinstance(existing.get("python"), dict) else {}
    incoming_python = (incoming.get("python") or {}) if isinstance(incoming.get("python"), dict) else {}
    existing_exe = _non_empty_text(existing_python.get("executable"))
    incoming_exe = _non_empty_text(incoming_python.get("executable"))
    if existing_exe and not _is_generic_python_executable(existing_exe) and _is_generic_python_executable(incoming_exe):
        merged.setdefault("python", {})["executable"] = existing_exe

    existing_llm = (existing.get("llm") or {}) if isinstance(existing.get("llm"), dict) else {}
    incoming_llm = (incoming.get("llm") or {}) if isinstance(incoming.get("llm"), dict) else {}
    existing_library = {
        str(item.get("id") or ""): item
        for item in (existing_llm.get("modelLibrary") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    merged_library = merged.get("llm", {}).get("modelLibrary") if isinstance(merged.get("llm"), dict) else None
    if isinstance(merged_library, list):
        for item in merged_library:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            old_key = _non_empty_text((existing_library.get(item_id) or {}).get("apiKey"))
            new_key = _non_empty_text(item.get("apiKey"))
            if old_key and not new_key:
                item["apiKey"] = old_key

    for model_key in ("codeModel", "autoRealizeModel", "feedbackModel", "vllm"):
        old_model = existing_llm.get(model_key) if isinstance(existing_llm.get(model_key), dict) else {}
        new_model = incoming_llm.get(model_key) if isinstance(incoming_llm.get(model_key), dict) else {}
        old_key = _non_empty_text(old_model.get("apiKey"))
        new_key = _non_empty_text(new_model.get("apiKey"))
        if old_key and not new_key:
            merged.setdefault("llm", {}).setdefault(model_key, {})["apiKey"] = old_key

    existing_mlevolve = existing.get("mlevolve") if isinstance(existing.get("mlevolve"), dict) else {}
    incoming_mlevolve = incoming.get("mlevolve") if isinstance(incoming.get("mlevolve"), dict) else {}
    old_embedding_key = _non_empty_text(existing_mlevolve.get("embeddingApiKey"))
    new_embedding_key = _non_empty_text(incoming_mlevolve.get("embeddingApiKey"))
    if old_embedding_key and not new_embedding_key:
        merged.setdefault("mlevolve", {})["embeddingApiKey"] = old_embedding_key


def get_global_settings() -> GlobalSettingsModel:
    return GlobalSettingsModel.model_validate(ensure_global_settings())


def save_global_settings(payload: GlobalSettingsModel) -> None:
    existing = ensure_global_settings()
    raw = payload.model_dump()
    raw = _deep_merge_settings(existing, raw)
    _preserve_sensitive_settings(raw, existing, payload.model_dump())
    raw.pop("resource", None)
    py = raw.get("python", {}) if isinstance(raw, dict) else {}
    raw["python"] = {"executable": str((py or {}).get("executable", "python"))}
    write_yaml(GLOBAL_SETTINGS_FILE, raw, sensitive=True)


# Importing the Gateway application is its startup path under uvicorn. Ensure
# the ignored local settings file exists before the browser requests it.
ensure_global_settings()


def _validate_start(task: TaskModel) -> tuple[Path, Path]:
    if not task.input_root.strip():
        raise HTTPException(status_code=400, detail="请先配置输入文件夹(input_root)再启动任务")

    input_root = Path(task.input_root).expanduser().resolve()
    output_root = resolve_output_root(task.output_root)
    run_dir = output_root / task.task_name

    if not input_root.exists():
        raise HTTPException(status_code=400, detail=f"input_root does not exist: {input_root}")
    if run_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"任务开始失败：输出目录已存在同名文件夹 `{run_dir}`，请重命名任务。",
        )
    return input_root, output_root


def _find_original_description(input_root: Path) -> Path | None:
    candidates = [p for p in input_root.rglob("*") if p.is_file() and p.name.lower() == "description.md"]
    if not candidates:
        return None

    def _rank(path: Path) -> tuple[int, int, str]:
        try:
            rel = path.relative_to(input_root)
            depth = len(rel.parts)
        except ValueError:
            depth = len(path.parts)
        # Prefer a root-level description.md, then shallower files.
        return (0 if path.parent.resolve() == input_root.resolve() else 1, depth, str(path).lower())

    return sorted(candidates, key=_rank)[0]


def _is_sample_submission_like(path: Path) -> bool:
    compact = "".join(ch for ch in path.stem.lower() if ch.isalnum())
    return "samplesubmission" in compact or path.name.lower() == "sample_submission.csv"


def _read_csv_header(path: Path) -> list[str]:
    if not path.exists() or path.suffix.lower() != ".csv":
        return []
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return [str(c).strip() for c in next(csv.reader(f), []) if str(c).strip()]
        except Exception:
            continue
    return []


def _direct_mode_enabled(task: TaskModel) -> bool:
    return bool(getattr(task.config.auto_realize, "direct_automl_from_description", False))


def _sample_submission_required(autorealize_dir: Path, configured: bool) -> bool:
    if not configured:
        return False
    context_required = _mlevolve_generate_submission_required(autorealize_dir, configured)
    if context_required is False:
        return False
    report = safe_read_json(autorealize_dir / "realize_report" / "submission_report.json", {})
    source = str(report.get("source", "") if isinstance(report, dict) else "")
    if source in {"not_applicable", "skipped_no_authoritative_contract", "disabled_by_config", "skipped_generation_failed"}:
        return False
    return True


def _prepare_direct_autorealize_output(
    *,
    task_id: str,
    task: TaskModel,
    input_root: Path,
    run_dir: Path,
    autorealize_dir: Path,
    clean: bool = False,
) -> bool:
    desc_src = _find_original_description(input_root)
    if desc_src is None:
        store.set_status(
            task_id,
            status="failed",
            phase="prepare_automl_input_failed",
            last_error="直接启动 AutoML 需要输入目录中存在 description.md；请放入人工确认的赛题说明后重试。",
        )
        return False

    try:
        source = input_root.expanduser().resolve()
        target = autorealize_dir.expanduser().resolve()
        if target == source:
            pass
        else:
            try:
                target.relative_to(source)
                store.set_status(
                    task_id,
                    status="failed",
                    phase="prepare_automl_input_failed",
                    last_error=f"拒绝把输入目录复制到其子目录，避免递归复制: input_root={source}, target={target}",
                )
                return False
            except ValueError:
                pass
            if clean and target.exists():
                if not _is_safe_stage_dir(run_dir, target, {"autorealize"}):
                    store.set_status(
                        task_id,
                        status="failed",
                        phase="prepare_automl_input_failed",
                        last_error=f"Refused to delete unsafe direct AutoML input directory: {target}",
                    )
                    return False
                _remove_tree_with_retries(target)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, dirs_exist_ok=True)

        prepared_desc = target / "description.md"
        if desc_src.resolve() != prepared_desc.resolve():
            shutil.copy2(desc_src, prepared_desc)
        origin_desc = target / "description_origin.md"
        if desc_src.resolve() != origin_desc.resolve():
            shutil.copy2(desc_src, origin_desc)

        sample_candidates = [
            p
            for p in sorted(target.rglob("*"), key=lambda x: str(x).lower())
            if p.is_file() and _is_sample_submission_like(p) and "realize_report" not in p.parts
        ]
        root_sample = target / "sample_submission.csv"
        if sample_candidates and sample_candidates[0].resolve() != root_sample.resolve():
            if sample_candidates[0].suffix.lower() == ".csv":
                shutil.copy2(sample_candidates[0], root_sample)

        report_dir = target / "realize_report"
        report_dir.mkdir(parents=True, exist_ok=True)
        desc_text = prepared_desc.read_text(encoding="utf-8", errors="ignore")
        file_list = []
        for p in sorted(target.rglob("*"), key=lambda x: str(x).lower()):
            if p.is_file():
                try:
                    rp = str(p.relative_to(target)).replace("\\", "/")
                except ValueError:
                    rp = str(p)
                if not rp.startswith("realize_report/"):
                    file_list.append(rp)

        sample_files = [x for x in file_list if _is_sample_submission_like(Path(x))]
        root_sample_rel = "sample_submission.csv" if root_sample.exists() else (sample_files[0] if sample_files else None)
        description_rel = str(desc_src.relative_to(input_root)).replace("\\", "/")
        sample_columns = _read_csv_header(root_sample) if root_sample.exists() else []
        submission_contract = {
            "is_defined": bool(sample_columns),
            "is_authoritative": bool(sample_columns),
            "output_filename": "submission.csv",
            "sample_filename": Path(root_sample_rel).name if root_sample_rel else "sample_submission.csv",
            "columns": sample_columns,
            "column_descriptions": {},
            "row_unit": "",
            "row_count_rule": "",
            "format_description": "",
            "validation_rules": [],
            "source": root_sample_rel or "",
            "evidence": [f"Official sample submission file with columns: {sample_columns}"] if sample_columns else [],
            "confidence": 0.98 if sample_columns else 0.0,
            "unresolved_questions": [],
        }
        authoritative_memory = {
            "has_authoritative_sources": True,
            "summary": "直接使用输入目录中的 description.md 作为任务定义。",
            "task_goal": task.config.auto_realize.task_hint,
            "input_requirements": ["以输入目录和原始 description.md 说明为准。"],
            "output_requirements": (
                [f"提交列以 `{root_sample_rel}` 为准: {', '.join(sample_columns)}"]
                if sample_columns
                else ["未发现可解析的官方 sample_submission；输出协议以原始 description.md 为准。"]
            ),
            "evaluation_requirements": ["以原始 description.md 中的评估协议为准。"],
            "constraints": ["不得由 AutoRealize 重新发明任务定义、提交格式或评估协议。"],
            "leakage_guards": [],
            "submission_contract": submission_contract,
            "evidence_items": [
                {
                    "source_path": description_rel,
                    "source_type": "original_description",
                    "priority": "high",
                    "evidence": desc_text[:1000],
                }
            ],
            "source_files": [description_rel, *([root_sample_rel] if root_sample_rel else [])],
            "unresolved_questions": [],
            "context_routing_notes": [
                "Direct AutoML mode skips AutoRealize generation; downstream agents must treat original description.md as canonical."
            ],
        }
        priority_order = [
            "original description.md / README / official requirement/spec documents",
            "official sample_submission or explicitly documented output contract",
            "user task hint",
            "data field profiles and relation probes",
        ]
        do_not_invent = [
            "Do not invent submission columns or output filenames when no authoritative source defines them.",
            "Do not invent a primary metric, metric direction, row count rule, or fixed random seed.",
            "Do not override original description/README/spec constraints with data-profile heuristics.",
            "For RL or optimization tasks without an official tabular submission contract, keep the output protocol from the original description.",
        ]
        route_base = {
            "priority_order": priority_order,
            "do_not_invent": do_not_invent,
        }
        agent_context_pack = {
            "schema_version": "autorealize.agent_context_pack.v1",
            "purpose": "Shared compact memory and routing policy for direct AutoML mode.",
            "task_hint": task.config.auto_realize.task_hint,
            "priority_order": priority_order,
            "do_not_invent": do_not_invent,
            "authoritative_memory": {
                "has_authoritative_sources": True,
                "source_files": authoritative_memory["source_files"],
                "summary": authoritative_memory["summary"],
                "task_goal": authoritative_memory["task_goal"],
                "input_requirements": authoritative_memory["input_requirements"],
                "output_requirements": authoritative_memory["output_requirements"],
                "evaluation_requirements": authoritative_memory["evaluation_requirements"],
                "constraints": authoritative_memory["constraints"],
                "leakage_guards": [],
                "unresolved_questions": [],
                "context_routing_notes": authoritative_memory["context_routing_notes"],
                "evidence_items": authoritative_memory["evidence_items"],
            },
            "submission_contract": submission_contract,
            "constraint_memory": {"summary": "Direct mode uses the original description as the constraint source.", "items": []},
            "data_memory": {
                "tables": [],
                "documents": [
                    {
                        "path": description_rel,
                        "role": "task_requirement",
                        "summary": desc_text[:1200],
                        "columns": [],
                        "field_descriptions": {},
                        "field_profiles": [],
                        "warnings": [],
                    }
                ],
                "relations": [],
                "sampled_filename_patterns": [],
                "filename_sample_groups": [],
                "field_glossary": {},
                "metric_candidates": [],
                "time_clues": [],
            },
            "context_routes": {
                "task_classifier": {
                    **route_base,
                    "must_read": ["authoritative_memory.task_goal", "submission_contract"],
                    "allowed_inference": "Infer task type only if original description is silent; never decide submission schema here.",
                },
                "description_writer": {
                    **route_base,
                    "must_read": ["authoritative_memory", "submission_contract"],
                    "writing_policy": [
                        "Do not rewrite the original description in direct mode.",
                        "No reflection logs, issues/fixes, ambiguity_points, or internal process notes.",
                    ],
                },
                "evaluation_contract_agent": {
                    **route_base,
                    "must_read": ["authoritative_memory.evaluation_requirements", "submission_contract.validation_rules"],
                    "repair_policy": "Prefer original description.md when resolving ambiguity.",
                },
                "sample_submission_builder": {
                    **route_base,
                    "must_read": ["submission_contract"],
                    "activation_policy": "Only reuse official sample_submission in direct mode; do not generate a new schema.",
                },
                "automl": {
                    **route_base,
                    "must_read": ["final description.md", "authoritative_memory", "submission_contract"],
                    "priority": "When any generated context conflicts with original description.md, prefer original description.md.",
                },
            },
        }
        data_description = "\n".join(
            [
                "# 数据与任务说明",
                "",
                "本任务启用了“跳过 AutoRealize，直接启动 AutoML”模式。",
                "输入目录中的 `description.md` 被视为人工确认的最高优先级任务说明；AutoDecision 未重新生成赛题描述、提交格式或评估协议。",
                "",
                "## 原始任务说明",
                f"- 来源: `{str(desc_src.relative_to(input_root)).replace(chr(92), '/')}`",
                "",
                "## 文件清单",
                *[f"- `{x}`" for x in file_list[:300]],
            ]
        )
        (report_dir / "data_description.md").write_text(data_description, encoding="utf-8")
        (report_dir / "original_requirements.txt").write_text(desc_text, encoding="utf-8")
        write_json(report_dir / "authoritative_task_memory.json", authoritative_memory)
        write_json(report_dir / "agent_context_pack.json", agent_context_pack)
        write_json(
            report_dir / "data_cognition_report.json",
            {
                "schema_version": "autorealize.data_cognition_report.v1",
                "mode": "direct_automl_from_description",
                "description_source": str(desc_src),
                "files": file_list,
                "authoritative_memory": authoritative_memory,
                "agent_context_pack": agent_context_pack,
                "summary": {
                    "file_count": len(file_list),
                    "requirement_doc_count": 1,
                    "official_sample_submission_count": len(sample_files),
                },
            },
        )
        write_json(
            report_dir / "task_definition_report.json",
            {
                "schema_version": "autorealize.task_definition_report.v1",
                "mode": "direct_automl_from_description",
                "description_source": str(desc_src),
                "downstream_context": {
                    "task_hint": task.config.auto_realize.task_hint,
                    "description_source": str(desc_src),
                    "generate_sample_submission": bool(sample_files),
                    "official_sample_submission_files": sample_files,
                    "authoritative_memory": authoritative_memory,
                    "authoritative_submission_contract": submission_contract,
                    "agent_context_pack": agent_context_pack,
                    "context_routes": agent_context_pack["context_routes"],
                    "do_not_invent": do_not_invent,
                },
                "artifacts": {
                    "description": "description.md",
                    "sample_submission": root_sample_rel,
                },
            },
        )
        write_json(
            report_dir / "submission_report.json",
            {
                "schema_version": "autorealize.submission_report.v1",
                "passed": True,
                "source": "official_sample_reused" if root_sample_rel else "not_applicable",
                "target_file": root_sample_rel,
                "issues": [],
                "reason": (
                    "输入目录已包含 sample_submission 样例。"
                    if root_sample_rel
                    else "直接 AutoML 模式未发现官方 sample_submission；提交/评估格式以原始 description.md 为准。"
                ),
            },
        )
        write_json(
            report_dir / "current_state.json",
            {
                "status": "completed",
                "phase": "direct_automl_from_description",
                "message": "AutoRealize skipped; original description.md prepared for AutoML.",
                "updated_at": now_ts(),
            },
        )
        write_json(
            report_dir / "run_summary.json",
            {
                "schema_version": "autorealize.run_summary.v1",
                "mode": "direct_automl_from_description",
                "run_name": "autorealize",
                "input_root": str(input_root),
                "run_dir": str(target),
                "task_hint": task.config.auto_realize.task_hint,
                "modules": {
                    "data_cognition": {"enabled": False, "artifact": "data_description.md"},
                    "task_definition": {"enabled": False, "description": "description.md"},
                },
            },
        )
        write_json(
            report_dir / "frontend_manifest.json",
            {
                "schema_version": "autorealize.frontend_manifest.v1",
                "mode": "direct_automl_from_description",
                "main_artifacts": ["description.md", "realize_report/data_description.md"],
                "description_source": str(desc_src),
            },
        )
        event = {
            "ts": now_ts(),
            "scope": "pipeline.direct_automl_from_description",
            "status": "COMPLETED",
            "description_source": str(desc_src),
        }
        (report_dir / "event_stream.jsonl").write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
        store.set_status(
            task_id,
            status="running",
            phase="automl_input_ready",
            run_dir=str(run_dir),
            last_error=None,
        )
        return True
    except Exception as e:
        store.set_status(task_id, status="failed", phase="prepare_automl_input_failed", last_error=f"直接准备 AutoML 输入失败: {e}")
        return False


def _task_layout(task: TaskModel, output_root: Path | None = None) -> dict[str, Path]:
    root_base = output_root if output_root is not None else resolve_output_root(task.output_root)
    task_root = root_base / task.task_name
    ar_dir = task_root / "autorealize"
    automl_root = task_root / "automl"
    automl_logs_root = automl_root / "logs"
    automl_workspaces_root = automl_root / "workspaces"
    report_dir = task_root / "report"
    return {
        "task_root": task_root,
        "autorealize_dir": ar_dir,
        "automl_root": automl_root,
        "automl_logs_root": automl_logs_root,
        "automl_workspaces_root": automl_workspaces_root,
        "report_dir": report_dir,
    }


def _resolve_autorealize_dir(task: TaskModel) -> Path:
    if not task.run_dir:
        raise HTTPException(status_code=400, detail="task has no run_dir; cannot resolve AutoRealize output")
    run_dir = Path(task.run_dir).expanduser().resolve()
    ar_dir = run_dir / "autorealize"
    if not ar_dir.exists() or not ar_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"AutoRealize output not found: {ar_dir}")
    return ar_dir


def _validate_automl_rerun(task: TaskModel) -> tuple[Path, Path, Path, Path, Path]:
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task is running; cannot rerun AutoML")

    if _direct_mode_enabled(task):
        run_dir = _resolve_task_run_dir_for_rerun(task)
        autorealize_dir = run_dir / "autorealize"
    else:
        autorealize_dir = _resolve_autorealize_dir(task)
    required_files = [
        autorealize_dir / "description.md",
    ]
    if _sample_submission_required(autorealize_dir, task.config.auto_realize.generate_sample_submission):
        required_files.append(autorealize_dir / "sample_submission.csv")
    missing = [str(p) for p in required_files if not p.exists()]
    if missing and not _direct_mode_enabled(task):
        raise HTTPException(
            status_code=400,
            detail=f"AutoRealize outputs are incomplete; missing files: {missing}",
        )
    if missing and _direct_mode_enabled(task):
        input_root = Path(task.input_root).expanduser().resolve()
        desc_src = _find_original_description(input_root) if input_root.exists() else None
        if desc_src is None:
            raise HTTPException(
                status_code=400,
                detail=f"直接 AutoML 模式需要 input_root 中存在 description.md；当前 AutoRealize 输出缺失: {missing}",
            )

    layout = _task_layout(task)
    automl_logs_root = layout["automl_logs_root"]
    automl_workspaces_root = layout["automl_workspaces_root"]
    ml_log_dir = automl_logs_root / task.task_name
    ml_ws_dir = automl_workspaces_root / task.task_name
    return autorealize_dir, automl_logs_root, automl_workspaces_root, ml_log_dir, ml_ws_dir


def _validate_direct_automl_start(task: TaskModel) -> tuple[Path, Path, Path, Path, Path]:
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task is running; cannot start AutoML")
    if not task.input_root.strip():
        raise HTTPException(status_code=400, detail="请先配置输入文件夹(input_root)再直接启动 AutoML")
    if not task.task_name.strip():
        raise HTTPException(status_code=400, detail="请先配置任务名(task_name)再直接启动 AutoML")

    input_root = Path(task.input_root).expanduser().resolve()
    if not input_root.exists() or not input_root.is_dir():
        raise HTTPException(status_code=400, detail=f"input_root does not exist: {input_root}")
    if _find_original_description(input_root) is None:
        raise HTTPException(
            status_code=400,
            detail="直接启动 AutoML 需要输入目录中存在 description.md；请放入人工确认的赛题说明后重试。",
        )

    run_dir = _resolve_task_run_dir_for_rerun(task)
    if run_dir.exists() and not _is_safe_task_output_dir(task, run_dir):
        raise HTTPException(
            status_code=400,
            detail=f"Refused to write unsafe task directory: {run_dir}",
        )
    return (
        input_root,
        run_dir,
        run_dir / "autorealize",
        run_dir / "automl" / "logs",
        run_dir / "automl" / "workspaces",
    )


def _resolve_task_run_dir_for_rerun(task: TaskModel) -> Path:
    if task.run_dir:
        return Path(task.run_dir).expanduser().resolve()
    return (resolve_output_root(task.output_root) / task.task_name).resolve()


def _validate_autorealize_rerun(task: TaskModel) -> tuple[Path, Path, Path, Path, Path]:
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task is running; cannot rerun AutoRealize")
    if not task.input_root.strip():
        raise HTTPException(status_code=400, detail="请先配置输入文件夹(input_root)再重跑 AutoRealize")
    if not task.task_name.strip():
        raise HTTPException(status_code=400, detail="请先配置任务名(task_name)再重跑 AutoRealize")

    input_root = Path(task.input_root).expanduser().resolve()
    if not input_root.exists():
        raise HTTPException(status_code=400, detail=f"input_root does not exist: {input_root}")

    run_dir = _resolve_task_run_dir_for_rerun(task)
    if run_dir.exists() and not _is_safe_task_output_dir(task, run_dir):
        raise HTTPException(
            status_code=400,
            detail=f"Refused to rewrite unsafe task directory: {run_dir}",
        )
    return input_root, run_dir, run_dir / "autorealize", run_dir / "automl", run_dir / "report"


def _validate_autoreport_rerun(task: TaskModel) -> tuple[Path, Path, Path, Path | None, Path | None, Path]:
    if task.status == "running":
        raise HTTPException(status_code=400, detail="task is running; cannot rerun AutoReport")
    if not task.config.auto_report.enabled:
        raise HTTPException(status_code=400, detail="AutoReport is disabled in task config")

    run_dir = _resolve_task_run_dir_for_rerun(task)
    if run_dir.exists() and not _is_safe_task_output_dir(task, run_dir):
        raise HTTPException(
            status_code=400,
            detail=f"Refused to rewrite unsafe task directory: {run_dir}",
        )
    autorealize_dir = run_dir / "autorealize"
    require_sample = _sample_submission_required(
        autorealize_dir,
        task.config.auto_realize.generate_sample_submission,
    )
    if not _autorealize_outputs_ready(autorealize_dir, require_sample_submission=require_sample):
        if _direct_mode_enabled(task):
            input_root = Path(task.input_root).expanduser().resolve()
            desc_src = _find_original_description(input_root) if input_root.exists() else None
            if desc_src is not None:
                automl_root = run_dir / "automl"
                ml_log_dir = _pick_local_automl_log_dir(task)
                ml_ws_dir = _pick_local_automl_workspace_dir(task, exp_name=ml_log_dir.name if ml_log_dir else None)
                return run_dir, autorealize_dir, automl_root, ml_log_dir, ml_ws_dir, run_dir / "report"
        raise HTTPException(
            status_code=400,
            detail=f"AutoRealize outputs are incomplete; cannot rerun AutoReport: {autorealize_dir}",
        )

    automl_root = run_dir / "automl"
    ml_log_dir = _pick_local_automl_log_dir(task)
    ml_ws_dir = _pick_local_automl_workspace_dir(task, exp_name=ml_log_dir.name if ml_log_dir else None)
    return run_dir, autorealize_dir, automl_root, ml_log_dir, ml_ws_dir, run_dir / "report"


def _candidate_full_rerun_dirs(task: TaskModel) -> list[Path]:
    dirs: list[Path] = []
    try:
        configured_root = resolve_output_root(task.output_root) / task.task_name
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
    if not task.task_name.strip():
        return False
    try:
        candidate = path.expanduser().resolve()
    except Exception:
        return False

    allowed_roots: list[Path] = []
    for root in (
        resolve_output_root(task.output_root),
        PROJECT_RUNS_DIR,
        DEFAULT_RUNS_DIR,
        LEGACY_BACKEND_RUNS_DIR,
        LEGACY_AUTOREALIZE_RUNS_DIR,
    ):
        try:
            resolved_root = root.expanduser().resolve()
        except Exception:
            continue
        if str(resolved_root).lower() not in {str(x).lower() for x in allowed_roots}:
            allowed_roots.append(resolved_root)

    # Only allow deleting/reusing the direct child named exactly as the task.
    # This keeps old frontend/backend/runs tasks recoverable without opening
    # the safety gate to arbitrary folders.
    return any(candidate.parent == root and candidate.name == task.task_name for root in allowed_roots)


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


def _is_safe_stage_dir(run_dir: Path, target: Path, allowed_names: set[str]) -> bool:
    try:
        root = run_dir.expanduser().resolve()
        candidate = target.expanduser().resolve()
        candidate.relative_to(root)
    except Exception:
        return False
    return candidate.parent == root and candidate.name in allowed_names


def _remove_stage_dirs_for_rerun(
    *,
    task_id: str,
    run_dir: Path,
    targets: list[Path],
    allowed_names: set[str],
    phase: str,
    label: str,
) -> bool:
    for target in targets:
        if not target.exists():
            continue
        if not _is_safe_stage_dir(run_dir, target, allowed_names):
            store.set_status(
                task_id,
                status="failed",
                phase=phase,
                last_error=f"Refused to delete unsafe stage directory: {target}",
            )
            return False
        try:
            _remove_tree_with_retries(target)
        except Exception as e:
            store.set_status(
                task_id,
                status="failed",
                phase=phase,
                last_error=f"{label}前清理旧结果失败: {e}。如果是 Windows 文件占用，请关闭该文件的预览器/PDF阅读器/资源管理器预览后重试。",
            )
            return False
    return True


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
    template_path = AUTOREALIZE_DIR / "config" / "config.yaml"
    try:
        cfg = yaml.safe_load(template_path.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        cfg = {}
    ar = task.config.auto_realize
    cfg.setdefault("switches", {})
    cfg.setdefault("llm", {})
    cfg.setdefault("vllm", {})
    cfg.setdefault("parallel", {})
    cfg.setdefault("telemetry", {})
    cfg.setdefault("knowledge", {})
    cfg.setdefault("investigation", {})
    cfg.setdefault("data", {})

    llm_concurrency = max(1, int(ar.llm_concurrency or 1))

    cfg["switches"]["run_data_cognition"] = True
    cfg["switches"]["run_task_definition"] = True
    cfg["switches"]["enable_fewshot"] = ar.enable_fewshot
    cfg["switches"]["generate_sample_submission"] = ar.generate_sample_submission
    cfg["switches"]["prefer_original_description"] = True
    cfg["switches"]["direct_automl_from_description"] = False
    cfg["llm"]["request_timeout_seconds"] = ar.llm_timeout
    cfg["llm"]["max_concurrent_requests"] = llm_concurrency
    cfg["llm"]["enable_thinking"] = ar.llm_enable_thinking
    cfg["llm"]["reasoning_effort"] = ar.llm_reasoning_effort
    cfg["llm"]["structured_disable_thinking"] = ar.llm_structured_disable_thinking
    cfg["parallel"]["cognition_max_workers"] = llm_concurrency
    cfg["telemetry"]["enabled"] = not ar.no_telemetry
    cfg["knowledge"]["enabled"] = not ar.no_knowledge
    cfg["llm"]["enable_cache"] = not ar.no_llm_cache
    cfg["investigation"]["enabled"] = bool(ar.enable_question_investigator)
    cfg["data"]["auto_generate_predict_split"] = False

    llm = gs.llm
    autorealize_model = _selected_model(llm, "autoRealize", fallback_role="autoMlCode")
    vllm = _selected_model(llm, "autoRealizeVision")
    if autorealize_model.get("baseUrl"):
        cfg["llm"]["base_url"] = autorealize_model.get("baseUrl")
    if autorealize_model.get("model"):
        cfg["llm"]["model_name"] = autorealize_model.get("model")
    # Secrets are injected through the service process environment and must not
    # be persisted in task YAML under frontend/backend/.state.
    cfg["llm"]["api_key"] = None
    cfg["llm"]["enable_thinking"] = _legacy_enable_thinking(autorealize_model.get("thinkingMode", autorealize_model.get("enableThinking")))
    effort = _normal_reasoning_effort(autorealize_model.get("reasoningEffort"))
    cfg["llm"]["reasoning_effort"] = None if effort == "default" else effort
    max_tokens = _normal_max_tokens(autorealize_model.get("maxTokens", autorealize_model.get("max_tokens")))
    if max_tokens is not None:
        cfg["llm"]["max_tokens"] = max_tokens
        cfg["llm"]["structured_max_tokens"] = max_tokens
    cfg["llm"]["structured_disable_thinking"] = True

    cfg["vllm"]["enabled"] = bool(ar.enable_vllm)
    if vllm.get("baseUrl"):
        cfg["vllm"]["base_url"] = vllm.get("baseUrl")
    if vllm.get("model"):
        cfg["vllm"]["model_name"] = vllm.get("model")
    cfg["vllm"]["api_key"] = None

    out = STATE_DIR / f"{task.id}.autorealize.config.yaml"
    write_private_text(out, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    return out


def _automl_engine(task: TaskModel) -> str:
    return "mlevolve"


def _mlevolve_generate_submission_required(autorealize_dir: Path, configured: bool) -> bool:
    """Honor AutoRealize's output protocol while preserving manual disable."""
    if not configured:
        return False
    report_dir = autorealize_dir / "realize_report"
    automl_pack = safe_read_json(report_dir / "automl_context_pack.json", {})
    output = {}
    if isinstance(automl_pack, dict):
        output = automl_pack.get("output_contract") if isinstance(automl_pack.get("output_contract"), dict) else {}
    if not output:
        bundle = safe_read_json(report_dir / "description_protocol_bundle.json", {})
        output = bundle.get("output") if isinstance(bundle, dict) and isinstance(bundle.get("output"), dict) else {}
    if output:
        if bool(output.get("sample_submission_required")):
            return True
        reason = str(output.get("no_sample_submission_reason") or "").strip()
        kind = str(output.get("output_kind") or "").strip().lower()
        columns = output.get("columns") if isinstance(output.get("columns"), list) else []
        if reason and (kind in {"policy", "solution", "solution_table", "artifact", "report"} or not columns):
            return False
    problem = safe_read_json(report_dir / "problem_paradigm_report.json", {})
    paradigm = str(problem.get("problem_paradigm") or "").strip()
    if paradigm in {"static_optimization", "reinforcement_learning"} and not (autorealize_dir / "sample_submission.csv").exists():
        return False
    return True


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
    code_model = _selected_model(llm, "autoMlCode")
    feedback_model = _selected_model(llm, "autoMlFeedback", fallback_role="autoMlCode")
    embedding_model = _selected_model(llm, "embedding")
    py = gs.python.get("executable", "python")

    exp_name = exp_name or task.task_name

    def _as_cli_str(value: Any, default: str = "") -> str:
        v = default if value is None else str(value)
        return json.dumps(v, ensure_ascii=False)

    generate_submission = _mlevolve_generate_submission_required(autorealize_dir, bool(am.generate_submission))

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
        "preprocess_data=true",
        f"copy_data={'true' if am.copy_data else 'false'}",
        f"start_cpu_id=0",
        f"cpu_number={int(task.config.resources.cpu_cores)}",
        f"resources.cpu_cores={int(task.config.resources.cpu_cores)}",
        f"resources.memory_limit_gb={float(task.config.resources.memory_limit_gb)}",
        f"resources.accelerator_mode={_as_cli_str(task.config.resources.accelerator_mode, 'all')}",
        f"resources.accelerator_device_ids={json.dumps(task.config.resources.accelerator_device_ids, ensure_ascii=False)}",
        f"resources.monitor_interval_seconds={float(task.config.resources.monitor_interval_seconds)}",
        f"torch_hub_dir={_as_cli_str(global_mlevolve.get('torchHubDir', getattr(am, 'torch_hub_dir', '')))}",
        f"pretrain_model_dir={_as_cli_str(global_mlevolve.get('pretrainModelDir', getattr(am, 'pretrain_model_dir', '')))}",
        f"use_grading_server={'true' if am.use_grading_server else 'false'}",
        f"exec.timeout={am.exec_timeout_secs}",
        "exec.agent_file_name=runfile.py",
        f"agent.steps={am.steps}",
        f"agent.time_limit={am.time_limit_secs}",
        f"agent.initial_drafts={am.initial_drafts}",
        "agent.seed=42",
        "agent.data_preview=true",
        f"agent.generate_submission={'true' if generate_submission else 'false'}",
        f"agent.code.model={_as_cli_str(_model_cli_value(code_model, 'model', 'deepseek-v4-pro'), 'deepseek-v4-pro')}",
        "agent.code.temp=0.5",
        f"agent.code.base_url={_as_cli_str(_model_cli_value(code_model, 'baseUrl', 'https://api.deepseek.com'), 'https://api.deepseek.com')}",
        f"agent.code.enable_thinking={_model_thinking_cli(code_model)}",
        f"agent.code.reasoning_effort={_model_reasoning_cli(code_model)}",
        f"agent.feedback.model={_as_cli_str(_model_cli_value(feedback_model, 'model', 'deepseek-v4-pro'), 'deepseek-v4-pro')}",
        "agent.feedback.temp=0.5",
        f"agent.feedback.base_url={_as_cli_str(_model_cli_value(feedback_model, 'baseUrl', 'https://api.deepseek.com'), 'https://api.deepseek.com')}",
        f"agent.feedback.enable_thinking={_model_thinking_cli(feedback_model)}",
        f"agent.feedback.reasoning_effort={_model_reasoning_cli(feedback_model)}",
        f"agent.check_data_leakage={'true' if am.check_data_leakage else 'false'}",
        f"agent.use_diff_mode={'true' if am.use_diff_mode else 'false'}",
        "agent.fusion_vs_evolution_prob=0.3",
        "agent.branch_fusion_trigger_prob=1.0",
        "agent.max_fusion_drafts=2",
        f"agent.use_global_memory={'true' if am.use_global_memory else 'false'}",
        f"agent.memory_similarity_threshold={am.memory_similarity_threshold}",
        f"agent.memory_embedding_backend={_as_cli_str(am.memory_embedding_backend, 'openai')}",
        f"agent.memory_embedding_base_url={_as_cli_str(_model_cli_value(embedding_model, 'baseUrl', global_mlevolve.get('embeddingBaseUrl', getattr(am, 'memory_embedding_base_url', ''))))}",
        f"agent.memory_embedding_model={_as_cli_str(_model_cli_value(embedding_model, 'model', global_mlevolve.get('embeddingModel', getattr(am, 'memory_embedding_model', ''))))}",
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
    code_max_tokens = _model_max_tokens_cli(code_model)
    feedback_max_tokens = _model_max_tokens_cli(feedback_model)
    if code_max_tokens is not None:
        cmd.append(f"agent.code.max_tokens={code_max_tokens}")
    if feedback_max_tokens is not None:
        cmd.append(f"agent.feedback.max_tokens={feedback_max_tokens}")
    if am.goal:
        cmd.append(f"goal={_as_cli_str(am.goal)}")
    if am.eval:
        cmd.append(f"eval={_as_cli_str(am.eval)}")
    return cmd


def _write_mlevolve_config(task_id: str, command: list[str]) -> Path:
    """Compile frontend-selected dotted overrides into one task-level YAML."""
    template_path = MLEVOLVE_DIR / "config" / "config.yaml"
    try:
        cfg = yaml.safe_load(template_path.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        cfg = {}

    for item in command[2:]:
        if not isinstance(item, str) or "=" not in item:
            continue
        dotted_key, raw_value = item.split("=", 1)
        dotted_key = dotted_key.strip()
        if not dotted_key:
            continue
        if dotted_key in MLEVOLVE_SECRET_CONFIG_KEYS:
            continue
        try:
            value = yaml.safe_load(raw_value)
        except Exception:
            value = raw_value
        target = cfg
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                child = {}
                target[part] = child
            target = child
        target[parts[-1]] = value

    agent_cfg = cfg.setdefault("agent", {})
    agent_cfg.setdefault("code", {})["api_key"] = ""
    agent_cfg.setdefault("feedback", {})["api_key"] = ""
    agent_cfg["memory_embedding_api_key"] = ""

    out = STATE_DIR / f"{task_id}.mlevolve.config.yaml"
    write_private_text(out, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    return out


def _without_mlevolve_secret_args(args: list[str]) -> list[str]:
    return [
        item
        for item in args
        if not any(item.startswith(f"{key}=") for key in MLEVOLVE_SECRET_CONFIG_KEYS)
    ]


def _mlevolve_secret_env(gs: GlobalSettingsModel) -> dict[str, str]:
    code_model = _selected_model(gs.llm, "autoMlCode")
    feedback_model = _selected_model(gs.llm, "autoMlFeedback", fallback_role="autoMlCode")
    embedding_model = _selected_model(gs.llm, "embedding")
    code_key = str(code_model.get("apiKey") or "")
    values = {
        "DEEPSEEK_API_KEY": code_key,
        "MLEVOLVE_CODE_API_KEY": code_key,
        "MLEVOLVE_FEEDBACK_API_KEY": str(feedback_model.get("apiKey") or ""),
        "MLEVOLVE_EMBEDDING_API_KEY": str(embedding_model.get("apiKey") or ""),
    }
    return {key: value for key, value in values.items() if value}


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
            time.sleep(min(30.0, 2.0 ** (attempt - 1)))
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
                    "10061",
                    "actively refused",
                    "积极拒绝",
                    "connection reset",
                    "connection aborted",
                    "bad gateway",
                    "temporary failure",
                    "getaddrinfo",
                    "11001",
                    "name resolution",
                    "name or service not known",
                    "503",
                    "502",
                    "504",
                ]
            )
            if (not retryable) or attempt >= NETWORK_RETRY_MAX_ATTEMPTS:
                raise RuntimeError(f"POST {url} failed: {e}")
            time.sleep(min(30.0, 2.0 ** (attempt - 1)))
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
            time.sleep(min(30.0, 2.0 ** (attempt - 1)))
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
                    "10061",
                    "actively refused",
                    "积极拒绝",
                    "connection reset",
                    "connection aborted",
                    "bad gateway",
                    "temporary failure",
                    "getaddrinfo",
                    "11001",
                    "name resolution",
                    "name or service not known",
                    "503",
                    "502",
                    "504",
                ]
            )
            if (not retryable) or attempt >= NETWORK_RETRY_MAX_ATTEMPTS:
                raise RuntimeError(f"GET {url} failed: {e}")
            time.sleep(min(30.0, 2.0 ** (attempt - 1)))
    raise RuntimeError(f"GET {url} failed: {last_error}")


def _wait_for_service_ready(
    base_url: str,
    service_name: str,
    *,
    timeout_secs: float = SERVICE_START_READY_TIMEOUT_SECS,
    poll_secs: float = SERVICE_START_READY_POLL_SECS,
) -> None:
    """Wait for a core service before creating stage outputs or starting a job."""

    health_url = base_url.rstrip("/") + "/health"
    deadline = time.monotonic() + max(0.1, float(timeout_secs))
    last_error: Exception | None = None
    while True:
        try:
            req = urllib.request.Request(url=health_url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if 200 <= int(getattr(resp, "status", 200)) < 300:
                    body = resp.read().decode("utf-8", errors="replace")
                    payload = json.loads(body) if body else {}
                    if not payload or str(payload.get("status") or "ok").lower() == "ok":
                        return
        except Exception as exc:  # noqa: BLE001
            last_error = exc

        if time.monotonic() >= deadline:
            detail = f": {last_error}" if last_error else ""
            restart_command = (
                "`powershell -ExecutionPolicy Bypass -File .\\scripts\\dev-restart.ps1 -Wait`"
                if os.name == "nt"
                else "`./scripts/dev-restart.sh`"
            )
            raise RuntimeError(
                f"{service_name} service is not ready at {health_url}{detail}. "
                "请检查全局设置 coreServices 中的服务地址；本地开发请运行 "
                f"{restart_command}。"
            )
        time.sleep(max(0.05, float(poll_secs)))


def _service_base_urls(gs: GlobalSettingsModel) -> tuple[str, str, str, int]:
    core = gs.coreServices or {}
    ar_base = str(core.get("autoRealizeBaseUrl") or "http://127.0.0.1:18101").strip().rstrip("/")
    mlevolve_base = str(core.get("mlevolveBaseUrl") or "http://127.0.0.1:18103").strip().rstrip("/")
    report_base = str(core.get("autoReportBaseUrl") or "http://127.0.0.1:18104").strip().rstrip("/")
    timeout_secs = int(core.get("requestTimeoutSecs") or 10)
    return ar_base, mlevolve_base, report_base, timeout_secs


def _poll_remote_job(base_url: str, job_id: str, timeout_secs: int = 15) -> dict[str, Any]:
    reconnect_attempt = 0
    last_error = ""
    while True:
        try:
            status = _json_get(base_url, f"/jobs/{job_id}", timeout_secs=timeout_secs)
            reconnect_attempt = 0
            last_error = ""
        except Exception as exc:
            reconnect_attempt += 1
            last_error = str(exc)
            if reconnect_attempt >= SERVICE_POLL_RECONNECT_MAX_ATTEMPTS:
                raise RuntimeError(
                    f"service reconnect failed after {reconnect_attempt} attempts: {last_error}"
                ) from exc
            sleep_secs = min(
                SERVICE_POLL_RECONNECT_MAX_SLEEP_SECS,
                SERVICE_POLL_RECONNECT_BASE_SLEEP_SECS * reconnect_attempt,
            )
            time.sleep(sleep_secs)
            continue
        state = str(status.get("status") or "")
        if state in {"completed", "failed", "stopped"}:
            return status
        time.sleep(1.0)


def _is_interrupted_exit_code(exit_code: Any) -> bool:
    try:
        code = int(exit_code)
    except Exception:
        return False
    # Windows CTRL_C_EVENT/CTRL_BREAK_EVENT is reported as 0xC000013A.
    return code in {3221225786, -1073741510, 130, -2, -15}


def _is_automl_budget_exhausted_status(status: dict[str, Any]) -> bool:
    text = " ".join(
        str(status.get(key) or "")
        for key in ("last_error", "stdout_tail", "stderr_tail")
    )
    return (
        "search budget was exhausted" in text
        or "Search budget is exhausted" in text
        or "MLEvolve search budget exhausted" in text
        or "Time limit reached (configured=" in text
    )


def _autorealize_outputs_ready(autorealize_dir: Path, *, require_sample_submission: bool = True) -> bool:
    required = [
        autorealize_dir / "description.md",
        autorealize_dir / "realize_report" / "data_description.md",
    ]
    if require_sample_submission:
        required.append(autorealize_dir / "sample_submission.csv")
    return all(p.exists() for p in required)


def _report_outputs_ready(report_dir: Path) -> bool:
    return (report_dir / "report.json").exists() and (report_dir / "report.md").exists()


def _report_evidence_paths(
    *,
    autorealize_dir: Path,
    automl_root: Path,
    ml_log_dir: Path | None,
    ml_ws_dir: Path | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    evidence.append({"label": "autorealize", "path": str(autorealize_dir), "kind": "autorealize", "required": True})
    if automl_root.exists():
        evidence.append({"label": "automl_root", "path": str(automl_root), "kind": "automl", "required": False})
    if ml_log_dir is not None and ml_log_dir.exists():
        evidence.append({"label": "automl_logs", "path": str(ml_log_dir), "kind": "automl", "required": False})
    if ml_ws_dir is not None and ml_ws_dir.exists():
        evidence.append({"label": "automl_workspace", "path": str(ml_ws_dir), "kind": "automl", "required": False})
    return evidence


def _run_report_stage(
    *,
    task_id: str,
    task: TaskModel,
    gs: GlobalSettingsModel,
    autorealize_dir: Path,
    automl_root: Path,
    ml_log_dir: Path | None,
    ml_ws_dir: Path | None,
    report_dir: Path,
    report_base: str,
    req_timeout: int,
) -> bool:
    cfg = task.config.auto_report
    if not cfg.enabled:
        return True
    report_dir.mkdir(parents=True, exist_ok=True)
    feedback_model = _selected_model(gs.llm, "autoMlFeedback", fallback_role="autoMlCode")
    code_model = _selected_model(gs.llm, "autoMlCode")
    report_model = feedback_model
    if not (report_model.get("model") and report_model.get("baseUrl") and report_model.get("apiKey")):
        report_model = code_model
    report_api_key = str(report_model.get("apiKey") or "")
    store.set_status(
        task_id,
        status="running",
        phase="report",
        report_dir=str(report_dir),
        last_error=None,
    )
    payload = {
        "task_id": task_id,
        "task_name": task.task_name,
        "output_dir": str(report_dir),
        "python_executable": str(gs.python.get("executable", "python")),
        "working_dir": str(AUTOREPORT_DIR),
        "evidence_paths": _report_evidence_paths(
            autorealize_dir=autorealize_dir,
            automl_root=automl_root,
            ml_log_dir=ml_log_dir,
            ml_ws_dir=ml_ws_dir,
        ),
        "config": {
            "report_title": f"{task.task_name} AutoDecision 运行报告",
            "audience": cfg.audience,
            "language": cfg.language,
            "include_raw_logs": cfg.include_raw_logs,
            "include_code_excerpt": cfg.include_code_excerpt,
            "use_llm": True,
            "llm": {
                "model": str(report_model.get("model") or ""),
                "base_url": str(report_model.get("baseUrl") or ""),
                "api_key": None,
                "temperature": 0.25,
                "max_tokens": 8192,
                "max_prompt_chars": 60000,
            },
        },
        "env_overrides": {"DEEPSEEK_API_KEY": report_api_key},
    }
    try:
        report_start = _json_post(report_base, "/jobs/start", payload, timeout_secs=req_timeout)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="report_failed", last_error=f"AutoReport service start failed: {e}")
        return False
    report_job_id = str(report_start.get("job_id") or "")
    if not report_job_id:
        store.set_status(task_id, status="failed", phase="report_failed", last_error="AutoReport service returned empty job_id")
        return False
    store.attach_handle(
        task_id,
        RuntimeHandle(
            process=None,
            source="autoreport_service",
            remote_base_url=report_base,
            remote_job_id=report_job_id,
            started_at=now_ts(),
        ),
    )
    try:
        report_status = _poll_remote_job(report_base, report_job_id, timeout_secs=req_timeout)
    except Exception as e:
        store.pop_handle(task_id)
        store.set_status(task_id, status="failed", phase="report_failed", last_error=f"AutoReport service poll failed: {e}")
        return False
    store.pop_handle(task_id)
    report_state = str(report_status.get("status") or "")
    report_code = report_status.get("exit_code")
    if report_code is None and report_state == "completed":
        report_code = 0
    if report_state != "completed" or report_code != 0:
        tail = str(report_status.get("stderr_tail") or report_status.get("stdout_tail") or report_status.get("last_error") or "").strip()
        msg = f"AutoReport exited with code {report_code if report_code is not None else '?'}"
        if tail:
            msg = f"{msg}: {tail.splitlines()[-1][:180]}"
        store.set_status(task_id, status="failed", phase="report_failed", last_error=msg)
        return False
    return True


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
    autorealize_model = _selected_model(gs.llm or {}, "autoRealize", fallback_role="autoMlCode")
    vllm = _selected_model(gs.llm or {}, "autoRealizeVision")

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
        "auto_generate_predict_split": False,
        "env_overrides": {
            "DEEPSEEK_API_KEY": str(autorealize_model.get("apiKey") or ""),
            "AUTOREALIZE_VISION_API_KEY": str(vllm.get("apiKey") or ""),
        },
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
        ar_base, mlevolve_base, report_base, req_timeout = _service_base_urls(gs)
        input_root, output_root = _validate_start(task)
        run_started_at = now_ts()
        layout = _task_layout(task, output_root)
        run_dir = layout["task_root"]
        autorealize_dir = layout["autorealize_dir"]
        automl_root = layout["automl_root"]
        automl_logs_root = layout["automl_logs_root"]
        automl_workspaces_root = layout["automl_workspaces_root"]
        report_dir = layout["report_dir"]
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
            report_dir.mkdir(parents=True, exist_ok=True)
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
        code_model = _selected_model(llm, "autoMlCode")
        if code_model.get("apiKey"):
            env["DEEPSEEK_API_KEY"] = str(code_model["apiKey"])

        store.set_status(task_id, status="running", phase="autorealize", run_dir=str(run_dir), run_started_at=run_started_at, last_error=None)
        if _direct_mode_enabled(task):
            ok_ar = _prepare_direct_autorealize_output(
                task_id=task_id,
                task=task,
                input_root=input_root,
                run_dir=run_dir,
                autorealize_dir=autorealize_dir,
                clean=True,
            )
        else:
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
            mlevolve_service_base=mlevolve_base,
            req_timeout=req_timeout,
        )
        if not ok:
            return

        ok_report = _run_report_stage(
            task_id=task_id,
            task=task,
            gs=gs,
            autorealize_dir=autorealize_dir,
            automl_root=automl_root,
            ml_log_dir=ml_log_dir,
            ml_ws_dir=ml_ws_dir,
            report_dir=report_dir,
            report_base=report_base,
            req_timeout=req_timeout,
        )
        if not ok_report:
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
    mlevolve_service_base: str,
    req_timeout: int,
    resume_existing: bool = False,
) -> bool:
    engine = _automl_engine(task)
    mlevolve_log_dir = ml_log_dir if resume_existing else automl_logs_root
    mlevolve_workspace_dir = ml_ws_dir if resume_existing else automl_workspaces_root
    ml_cmd = _build_mlevolve_command(
        task,
        gs,
        autorealize_dir=autorealize_dir,
        automl_logs_root=mlevolve_log_dir,
        automl_workspaces_root=mlevolve_workspace_dir,
        exp_name=exp_name,
    )
    mlevolve_config_path = _write_mlevolve_config(task_id, ml_cmd)
    service_base = mlevolve_service_base
    working_dir = str(MLEVOLVE_DIR)
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
        start_payload = {
            "task_id": task_id,
            "python_executable": str(gs.python.get("executable", "python")),
            "working_dir": working_dir,
            "env_overrides": _mlevolve_secret_env(gs),
            "config_path": str(mlevolve_config_path),
            "args": _without_mlevolve_secret_args(ml_cmd[2:]),
            "log_dir": str(mlevolve_log_dir),
            "workspace_dir": str(mlevolve_workspace_dir),
            "graceful_shutdown_buffer_secs": graceful_shutdown_buffer_secs,
            "resume": bool(resume_existing),
        }
        ml_start = _json_post(
            service_base,
            "/jobs/start",
            start_payload,
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
    ml_budget_exhausted = _is_automl_budget_exhausted_status(ml_status)
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
    try:
        _persist_resolved_automl_paths(task_id)
    except Exception:
        # Path reconciliation improves snapshots/resume, but must never turn a
        # completed expensive search into a failed task.
        pass
    if ml_budget_exhausted and ml_state in {"completed", "stopped"}:
        store.set_status(task_id, status="running", phase="automl_completed", last_error=None)
        return True
    if ml_state == "stopped" or (_is_interrupted_exit_code(ml_code) and not ml_budget_exhausted):
        stop_msg = str(ml_status.get("last_error") or "").strip()
        if not stop_msg:
            stop_msg = f"AutoML interrupted by console/control signal (exit code {ml_code})."
        store.set_status(task_id, status="stopped", phase="stopped", last_error=stop_msg)
        return False
    if ml_state != "completed" or (ml_code != 0 and not ml_budget_exhausted):
        err_hint = ""
        tail = (ml_stderr or ml_stdout or str(ml_status.get("last_error") or "")).strip()
        if tail:
            err_hint = tail.splitlines()[-1][:180]
        msg = f"AutoML exited with code {ml_code if ml_code is not None else '?'}"
        if err_hint:
            msg = f"{msg}: {err_hint}"
        store.set_status(task_id, status="failed", phase="automl_failed", last_error=msg)
        return False
    if ml_budget_exhausted:
        store.set_status(task_id, status="running", phase="automl_completed", last_error=None)
    return True


def _rerun_autorealize_thread(task_id: str) -> None:
    try:
        task = store.get(task_id)
        gs = get_global_settings()
        ar_base, _mlevolve_base, _report_base, req_timeout = _service_base_urls(gs)
        input_root, run_dir, autorealize_dir, _automl_root, _report_dir = _validate_autorealize_rerun(task)

        store.set_status(
            task_id,
            status="running",
            phase="autorealize",
            run_dir=str(run_dir),
            run_started_at=now_ts(),
            last_error=None,
        )
        ok_clean = _remove_stage_dirs_for_rerun(
            task_id=task_id,
            run_dir=run_dir,
            targets=[autorealize_dir],
            allowed_names={"autorealize"},
            phase="autorealize_failed",
            label="重跑 AutoRealize",
        )
        if not ok_clean:
            return
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            store.set_status(task_id, status="failed", phase="autorealize_failed", last_error=f"重跑 AutoRealize 准备目录失败: {e}")
            return

        if _direct_mode_enabled(task):
            ok = _prepare_direct_autorealize_output(
                task_id=task_id,
                task=task,
                input_root=input_root,
                run_dir=run_dir,
                autorealize_dir=autorealize_dir,
                clean=False,
            )
        else:
            ok = _run_autorealize_stage(
                task_id=task_id,
                task=task,
                gs=gs,
                input_root=input_root,
                run_dir=run_dir,
                ar_base=ar_base,
                req_timeout=req_timeout,
            )
        if not ok:
            return
        store.set_status(task_id, status="completed", phase="autorealize_completed", run_dir=str(run_dir), last_error=None)
    except HTTPException as e:
        detail = getattr(e, "detail", None)
        msg = str(detail) if detail is not None else str(e)
        store.set_status(task_id, status="failed", phase="autorealize_failed", last_error=msg)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="autorealize_failed", last_error=f"重跑 AutoRealize 异常: {e}")


def _rerun_autoreport_thread(task_id: str) -> None:
    try:
        task = store.get(task_id)
        gs = get_global_settings()
        _ar_base, _mlevolve_base, report_base, req_timeout = _service_base_urls(gs)
        run_dir, autorealize_dir, automl_root, ml_log_dir, ml_ws_dir, report_dir = _validate_autoreport_rerun(task)

        store.set_status(
            task_id,
            status="running",
            phase="report",
            run_dir=str(run_dir),
            run_started_at=now_ts(),
            last_error=None,
        )
        ok_clean = _remove_stage_dirs_for_rerun(
            task_id=task_id,
            run_dir=run_dir,
            targets=[report_dir],
            allowed_names={"report"},
            phase="report_failed",
            label="重跑 AutoReport",
        )
        if not ok_clean:
            return
        store.clear_output_paths(task_id, report=True)

        if _direct_mode_enabled(task):
            input_root = Path(task.input_root).expanduser().resolve()
            ok_direct = _prepare_direct_autorealize_output(
                task_id=task_id,
                task=task,
                input_root=input_root,
                run_dir=run_dir,
                autorealize_dir=autorealize_dir,
                clean=False,
            )
            if not ok_direct:
                return
            store.set_status(
                task_id,
                status="running",
                phase="report",
                run_dir=str(run_dir),
                report_dir=str(report_dir),
                last_error=None,
            )

        ok = _run_report_stage(
            task_id=task_id,
            task=task,
            gs=gs,
            autorealize_dir=autorealize_dir,
            automl_root=automl_root,
            ml_log_dir=ml_log_dir,
            ml_ws_dir=ml_ws_dir,
            report_dir=report_dir,
            report_base=report_base,
            req_timeout=req_timeout,
        )
        if not ok:
            return
        store.set_status(task_id, status="completed", phase="report_completed", report_dir=str(report_dir), last_error=None)
    except HTTPException as e:
        detail = getattr(e, "detail", None)
        msg = str(detail) if detail is not None else str(e)
        store.set_status(task_id, status="failed", phase="report_failed", last_error=msg)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="report_failed", last_error=f"重跑 AutoReport 异常: {e}")


def _rerun_automl_thread(task_id: str) -> None:
    task = store.get(task_id)
    gs = get_global_settings()
    _ar_base, mlevolve_base, _report_base, req_timeout = _service_base_urls(gs)
    autorealize_dir, automl_logs_root, automl_workspaces_root, _old_ml_log_dir, _old_ml_ws_dir = _validate_automl_rerun(task)
    run_dir = _resolve_task_run_dir_for_rerun(task)
    try:
        _wait_for_service_ready(mlevolve_base, "AutoML")
    except Exception as e:
        store.set_status(
            task_id,
            status="failed",
            phase="automl_failed",
            last_error=str(e),
        )
        return
    if _direct_mode_enabled(task):
        input_root = Path(task.input_root).expanduser().resolve()
        ok_direct = _prepare_direct_autorealize_output(
            task_id=task_id,
            task=task,
            input_root=input_root,
            run_dir=run_dir,
            autorealize_dir=autorealize_dir,
            clean=True,
        )
        if not ok_direct:
            return
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
    code_model = _selected_model(llm, "autoMlCode")
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
        mlevolve_service_base=mlevolve_base,
        req_timeout=req_timeout,
    )
    if not ok:
        return
    store.set_status(task_id, status="completed", phase="automl_completed")


def _start_direct_automl_thread(task_id: str) -> None:
    try:
        task = store.get(task_id)
        gs = get_global_settings()
        _ar_base, mlevolve_base, _report_base, req_timeout = _service_base_urls(gs)
        input_root, run_dir, autorealize_dir, automl_logs_root, automl_workspaces_root = _validate_direct_automl_start(task)

        # Persist direct mode so later snapshot/rerun/resume paths use the same
        # original-description contract instead of expecting generated AutoRealize outputs.
        if not task.config.auto_realize.direct_automl_from_description:
            updated = task.config.model_copy(deep=True)
            updated.auto_realize.direct_automl_from_description = True
            updated.auto_realize.prefer_original_description = True
            task = TaskModel.model_validate(store.update(task_id, updated).model_dump())

        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            autorealize_dir.mkdir(parents=True, exist_ok=True)
            automl_logs_root.mkdir(parents=True, exist_ok=True)
            automl_workspaces_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            store.set_status(task_id, status="failed", phase="automl_failed", last_error=f"直接启动 AutoML 准备目录失败: {e}")
            return

        store.clear_output_paths(task_id, auto_ml=True)
        store.set_status(
            task_id,
            status="running",
            phase="automl_input_ready",
            run_dir=str(run_dir),
            run_started_at=now_ts(),
            last_error=None,
        )
        ok_direct = _prepare_direct_autorealize_output(
            task_id=task_id,
            task=task,
            input_root=input_root,
            run_dir=run_dir,
            autorealize_dir=autorealize_dir,
            clean=True,
        )
        if not ok_direct:
            return

        run_suffix = time.strftime("%Y%m%d_%H%M%S")
        ml_exp_name, ml_log_dir, ml_ws_dir = _build_automl_paths(
            task,
            automl_logs_root=automl_logs_root,
            automl_workspaces_root=automl_workspaces_root,
            run_suffix=run_suffix,
        )
        try:
            ml_log_dir.mkdir(parents=True, exist_ok=False)
            ml_ws_dir.mkdir(parents=True, exist_ok=False)
        except Exception as e:
            store.set_status(task_id, status="failed", phase="automl_failed", last_error=f"直接启动 AutoML 创建实验目录失败: {e}")
            return

        env = os.environ.copy()
        code_model = _selected_model(gs.llm, "autoMlCode")
        if code_model.get("apiKey"):
            env["DEEPSEEK_API_KEY"] = str(code_model["apiKey"])

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
            mlevolve_service_base=mlevolve_base,
            req_timeout=req_timeout,
        )
        if not ok:
            return
        store.set_status(task_id, status="completed", phase="automl_completed", run_dir=str(run_dir), last_error=None)
    except HTTPException as e:
        detail = getattr(e, "detail", None)
        msg = str(detail) if detail is not None else str(e)
        store.set_status(task_id, status="failed", phase="automl_failed", last_error=msg)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="automl_failed", last_error=f"直接启动 AutoML 异常: {e}")


def _resume_task_thread(task_id: str) -> None:
    task = store.get(task_id)
    if task.status == "running":
        store.set_status(task_id, status="failed", phase="resume_failed", last_error="任务当前仍在运行，无法继续")
        return

    gs = get_global_settings()
    ar_base, mlevolve_base, report_base, req_timeout = _service_base_urls(gs)

    if not task.input_root.strip() or not task.output_root.strip():
        store.set_status(task_id, status="failed", phase="resume_failed", last_error="缺少输入或输出目录配置，无法继续")
        return

    input_root = Path(task.input_root).expanduser().resolve()
    output_root = resolve_output_root(task.output_root)
    layout = _task_layout(task, output_root)
    run_dir = layout["task_root"]
    autorealize_dir = layout["autorealize_dir"]
    automl_root = layout["automl_root"]
    automl_logs_root = layout["automl_logs_root"]
    automl_workspaces_root = layout["automl_workspaces_root"]
    report_dir = layout["report_dir"]

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        autorealize_dir.mkdir(parents=True, exist_ok=True)
        automl_logs_root.mkdir(parents=True, exist_ok=True)
        automl_workspaces_root.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        store.set_status(task_id, status="failed", phase="resume_failed", last_error=f"继续任务准备目录失败: {e}")
        return

    env = os.environ.copy()
    llm = gs.llm
    code_model = _selected_model(llm, "autoMlCode")
    if code_model.get("apiKey"):
        env["DEEPSEEK_API_KEY"] = str(code_model["apiKey"])

    # Resume strategy:
    # 1) If AutoRealize outputs are not complete, rerun AutoRealize.
    # 2) If AutoML disabled, finish.
    # 3) If AutoML outputs exist, continue AutoML in-place with same exp_name.
    # 4) Else start a new AutoML run.
    require_sample = _sample_submission_required(
        autorealize_dir,
        task.config.auto_realize.generate_sample_submission,
    )
    if not _autorealize_outputs_ready(autorealize_dir, require_sample_submission=require_sample):
        if _direct_mode_enabled(task):
            ok_ar = _prepare_direct_autorealize_output(
                task_id=task_id,
                task=task,
                input_root=input_root,
                run_dir=run_dir,
                autorealize_dir=autorealize_dir,
                clean=False,
            )
        else:
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

    if task.phase == "report_failed":
        existing_log_dir = Path(task.auto_ml_log_dir).expanduser().resolve() if task.auto_ml_log_dir else None
        existing_ws_dir = Path(task.auto_ml_workspace_dir).expanduser().resolve() if task.auto_ml_workspace_dir else None
        if existing_log_dir is not None and existing_log_dir.exists():
            ok_report = _run_report_stage(
                task_id=task_id,
                task=task,
                gs=gs,
                autorealize_dir=autorealize_dir,
                automl_root=automl_root,
                ml_log_dir=existing_log_dir,
                ml_ws_dir=existing_ws_dir if existing_ws_dir and existing_ws_dir.exists() else None,
                report_dir=report_dir,
                report_base=report_base,
                req_timeout=req_timeout,
            )
            if not ok_report:
                return
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
        mlevolve_service_base=mlevolve_base,
        req_timeout=req_timeout,
        resume_existing=can_resume_automl,
    )
    if not ok:
        return
    ok_report = _run_report_stage(
        task_id=task_id,
        task=task,
        gs=gs,
        autorealize_dir=autorealize_dir,
        automl_root=automl_root,
        ml_log_dir=ml_log_dir,
        ml_ws_dir=ml_ws_dir,
        report_dir=report_dir,
        report_base=report_base,
        req_timeout=req_timeout,
    )
    if not ok_report:
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


def _parse_log_events_tail_local(log_path: Path, limit: int = 400) -> list[dict[str, Any]]:
    pattern = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+(?P<level>[A-Z]+):\s+(?P<msg>.*)$")
    rows: list[dict[str, Any]] = []
    for line in safe_read_tail_lines(log_path, limit=limit, byte_limit=768_000):
        text = line.strip()
        if not text:
            continue
        match = pattern.match(text)
        if match:
            rows.append(
                {
                    "ts": match.group("ts"),
                    "component": log_path.name,
                    "event": match.group("level"),
                    "message": match.group("msg"),
                }
            )
        else:
            rows.append({"ts": "", "component": log_path.name, "event": "INFO", "message": text})
    return rows[-limit:]


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
        _add(resolve_output_root(task.output_root) / task.task_name)
    if task.task_name:
        _add(PROJECT_RUNS_DIR / task.task_name)
        _add(DEFAULT_RUNS_DIR / task.task_name)
        _add(LEGACY_BACKEND_RUNS_DIR / task.task_name)
        _add(LEGACY_AUTOREALIZE_RUNS_DIR / task.task_name)

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
    out["question_investigation_report"] = safe_read_json(report_dir / "question_investigation_report.json", {})
    out["task_definition_report"] = safe_read_json(report_dir / "task_definition_report.json", {})
    out["submission_report"] = safe_read_json(report_dir / "submission_report.json", {})
    out["evaluation_contract_report"] = safe_read_json(report_dir / "evaluation_contract_report.json", {})
    out["main_task_protocol"] = safe_read_json(report_dir / "main_task_protocol.json", {})
    out["automl_context_pack"] = safe_read_json(report_dir / "automl_context_pack.json", {})
    out["authoritative_task_memory"] = safe_read_json(report_dir / "authoritative_task_memory.json", {})
    out["agent_context_pack"] = safe_read_json(report_dir / "agent_context_pack.json", {})
    out["retrieved_knowledge"] = safe_read_json(report_dir / "retrieved_knowledge.json", [])
    out["events"] = _parse_jsonl_local(report_dir / "event_stream.jsonl", limit=400)
    dir_tree_file = report_dir / "directory_tree.txt"
    out["directory_tree_text"] = dir_tree_file.read_text(encoding="utf-8", errors="ignore") if dir_tree_file.exists() else ""
    out["output_tree_text"] = _render_directory_tree_local(autorealize_dir)
    desc_file = autorealize_dir / "description.md"
    out["description_text"] = desc_file.read_text(encoding="utf-8", errors="ignore") if desc_file.exists() else ""
    data_desc_file = report_dir / "data_description.md"
    out["data_description_text"] = data_desc_file.read_text(encoding="utf-8", errors="ignore") if data_desc_file.exists() else ""
    automl_context_file = report_dir / "automl_context.md"
    out["automl_context_text"] = automl_context_file.read_text(encoding="utf-8", errors="ignore") if automl_context_file.exists() else ""
    original_file = report_dir / "original_requirements.txt"
    out["original_requirements_text"] = original_file.read_text(encoding="utf-8", errors="ignore") if original_file.exists() else ""
    out["file_cognition_index"] = _load_file_cognition_index_local(report_dir)
    return out


def _automl_run_identity(path: Path) -> str:
    """Normalize service-wrapper and MLEvolve artifact directory names."""
    name = path.name
    wrapper = re.match(r"^(\d{8})_(\d{6})_(.+)$", name)
    if wrapper:
        return f"{wrapper.group(1)}{wrapper.group(2)}|{wrapper.group(3)}"
    engine = re.match(r"^(\d{14})_(.+)$", name)
    if engine:
        return f"{engine.group(1)}|{engine.group(2)}"
    return ""


def _automl_log_dir_score(path: Path) -> tuple[int, float]:
    """Prefer actual engine artifacts over service/frontend wrapper folders."""
    score = 0
    if (path / "journal.json").is_file():
        score += 1000
    if (path / "filtered_journal.json").is_file():
        score += 700
    if (path / "run_status.json").is_file():
        score += 300
    if (path / "MLEvolve.log").is_file():
        score += 200
    if (path / "pending_nodes.json").is_file():
        score += 100
    if (path / "best_solution.py").is_file():
        score += 80
    if (path / "_service_stdout.log").is_file() or (path / "_frontend_stdout.log").is_file():
        score += 10
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    return score, modified


def _automl_log_candidates(task: TaskModel) -> tuple[list[Path], Path | None]:
    preferred: Path | None = None
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            return
        key = str(resolved)
        if key in seen or not resolved.exists() or not resolved.is_dir():
            return
        seen.add(key)
        candidates.append(resolved)

    if task.auto_ml_log_dir:
        preferred = Path(task.auto_ml_log_dir).expanduser().resolve()
        _add(preferred)
        if preferred.parent.is_dir():
            for child in preferred.parent.iterdir():
                if child.is_dir():
                    _add(child)
    for run_dir in _candidate_task_run_dirs(task):
        logs_root = run_dir / "automl" / "logs"
        if not logs_root.exists() or not logs_root.is_dir():
            continue
        for child in logs_root.iterdir():
            if child.is_dir():
                _add(child)
    return candidates, preferred


def _pick_local_automl_log_dir(task: TaskModel) -> Path | None:
    candidates, preferred = _automl_log_candidates(task)
    if not candidates:
        return None

    preferred_identity = _automl_run_identity(preferred) if preferred is not None else ""
    preferred_parent = preferred.parent if preferred is not None else None
    matching = [
        candidate
        for candidate in candidates
        if (
            preferred_identity
            and preferred_parent is not None
            and candidate.parent == preferred_parent
            and _automl_run_identity(candidate) == preferred_identity
        )
    ]
    # A real MLEvolve directory has at least a journal, run log, pending state,
    # or run status. Wrapper folders contain only service/frontend tail logs.
    meaningful = [candidate for candidate in matching if _automl_log_dir_score(candidate)[0] >= 100]
    if meaningful:
        return max(meaningful, key=_automl_log_dir_score)
    if preferred is not None and preferred.exists() and preferred.is_dir():
        return preferred

    meaningful = [candidate for candidate in candidates if _automl_log_dir_score(candidate)[0] >= 100]
    if meaningful:
        return max(meaningful, key=_automl_log_dir_score)
    return max(candidates, key=_automl_log_dir_score)


def _pick_local_automl_workspace_dir(task: TaskModel, exp_name: str | None) -> Path | None:
    preferred = (
        Path(task.auto_ml_workspace_dir).expanduser().resolve()
        if task.auto_ml_workspace_dir
        else None
    )
    for run_dir in _candidate_task_run_dirs(task):
        ws_root = run_dir / "automl" / "workspaces"
        if not ws_root.exists() or not ws_root.is_dir():
            continue
        if exp_name:
            p = ws_root / exp_name
            if p.exists() and p.is_dir():
                return p
        if preferred is not None:
            preferred_identity = _automl_run_identity(preferred)
            if preferred_identity:
                matching = [
                    candidate
                    for candidate in ws_root.iterdir()
                    if candidate.is_dir() and _automl_run_identity(candidate) == preferred_identity
                ]
                if matching:
                    matching.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    return matching[0]
    if preferred is not None and preferred.exists() and preferred.is_dir():
        return preferred
    for run_dir in _candidate_task_run_dirs(task):
        ws_root = run_dir / "automl" / "workspaces"
        if not ws_root.exists() or not ws_root.is_dir():
            continue
        candidates = [x for x in ws_root.iterdir() if x.is_dir()]
        if not candidates:
            continue
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    return None


def _persist_resolved_automl_paths(task_id: str) -> None:
    """Replace service-wrapper paths with the directories containing artifacts."""
    task = store.get(task_id)
    log_dir = _pick_local_automl_log_dir(task)
    if log_dir is None:
        return
    workspace_dir = _pick_local_automl_workspace_dir(task, exp_name=log_dir.name)
    if str(log_dir) == str(task.auto_ml_log_dir or "") and (
        workspace_dir is None or str(workspace_dir) == str(task.auto_ml_workspace_dir or "")
    ):
        return
    store.set_status(
        task_id,
        status=task.status,
        phase=task.phase,
        auto_ml_log_dir=str(log_dir),
        auto_ml_workspace_dir=str(workspace_dir) if workspace_dir is not None else None,
    )


def _build_local_automl_snapshot(task: TaskModel) -> dict[str, Any]:
    log_dir = _pick_local_automl_log_dir(task)
    if log_dir is None:
        return {}
    ws_dir = _pick_local_automl_workspace_dir(task, exp_name=log_dir.name)
    # `filtered_journal.json` is usually the best-path projection, not the
    # whole search tree. Prefer the full journal while keeping a size guard so
    # huge historical runs cannot block the UI polling endpoint.
    journal_source = ""
    journal = {}
    journal_path = log_dir / "journal.json"
    filtered_journal_path = log_dir / "filtered_journal.json"
    try:
        if journal_path.exists() and journal_path.stat().st_size <= 150 * 1024 * 1024:
            journal = safe_read_json(journal_path, {})
            if isinstance(journal, dict) and journal:
                journal_source = "journal"
    except Exception:
        journal = {}
    if not isinstance(journal, dict) or not journal:
        journal = safe_read_json(filtered_journal_path, {})
        if isinstance(journal, dict) and journal:
            journal_source = "filtered_journal"
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
            llm_insight = n.get("llm_insight")
            parser_analysis = n.get("parser_analysis") or n.get("analysis")
            nodes.append(
                {
                    "id": node_id,
                    "parent_id": node2parent.get(node_id),
                    "stage": n.get("stage"),
                    "plan": n.get("plan"),
                    "code": n.get("code"),
                    "result": result,
                    "insight": llm_insight or n.get("analysis"),
                    "llm_insight": llm_insight,
                    "parser_analysis": parser_analysis,
                    "decision_signals": n.get("decision_signals"),
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
                    "status": n.get("status"),
                }
            )
    journal_node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    pending_nodes = [
        node for node in read_mlevolve_pending_nodes(log_dir)
        if str(node.get("id")) not in journal_node_ids
    ]
    engine = _automl_engine(task)
    out: dict[str, Any] = {
        "engine": engine,
        "log_dir": str(log_dir),
        "workspace_dir": str(ws_dir) if ws_dir is not None else "",
        "events": _parse_jsonl_local(log_dir / "event_stream.jsonl", limit=400)
        or _parse_log_events_tail_local(log_dir / "MLEvolve.log", limit=400),
        "nodes": nodes,
        "pending_nodes": pending_nodes,
        "best_node_id": best_id,
        "journal_source": journal_source,
        "run_status": safe_read_json(log_dir / "run_status.json", {}),
        "resource_usage": safe_read_json(log_dir / "resource_usage.json", {}),
        "ml_log": safe_read_text_tail(log_dir / "MLEvolve.log", limit=60000),
        "verbose_log": safe_read_text_tail(log_dir / "MLEvolve.verbose.log", limit=60000),
        "frontend_stdout": safe_read_text_tail(log_dir / "_frontend_stdout.log", limit=60000),
        "frontend_stderr": safe_read_text_tail(log_dir / "_frontend_stderr.log", limit=60000),
        "service_stdout": safe_read_text_tail(log_dir / "_service_stdout.log", limit=60000),
        "service_stderr": safe_read_text_tail(log_dir / "_service_stderr.log", limit=60000),
    }
    if ws_dir is not None:
        best_solution_code = ws_dir / "best_solution" / "solution.py"
        best_metric_text = ws_dir / "best_solution" / "metric.txt"
        out["best_solution_code"] = safe_read_text_tail(best_solution_code, limit=200000)
        out["best_metric_text"] = safe_read_text_tail(best_metric_text, limit=20000)
    return out


def _pick_local_report_dir(task: TaskModel) -> Path | None:
    candidates: list[Path] = []
    if task.report_dir:
        candidates.append(Path(task.report_dir).expanduser().resolve())
    if task.run_dir:
        candidates.append(Path(task.run_dir).expanduser().resolve() / "report")
    try:
        candidates.append(_task_layout(task)["report_dir"])
    except Exception:
        pass
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.exists() and path.is_dir():
            return path
    return None


def _build_local_report_snapshot(task: TaskModel) -> dict[str, Any]:
    report_dir = _pick_local_report_dir(task)
    if report_dir is None:
        return {}
    resolved_path = report_dir / "resolved_config.yaml"
    if not resolved_path.exists():
        resolved_path = next(iter(sorted(report_dir.glob("*config*.yaml"))), resolved_path)
    resolved = safe_read_yaml(resolved_path, {})
    if not resolved:
        resolved = safe_read_json(report_dir / "resolved_config.json", {})
    runtime = dict(resolved.get("runtime") or {})
    generation = dict(resolved.get("generation") or {})
    state_name = str(runtime.get("current_state_filename") or "current_state.json")
    event_name = str(runtime.get("event_stream_filename") or "event_stream.jsonl")
    event_limit = max(1, int(runtime.get("snapshot_event_limit") or 500))
    text_tail = max(0, int(runtime.get("snapshot_text_tail_chars") or 60000))
    report_json_name = str(generation.get("report_json_filename") or "report.json")
    report_md_name = str(generation.get("report_markdown_filename") or "report.md")
    return {
        "output_dir": str(report_dir),
        "current_state": safe_read_json(report_dir / state_name, {}),
        "events": _parse_jsonl_local(report_dir / event_name, limit=event_limit),
        "report": safe_read_json(report_dir / report_json_name, {}),
        "report_markdown": (report_dir / report_md_name).read_text(encoding="utf-8", errors="ignore") if (report_dir / report_md_name).exists() else "",
        "resolved_config": resolved,
        "stdout": safe_read_text_tail(report_dir / "_service_stdout.log", limit=text_tail),
        "stderr": safe_read_text_tail(report_dir / "_service_stderr.log", limit=text_tail),
    }


def _read_autorealize_snapshot(task: TaskModel) -> dict[str, Any]:
    if not task.run_dir:
        return {}
    gs = get_global_settings()
    ar_base, _mlevolve_base, _report_base, req_timeout = _service_base_urls(gs)
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
    _ar_base, mlevolve_base, _report_base, req_timeout = _service_base_urls(gs)
    engine = _automl_engine(task)
    local = _build_local_automl_snapshot(task)
    if local:
        local["snapshot_source"] = "local"
        return local
    payload = {
        "log_dir": str(task.auto_ml_log_dir or ""),
        "workspace_dir": str(task.auto_ml_workspace_dir or ""),
        "run_dir": str(task.run_dir or ""),
        "task_name": str(task.task_name or ""),
    }
    try:
        remote = _json_post(mlevolve_base, "/snapshot", payload, timeout_secs=min(req_timeout, 5))
        remote["snapshot_source"] = "remote"
        return remote
    except Exception:
        raise


def _read_report_snapshot(task: TaskModel) -> dict[str, Any]:
    gs = get_global_settings()
    _ar_base, _mlevolve_base, report_base, req_timeout = _service_base_urls(gs)
    report_dir = task.report_dir or (str(Path(task.run_dir).expanduser().resolve() / "report") if task.run_dir else "")
    if not report_dir:
        return {}
    try:
        return _json_post(report_base, "/snapshot", {"output_dir": report_dir}, timeout_secs=req_timeout)
    except Exception:
        local = _build_local_report_snapshot(task)
        if local:
            return local
        raise


def _pick_dir_tkinter(initial_path: str, title: str) -> tuple[str | None, str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update_idletasks()
        selected = filedialog.askdirectory(
            parent=root,
            title=title or "Select Directory",
            initialdir=initial_path or None,
            mustexist=True,
        )
    finally:
        root.destroy()
    if selected:
        return selected, "selected"
    return None, "cancelled"


def _escape_applescript_text(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _pick_dir_macos_osascript(initial_path: str, title: str) -> tuple[str | None, str]:
    if not shutil.which("osascript"):
        return None, "unavailable"
    prompt = _escape_applescript_text(title or "Select Directory")
    lines = [
        'tell application "System Events" to activate',
        "delay 0.15",
    ]
    if initial_path and Path(initial_path).exists():
        initial = _escape_applescript_text(str(Path(initial_path).expanduser().resolve()))
        lines.append(
            f'set theFolder to choose folder with prompt "{prompt}" default location POSIX file "{initial}"'
        )
    else:
        lines.append(f'set theFolder to choose folder with prompt "{prompt}"')
    lines.append("POSIX path of theFolder")
    proc = subprocess.run(
        ["osascript", "-e", "\n".join(lines)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode == 0:
        out = proc.stdout.strip()
        return (out, "selected") if out else (None, "cancelled")
    error = (proc.stderr or "").lower()
    if proc.returncode == 1 or "user canceled" in error or "-128" in error:
        return None, "cancelled"
    return None, "unavailable"


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


def _windows_dialog_owner_powershell() -> str:
    return (
        "Add-Type -TypeDefinition @'\n"
        "using System;\n"
        "using System.Runtime.InteropServices;\n"
        "using System.Windows.Forms;\n"
        "public sealed class AutoDecisionDialogOwner : IWin32Window {\n"
        "  public IntPtr Handle { get; private set; }\n"
        "  public AutoDecisionDialogOwner(IntPtr handle) { Handle = handle; }\n"
        "  [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();\n"
        "  [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);\n"
        "}\n"
        "'@ -ReferencedAssemblies 'System.Windows.Forms.dll';\n"
        "$ownerHandle=[AutoDecisionDialogOwner]::GetForegroundWindow();\n"
        "if($ownerHandle -ne [IntPtr]::Zero){[AutoDecisionDialogOwner]::SetForegroundWindow($ownerHandle)|Out-Null};\n"
        "$owner=[AutoDecisionDialogOwner]::new($ownerHandle);\n"
    )


def _pick_dir_windows_shell(title: str) -> tuple[str | None, str]:
    desc = title.replace("'", " ").replace('"', " ")
    ps = (
        "$ErrorActionPreference='Stop';"
        "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');\n"
        + _windows_dialog_owner_powershell()
        + "$shell=New-Object -ComObject Shell.Application;"
        + f"$folder=$shell.BrowseForFolder($ownerHandle.ToInt64(),'{desc}',0x41,0);"
        + "if($folder -ne $null -and $folder.Self -and $folder.Self.Path){"
        + "  Write-Output ('__PICKED_PATH__' + $folder.Self.Path)"
        + "}else{"
        + "  Write-Output '__CANCELLED__'"
        + "}"
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
        + _windows_dialog_owner_powershell()
        + "$d=New-Object System.Windows.Forms.OpenFileDialog;"
        + f"$d.Title='{safe_title}';"
        + f"$d.InitialDirectory='{init_ps}';"
        + "$d.CheckFileExists=$false;"
        + "$d.CheckPathExists=$true;"
        + "$d.ValidateNames=$false;"
        + "$d.Multiselect=$false;"
        + "$d.RestoreDirectory=$true;"
        + "$d.DereferenceLinks=$true;"
        + "$d.AutoUpgradeEnabled=$true;"
        + "$d.Filter='文件夹|*.autodecision_folder';"
        + "$d.FileName='选择此文件夹';"
        + "$r=if($ownerHandle -ne [IntPtr]::Zero){$d.ShowDialog($owner)}else{$d.ShowDialog()};"
        + "if($r -eq [System.Windows.Forms.DialogResult]::OK -and $d.FileName){"
        + "  Write-Output ('__PICKED_PATH__' + $d.FileName)"
        + "}else{"
        + "  Write-Output '__CANCELLED__'"
        + "}"
    )
    rc, out, _err = _run_powershell_hidden(ps, timeout=900)
    if rc != 0:
        return None, "unavailable"
    value, status = _extract_picker_output(out)
    if status == "selected" and value:
        return value, "selected"
    return None, "cancelled"


def _linux_graphical_session_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _pick_dir_linux_zenity(initial_path: str, title: str) -> tuple[str | None, str]:
    executable = shutil.which("zenity")
    if not executable or not _linux_graphical_session_available():
        return None, "unavailable"
    cmd = [executable, "--file-selection", "--directory", "--title", title]
    if initial_path and Path(initial_path).exists():
        cmd.extend(["--filename", initial_path if initial_path.endswith("/") else f"{initial_path}/"])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode == 0:
        out = proc.stdout.strip()
        return (out, "selected") if out else (None, "cancelled")
    if proc.returncode == 1:
        return None, "cancelled"
    return None, "unavailable"


def _pick_dir_linux_kdialog(initial_path: str, title: str) -> tuple[str | None, str]:
    executable = shutil.which("kdialog")
    if not executable or not _linux_graphical_session_available():
        return None, "unavailable"
    start = initial_path if initial_path and Path(initial_path).exists() else str(Path.home())
    proc = subprocess.run(
        [executable, "--getexistingdirectory", start, "--title", title],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode == 0:
        out = proc.stdout.strip()
        return (out, "selected") if out else (None, "cancelled")
    if proc.returncode == 1:
        return None, "cancelled"
    return None, "unavailable"


def _pick_directory_native(initial_path: str, title: str) -> tuple[str | None, str, str]:
    # 1) OS-specific first (more stable in service/threaded contexts)
    if sys.platform == "darwin":
        try:
            picked, status = _pick_dir_macos_osascript(initial_path=initial_path, title=title)
            if picked:
                return picked, "osascript", "selected"
        except Exception:
            status = "unavailable"
        return None, "osascript", status
    elif os.name == "nt":
        picked, status = _pick_dir_windows_modern(initial_path=initial_path, title=title)
        if picked:
            return picked, "windows-explorer-folder-picker", "selected"
        if status == "cancelled":
            return None, "windows-explorer-folder-picker", "cancelled"
        # fallback on shell picker only when primary native API unavailable
        picked2, status2 = _pick_dir_windows_shell(title=title)
        if picked2:
            return picked2, "windows-shell-browse", "selected"
        if status2 == "cancelled":
            return None, "windows-shell-browse", "cancelled"
        return None, "none", "cancelled_or_unavailable"
    else:
        try:
            picked, status = _pick_dir_linux_zenity(initial_path=initial_path, title=title)
            if picked:
                return picked, "zenity", "selected"
            if status == "cancelled":
                return None, "zenity", "cancelled"
        except Exception:
            pass
        try:
            picked, status = _pick_dir_linux_kdialog(initial_path=initial_path, title=title)
            if picked:
                return picked, "kdialog", "selected"
            if status == "cancelled":
                return None, "kdialog", "cancelled"
        except Exception:
            pass

    # 2) tkinter fallback (non-Windows only)
    if os.name != "nt" and (sys.platform == "darwin" or _linux_graphical_session_available()):
        try:
            picked, status = _pick_dir_tkinter(initial_path=initial_path, title=title)
            if picked:
                return picked, "tkinter", "selected"
            if status == "cancelled":
                return None, "tkinter", "cancelled"
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
    if lowered_name in {"select folder", "[select this folder]", "选择此文件夹"}:
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

    def add_env_python(env_dir: Path, source: str) -> None:
        exe_dirs = [env_dir / "Scripts", env_dir] if os.name == "nt" else [env_dir / "bin"]
        for exe_dir in exe_dirs:
            for n in names:
                exe = exe_dir / n
                if exe.exists():
                    out.append((exe, source))
                    return

    def add_root(root: Path, roots: list[Path]) -> None:
        try:
            resolved = root.expanduser().resolve()
        except Exception:
            resolved = root
        if str(resolved).lower() not in {str(x).lower() for x in roots}:
            roots.append(resolved)

    conda_exe = os.environ.get("CONDA_EXE", "").strip()
    conda_cmds: list[str] = []
    if conda_exe:
        conda_cmds.append(conda_exe)
    path_conda = shutil.which("conda")
    if path_conda:
        conda_cmds.append(path_conda)

    if os.name == "nt":
        program_data = os.environ.get("ProgramData", r"C:\ProgramData")
        for root_name in ("anaconda3", "miniconda3", "mambaforge", "miniforge3"):
            for candidate in (
                Path(program_data) / root_name / "Scripts" / "conda.exe",
                Path(program_data) / root_name / "condabin" / "conda.bat",
            ):
                if candidate.exists():
                    conda_cmds.append(str(candidate))

    seen_cmds: set[str] = set()
    for cmd in conda_cmds:
        cmd_key = cmd.lower()
        if cmd_key in seen_cmds:
            continue
        seen_cmds.add(cmd_key)
        try:
            proc = subprocess.run(
                [cmd, "info", "--envs", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                payload = json.loads(proc.stdout)
                for env_dir in payload.get("envs", []):
                    add_env_python(Path(env_dir), "conda")
        except Exception:
            pass

    home = Path.home()
    conda_roots: list[Path] = []
    for root in (home / "anaconda3", home / "miniconda3", home / "mambaforge", home / "miniforge3", home / ".conda"):
        add_root(root, conda_roots)
    if os.name == "nt":
        user = os.environ.get("USERPROFILE", "")
        if user:
            for root in (
                Path(user) / "anaconda3",
                Path(user) / "miniconda3",
                Path(user) / "mambaforge",
                Path(user) / "miniforge3",
                Path(user) / ".conda",
            ):
                add_root(root, conda_roots)
        program_data = os.environ.get("ProgramData", r"C:\ProgramData")
        for root in (
            Path(program_data) / "anaconda3",
            Path(program_data) / "miniconda3",
            Path(program_data) / "mambaforge",
            Path(program_data) / "miniforge3",
        ):
            add_root(root, conda_roots)
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            for root in (
                Path(local_app_data) / "anaconda3",
                Path(local_app_data) / "miniconda3",
            ):
                add_root(root, conda_roots)
    for root in conda_roots:
        if not root.exists():
            continue
        base_exe = root / ("python.exe" if os.name == "nt" else "bin/python")
        if base_exe.exists():
            out.append((base_exe, "conda-base"))
        envs_dir = root / "envs"
        if not envs_dir.exists():
            continue
        for env_dir in envs_dir.iterdir():
            if not env_dir.is_dir():
                continue
            add_env_python(env_dir, "conda")
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
    return _redact_global_settings_for_client(get_global_settings().model_dump())


@app.put("/api/settings/global")
def put_settings(payload: GlobalSettingsModel) -> dict[str, str]:
    save_global_settings(payload)
    return {"status": "ok"}


@app.get("/api/resources/inventory")
def get_resource_inventory() -> dict[str, Any]:
    gs = get_global_settings()
    _autorealize_base, mlevolve_base, _report_base, request_timeout = _service_base_urls(gs)
    python_executable = str(gs.python.get("executable") or "python").strip() or "python"
    query = urllib.parse.urlencode({"python_executable": python_executable})
    try:
        return _json_get(
            mlevolve_base,
            f"/resources/inventory?{query}",
            timeout_secs=max(30, request_timeout),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MLEvolve resource detection failed: {exc}") from exc


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


@app.post("/api/tasks/rerun-autorealize")
def rerun_autorealize(payload: RerunAutoRealizeRequest) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for rerun autorealize")
    task = store.get(payload.task_id)
    _validate_autorealize_rerun(task)
    thread = threading.Thread(target=_rerun_autorealize_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id, "mode": "autorealize_only"}


@app.post("/api/tasks/rerun-automl")
def rerun_automl(payload: RerunAutoMLRequest) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for rerun automl")
    task = store.get(payload.task_id)
    _validate_automl_rerun(task)
    gs = get_global_settings()
    _ar_base, mlevolve_base, _report_base, _req_timeout = _service_base_urls(gs)
    try:
        _wait_for_service_ready(mlevolve_base, "AutoML")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    thread = threading.Thread(target=_rerun_automl_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id, "mode": "automl_only"}


@app.post("/api/tasks/start-automl")
def start_direct_automl(payload: StartDirectAutoMLRequest) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for direct automl start")
    task = store.get(payload.task_id)
    _validate_direct_automl_start(task)
    thread = threading.Thread(target=_start_direct_automl_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id, "mode": "direct_automl"}


@app.post("/api/tasks/rerun-autoreport")
@app.post("/api/tasks/rerun-report")
def rerun_autoreport(payload: RerunAutoReportRequest) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for rerun autoreport")
    task = store.get(payload.task_id)
    _validate_autoreport_rerun(task)
    thread = threading.Thread(target=_rerun_autoreport_thread, args=(payload.task_id,), daemon=True)
    thread.start()
    return {"status": "started", "task_id": payload.task_id, "mode": "autoreport_only"}


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
    report: dict[str, Any] = {}
    snapshot_errors: dict[str, str] = {}
    try:
        ar = _read_autorealize_snapshot(task)
    except Exception as e:
        snapshot_errors["auto_realize"] = str(e)
    try:
        ml = _read_automl_snapshot(task)
    except Exception as e:
        snapshot_errors["auto_ml"] = str(e)
    try:
        report = _read_report_snapshot(task)
    except Exception as e:
        snapshot_errors["auto_report"] = str(e)
    return {
        "task": task.model_dump(),
        "auto_realize": ar,
        "auto_ml": ml,
        "auto_report": report,
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
    if not DIRECTORY_PICKER_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "path": None,
            "method": "none",
            "reason": "picker_busy",
            "raw_path": None,
            "platform": sys.platform,
        }
    try:
        picked, method, status = _pick_directory_native(initial_path=initial_path, title=title)
    finally:
        DIRECTORY_PICKER_LOCK.release()
    normalized = _normalize_selected_directory(picked or "")
    if normalized:
        return {
            "ok": True,
            "path": normalized,
            "method": method,
            "reason": "selected",
            "raw_path": picked,
            "platform": sys.platform,
        }
    reason = status
    if status == "selected" and picked:
        reason = "invalid_selection"
    return {
        "ok": False,
        "path": None,
        "method": method,
        "reason": reason,
        "raw_path": picked,
        "platform": sys.platform,
    }


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


from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from autoreport.config import config_schema, load_config


DEFAULT_WORKDIR = Path(__file__).resolve().parent


class EvidencePathModel(BaseModel):
    label: str
    path: str
    kind: str = "auto"
    required: bool = False


class StartReportRequest(BaseModel):
    task_id: str = ""
    task_name: str = "autoreport_task"
    output_dir: str
    evidence_paths: list[EvidencePathModel] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    config_path: str = ""
    python_executable: str = "python"
    working_dir: str = ""
    env_overrides: dict[str, str] = Field(default_factory=dict)


class StopRequest(BaseModel):
    job_id: str


class SnapshotRequest(BaseModel):
    output_dir: str


@dataclass
class Job:
    job_id: str
    task_id: str
    output_dir: str
    status: str = "created"
    process: subprocess.Popen[str] | None = None
    exit_code: int | None = None
    last_error: str | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def create(self, task_id: str, output_dir: str) -> Job:
        with self._lock:
            job = Job(job_id=uuid.uuid4().hex, task_id=task_id, output_dir=output_dir)
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise HTTPException(status_code=404, detail="job not found")
            return self._jobs[job_id]

    def set_process(self, job_id: str, proc: subprocess.Popen[str]) -> None:
        with self._lock:
            self._jobs[job_id].process = proc
            self._jobs[job_id].status = "running"

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in kwargs.items():
                setattr(job, key, value)

    def status(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        return {
            "job_id": job.job_id,
            "task_id": job.task_id,
            "output_dir": job.output_dir,
            "status": job.status,
            "exit_code": job.exit_code,
            "last_error": job.last_error,
            "stdout_tail": job.stdout_tail,
            "stderr_tail": job.stderr_tail,
        }


store = JobStore()
app = FastAPI(title="AutoReport API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _tail(text: str, limit: int = 120000) -> str:
    return text[-limit:] if text else ""


def _safe_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig", errors="ignore"))
    except Exception:
        return default


def _parse_jsonl(path: Path, limit: int = 400) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _build_snapshot(output_dir_raw: str) -> dict[str, Any]:
    out_dir = Path(output_dir_raw).expanduser().resolve()
    return {
        "output_dir": str(out_dir),
        "current_state": _safe_read_json(out_dir / "current_state.json", {}),
        "events": _parse_jsonl(out_dir / "event_stream.jsonl", limit=500),
        "report": _safe_read_json(out_dir / "report.json", {}),
        "report_markdown": (out_dir / "report.md").read_text(encoding="utf-8", errors="ignore") if (out_dir / "report.md").exists() else "",
        "resolved_config": _safe_read_json(out_dir / "resolved_config.json", {}),
        "stdout": (out_dir / "_service_stdout.log").read_text(encoding="utf-8", errors="ignore")[-60000:] if (out_dir / "_service_stdout.log").exists() else "",
        "stderr": (out_dir / "_service_stderr.log").read_text(encoding="utf-8", errors="ignore")[-60000:] if (out_dir / "_service_stderr.log").exists() else "",
    }


def _write_generated_config(req: StartReportRequest) -> Path:
    out_dir = Path(req.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if req.config_path.strip():
        return Path(req.config_path).expanduser().resolve()
    raw = dict(req.config or {})
    raw["task_name"] = req.task_name
    raw["output_dir"] = str(out_dir)
    raw["evidence_paths"] = [item.model_dump() for item in req.evidence_paths]
    raw["use_llm"] = bool(raw.get("use_llm", True))
    path = out_dir / "_service_config.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _validate_llm_start_config(req: StartReportRequest) -> None:
    if req.config_path.strip():
        try:
            cfg = load_config(req.config_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid AutoReport config_path: {exc}") from exc
        raw = {"use_llm": cfg.use_llm, "llm": cfg.llm}
    else:
        raw = dict(req.config or {})

    if not bool(raw.get("use_llm", True)):
        raise HTTPException(status_code=400, detail="AutoReport requires LLM; config.use_llm must be true")
    llm = dict(raw.get("llm") or {})
    model = str(llm.get("model") or llm.get("model_name") or "").strip()
    base_url = str(llm.get("base_url") or llm.get("baseUrl") or "").strip()
    api_key = str(
        llm.get("api_key")
        or llm.get("apiKey")
        or (req.env_overrides or {}).get("DEEPSEEK_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or ""
    ).strip()
    missing = []
    if not model:
        missing.append("llm.model")
    if not base_url:
        missing.append("llm.base_url")
    if not api_key:
        missing.append("llm.api_key")
    if missing:
        raise HTTPException(status_code=400, detail=f"AutoReport LLM config missing: {', '.join(missing)}")


def _run_job(job_id: str, req: StartReportRequest) -> None:
    out_dir = Path(req.output_dir).expanduser().resolve()
    cfg_path = _write_generated_config(req)
    workdir = Path(req.working_dir).expanduser().resolve() if req.working_dir.strip() else DEFAULT_WORKDIR
    cmd = [req.python_executable or "python", "-m", "autoreport.cli", "--config", str(cfg_path)]
    env = os.environ.copy()
    env.update(req.env_overrides or {})
    try:
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **popen_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="failed", last_error=f"start failed: {exc}")
        return
    store.set_process(job_id, proc)
    out, err = proc.communicate()
    exit_code = proc.returncode
    out_dir.mkdir(parents=True, exist_ok=True)
    if out:
        (out_dir / "_service_stdout.log").write_text(_tail(out), encoding="utf-8", errors="ignore")
    if err:
        (out_dir / "_service_stderr.log").write_text(_tail(err), encoding="utf-8", errors="ignore")
    status = "completed" if exit_code == 0 else "failed"
    last_error = None if exit_code == 0 else ((err or out or f"AutoReport exited with code {exit_code}").strip().splitlines()[-1][:300])
    store.update(job_id, status=status, exit_code=exit_code, last_error=last_error, stdout_tail=_tail(out or ""), stderr_tail=_tail(err or ""))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/usage")
def usage() -> dict[str, Any]:
    return {
        "cli": "python -m autoreport.cli --config config.example.json",
        "evidence_arg": "python -m autoreport.cli --task-name demo --output-dir runs/demo/report --evidence autorealize=/path/ar::autorealize --evidence automl=/path/ml::automl",
        "config_schema": config_schema(),
    }


@app.get("/config/schema")
def get_config_schema() -> dict[str, Any]:
    return config_schema()


@app.post("/jobs/start")
def start_job(req: StartReportRequest) -> dict[str, Any]:
    if not req.output_dir.strip():
        raise HTTPException(status_code=400, detail="output_dir is required")
    if not req.config_path.strip() and not req.evidence_paths:
        raise HTTPException(status_code=400, detail="evidence_paths or config_path is required")
    _validate_llm_start_config(req)
    job = store.create(req.task_id, str(Path(req.output_dir).expanduser().resolve()))
    thread = threading.Thread(target=_run_job, args=(job.job_id, req), daemon=True)
    thread.start()
    return {"job_id": job.job_id, "status": "started", "output_dir": job.output_dir}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    return store.status(job_id)


@app.post("/jobs/stop")
def stop_job(req: StopRequest) -> dict[str, Any]:
    job = store.get(req.job_id)
    proc = job.process
    if proc is None or proc.poll() is not None:
        return {"status": "not_running", "job_id": req.job_id}
    try:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    store.update(req.job_id, status="stopped", last_error="stopped by user")
    return {"status": "stopping", "job_id": req.job_id}


@app.post("/snapshot")
def snapshot(req: SnapshotRequest) -> dict[str, Any]:
    try:
        return _build_snapshot(req.output_dir)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"snapshot failed: {exc}")

"""Local product APIs. Reads delivery evidence without importing generated code."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pydantic import Field
from starlette.background import BackgroundTask


class ModelProbe(BaseModel):
    role: str
    capability: Literal["text", "image"] = "text"


# Raw local inference data does not enter the planning model's context.
MAX_TRIAL_INPUT_BYTES = 16 * 1024**2


class SolutionTrial(BaseModel):
    input_mode: str = "json"
    data_json: str = Field(default="", max_length=MAX_TRIAL_INPUT_BYTES)
    csv_path: str = ""
    timeout_seconds: int = Field(default=30, ge=1, le=120)


TRIAL_LOCK = threading.Lock()
CONTRACT_FILES = (
    "description.md", "task_requirements.md", "validation_protocol.md", "autorealize_context.md",
    "realize_report/main_task_protocol.json", "realize_report/data_access_protocol.json",
    "realize_report/automl_context_pack.json", "realize_report/automl_context.md",
    "realize_report/evaluation_contract_report.json", "realize_report/task_definition_report.json",
)
CONTRACT_MAX_BYTES = 16 * 1024**2
CONTRACT_TOTAL_BYTES = 64 * 1024**2
PRIVATE_EVIDENCE_DIRS = {
    "evaluation_evidence", "__pycache__", ".git", ".env",
    "input", "runtime",
}
PRIVATE_EVIDENCE_FILES = {
    "dev_payloads.json", "dev_row_evidence.json", "holdout_index.json",
    "holdout_payloads.json", "holdout_rows.json", "holdout_predictions.csv",
    "holdout_rows.csv", "holdout_evidence.json", "holdout_evidence.csv",
    "holdout_predictions.json", "holdout_metrics.json", "development_evidence.csv",
    "development_evidence.json", "development_rows.csv", "validation_payloads.json",
    "validation_evidence.csv", "validation_evidence.json", "predict_sample_input.json",
    "predict_sample_output.json", "search_audit.json", "final_evaluation.json",
    "final_summary.json", "status.json", "execution.log",
}
PRIVATE_EVIDENCE_PREFIXES = (
    "holdout_", "development_evidence", "development_rows", "dev_row_evidence",
)


def stop_process_tree(process):
    import psutil
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.Error:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=3)
    except psutil.NoSuchProcess:
        pass
    process.wait(timeout=5)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def safe_file(root: Path, path: Path) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or path.is_symlink() or not resolved.is_file():
        raise HTTPException(409, "方案文件越界、链接或缺失，不能导出")
    # Reject directory symlinks/junctions as well as leaf links.
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise HTTPException(409, "方案目录包含链接，不能导出")
    return resolved


def solution_files(root: Path):
    """Export the actual package, never the entire workspace/input/log/config tree."""
    files = []
    total = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        lowered_parts = [part.lower() for part in rel.parts]
        if any(
            lowered_parts[index:index + 2] == ["working", "evidence"]
            for index in range(len(lowered_parts) - 1)
        ):
            continue
        if any(part in PRIVATE_EVIDENCE_DIRS for part in lowered_parts):
            continue
        if "final_evaluation" in lowered_parts:
            index = lowered_parts.index("final_evaluation")
            if lowered_parts[index + 1:index + 2] != ["artifacts"]:
                continue
        if any(
            part in PRIVATE_EVIDENCE_FILES or part.startswith(PRIVATE_EVIDENCE_PREFIXES)
            for part in lowered_parts
        ):
            continue
        if path.is_symlink():
            raise HTTPException(409, "方案包包含符号链接")
        if not path.is_file():
            continue
        safe_file(root, path)
        if path.name.lower() in {"config.yaml", "global_settings.yaml", "secrets.json"} or path.suffix == ".pyc":
            continue
        total += path.stat().st_size
        if len(files) >= 20000 or total > 4 * 1024**3:
            raise HTTPException(413, "方案包超过 4 GiB 或 20000 个文件，请使用本地目录交付")
        files.append((path, rel.as_posix()))
    return files, total


def contract_sources(task, root):
    """Resolve only known contracts from this workspace or its recorded run's AutoRealize.

    Older runs linked their input to AutoRealize output. Materializing those links
    is a snapshot taken now, not evidence that the contract never changed.
    """
    result, total = [], 0
    workspace = root.parent
    for name in CONTRACT_FILES:
        original = workspace / 'input' / name
        if not original.is_file():
            continue
        mode = 'workspace_input'
        try:
            path = safe_file(workspace, original)
        except HTTPException as exc:
            if not getattr(task, 'run_dir', None):
                raise
            historic_root = Path(task.run_dir) / 'autorealize'
            path = safe_file(historic_root, historic_root / name)
            if original.resolve() != path:
                raise exc
            mode = 'recorded_run_autorealize_link_snapshot'
        size = path.stat().st_size
        total += size
        if size > CONTRACT_MAX_BYTES or total > CONTRACT_TOTAL_BYTES:
            raise HTTPException(413, '合同超过单文件16 MiB或合计64 MiB交付上限；请使用本地目录交付')
        result.append((name, path, mode))
    return result


def inspect_source_solution(g, task, *, package_root=None):
    log = g._pick_local_automl_log_dir(task) if package_root is None else None
    workspace = Path(package_root).parent if package_root is not None else g._pick_local_automl_workspace_dir(task, log.name if log else None)
    empty = {"available": False, "exportable": False, "issues": ["尚未生成选定方案包"], "files": []}
    if workspace is None:
        return empty, None
    root = workspace / "best_solution"
    if not root.is_dir():
        return empty, None
    safe_file(workspace, root / "solution_manifest.json")
    manifest = g.safe_read_json(root / "solution_manifest.json", {})
    if not isinstance(manifest, dict) or not manifest.get("node_id"):
        raise HTTPException(409, "选定方案缺少有效身份清单")
    files, size = solution_files(root)
    names = {name for _, name in files}
    issues = []
    for name in ["solution.py", manifest.get("implementation_path"), manifest.get("generated_source_path")]:
        if name and name not in names:
            issues.append(f"缺少实现文件：{name}")
    model_path = g.safe_read_text_tail(root / "model_path.txt", limit=4096).strip()
    portable_model = None
    raw_model = model_path or str(manifest.get("artifact_path") or "")
    if raw_model:
        candidate = Path(raw_model)
        candidate = candidate if candidate.is_absolute() else root / candidate
        try:
            portable_model = safe_file(root, candidate).relative_to(root.resolve()).as_posix()
            if portable_model not in names:
                issues.append("模型文件不在可导出范围")
        except HTTPException:
            issues.append("模型路径未指向方案包内部文件，需要修复交付包")
    elif manifest.get("artifact_required"):
        issues.append("方案要求模型文件，但没有记录模型路径")
    implementation = manifest.get("implementation_path")
    expected = manifest.get("implementation_file_sha256")
    if implementation and implementation in names and expected:
        actual = hashlib.sha256(safe_file(root, root / implementation).read_bytes()).hexdigest()
        if actual != expected:
            issues.append("选定实现的校验值已改变")
    if task.status == "running":
        issues.append("实验运行中，方案文件可能更新；停止或完成后再导出")
    return {
        "available": True, "exportable": not issues, "issues": issues,
        "node_id": manifest.get("node_id"), "manifest": manifest,
        "model_path": portable_model, "directory": str(root), "size_bytes": size,
        "files": [{"path": name, "size": p.stat().st_size} for p, name in files],
        "usage": g.safe_read_text_tail(root / "TRAINING_CONFIGURATION.md", limit=20000),
        "verification": {name: g.safe_read_json(root / name, {}) for name in (
            "inference-verification.json", "training-verification.json") if (root / name).is_file()},
        "portability": "wrapper_present" if implementation else "legacy_unverified",
        "notice": "包结构检查不代表业务达标、独立验收或依赖可用。不同任务的输入结构以冻结合同和实现接口为准。",
        "contracts": [name for name in CONTRACT_FILES if (workspace / "input" / name).is_file()],
        "trial_ready": not issues and bool(implementation and expected) and manifest.get("entrypoint") in {"predict", "solve", "rollout"},
    }, root


def inspect_solution(g, task):
    info, root = inspect_source_solution(g, task)
    if task.status != 'running':
        from delivery import resolve_prepared
        prepared = resolve_prepared(g, task, info, root)
        if prepared is not None:
            return prepared
    return info, root


def install(g):
    app = g.app
    version_path = g.APP_ROOT / "VERSION"

    @app.get("/api/system/readiness")
    def readiness(task_id: str = ""):
        settings = g.get_global_settings()
        checks = []

        def add(key, label, status, detail):
            checks.append(dict(key=key, label=label, status=status, detail=detail))

        exe = str(settings.python.get("executable") or "")
        try:
            probe = subprocess.run([exe, "-I", "-c",
                "import sys,json,importlib.util; print(json.dumps({'version':list(sys.version_info[:3]),'missing':[m for m in ['fastapi','yaml','numpy','pandas','openai','psutil'] if importlib.util.find_spec(m) is None]}))"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(probe.stdout)
            ok = probe.returncode == 0 and data["version"][:2] >= [3, 10] and not data["missing"]
            add("python", "Python 与基础依赖", "pass" if ok else "fail",
                f"Python {'.'.join(map(str, data['version']))}；缺少依赖：{', '.join(data['missing']) or '无'}。任务特定依赖仍需运行时检查。")
        except Exception:
            add("python", "Python 与基础依赖", "fail", "无法执行已配置的解释器，请在系统设置中选择有效环境。")

        bases = g._service_base_urls(settings)[:3]
        def service(row):
            key, label, base = row
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as response:
                    ok = response.status == 200
                return key, label, "pass" if ok else "fail", "服务在线" if ok else "服务未就绪"
            except Exception:
                return key, label, "fail", "未连接，请启动本地运行器并检查服务设置。"
        task = g.store.get(task_id) if task_id else None
        services = list(zip(["autorealize", "automl", "report"], ["数据分析服务", "方案搜索服务", "报告服务"], bases))
        if task and not task.config.auto_report.enabled:
            services = services[:2]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for row in pool.map(service, services):
                add(*row)
        validations = g.safe_read_json(g.STATE_DIR / "model_checks.json", {})
        roles = [("autoRealize", "数据分析模型（要求多模态）"), ("autoMlCode", "方案生成模型"), ("autoMlFeedback", "评审与报告模型")]
        providers = []
        for role, label in roles:
            model = g._selected_model(settings.llm, role)
            parsed = urllib.parse.urlsplit(str(model.get("baseUrl") or ""))
            configured = bool(model.get("model") and parsed.scheme in {"http", "https"} and parsed.hostname)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            configured = configured and (local or bool(model.get("apiKey")))
            saved = validations.get(role, {})
            verified = saved.get("fingerprint") == fingerprint(model) and time.time() - saved.get("at", 0) < 86400
            if role == "autoRealize":
                verified = verified and saved.get("capability") == "image_request_only"
            provider_status = "pass" if configured and verified else "fail" if not configured or role == "autoRealize" else "warn"
            add(role, label, provider_status,
                ("图像请求测试通过。" if role == "autoRealize" else "连接测试通过。") if configured and verified else
                ("请测试图像输入，确认支持多模态。" if role == "autoRealize" else "尚未测试连接，或测试已过期。") if configured else "请填写模型、API 地址和密钥。")
            providers.append({"role": role, "model": model.get("model", ""), "host": parsed.hostname or "", "local": local})
        root = g.resolve_output_root(task.output_root if task else "")
        ancestor = root
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        disk = shutil.disk_usage(ancestor)
        add("storage", "本地输出空间", "pass" if os.access(ancestor, os.W_OK) and disk.free > 1024**3 else "fail",
            f"输出：{root}；可用 {disk.free / 1024**3:.1f} GiB。运行过程中仍可能耗尽空间。")
        if task:
            path = Path(task.input_root).expanduser()
            add("input", "任务数据目录", "pass" if task.input_root.strip() and path.is_dir() and os.access(path, os.R_OK) else "fail", str(path))
            if not task.run_dir:
                target = root / task.task_name
                add("target", "实验输出目录", "fail" if target.exists() else "pass", "目录已存在，请创建新实验或修改名称。" if target.exists() else "将创建独立实验目录。")
        return {"version": version_path.read_text().strip(), "checked_at": time.time(),
            "ready": not any(c["status"] == "fail" for c in checks), "checks": checks,
            "providers": providers, "output_root": str(root),
            "lifecycle": "关闭浏览器不会停止后台任务。退出运行器或电脑休眠会中断执行；恢复需检查点可用。",
            "data_policy": "输入目录在本机读取；使用远程模型时，材料、摘要或生成代码可能发送给相应 Provider。本地部署不等于离线。"}

    @app.post("/api/system/probe-model")
    def probe_model(payload: ModelProbe):
        if payload.role not in {"autoRealize", "autoMlCode", "autoMlFeedback", "promptOptimizer"}:
            raise HTTPException(400, "请选择数据分析、编码或评审模型")
        model = g._selected_model(g.get_global_settings().llm, payload.role)
        base = str(model.get("baseUrl") or "").rstrip("/")
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise HTTPException(400, "模型服务地址无效")
        endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        content = "Reply OK."
        if payload.capability == "image":
            # Small generated RGB image; the probe never reads project files.
            import base64
            import struct
            import zlib
            def chunk(kind, data):
                return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
            png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 32, 32, 8, 2, 0, 0, 0))
            png += chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff\x00\x00' * 32) * 32)) + chunk(b'IEND', b'')
            content = [{"type": "text", "text": "Name the dominant color of this image in one word."},
                       {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode('ascii')}}]
        request_body = {"model": model.get("model"), "messages": [{"role": "user", "content": content}], "max_tokens": 128}
        if parsed.hostname == 'api.deepseek.com':
            request_body['thinking'] = {'type': 'disabled'}
        body = json.dumps(request_body).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "AutoDecision"}
        if model.get("apiKey"):
            headers["Authorization"] = "Bearer " + str(model["apiKey"])
        try:
            req = urllib.request.Request(endpoint, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.loads(response.read(1024 * 1024))
            if not result.get("choices") or not result['choices'][0].get('message', {}).get('content'):
                raise ValueError("missing choices")
            answer = result['choices'][0]['message']['content']
            if payload.capability == "image" and not re.search(r"\bred\b|红色|红", answer, re.IGNORECASE):
                raise ValueError("image content not recognized")
        except Exception:
            # Never echo a provider response, URL with credentials, or key in diagnostics.
            raise HTTPException(400, "图像请求失败，请检查所选数据分析模型是否支持图片输入，以及 API 地址和密钥。" if payload.capability == "image" else "连接测试失败，请检查模型 ID、API 地址和密钥。")
        with g.GLOBAL_SETTINGS_LOCK:
            path = g.STATE_DIR / "model_checks.json"
            checks = g.safe_read_json(path, {})
            checks[payload.role] = {"fingerprint": fingerprint(model), "at": time.time(), "capability": payload.capability + "_request_only"}
            g.write_json(path, checks, sensitive=True)
        return {"status": "verified", "capability": payload.capability + "_request_only"}

    @app.post("/api/tasks/{task_id}/experiments")
    def new_experiment(task_id: str):
        # Clone configuration into a new task record; never move/clean old files.
        with g.store._lock:
            original = g.store.get(task_id)
            config = original.config.model_copy(deep=True)
            config.task_name = original.task_name[:80] + "__" + g.uuid.uuid4().hex[:10]
            child = g.store.create(config)
            child.experiment_group_id = original.experiment_group_id or original.id
            child.parent_task_id = original.id
            g.store._persist()
            return child.model_dump()

    @app.get("/api/tasks/{task_id}/experiments")
    def experiments(task_id: str):
        original = g.store.get(task_id)
        group = original.experiment_group_id or original.id
        return [t.model_dump() for t in g.store.list_tasks() if (t.experiment_group_id or t.id) == group]

    @app.get("/api/tasks/{task_id}/solution")
    def solution(task_id: str):
        return inspect_solution(g, g.store.get(task_id))[0]

    @app.get("/api/tasks/{task_id}/solution/bundle")
    def bundle(task_id: str):
        task = g.store.get(task_id)
        info, root = inspect_solution(g, task)
        if not info["exportable"]:
            raise HTTPException(409, "；".join(info["issues"]))
        return export_solution_bundle(g, task, info, root)

    @app.get("/api/system/diagnostics")
    def diagnostics():
        # Deliberately omit settings, prompts, raw logs, input paths, and provider responses.
        versions = {}
        for name, root in [("gateway", g.APP_ROOT), ("AutoRealize", g.AUTOREALIZE_DIR), ("AlgoEvolve", g.ALGOEVOLVE_DIR), ("AutoReport", g.AUTOREPORT_DIR)]:
            try:
                result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                versions[name] = result.stdout.strip() if result.returncode == 0 else "unknown"
            except Exception:
                versions[name] = "unknown"
        return {"release": version_path.read_text().strip(), "source_heads": versions, "generated_at": time.time(),
            "tasks": [{"id": t.id, "status": t.status, "phase": t.phase} for t in g.store.list_tasks()],
            "notice": "不含模型密钥、原始日志或数据；源码 HEAD 不代表工作区没有修改。"}

    @app.post("/api/tasks/{task_id}/solution/trial")
    def trial(task_id: str, payload: SolutionTrial):
        return execute_trial(g, g.store.get(task_id), payload)

    @app.get("/api/tasks/{task_id}/solution/trials")
    def trial_history(task_id: str):
        g.store.get(task_id)
        root = g.STATE_DIR / "trials" / task_id
        rows = []
        for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            if path.stat().st_size > 2 * 1024**2:
                continue
            data = g.safe_read_json(safe_file(root, path), {})
            if data.get("task_id") == task_id:
                rows.append({key: data.get(key) for key in ("trial_id", "created_at", "node_id", "entrypoint", "input_sha256")})
        return rows

    @app.get("/api/tasks/{task_id}/solution/trials/{trial_id}")
    def trial_record(task_id: str, trial_id: str):
        g.store.get(task_id)
        if not g.re.fullmatch(r"[0-9a-f]{32}", trial_id):
            raise HTTPException(400, "试算记录编号无效")
        root = g.STATE_DIR / "trials" / task_id
        path = root / (trial_id + ".json")
        if not path.is_file():
            raise HTTPException(404, "试算记录不存在")
        safe_file(root, path)
        if path.stat().st_size > 2 * 1024**2:
            raise HTTPException(413, "试算记录过大")
        return g.safe_read_json(path, {})

    return {"bundle": bundle, "trial": trial, "new_experiment": new_experiment}


def execute_trial(g, task, payload: SolutionTrial, *, inspected=None, expected_hashes=None, persist_trial=True, dataframes=None, decision_code=None):
    """Shared inference service for task delivery and frozen Studio package copies."""
    if decision_code:
        from decision_program import validate_program
        validate_program(decision_code)
    info, root = inspected if inspected is not None else inspect_solution(g, task)
    if not info.get("trial_ready"):
        raise HTTPException(409, "试算需要已停止、模型齐全且实现校验通过的可迁移方案包")
    if payload.input_mode not in {"json", "csv"}:
        raise HTTPException(400, "输入类型必须为 JSON 或 CSV")
    if payload.input_mode == "json":
        try:
            parsed = json.loads(payload.data_json)
        except ValueError:
            raise HTTPException(400, "JSON 输入格式错误")
        if not isinstance(parsed, (dict, list)):
            raise HTTPException(400, "JSON 输入需要为业务对象或数组")
        input_bytes = payload.data_json.encode("utf-8")
        if len(input_bytes) > MAX_TRIAL_INPUT_BYTES:
            raise HTTPException(413, "JSON 输入超过 16 MiB，未截断数据")
    else:
        try:
            path = safe_file(Path(task.input_root), Path(payload.csv_path).expanduser())
        except HTTPException:
            raise HTTPException(400, "CSV 必须位于本任务输入目录内，且不能为链接")
        if path.suffix.lower() != ".csv" or path.stat().st_size > 16 * 1024**2:
            raise HTTPException(400, "CSV 试算仅支持不超过 16 MiB 的 .csv 文件")
        input_bytes = path.read_bytes()
    if not TRIAL_LOCK.acquire(blocking=False):
        raise HTTPException(409, "已有本地试算在执行，请完成后再试")
    try:
        with tempfile.TemporaryDirectory(prefix="autodecision-trial-") as directory:
            temporary = Path(directory)
            files, total = solution_files(root)
            if shutil.disk_usage(temporary).free < total + 256 * 1024**2:
                raise HTTPException(507, "临时磁盘空间不足，无法复制方案进行试算")
            package = temporary / "solution"
            package.mkdir()
            package_hashes = {}
            for source, name in files:
                target = package / name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with safe_file(root, source).open("rb") as src, target.open("wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                        digest.update(chunk)
                package_hashes[name] = digest.hexdigest()
            if expected_hashes is not None and package_hashes != expected_hashes:
                raise HTTPException(409, "已发布包内容发生变化，拒绝调用；请重新检查包版本")
            implementation = info["manifest"]["implementation_path"]
            if package_hashes.get(implementation) != info["manifest"]["implementation_file_sha256"]:
                raise HTTPException(409, "复制期间方案实现发生变化，请重新检查成果")
            (temporary / ("trial_input.csv" if payload.input_mode == "csv" else "trial_input.json")).write_bytes(input_bytes)
            (temporary / "trial_request.json").write_text(json.dumps({"input_mode": payload.input_mode,
                "entrypoint": info["manifest"]["entrypoint"], "model_path": info["model_path"],
                "dataframes": dataframes or [], "decision_code": decision_code}), encoding="utf-8")
            settings = g.get_global_settings()
            env = os.environ.copy()
            for key in list(env):
                if any(word in key.upper() for word in ("API_KEY", "APIKEY", "TOKEN", "SECRET")):
                    env.pop(key)
            env.update(CUDA_VISIBLE_DEVICES="", HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="", ONEAPI_DEVICE_SELECTOR="opencl:cpu", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
            # Discard candidate stdout/stderr: arbitrary output is not a safe diagnostic channel.
            process = subprocess.Popen([str(settings.python.get("executable") or g.sys.executable), "-I",
                str(g.BACKEND_DIR / "solution_trial_runner.py"), str(temporary)], cwd=temporary,
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                process.wait(timeout=payload.timeout_seconds)
            except subprocess.TimeoutExpired:
                stop_process_tree(process)
                raise HTTPException(408, "试算超时，已终止进程树。原实验文件未被打包器修改。")
            result_path = temporary / "trial_result.json"
            if process.returncode or not result_path.is_file():
                raise HTTPException(422, "试算失败：请核对输入结构、方案依赖与运行环境。需要 GPU、文件路径或其他专用输入的方案请按接口说明运行。")
            safe_file(temporary, result_path)
            if result_path.stat().st_size > 1024**2:
                raise HTTPException(413, "试算结果超过 1 MiB 预览上限")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            trial_id = g.uuid.uuid4().hex
            record = {"trial_id": trial_id, "task_id": task.id, "node_id": info["node_id"],
                "entrypoint": info["manifest"]["entrypoint"], "implementation_sha256": info["manifest"].get("implementation_file_sha256"),
                "package_sha256": package_hashes,
                "input_sha256": hashlib.sha256(input_bytes).hexdigest(), "created_at": time.time(), "result": result,
                "scope": "用户输入上的本地调用；不改写搜索成绩，不构成独立验收。"}
            if decision_code:
                record["decision"] = json.loads(safe_file(temporary, temporary / "trial_decision.json").read_text(encoding="utf-8"))
            if persist_trial:
                g.write_json(g.STATE_DIR / "trials" / task.id / (trial_id + ".json"), record, sensitive=True)
            return record
    finally:
        TRIAL_LOCK.release()



def export_solution_bundle(g, task, info, root):
    files, total = solution_files(root)
    if shutil.disk_usage(tempfile.gettempdir()).free < total + 256 * 1024**2:
        raise HTTPException(507, "临时目录空间不足，无法生成方案包")
    handle, temporary = tempfile.mkstemp(suffix=".zip", prefix="autodecision-solution-")
    os.close(handle)
    try:
        hashes = {}
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path, name in files:
                if name in {"model_path.txt", "solution_manifest.json", "package_inventory.json", "LOCAL_USAGE.md"} or name in {"contract/" + item for item in info["contracts"]}:
                    continue
                if name == 'contract_provenance.json' and not info.get('delivery_id'):
                    continue
                # Stream large models; compare stat before/after to reject concurrent writes.
                before = path.stat()
                digest = hashlib.sha256()
                with safe_file(root, path).open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        target.write(chunk)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise HTTPException(409, "方案正在变化，请稍后导出")
                hashes[name] = digest.hexdigest()
            # Always use this experiment's frozen input, never today's task-root contract.
            provenance = []
            for name, path, mode in contract_sources(task, root):
                body = path.read_bytes()
                archive.writestr("contract/" + name, body)
                hashes["contract/" + name] = hashlib.sha256(body).hexdigest()
                provenance.append({'path': name, 'source': str(path), 'mode': mode,
                    'sha256': hashes['contract/' + name], 'bytes': len(body)})
            if not info.get('delivery_id'):
                body = json.dumps({'schema_version': 'autodecision.contract_sources.v1', 'snapshot_at': time.time(),
                    'files': provenance, 'notice': '链接合同是整理时的来源快照，未证明实验结束后未变化。'}, ensure_ascii=False, indent=2)
                archive.writestr('contract_provenance.json', body)
                hashes['contract_provenance.json'] = hashlib.sha256(body.encode('utf-8')).hexdigest()
            manifest = dict(info["manifest"])
            if info["model_path"]:
                manifest["artifact_path"] = info["model_path"]
                archive.writestr("model_path.txt", info["model_path"] + "\n")
            archive.writestr("solution_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("package_inventory.json", json.dumps({
                "schema_version": "autodecision.solution_export.v1",
                "version": (g.APP_ROOT / "VERSION").read_text().strip(),
                "task_id": task.id,
                "node_id": info["node_id"],
                "sha256": hashes,
            }, ensure_ascii=False, indent=2))
            archive.writestr("LOCAL_USAGE.md", "# 本地方案交付\n\n保留整个目录及文件相对位置。先阅读 solution_manifest.json 的 entrypoint、evaluation_protocol 和实现代码输入约定。\n\n"
                "requirements.txt（如有）是环境线索，尚未在干净环境验证。导入生成代码会执行 Python；请在独立环境使用。\n\n"
                "预测/求解与 train/retrain 分开，不能通过重新训练代替已有模型试算。不同任务的 data 参数格式不同，本版没有通用 CSV 适配器。\n\n"
                "model_path.txt 已转换为包内相对路径。历史包内实现仍可能有绝对路径依赖；移动后须按任务合同验证。\n")
        return FileResponse(temporary, media_type="application/zip", filename=f"solution-{task.id[:12]}.zip",
            background=BackgroundTask(Path(temporary).unlink, missing_ok=True))
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise

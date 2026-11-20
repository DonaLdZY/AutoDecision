"""Shared local launcher: Decision Studio is the default product frontend.

PowerShell and Bash entry points delegate here so service identity, ports,
health checks and process records have the same meaning on every platform.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

import psutil

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Service:
    name: str
    directory: Path
    port: int
    module: str = ""
    frontend: bool = False

    @property
    def url(self):
        suffix = "/api/health" if self.name == "gateway-api" else "/health" if self.module else "/"
        return f"http://127.0.0.1:{self.port}{suffix}"


SERVICES = [
    Service("autorealize-api", ROOT / "core/AutoRealize", 18101, "autorealize.service_api:app"),
    Service("algoevolve-api", ROOT / "core/AlgoEvolve", 18103, "service_api:app"),
    Service("autoreport-api", ROOT / "core/AutoReport", 18104, "service_api:app"),
    Service("gateway-api", ROOT / "frontend/backend", 18080, "app:app"),
    Service("decision-studio", ROOT / "frontend/decision-studio", 5178, frontend=True),
]
LEGACY = Service("legacy-ui", ROOT / "frontend/ui", 5173, frontend=True)
ALIASES = {"frontend": "decision-studio", "frontend-ui": "decision-studio", "ui": "decision-studio",
           "studio": "decision-studio", "gateway": "gateway-api", "backend": "gateway-api",
           "autorealize": "autorealize-api", "algoevolve": "algoevolve-api", "mlevolve": "algoevolve-api",
           "mlevolve-api": "algoevolve-api", "autoreport": "autoreport-api"}


def normalized(path):
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def settings_path():
    value = Path(os.environ.get("AUTODECISION_GLOBAL_SETTINGS_PATH", ROOT / "frontend/config/global_settings.yaml"))
    return value if value.is_absolute() else ROOT / value


def resolve_python(explicit=""):
    override = explicit or os.environ.get("AUTODECISION_PYTHON_EXECUTABLE") or os.environ.get("AUTODECISION_PYTHON")
    if not override and settings_path().exists():
        import yaml
        settings = yaml.safe_load(settings_path().read_text(encoding="utf-8-sig")) or {}
        override = (settings.get("python") or {}).get("executable")
    value = str(override or sys.executable)
    executable = shutil.which(value)
    if not executable:
        raise RuntimeError(f"Python not found: {value}. Use --python PATH / -PythonExecutable PATH.")
    return executable


def node_supported(version):
    major, minor, *_ = (int(x) for x in version.lstrip("v").split("."))
    return (major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major > 22


def process_matches(service, command, cwd):
    """Never adopt/stop a process merely because it occupies a familiar port."""
    if normalized(cwd) != normalized(service.directory):
        return False
    if service.module:
        return any(command[i:i + 3] == ["-m", "uvicorn", service.module] for i in range(len(command) - 2))
    script = service.directory / "node_modules/vite/bin/vite.js"
    return any(normalized(arg) == normalized(script) for arg in command if "vite" in arg)


def http_json(url, authenticated=False):
    headers = {}
    if authenticated and os.environ.get("AUTODECISION_API_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["AUTODECISION_API_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=2) as response:
        return json.load(response)


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def command_uses_port(command, port):
    """An unreliable socket state needs an explicit, unambiguous command-line port."""
    values = []
    for index, argument in enumerate(command):
        if argument == "--port":
            values.append(command[index + 1] if index + 1 < len(command) else "")
        elif argument.startswith("--port="):
            values.append(argument.partition("=")[2])
    return values == [str(port)]


def listener(service):
    connections = psutil.net_connections(kind="tcp")
    owners = {row.pid for row in connections
              if row.status == psutil.CONN_LISTEN and row.laddr.port == service.port and row.pid}
    unknown_state = False
    # Some Windows TCP tables supply the correct endpoint/PID but an unreliable
    # state (observed NONE, FIN_WAIT1 and CLOSE) for listening sockets. The lack
    # of a remote endpoint is the stable discriminator; ignore the state label.
    # Never infer ownership from a reachable port alone:
    # require one local endpoint without a peer, then verify the actual process
    # directory, service command and explicit port before adopting/stopping it.
    if not owners and sys.platform == "win32":
        candidates = {row.pid for row in connections
                      if row.laddr and row.laddr.port == service.port
                      and row.laddr.ip in {"127.0.0.1", "0.0.0.0", "::", "::1"}
                      and not row.raddr and row.pid}
        if candidates and port_open(service.port):
            owners = candidates
            unknown_state = True
    if len(owners) > 1:
        raise RuntimeError(f"Port {service.port} has multiple owners; no process was stopped.")
    if owners:
        process = psutil.Process(owners.pop())
        command = process.cmdline()
        if (not process_matches(service, command, process.cwd())
                or (unknown_state and not command_uses_port(command, service.port))):
            raise RuntimeError(f"Port {service.port} belongs to another process; no process was stopped.")
        return process
    if port_open(service.port):
        raise RuntimeError(f"Cannot verify owner of port {service.port}; no process was stopped.")
    return None


def state_directory():
    return Path(os.environ.get("AUTODECISION_LAUNCHER_STATE_DIR", ROOT / ".dev-state")).resolve()


def read_state(directory):
    path = directory / "studio-processes.json"
    if not path.exists():
        return {"schema": 1, "root": str(ROOT), "processes": []}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if normalized(value.get("root", "")) != normalized(ROOT):
        raise RuntimeError("Launcher state belongs to a different repository.")
    return value


def write_state(directory, state):
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f"studio-processes.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "studio-processes.json")


def record(service, process, **extra):
    return {"name": service.name, "pid": process.pid, "created": process.create_time(),
            "port": service.port, "workdir": str(service.directory), **extra}


def remember(directory, state, row):
    state["processes"] = [p for p in state["processes"] if p["name"] != row["name"]] + [row]
    write_state(directory, state)


def healthy(service):
    try:
        if service.module:
            return http_json(service.url).get("status") == "ok"
        with urllib.request.urlopen(service.url, timeout=2) as response:
            return response.status == 200 and b"AutoDecision" in response.read(8192)
    except (OSError, ValueError):
        return False


def guard_active_work():
    """Stopping the frontend is independent; backend lifecycle respects active work."""
    if port_open(18080):
        try:
            tasks = http_json("http://127.0.0.1:18080/api/tasks", authenticated=True)
            workspace = http_json("http://127.0.0.1:18080/api/studio/state", authenticated=True)
        except (OSError, ValueError) as exc:
            raise RuntimeError("Cannot check active work. Set AUTODECISION_API_TOKEN if required; no backend stopped.") from exc
        if any(t.get("status") in {"running", "starting", "stopping"} for t in tasks):
            raise RuntimeError("Research is running. Stop it in Decision Studio before stopping/restarting backend services.")
        if any(row.get("status") == "running" for row in workspace.get("invocations", [])):
            raise RuntimeError("An inference call is running; no backend stopped.")
        return
    root = Path(os.environ.get("AUTODECISION_STATE_DIR", ROOT / "frontend/backend/.state"))
    task_file = root / "tasks.json"
    if task_file.exists():
        raw = json.loads(task_file.read_text(encoding="utf-8-sig"))
        tasks = raw.get("tasks", []) if isinstance(raw, dict) else raw
        if isinstance(tasks, dict):
            tasks = list(tasks.values())
        if any(t.get("status") == "running" for t in tasks):
            raise RuntimeError("Persisted research is marked running; inspect it before stopping Core services.")
    db = root / "studio/studio.sqlite3"
    if db.exists():
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT body FROM documents WHERE kind='invocations'")
            if any(json.loads(row[0]).get("status") == "running" for row in rows):
                raise RuntimeError("A persisted inference call is marked running; no backend stopped.")


def stop_process(process):
    import psutil
    try:
        targets = process.children(recursive=True) + [process]
    except psutil.NoSuchProcess:
        return
    for target in reversed(targets):
        try:
            target.terminate()
        except psutil.NoSuchProcess:
            pass
    _, remaining = psutil.wait_procs(targets, timeout=5)
    for target in remaining:
        try:
            target.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(remaining, timeout=3)


def selected_services(args):
    front = LEGACY if args.legacy_ui else SERVICES[-1]
    services = SERVICES[:-1] + [front]
    if args.only:
        name = ALIASES.get(args.only, args.only)
        if args.legacy_ui and name == "decision-studio":
            name = "legacy-ui"
        result = [s for s in SERVICES + [LEGACY] if s.name == name]
        if not result:
            raise RuntimeError(f"Unknown service: {args.only}")
        return result
    if args.frontend_only:
        return [front]
    return services[-2:] if args.no_core else services


def dependencies(python, services):
    if any(s.module for s in services):
        imports = "import fastapi,uvicorn,yaml,psutil"
        if any(s.module and s.name != "gateway-api" for s in services):
            imports += ",numpy,pandas,openai"
        result = subprocess.run([python, "-I", "-c", imports], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"Selected Python lacks isolated runtime dependencies: {python}\n"
                               f"Install requirements.txt into that environment.\n{result.stderr.strip()}")
    if any(s.frontend for s in services):
        node = shutil.which("node")
        if not node or not shutil.which("npm.cmd" if os.name == "nt" else "npm"):
            raise RuntimeError("Node.js and npm are required for Decision Studio.")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if not node_supported(version):
            raise RuntimeError("Node.js requires ^20.19.0 or >=22.12.0; Node 22/24 LTS recommended.")


def npm(service, *arguments):
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    subprocess.run([executable, *arguments], cwd=service.directory, check=True)


def start_services(args, services, directory, state):
    state_before = copy.deepcopy(state)
    started = []
    stopped_existing = set()
    try:
        _start_services(
            args,
            services,
            directory,
            state,
            started=started,
            stopped_existing=stopped_existing,
        )
    except BaseException:
        for _, process in reversed(started):
            try:
                stop_process(process)
            except Exception:
                pass
        state.clear()
        state.update(state_before)
        if stopped_existing:
            state["processes"] = [
                row for row in state.get("processes", [])
                if row.get("name") not in stopped_existing
            ]
        try:
            write_state(directory, state)
        except OSError:
            pass
        raise


def _start_services(args, services, directory, state, *, started, stopped_existing):
    import psutil
    python = resolve_python(args.python) if any(s.module for s in services) else sys.executable
    dependencies(python, services)
    # Verify every occupied port before creating any process.
    for service in services:
        process = listener(service)
        if process and not healthy(service):
            raise RuntimeError(f"{service.name} occupies {service.port} but is unhealthy; inspect logs before restart.")
    for service in services:
        process = listener(service)
        if service.frontend:
            if not (service.directory / "node_modules/vite/bin/vite.js").is_file():
                npm(service, "ci", "--no-audit", "--no-fund")
            if not args.dev:
                npm(service, "run", "build")
            mode = "dev" if args.dev else "preview"
            config_hash = hashlib.sha256((service.directory / "vite.config.ts").read_bytes()).hexdigest()
            if process:
                actual_mode = "preview" if "preview" in process.cmdline() else "dev"
                previous = next((p for p in state["processes"] if p["name"] == service.name), {})
                target = os.environ.get("AUTODECISION_GATEWAY_TARGET", "http://127.0.0.1:18080")
                # Restart only the verified frontend when its launch mode/proxy changes.
                if (actual_mode != mode or previous.get("gateway_target") != target
                        or previous.get("config_hash") != config_hash):
                    stop_process(process)
                    stopped_existing.add(service.name)
                    process = None
        if process:
            previous = next((p for p in state["processes"] if p["name"] == service.name and p["pid"] == process.pid
                             and p.get("created") == process.create_time()), {})
            remember(directory, state, {**previous, **record(service, process)})
            print(f"Reused {service.name} on {service.port} (PID {process.pid}); restart explicitly to load backend changes.", flush=True)
            continue
        if service.module:
            command = [python, "-m", "uvicorn", service.module, "--host", "127.0.0.1", "--port", str(service.port)]
        else:
            command = [shutil.which("node"), str(service.directory / "node_modules/vite/bin/vite.js")]
            if not args.dev:
                command += ["preview"]
            command += ["--host", "127.0.0.1", "--port", str(service.port), "--strictPort"]
        log_dir = directory / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000:06}"
        output = log_dir / f"{service.name}-{stamp}.stdout.log"
        error = log_dir / f"{service.name}-{stamp}.stderr.log"
        with output.open("wb") as stdout, error.open("wb") as stderr:
            child = subprocess.Popen(command, cwd=service.directory, stdout=stdout, stderr=stderr,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     start_new_session=os.name != "nt")
        process = psutil.Process(child.pid)
        started.append((service, process))
        row = record(service, process, stdout=str(output), stderr=str(error), mode="dev" if args.dev else "preview",
                     config_hash=config_hash if service.frontend else "",
                     gateway_target=os.environ.get("AUTODECISION_GATEWAY_TARGET", "http://127.0.0.1:18080"))
        remember(directory, state, row)
        deadline = time.monotonic() + 45
        while not healthy(service):
            if child.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"{service.name} failed to start. Logs: {error}")
            time.sleep(.3)
        print(f"Ready {service.name}: {service.url} (PID {child.pid})", flush=True)
    if any(s.frontend for s in services):
        port = next(s.port for s in services if s.frontend)
        url = f"http://127.0.0.1:{port}/#chat" if port == 5178 else f"http://127.0.0.1:{port}/"
        print(f"Open AutoDecision: {url}", flush=True)
        if args.open:
            webbrowser.open(url)


def stop_services(services, directory, state):
    import psutil
    processes = []
    # Preflight all identities and active work before stopping the first service.
    for service in services:
        process = listener(service)
        if not process:
            row = next((p for p in state["processes"] if p["name"] == service.name), None)
            if row and psutil.pid_exists(row["pid"]):
                candidate = psutil.Process(row["pid"])
                if row.get("created") == candidate.create_time() and process_matches(service, candidate.cmdline(), candidate.cwd()):
                    process = candidate
        if process:
            processes.append((service, process))
    if any(s.module for s, _ in processes):
        guard_active_work()
    for service, process in reversed(processes):
        stop_process(process)
        print(f"Stopped {service.name} (PID {process.pid})", flush=True)
    names = {s.name for s in services}
    state["processes"] = [p for p in state["processes"] if p["name"] not in names]
    write_state(directory, state)


def show_status(services):
    for service in services:
        try:
            process = listener(service)
            label = "healthy" if process and healthy(service) else "stopped" if not process else "unhealthy"
            print(f"{service.name:18} {service.port:<6} {label:10} PID {process.pid if process else '-'}")
        except RuntimeError as exc:
            print(f"{service.name:18} {service.port:<6} {exc}")
    if healthy(SERVICES[-2]):
        try:
            data = http_json("http://127.0.0.1:18080/api/studio/state", authenticated=True)
            print(f"Loaded Decision Studio API version: {data.get('version', 'unknown')}")
        except (OSError, ValueError):
            print("Gateway online; API version unavailable (check token).")


def logs(args, directory, state):
    if not args.name:
        for row in state["processes"]:
            print(row["name"], row.get("stdout", "reused externally; use original launcher logs"), row.get("stderr", ""))
        return
    name = ALIASES.get(args.name, args.name)
    row = next((p for p in state["processes"] if p["name"] == name), None)
    if not row:
        raise RuntimeError(f"No service log record: {name}")
    paths = [Path(row[k]) for k in ("stdout", "stderr") if row.get(k) and Path(row[k]).is_file()]
    if not paths:
        print("Reused external service; consult the original launcher's logs.")
        return
    offsets = {}
    for path in paths:
        with path.open("rb") as stream:
            print(f"[{path.name}]", flush=True)
            # Read a bounded tail even when logs contain a large traceback/output.
            stream.seek(max(0, path.stat().st_size - 256 * 1024))
            print("\n".join(stream.read().decode("utf-8", errors="replace").splitlines()[-args.lines:]), flush=True)
            offsets[path] = stream.tell()
    while args.follow:
        time.sleep(.5)
        for path in paths:
            with path.open("rb") as stream:
                stream.seek(offsets[path] if path.stat().st_size >= offsets[path] else 0)
                chunk = stream.read()
                offsets[path] = stream.tell()
                if chunk:
                    print(chunk.decode("utf-8", errors="replace"), end="", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="AutoDecision local product launcher (Decision Studio :5178 by default).")
    parser.add_argument("action", choices=["up", "down", "restart", "status", "logs"])
    parser.add_argument("--python", default="", help="Python environment for Gateway and Core services")
    parser.add_argument("--dev", action="store_true", help="Use Decision Studio Vite hot reload; otherwise build and preview")
    parser.add_argument("--open", action="store_true", help="Open the frontend browser tab")
    parser.add_argument("--no-core", action="store_true", help="Gateway + frontend only")
    parser.add_argument("--frontend-only", action="store_true", help="Frontend only; no Python service dependency checks")
    parser.add_argument("--legacy-ui", action="store_true", help="Explicitly select legacy research UI on 5173")
    parser.add_argument("--only", default="", help="Operate on one service; frontend/ui aliases select new Decision Studio")
    parser.add_argument("--name", default="", help="Service name for logs")
    parser.add_argument("--lines", type=int, default=80)
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--wait", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        directory = state_directory()
        state = read_state(directory)
        services = selected_services(args)
        if args.action == "status":
            show_status(services)
        elif args.action == "logs":
            logs(args, directory, state)
        else:
            # Reject simultaneous launch/stop/restart processes before mutating state.
            directory.mkdir(parents=True, exist_ok=True)
            lock_path = directory / "studio-launcher.lock"
            with lock_path.open("a+b") as lock:
                lock.seek(0, 2)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                state = read_state(directory)
                if args.action == "restart":
                    dependencies(resolve_python(args.python) if any(s.module for s in services) else sys.executable, services)
                if args.action in {"down", "restart"}:
                    stop_services(services, directory, state)
                if args.action in {"up", "restart"}:
                    start_services(args, services, directory, state)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, psutil.Error) as exc:
        print(f"AutoDecision: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

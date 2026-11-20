"""Behavior checks for default UI routing, ownership and non-destructive lifecycle."""
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

SPEC = importlib.util.spec_from_file_location("studio_launcher", Path(__file__).parents[1] / "studio.py")
studio = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = studio
SPEC.loader.exec_module(studio)


def options(**extra):
    return SimpleNamespace(legacy_ui=False, only="", frontend_only=False, no_core=False,
                           python="", dev=True, open=False, **extra)


def test_default_product_is_studio_and_legacy_requires_explicit_selection():
    default = studio.selected_services(options())
    assert default[-1].directory == studio.ROOT / "frontend/decision-studio"
    assert default[-1].port == 5178
    assert all(s.port != 5173 for s in default)
    args = options()
    args.legacy_ui = True
    assert studio.selected_services(args)[-1] == studio.LEGACY
    args.legacy_ui = False
    args.no_core = True
    assert [s.port for s in studio.selected_services(args)] == [18080, 5178]


def test_cross_platform_root_start_and_stop_scripts_delegate_to_shared_manager():
    root = studio.ROOT
    assert "'scripts/studio.ps1'" in (root / "start.ps1").read_text(encoding="utf-8")
    assert "'scripts/studio.ps1'" in (root / "stop.ps1").read_text(encoding="utf-8")
    assert "Action = 'down'" in (root / "stop.ps1").read_text(encoding="utf-8")
    assert '"$SCRIPT_DIR/scripts/studio.sh" up "$@"' in (root / "start.sh").read_text(encoding="utf-8")
    assert '"$SCRIPT_DIR/scripts/studio.sh" down "$@"' in (root / "stop.sh").read_text(encoding="utf-8")


@pytest.mark.parametrize("alias", ["frontend", "frontend-ui", "ui", "studio", "decision-studio"])
def test_frontend_restart_aliases_all_target_new_product(alias):
    args = options()
    args.only = alias
    assert studio.selected_services(args) == [studio.SERVICES[-1]]


@pytest.mark.parametrize("version,expected", [
    ("20.18.0", False), ("20.19.0", True), ("21.0.0", False),
    ("22.11.0", False), ("22.12.0", True), ("24.0.0", True), ("25.2.1", True),
])
def test_node_matches_frontend_declared_engine(version, expected):
    assert studio.node_supported(version) == expected


def test_listener_identity_needs_repository_cwd_and_exact_module(tmp_path):
    service = studio.SERVICES[3]
    command = [sys.executable, "-m", "uvicorn", "app:app", "--port", "18080"]
    assert studio.process_matches(service, command, service.directory)
    assert not studio.process_matches(service, command, tmp_path)
    assert not studio.process_matches(service, [sys.executable, "-c", "print('app:app')"], service.directory)
    frontend = studio.SERVICES[-1]
    assert studio.process_matches(frontend, ["node", str(frontend.directory / "node_modules/vite/bin/vite.js")], frontend.directory)
    assert not studio.process_matches(frontend, ["node", str(studio.LEGACY.directory / "node_modules/vite/bin/vite.js")], frontend.directory)


def test_same_port_other_application_is_rejected(monkeypatch, tmp_path):
    service = studio.SERVICES[3]
    monkeypatch.setattr(studio.psutil, "net_connections", lambda **kw: [SimpleNamespace(
        status=studio.psutil.CONN_LISTEN, laddr=SimpleNamespace(port=18080), pid=123)])
    monkeypatch.setattr(studio.psutil, "Process", lambda pid: SimpleNamespace(
        cmdline=lambda: [sys.executable, "-m", "uvicorn", "app:app"], cwd=lambda: str(tmp_path)))
    with pytest.raises(RuntimeError, match="another process"):
        studio.listener(service)


def test_active_research_or_inference_blocks_backend_lifecycle(monkeypatch):
    monkeypatch.setattr(studio, "port_open", lambda port: True)
    def active_research(url, **kwargs):
        return [{"status": "running"}] if url.endswith("tasks") else {"invocations": []}
    monkeypatch.setattr(studio, "http_json", active_research)
    with pytest.raises(RuntimeError, match="Research is running"):
        studio.guard_active_work()
    def active_inference(url, **kwargs):
        return [] if url.endswith("tasks") else {"invocations": [{"status": "running"}]}
    monkeypatch.setattr(studio, "http_json", active_inference)
    with pytest.raises(RuntimeError, match="inference call"):
        studio.guard_active_work()


def test_stop_preflights_all_services_before_stopping_any(monkeypatch, tmp_path):
    stopped = []
    def owner(service):
        if service.name == "gateway-api":
            raise RuntimeError("another application")
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(studio, "listener", owner)
    monkeypatch.setattr(studio, "stop_process", lambda process: stopped.append(process.pid))
    with pytest.raises(RuntimeError, match="another application"):
        studio.stop_services(studio.SERVICES, tmp_path, {"processes": []})
    assert stopped == []


def test_frontend_shutdown_does_not_check_or_stop_research(monkeypatch, tmp_path):
    stopped = []
    monkeypatch.setattr(studio, "listener", lambda service: SimpleNamespace(pid=987))
    monkeypatch.setattr(studio, "guard_active_work", lambda: pytest.fail("frontend stop must not touch backend"))
    monkeypatch.setattr(studio, "stop_process", lambda process: stopped.append(process.pid))
    studio.stop_services([studio.SERVICES[-1]], tmp_path, {"processes": []})
    assert stopped == [987]


def test_state_is_scoped_to_repository_and_written_atomically(tmp_path):
    state = {"schema": 1, "root": str(studio.ROOT), "processes": [{"name": "decision-studio", "pid": 1}]}
    studio.write_state(tmp_path, state)
    assert studio.read_state(tmp_path) == state
    assert not list(tmp_path.glob("*.tmp"))
    state["root"] = str(tmp_path)
    (tmp_path / "studio-processes.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(RuntimeError, match="different repository"):
        studio.read_state(tmp_path)


def test_cli_down_does_not_need_configured_python(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTODECISION_LAUNCHER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(studio, "resolve_python", lambda *a: pytest.fail("shutdown does not launch Python"))
    monkeypatch.setattr(studio, "listener", lambda service: None)
    assert studio.main(["down", "--frontend-only"]) == 0


def test_backend_restart_refuses_missing_dependencies_before_stopping(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTODECISION_LAUNCHER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(studio, "resolve_python", lambda *a: sys.executable)
    def missing(*a):
        raise RuntimeError("missing runtime dependencies")
    monkeypatch.setattr(studio, "dependencies", missing)
    monkeypatch.setattr(studio, "stop_services", lambda *a: pytest.fail("must preflight before stopping"))
    assert studio.main(["restart", "--only", "gateway"]) == 1


def test_start_failure_stops_new_processes_and_restores_launcher_state(monkeypatch, tmp_path):
    reused = SimpleNamespace(pid=100, create_time=lambda: 1.0, cmdline=lambda: [], cwd=lambda: "")
    services = [
        studio.Service("existing", tmp_path / "existing", 18100, "existing:app"),
        studio.Service("new-api", tmp_path / "new", 18101, "new:app"),
        studio.Service("broken-api", tmp_path / "broken", 18102, "broken:app"),
    ]
    initial = {"schema": 1, "root": str(studio.ROOT), "processes": [
        {"name": "existing", "pid": 100, "created": 1.0, "port": 18100, "workdir": str(services[0].directory)}
    ]}
    state = json.loads(json.dumps(initial))
    stopped = []
    next_pid = iter((201, 202))

    class Child:
        def __init__(self, pid):
            self.pid = pid
        def poll(self):
            return 1 if self.pid == 202 else None

    class Process:
        def __init__(self, pid):
            self.pid = pid
        def create_time(self):
            return 2.0

    monkeypatch.setattr(studio, "resolve_python", lambda *a: "python")
    monkeypatch.setattr(studio, "dependencies", lambda *a: None)
    monkeypatch.setattr(studio.psutil, "Process", Process)
    monkeypatch.setattr(studio, "listener", lambda service: reused if service.name == "existing" else None)
    monkeypatch.setattr(studio, "healthy", lambda service: service.name != "broken-api")
    monkeypatch.setattr(studio.subprocess, "Popen", lambda *a, **k: Child(next(next_pid)))
    monkeypatch.setattr(studio, "stop_process", lambda process: stopped.append(process.pid))

    with pytest.raises(RuntimeError, match="broken-api failed to start"):
        studio.start_services(options(), services, tmp_path / "state", state)

    assert stopped == [202, 201]
    assert state == initial
    assert json.loads((tmp_path / "state" / "studio-processes.json").read_text()) == initial


def unknown_state_fixture(monkeypatch, *, service=None, command=None, cwd=None, rows=None, reachable=True):
    service = service or studio.SERVICES[0]
    command = command if command is not None else [sys.executable, "-m", "uvicorn", service.module, "--port", str(service.port)]
    process = SimpleNamespace(pid=123, cmdline=lambda: command, cwd=lambda: str(cwd or service.directory))
    connection = SimpleNamespace(status=studio.psutil.CONN_NONE,
        laddr=SimpleNamespace(ip="127.0.0.1", port=service.port), raddr=(), pid=123)
    monkeypatch.setattr(studio.sys, "platform", "win32")
    monkeypatch.setattr(studio.psutil, "net_connections", lambda **kwargs: rows if rows is not None else [connection])
    monkeypatch.setattr(studio.psutil, "Process", lambda pid: process)
    monkeypatch.setattr(studio, "port_open", lambda port: reachable)
    return service, process, connection


@pytest.mark.parametrize("state", [studio.psutil.CONN_NONE, studio.psutil.CONN_FIN_WAIT1,
                                 studio.psutil.CONN_CLOSE, studio.psutil.CONN_ESTABLISHED])
@pytest.mark.parametrize("frontend", [False, True])
@pytest.mark.parametrize("equals_port", [False, True])
def test_windows_unknown_socket_state_recognizes_exact_local_service(monkeypatch, frontend, equals_port, state):
    service = studio.SERVICES[-1] if frontend else studio.SERVICES[0]
    command = (["node", str(service.directory / "node_modules/vite/bin/vite.js"), "preview"] if frontend
               else [sys.executable, "-m", "uvicorn", service.module])
    command += [f"--port={service.port}"] if equals_port else ["--port", str(service.port)]
    _, process, row = unknown_state_fixture(monkeypatch, service=service, command=command)
    row.status = state
    assert studio.listener(service) is process


@pytest.mark.parametrize("reason", ["directory", "module", "port", "missing_port", "duplicate_port"])
def test_windows_unknown_socket_state_rejects_unverified_process(monkeypatch, tmp_path, reason):
    service = studio.SERVICES[0]
    command = [sys.executable, "-m", "uvicorn", service.module, "--port", str(service.port)]
    if reason == "module":
        command[3] = "other:app"
    elif reason == "port":
        command[-1] = "18102"
    elif reason == "missing_port":
        command = command[:-2]
    elif reason == "duplicate_port":
        command += ["--port", str(service.port)]
    unknown_state_fixture(monkeypatch, service=service, command=command, cwd=tmp_path if reason == "directory" else None)
    with pytest.raises(RuntimeError, match="another process"):
        studio.listener(service)


@pytest.mark.parametrize("reason", ["connected", "wrong_address", "missing_pid", "other_platform", "established", "not_in_table"])
def test_open_port_alone_never_confirms_windows_unknown_owner(monkeypatch, reason):
    service, _, row = unknown_state_fixture(monkeypatch)
    if reason == "connected":
        row.raddr = SimpleNamespace(ip="127.0.0.1", port=54321)
    elif reason == "wrong_address":
        row.laddr.ip = "192.0.2.1"
    elif reason == "missing_pid":
        row.pid = None
    elif reason == "other_platform":
        monkeypatch.setattr(studio.sys, "platform", "linux")
    elif reason == "established":
        row.status = studio.psutil.CONN_ESTABLISHED
        row.raddr = SimpleNamespace(ip="127.0.0.1", port=54321)
    else:
        monkeypatch.setattr(studio.psutil, "net_connections", lambda **kwargs: [])
    with pytest.raises(RuntimeError, match="Cannot verify owner"):
        studio.listener(service)


def test_windows_unknown_state_with_multiple_owners_still_blocks(monkeypatch):
    service, _, row = unknown_state_fixture(monkeypatch)
    other = SimpleNamespace(**{**vars(row), "pid":456})
    monkeypatch.setattr(studio.psutil, "net_connections", lambda **kwargs: [row, other])
    with pytest.raises(RuntimeError, match="multiple owners"):
        studio.listener(service)


def test_windows_bound_port_without_listener_is_not_adopted(monkeypatch):
    service, _, _ = unknown_state_fixture(monkeypatch, reachable=False)
    monkeypatch.setattr(studio.psutil, "Process", lambda pid: pytest.fail("unreachable bound port is not a listener"))
    assert studio.listener(service) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch entry points")
@pytest.mark.parametrize("folder", [".", "frontend/decision-studio"])
@pytest.mark.parametrize("action", ["start", "stop"])
def test_batch_entry_points_preserve_failures_after_pause(tmp_path, folder, action):
    wrapper = next(path for path in (studio.ROOT / folder).glob("*.cmd")
                   if f"{action}.ps1" in path.read_text(encoding="utf-8")
                   or f"{action}-studio.ps1" in path.read_text(encoding="utf-8"))
    # Run the real batch contents against a failing stub, never live services.
    # Closed stdin lets pause return immediately, reproducing the lost exit code.
    isolated_wrapper = tmp_path / wrapper.name
    isolated_wrapper.write_bytes(wrapper.read_bytes())
    target = f"{action}-studio.ps1" if folder != "." else f"{action}.ps1"
    (tmp_path / target).write_text("exit 23\n", encoding="utf-8")
    result = subprocess.run([str(isolated_wrapper)], cwd=tmp_path, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    assert result.returncode == 23, result.stdout.decode(errors="replace")

from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import app


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell and user32")
def test_windows_dialog_owner_type_compiles_with_system_forms_reference() -> None:
    command = "$ErrorActionPreference='Stop';" + app._windows_dialog_owner_powershell() + "Write-Output __OWNER_OK__"

    rc, out, err = app._run_powershell_hidden(command, timeout=30)

    assert rc == 0, err
    assert "__OWNER_OK__" in out


def test_windows_picker_binds_dialog_to_foreground_window(tmp_path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_run(command: str, timeout: int = 900):
        captured["command"] = command
        return 0, "__PICKED_PATH__C:\\selected", ""

    monkeypatch.setattr(app, "_run_powershell_hidden", fake_run)

    picked, status = app._pick_dir_windows_modern(str(tmp_path), "Choose input")

    assert picked == "C:\\selected"
    assert status == "selected"
    assert "GetForegroundWindow" in captured["command"]
    assert "SetForegroundWindow" in captured["command"]
    assert "ShowDialog($owner)" in captured["command"]
    assert "System.Windows.Forms.OpenFileDialog" in captured["command"]
    assert "$d.FileName='选择此文件夹'" in captured["command"]


def test_macos_picker_activates_native_dialog_and_escapes_text(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(app.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n", stderr="")

    monkeypatch.setattr(app.subprocess, "run", fake_run)

    picked, status = app._pick_dir_macos_osascript(str(tmp_path), 'Choose "input"')

    assert picked == str(tmp_path)
    assert status == "selected"
    script = captured["args"][2]
    assert 'tell application "System Events" to activate' in script
    assert 'Choose \\"input\\"' in script
    assert captured["kwargs"]["timeout"] == 900


def test_linux_picker_fails_fast_without_graphical_session(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(app.shutil, "which", lambda _name: "/usr/bin/zenity")

    picked, status = app._pick_dir_linux_zenity("/tmp", "Choose input")

    assert picked is None
    assert status == "unavailable"


def test_linux_kdialog_uses_existing_directory_api(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(app.shutil, "which", lambda name: "/usr/bin/kdialog" if name == "kdialog" else None)

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n", stderr="")

    monkeypatch.setattr(app.subprocess, "run", fake_run)

    picked, status = app._pick_dir_linux_kdialog(str(tmp_path), "Choose input")

    assert picked == str(tmp_path)
    assert status == "selected"
    assert captured["args"][:2] == ["/usr/bin/kdialog", "--getexistingdirectory"]


def test_directory_picker_endpoint_returns_platform_and_normalized_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        app,
        "_pick_directory_native",
        lambda initial_path, title: (str(tmp_path), "test-native", "selected"),
    )

    with TestClient(app.app) as client:
        response = client.post(
            "/api/fs/pick-directory",
            json={"initial_path": "", "title": "Choose input"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["path"] == str(tmp_path.resolve())
    assert payload["method"] == "test-native"
    assert payload["platform"] == app.sys.platform

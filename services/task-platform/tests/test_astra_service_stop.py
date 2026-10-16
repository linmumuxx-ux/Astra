"""受管进程的身份和停止。macOS 的 ps 不保留 venv Python / npm-cli.js 路径。"""

from __future__ import annotations

import importlib.util
import os
import signal
import socket
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SERVICE_SCRIPT = ROOT / "ops" / "dev" / "astra_service.py"


def _load_service_module():
    spec = importlib.util.spec_from_file_location("astra_service_stop_under_test", SERVICE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


service = _load_service_module()
FRAMEWORK_PYTHON = (
    "/opt/homebrew/Cellar/python@3.12/3.12.7/Frameworks/Python.framework/"
    "Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
)


def _settings(tmp_path: Path):
    from types import SimpleNamespace

    return SimpleNamespace(
        gateway_enabled=True,
        mcp_transport="streamable-http",
        resolved_runtime_dir=tmp_path / "run",
        resolved_log_dir=tmp_path / "logs",
    )


def _local_command(executable, args):
    return ["/usr/local/lib/node_modules/npm/bin/npm-cli.js", *args]


def _macos_ps(command: list[str]) -> str:
    name = Path(command[0]).name
    if name.lower() in service._GENERIC_EXECUTABLES or name == "Python":
        shown = FRAMEWORK_PYTHON
    elif name == "npm-cli.js":
        shown = "npm"
    else:
        shown = name
    return " ".join([shown, *command[1:]])


def _managed_commands(tmp_path: Path) -> dict[str, list[str]]:
    commands = {
        name: command
        for name, command, _cwd, _env in service.core_services(
            "dev", _settings(tmp_path), "npm", _local_command
        )
    }
    return commands


def test_macos_ps_matches_module_and_npm_script_not_argv0(tmp_path):
    commands = _managed_commands(tmp_path)
    assert set(commands) >= {
        "backend",
        "runtime-beat",
        "runtime-control",
        "runtime-agent",
        "library-mcp",
        "gateway",
        "frontend",
    }
    for name, command in commands.items():
        shown = _macos_ps(command)
        assert service.command_line_has_markers(command, shown), name
        if Path(command[0]).name.lower() in service._GENERIC_EXECUTABLES or command[0].endswith("npm-cli.js"):
            assert command[0] not in shown

    backend = commands["backend"]
    assert "Python" not in service.command_markers(backend)
    assert "python" not in service.command_markers(backend)
    assert not service.command_line_has_markers(backend, FRAMEWORK_PYTHON)

    frontend = commands["frontend"]
    assert "npm" not in service.command_markers(frontend)
    assert "npm-cli.js" not in service.command_markers(frontend)
    assert not service.command_line_has_markers(frontend, "npm")
    assert service.command_line_has_markers(frontend, "npm run dev -- --host 0.0.0.0 --port 5174")


def test_identity_uses_start_time_pgid_and_cwd(monkeypatch):
    command = service.backend_command("dev")
    info = {
        "pid": 9,
        "pgid": 9,
        "started_at": "Fri Oct 16 15:22:01 2026",
        "cwd": "/srv/backend",
        "command": command,
    }
    live = {
        "pgid": 9,
        "started_at": info["started_at"],
        "cwd": "/srv/backend",
        "command_line": _macos_ps(command),
    }
    monkeypatch.setattr(service, "process_exists", lambda pid: True)
    monkeypatch.setattr(service, "read_process_identity", lambda pid: dict(live))

    assert service.identify_process(info, 9) == "ours"
    live["started_at"] = "Fri Oct 16 15:22:02 2026"
    assert service.identify_process(info, 9) == "reused"
    live["started_at"] = info["started_at"]
    live["cwd"] = "/other/app"
    assert service.identify_process(info, 9) == "unknown"
    live["cwd"] = "/srv/backend"
    live["command_line"] = FRAMEWORK_PYTHON
    assert service.identify_process(info, 9) == "unknown"


def test_stop_keeps_state_and_does_not_signal_unconfirmed_processes(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    backend = {
        "pid": 4242,
        "pgid": 4242,
        "started_at": "ticks:10",
        "cwd": str(tmp_path),
        "command": service.backend_command("dev"),
        "log": str(tmp_path / "backend.log"),
    }
    frontend = {
        "pid": 4243,
        "pgid": 4243,
        "started_at": "ticks:11",
        "cwd": str(tmp_path),
        "command": service.frontend_command("dev", "npm", _local_command),
        "log": str(tmp_path / "frontend.log"),
    }
    service.save_state(settings, "dev", {"backend": backend, "frontend": frontend})
    monkeypatch.setattr(service, "process_exists", lambda pid: True)

    def identify(info, pid):
        return "ours" if pid == 4242 else "unknown"

    monkeypatch.setattr(service, "identify_process", identify)
    signaled: list[int] = []

    def refuse(info, **kwargs):
        signaled.append(int(info["pid"]))
        return False

    monkeypatch.setattr(service, "stop_managed", refuse)

    assert service.stop(settings) == 1
    remaining = service.managed_processes(settings)
    assert set(remaining) == {"backend", "frontend"}
    assert signaled == [4242]


def test_reused_pid_is_not_signaled(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    service.save_state(
        settings,
        "dev",
        {
            "gateway": {
                "pid": 50,
                "pgid": 50,
                "started_at": "ticks:1",
                "cwd": str(tmp_path),
                "command": service.gateway_command("dev"),
                "log": str(tmp_path / "gateway.log"),
            }
        },
    )
    monkeypatch.setattr(service, "process_exists", lambda pid: True)
    monkeypatch.setattr(service, "identify_process", lambda info, pid: "reused")

    def refuse(info, **kwargs):
        raise AssertionError("reused pid must not be signaled")

    monkeypatch.setattr(service, "stop_managed", refuse)
    assert service.stop(settings) == 0
    assert service.managed_processes(settings) == {}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until(predicate, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_real_stop_frees_port_and_start_can_bind_again(tmp_path, monkeypatch):
    script = tmp_path / "hold_port.py"
    script.write_text(
        "\n".join(
            [
                "import os",
                "import time",
                "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer",
                "",
                "port = int(__import__('sys').argv[2])",
                "",
                "class Handler(BaseHTTPRequestHandler):",
                "    def do_GET(self):",
                "        self.send_response(200)",
                "        self.end_headers()",
                "        self.wfile.write(b'ok')",
                "",
                "    def log_message(self, format, *args):",
                "        return",
                "",
                "pid = os.fork()",
                "if pid == 0:",
                "    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()",
                "while True:",
                "    time.sleep(1)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    port = _free_port()
    command = [sys.executable, str(script), "--port", str(port)]
    calls: list[tuple[int, int]] = []
    real_killpg = os.killpg

    def spy(pgid, sig):
        calls.append((pgid, sig))
        return real_killpg(pgid, sig)

    monkeypatch.setattr(service.os, "killpg", spy)
    info = None
    try:
        info = service.spawn(settings, "backend", command, tmp_path)
        assert info["pgid"] == info["pid"]
        assert str(info["started_at"]).startswith("ticks:")
        service.save_state(settings, "dev", {"backend": info})
        assert _wait_until(lambda: service.port_in_use(port))
        assert service.stop(settings) == 0
        assert calls[0] == (info["pgid"], signal.SIGTERM)
        assert not service.port_in_use(port)
        assert not service.state_path(settings).exists()
        assert not service.process_exists(int(info["pid"]))

        restarted = service.spawn(settings, "backend", command, tmp_path)
        info = restarted
        service.save_state(settings, "dev", {"backend": restarted})
        assert _wait_until(lambda: service.port_in_use(port))
        assert service.stop(settings) == 0
        assert not service.port_in_use(port)
    finally:
        if info and (service.process_exists(int(info["pid"])) or service.port_in_use(port)):
            service.stop_managed(info)


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_stop_kills_listener_after_leader_exits(tmp_path, monkeypatch):
    script = tmp_path / "hold_port.py"
    script.write_text(
        "\n".join(
            [
                "import os",
                "import time",
                "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer",
                "",
                "port = int(__import__('sys').argv[2])",
                "",
                "class Handler(BaseHTTPRequestHandler):",
                "    def do_GET(self):",
                "        self.send_response(200)",
                "        self.end_headers()",
                "",
                "    def log_message(self, format, *args):",
                "        return",
                "",
                "if os.fork() == 0:",
                "    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()",
                "while True:",
                "    time.sleep(1)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    port = _free_port()
    command = [sys.executable, str(script), "--port", str(port)]
    calls: list[tuple[int, int]] = []
    real_killpg = os.killpg

    def spy(pgid, sig):
        calls.append((pgid, sig))
        return real_killpg(pgid, sig)

    monkeypatch.setattr(service.os, "killpg", spy)
    info = None
    try:
        info = service.spawn(settings, "backend", command, tmp_path)
        assert info["pgid"] == info["pid"]
        service.save_state(settings, "dev", {"backend": info})
        assert _wait_until(lambda: service.port_in_use(port))
        os.kill(int(info["pid"]), signal.SIGKILL)
        os.waitpid(int(info["pid"]), 0)
        assert service.port_in_use(port)
        assert service.stop(settings) == 0
        assert calls[0] == (info["pgid"], signal.SIGTERM)
        assert not service.port_in_use(port)
        assert not service.state_path(settings).exists()
    finally:
        if info and service.port_in_use(port):
            service.stop_managed(info)

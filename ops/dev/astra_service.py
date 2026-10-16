#!/usr/bin/env python3
"""Astra unified service lifecycle entry."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "services" / "task-platform"
FRONTEND = ROOT / "web" / "nexus"

BACKEND_HOST = os.getenv("ASTRA_SERVICE_BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("ASTRA_SERVICE_BACKEND_PORT", "8100"))
FRONTEND_HOST = os.getenv("ASTRA_SERVICE_FRONTEND_HOST", "0.0.0.0")
FRONTEND_PORT = int(os.getenv("ASTRA_SERVICE_FRONTEND_PORT", "5174"))
# API 中转数据面是独立 ASGI 进程（app.gateway.server:app）。默认只监听 loopback，
# 由同机 nginx 反代 /v1；模型长连接绝不进入主 Backend。
GATEWAY_HOST = os.getenv("ASTRA_SERVICE_GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.getenv("ASTRA_SERVICE_GATEWAY_PORT", "8110"))
TASK_MCP_PORT = int(os.getenv("ASTRA_TASK_MCP_PORT", "8202"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Astra service lifecycle manager")
    parser.add_argument("mode", choices=("dev", "pro"), help="dev=development, pro=production")
    parser.add_argument(
        "action",
        nargs="?",
        default="start",
        choices=("start", "stop", "restart", "status"),
    )
    return parser.parse_args()


def load_astra(mode: str) -> tuple[Any, Any, Any, Any]:
    os.environ["ASTRA_ENVIRONMENT"] = "development" if mode == "dev" else "production"
    if mode == "pro":
        os.environ["ASTRA_SEED_DEMO"] = "false"

    sys.path.insert(0, str(BACKEND))
    from app.assistant.server import AssistantOpenCodeServerManager
    from app.config.settings import get_settings
    from app.executors.process import local_command
    from app.runtime.opencode_server import OpenCodeServerManager

    return get_settings(), OpenCodeServerManager, AssistantOpenCodeServerManager, local_command


def state_path(settings: Any) -> Path:
    return settings.resolved_runtime_dir / "astra-service.json"


def process_exists(pid: int) -> bool:
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def load_state(settings: Any) -> dict[str, Any]:
    path = state_path(settings)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(settings: Any, mode: str, processes: dict[str, dict[str, Any]]) -> None:
    path = state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "processes": processes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_state(settings: Any) -> None:
    path = state_path(settings)
    if path.exists():
        path.unlink()


def managed_processes(settings: Any) -> dict[str, dict[str, Any]]:
    processes = load_state(settings).get("processes", {})
    return processes if isinstance(processes, dict) else {}


def spawn(
    settings: Any,
    name: str,
    command: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    settings.resolved_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = settings.resolved_log_dir / f"{name}.log"
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True

    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env or os.environ.copy(),
            **options,
        )
    identity = read_process_identity(process.pid) or {}
    return {
        "pid": process.pid,
        "pgid": identity.get("pgid"),
        "started_at": identity.get("started_at"),
        "log": str(log_path),
        "command": command,
        "cwd": str(cwd),
    }


_GENERIC_EXECUTABLES = {
    "python",
    "python3",
    "pythonw",
    "node",
    "npm",
    "npm.cmd",
}


def command_markers(command: list[str] | None) -> list[str]:
    """识别参数，而不是 argv[0]。

    macOS 的 ps 会把 venv 里的 Python 显示成 Frameworks/.../Python，
    把 npm-cli.js 显示成 ``npm run ...``。只用可执行文件路径会把仍在运行的
    受管进程当成别人的进程。
    """

    if not command:
        return []
    markers: list[str] = []
    args = command[1:]
    for index, token in enumerate(args):
        if token in {"-m", "-A", "-c"} and index + 1 < len(args):
            markers.append(args[index + 1])
        elif token == "run" and index + 1 < len(args) and not args[index + 1].startswith("-"):
            markers.append("run")
            markers.append(args[index + 1])
        elif token in {"beat", "worker"}:
            markers.append(token)
        elif token.startswith("--queues="):
            markers.append(token.split("=", 1)[1])
        elif token == "--queues" and index + 1 < len(args):
            markers.append(args[index + 1])
        elif token.startswith("--hostname="):
            markers.append(token.split("=", 1)[1].split("@", 1)[0])
        elif token == "--hostname" and index + 1 < len(args):
            markers.append(args[index + 1].split("@", 1)[0])
        elif token.startswith("--schedule="):
            markers.append(Path(token.split("=", 1)[1]).name)
        elif token == "--port" and index + 1 < len(args):
            markers.append(args[index + 1])
        elif token.startswith("--port="):
            markers.append(token.split("=", 1)[1])
        elif ":" in token and not token.startswith(("-", "/", "\\")):
            markers.append(token)
        elif Path(token).suffix in {".py", ".js", ".mjs", ".cjs"}:
            markers.append(Path(token).name)
    if not markers:
        name = Path(command[0]).name
        if name and name.lower() not in _GENERIC_EXECUTABLES and name != "Python":
            markers.append(name)
    unique: list[str] = []
    for marker in markers:
        if marker and marker not in unique:
            unique.append(marker)
    return unique


def command_line_has_markers(command: list[str] | None, command_line: str) -> bool:
    markers = command_markers(command)
    return bool(markers) and all(marker in command_line for marker in markers)


def command_port(command: list[str] | None) -> int | None:
    if not command:
        return None
    args = command[1:]
    for index, token in enumerate(args):
        raw = ""
        if token == "--port" and index + 1 < len(args):
            raw = args[index + 1]
        elif token.startswith("--port="):
            raw = token.split("=", 1)[1]
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _same_dir(left: str, right: str) -> bool:
    try:
        return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        return left == right


def _proc_stat_fields(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    end = raw.rfind(")")
    if end == -1:
        return None
    return raw[end + 2 :].split()


def _process_started_at(pid: int) -> str | None:
    fields = _proc_stat_fields(pid)
    if fields is not None and len(fields) >= 20:
        return f"ticks:{fields[19]}"
    proc = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    value = (proc.stdout or "").strip()
    return value or None


def _process_cwd(pid: int) -> str | None:
    try:
        return os.path.realpath(f"/proc/{pid}/cwd")
    except OSError:
        pass
    if not shutil.which("lsof"):
        return None
    proc = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    for line in (proc.stdout or "").splitlines():
        if line.startswith("n"):
            try:
                return os.path.realpath(line[1:])
            except OSError:
                return line[1:]
    return None


def _process_command_line(pid: int) -> str:
    path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = path.read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        raw = ""
    if raw:
        return raw
    proc = subprocess.run(
        ["ps", "-p", str(pid), "-o", "args="],
        check=False,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def _process_pgid(pid: int) -> int | None:
    if os.name == "nt" or not hasattr(os, "getpgid"):
        return None
    try:
        return os.getpgid(pid)
    except (OSError, ProcessLookupError):
        return None


def read_process_identity(pid: int) -> dict[str, Any] | None:
    if not process_exists(pid):
        return None
    return {
        "pgid": _process_pgid(pid),
        "cwd": _process_cwd(pid),
        "started_at": _process_started_at(pid),
        "command_line": _process_command_line(pid),
    }


def _launch_fields_match(info: dict[str, Any], live: dict[str, Any]) -> bool:
    if not info.get("started_at") or live.get("started_at") != info.get("started_at"):
        return False
    if os.name == "nt":
        return True
    recorded_pgid = info.get("pgid")
    if recorded_pgid is None or live.get("pgid") != int(recorded_pgid):
        return False
    live_cwd = live.get("cwd")
    recorded_cwd = str(info.get("cwd") or "")
    return bool(live_cwd and recorded_cwd and _same_dir(str(live_cwd), recorded_cwd))


def _proves_reuse(info: dict[str, Any], live: dict[str, Any]) -> bool:
    """启动时刻或进程组变了，说明这个 PID 已经不是当时拉起的进程。"""

    if not info.get("started_at") or not live.get("started_at"):
        return False
    if live["started_at"] != info["started_at"]:
        return True
    if os.name == "nt":
        return False
    recorded_pgid = info.get("pgid")
    live_pgid = live.get("pgid")
    return recorded_pgid is not None and live_pgid is not None and int(recorded_pgid) != int(live_pgid)


def identify_process(info: dict[str, Any], pid: int) -> str:
    """返回 gone、ours、reused 或 unknown。unknown 不发送信号。"""

    if not process_exists(pid):
        return "gone"
    live = read_process_identity(pid)
    if live is None:
        return "unknown"
    markers_match = command_line_has_markers(info.get("command"), live["command_line"])
    if _launch_fields_match(info, live) and markers_match:
        return "ours"
    if _proves_reuse(info, live):
        return "reused"
    return "unknown"


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def _is_zombie(pid: int) -> bool:
    fields = _proc_stat_fields(pid)
    return bool(fields) and fields[0] == "Z"


def _leader_live(pid: int) -> bool:
    return process_exists(pid) and not _is_zombie(pid)


def _reap_owned(pid: int, pgid: int | None) -> None:
    """回收本进程拉起、尚未 wait 的子进程。其他进程拉起的服务由 init 回收。"""

    if os.name == "nt" or not hasattr(os, "waitpid"):
        return
    targets = [int(pid)]
    if pgid is not None:
        targets.append(-int(pgid))
    for target in targets:
        while True:
            try:
                reaped, _status = os.waitpid(target, os.WNOHANG)
            except ChildProcessError:
                break
            except InterruptedError:
                continue
            except OSError:
                break
            if reaped == 0:
                break


def _linux_group_members(pgid: int) -> list[int]:
    members: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return members
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        fields = _proc_stat_fields(int(entry.name))
        if not fields or len(fields) < 3 or fields[0] == "Z":
            continue
        try:
            if int(fields[2]) == pgid:
                members.append(int(entry.name))
        except ValueError:
            continue
    return members


def _ps_group_members(pgid: int) -> list[int]:
    proc = subprocess.run(
        ["ps", "-ax", "-o", "pid=,pgid=,state="],
        check=False,
        capture_output=True,
        text=True,
    )
    members: list[int] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            member = int(parts[0])
            group = int(parts[1])
        except ValueError:
            continue
        if group == pgid and not parts[2].startswith("Z"):
            members.append(member)
    return members


def _live_group_members(pgid: int) -> list[int]:
    if Path("/proc").is_dir():
        return _linux_group_members(pgid)
    return _ps_group_members(pgid)


def _group_alive(pgid: int) -> bool:
    return bool(_live_group_members(pgid))


def _recorded_pgid(info: dict[str, Any], pid: int | None = None) -> int | None:
    raw = info.get("pgid")
    if raw is None:
        return pid
    return int(raw)


def _signal_group(pgid: int, sig: int) -> bool:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True


def _wait_stopped(pid: int, pgid: int | None, port: int | None, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        _reap_owned(pid, pgid)
        leader_alive = _leader_live(pid)
        group_alive = pgid is not None and _group_alive(pgid)
        listening = port is not None and port_in_use(port)
        if not leader_alive and not group_alive and not listening:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def stop_managed(info: dict[str, Any], *, term_timeout: float = 5, kill_timeout: float = 2) -> bool:
    """向进程组发信号，并确认进程退出、监听端口释放。"""

    pid = int(info["pid"])
    port = command_port(info.get("command"))
    if os.name == "nt":
        if process_exists(pid):
            stop_pid(pid)
        return _wait_stopped(pid, None, port, timeout=term_timeout)
    pgid = _recorded_pgid(info, pid)
    assert pgid is not None
    _reap_owned(pid, pgid)
    if _leader_live(pid) or _group_alive(pgid):
        if not _signal_group(pgid, signal.SIGTERM):
            return False
        if _wait_stopped(pid, pgid, port, timeout=term_timeout):
            return True
        if not _signal_group(pgid, signal.SIGKILL):
            return False
    return _wait_stopped(pid, pgid, port, timeout=kill_timeout)


def stop_pid(pid: int) -> None:
    if not process_exists(pid):
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
        if not taskkill:
            raise RuntimeError("taskkill.exe not found")
        subprocess.run(
            [taskkill, "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    _signal_group(pid, signal.SIGTERM)


def rollback(processes: dict[str, dict[str, Any]]) -> None:
    for info in reversed(list(processes.values())):
        try:
            stop_managed(info)
        except Exception:
            pass


def run_checked(command: list[str], cwd: Path, title: str) -> None:
    print(f"[PREP] {title}")
    result = subprocess.run(command, cwd=cwd, env=os.environ.copy(), check=False)
    if result.returncode:
        raise RuntimeError(f"{title} failed (exit={result.returncode})")


def find_npm() -> str:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm not found; install Node.js 20+")
    return npm


def upstream_workspace_ui_version() -> str:
    """返回 workspace-ui 固定的上游 OpenCode 版本（UPSTREAM.json tag）。

    UPSTREAM.json 是固定上游 UI 产物的唯一来源；缺失或损坏时必须显式失败，
    不能静默跳过启动时的固定上游版本校验。
    """

    path = ROOT / "web" / "workspace-ui" / "UPSTREAM.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"workspace-ui upstream metadata unreadable: {path} ({exc})"
        ) from exc
    tag = data.get("tag") if isinstance(data, dict) else None
    version = str(tag).strip().removeprefix("v") if isinstance(tag, str) else ""
    if not version:
        raise RuntimeError(f"workspace-ui upstream metadata missing valid 'tag': {path}")
    return version


def ensure_workspace_ui_bundle(version: str | None) -> None:
    """运行中的 OpenCode 版本必须有对应的 Workspace UI，不能回落到 Nexus 页面。"""

    cleaned = str(version or "").strip().removeprefix("v")
    if not cleaned or cleaned == "unknown":
        raise RuntimeError("OpenCode did not report a version; cannot select a Workspace UI bundle")
    path = FRONTEND / "public" / "opencode-workspace" / cleaned / "index.html"
    if not path.is_file():
        raise RuntimeError(
            f"workspace-ui bundle missing for running OpenCode {cleaned}: {path}; "
            "restore the committed bundle from the repository, or rebuild that version "
            "with: node tools/e2e/workspace_ui.mjs build"
        )


def missing_workspace_ui_bundles(settings: Any) -> list[Path]:
    """返回启动所需但缺失的 OpenCode 版本化 Workspace UI 产物路径。

    Runtime 实际引用 ``/opencode-workspace/<version>/index.html``，因此只校验配置的
    默认版本与 UPSTREAM.json 固定版本，不额外维护版本清单。
    """

    versions: list[str] = []
    for value in (
        settings.opencode_workspace_ui_default_version,
        upstream_workspace_ui_version(),
    ):
        version = str(value or "").strip().removeprefix("v")
        if version and version not in versions:
            versions.append(version)
    bundles = FRONTEND / "public" / "opencode-workspace"
    return [
        bundles / version / "index.html"
        for version in versions
        if not (bundles / version / "index.html").is_file()
    ]


def validate_start(mode: str, settings: Any) -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("Astra requires Python 3.11+")
    if not ((ROOT / ".env").is_file() or (ROOT / "ops" / "env" / ".env").is_file()):
        raise RuntimeError("env file not found; expected ops/env/.env or .env")
    if not (FRONTEND / "node_modules").is_dir():
        raise RuntimeError("web dependencies missing; run: cd web/nexus && npm ci")
    missing = missing_workspace_ui_bundles(settings)
    if missing:
        detail = "; ".join(str(path) for path in missing)
        raise RuntimeError(
            f"workspace-ui bundle missing: {detail}; "
            "restore the committed bundle from the repository, or rebuild the "
            "configured upstream version with: node tools/e2e/workspace_ui.mjs build"
        )

    if mode == "pro":
        database_url = (settings.database_url or "").lower()
        sqlite = database_url.startswith("sqlite") if database_url else settings.database_backend == "sqlite"
        if sqlite:
            raise RuntimeError("production mode requires MySQL")
        if settings.executor_type != "opencode_server":
            raise RuntimeError("production mode requires ASTRA_EXECUTOR_TYPE=opencode_server")
        validate_gateway_production(settings)


def validate_gateway_production(settings: Any) -> None:
    """正式模式启用 API 中转时，强制校验数据面依赖，不靠回退掩盖缺失配置。"""

    if not settings.gateway_enabled:
        return
    if not settings.gateway_master_key:
        raise RuntimeError(
            "production mode requires ASTRA_GATEWAY_MASTER_KEY when API gateway is enabled"
        )
    if not (settings.redis_url or "").strip():
        raise RuntimeError(
            "API gateway requires a configured Redis (ASTRA_REDIS_URL); "
            "in-process counters are not a fallback"
        )


def prepare(mode: str, settings: Any, npm: str, local_command: Any) -> None:
    validate_start(mode, settings)
    run_checked([sys.executable, "-m", "alembic", "upgrade", "head"], BACKEND, "database migration")
    run_checked([sys.executable, str(ROOT / "ops" / "dev" / "preflight.py")], ROOT, "preflight")
    if mode == "pro":
        run_checked(local_command(npm, ["run", "build"]), FRONTEND, "frontend production build")
        if not (FRONTEND / "dist" / "index.html").is_file():
            raise RuntimeError("web/nexus/dist/index.html not found after build")


def http_ready(url: str, *, accept_http_error: bool = False) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        # Task MCP GET /mcp answers 406 unless the client accepts SSE.
        # That response still means the process is listening.
        return accept_http_error and exc.code < 500
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def wait_http(
    name: str,
    url: str,
    timeout: int = 45,
    *,
    accept_http_error: bool = False,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_ready(url, accept_http_error=accept_http_error):
            print(f"[READY] {name}: {url}")
            return
        time.sleep(0.25)
    raise RuntimeError(f"{name} not ready: {url}")


def wait_process(name: str, info: dict[str, Any]) -> None:
    time.sleep(0.5)
    if not process_exists(int(info["pid"])):
        raise RuntimeError(f"{name} exited; log={info['log']}")


def wait_worker(name: str, info: dict[str, Any], timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    log_path = Path(info["log"])
    while time.monotonic() < deadline:
        if not process_exists(int(info["pid"])):
            raise RuntimeError(f"{name} exited; log={log_path}")
        try:
            log = log_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            log = ""
        if "ready." in log:
            print(f"[READY] {name}")
            return
        time.sleep(0.5)
    raise RuntimeError(f"{name} not ready; log={log_path}")


def start_opencode(
    settings: Any,
    OpenCodeServerManager: Any,
    AssistantOpenCodeServerManager: Any,
    processes: dict[str, dict[str, Any]],
) -> None:
    if settings.executor_type == "opencode_server":
        manager = OpenCodeServerManager(settings)
        health = asyncio.run(manager.health())
        if not health.healthy and not settings.opencode_server_url:
            print("[START] opencode-server")
            processes["opencode-server"] = spawn(
                settings,
                "opencode-server",
                manager.command(),
                ROOT,
                env=manager.process_environment(),
            )
        health = asyncio.run(manager.wait_until_ready())
        ensure_workspace_ui_bundle(health.version)
        print(f"[READY] employee OpenCode Server ({health.version or 'unknown'})")

    if not settings.assistant_enabled:
        return

    assistant = AssistantOpenCodeServerManager(settings)
    health = asyncio.run(assistant.health())
    if health.healthy:
        print(f"[READY] assistant OpenCode Server ({health.version or 'unknown'})")
        return
    if settings.assistant_opencode_url:
        print(f"[WARN] external assistant OpenCode Server unavailable: {health.detail}")
        return

    try:
        print("[START] assistant-opencode")
        processes["assistant-opencode"] = spawn(
            settings,
            "assistant-opencode",
            assistant.command(),
            assistant.workspace,
            env=assistant.process_environment(),
        )
        health = asyncio.run(assistant.wait_until_ready())
        print(f"[READY] assistant OpenCode Server ({health.version or 'unknown'})")
    except Exception as exc:
        info = processes.pop("assistant-opencode", None)
        if info:
            stop_managed(info)
        print(f"[WARN] platform assistant degraded: {exc}")


def backend_command(mode: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        BACKEND_HOST,
        "--port",
        str(BACKEND_PORT),
    ]
    # Uvicorn's Windows reload subprocess can run under a launcher/event-loop
    # combination that cannot create asyncio subprocesses. Keep hot reload on
    # Unix, but use explicit "dev restart" on Windows.
    if mode == "dev" and os.name != "nt":
        command.append("--reload")
    return command


def gateway_command(mode: str) -> list[str]:
    """独立 Gateway 数据面进程：只承载 /v1 转发，与任务 Runtime 隔离。"""

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.gateway.server:app",
        "--host",
        GATEWAY_HOST,
        "--port",
        str(GATEWAY_PORT),
    ]
    if mode == "dev" and os.name != "nt":
        command.append("--reload")
    return command


def frontend_command(mode: str, npm: str, local_command: Any) -> list[str]:
    script = "dev" if mode == "dev" else "preview"
    return local_command(
        npm,
        ["run", script, "--", "--host", FRONTEND_HOST, "--port", str(FRONTEND_PORT)],
    )


def task_mcp_command() -> list[str]:
    """Task MCP 入口。优先用服务虚拟环境里的 astra-task-mcp。"""

    scripts = "Scripts" if os.name == "nt" else "bin"
    name = "astra-task-mcp.exe" if os.name == "nt" else "astra-task-mcp"
    binary = BACKEND / ".venv" / scripts / name
    if binary.is_file():
        return [str(binary)]
    return [sys.executable, "-c", "from app.task_mcp import main; main()"]


def core_services(
    mode: str,
    settings: Any,
    npm: str,
    local_command: Any,
) -> list[tuple[str, list[str], Path, dict[str, str] | None]]:
    """核心受管服务清单：Backend、Celery、Task MCP、可选 Library MCP/Gateway、Frontend。

    只组装命令，不做启动与就绪等待，便于脚本级校验。Gateway 仅在
    ``ASTRA_GATEWAY_ENABLED=true`` 时作为独立进程加入；长连接不进入 Backend。
    """

    schedule = settings.resolved_runtime_dir / "celerybeat-schedule"
    services: list[tuple[str, list[str], Path, dict[str, str] | None]] = [
        ("backend", backend_command(mode), BACKEND, None),
        (
            "runtime-beat",
            [
                sys.executable, "-m", "celery", "-A", "app.runtime.celery_app:celery",
                "beat", "--loglevel=INFO", f"--schedule={schedule}",
            ],
            BACKEND,
            None,
        ),
        (
            "runtime-control",
            [
                sys.executable, "-m", "celery", "-A", "app.runtime.celery_app:celery",
                "worker", "--loglevel=INFO", "--pool=solo", "--queues=control",
                "--hostname=astra-control@%h",
            ],
            BACKEND,
            None,
        ),
        (
            "runtime-agent",
            [
                sys.executable, "-m", "celery", "-A", "app.runtime.celery_app:celery",
                "worker", "--loglevel=INFO", "--pool=solo", "--queues=agent",
                "--hostname=astra-agent@%h",
            ],
            BACKEND,
            None,
        ),
    ]

    services.append(("task-mcp", task_mcp_command(), BACKEND, None))

    if settings.mcp_transport == "streamable-http":
        services.append(("library-mcp", [sys.executable, "-m", "app.mcp_server"], BACKEND, None))

    # 只加载最近已发布配置，启动时不发布草稿。
    if settings.gateway_enabled:
        services.append(("gateway", gateway_command(mode), BACKEND, None))

    frontend_env = os.environ.copy()
    frontend_env["VITE_PROXY_TARGET"] = f"http://127.0.0.1:{BACKEND_PORT}"
    frontend_env["VITE_GATEWAY_PROXY_TARGET"] = f"http://127.0.0.1:{GATEWAY_PORT}"
    services.append(
        ("frontend", frontend_command(mode, npm, local_command), FRONTEND, frontend_env)
    )
    return services


def start_core(
    mode: str,
    settings: Any,
    npm: str,
    local_command: Any,
    processes: dict[str, dict[str, Any]],
) -> None:
    services = core_services(mode, settings, npm, local_command)

    for name, command, cwd, env in services:
        print(f"[START] {name}")
        processes[name] = spawn(settings, name, command, cwd, env=env)
        wait_process(name, processes[name])

    wait_http("backend", f"http://127.0.0.1:{BACKEND_PORT}/api/health")
    wait_worker("runtime-control", processes["runtime-control"])
    wait_worker("runtime-agent", processes["runtime-agent"])
    if "gateway" in processes:
        wait_http("gateway", f"http://127.0.0.1:{GATEWAY_PORT}/healthz")
    if "task-mcp" in processes:
        wait_http(
            "task-mcp",
            f"http://127.0.0.1:{TASK_MCP_PORT}/mcp",
            accept_http_error=True,
        )
    wait_http("frontend", f"http://127.0.0.1:{FRONTEND_PORT}")


def status(settings: Any) -> int:
    state = load_state(settings)
    processes = state.get("processes", {})
    if not processes:
        print("Astra is not running.")
        return 1

    print(f"Astra mode: {state.get('mode', 'unknown')}")
    healthy = True
    for name, info in processes.items():
        running = process_exists(int(info["pid"]))
        healthy = healthy and running
        print(
            f"[{'RUNNING' if running else 'STOPPED':7}] "
            f"{name:<20} PID={info['pid']} LOG={info['log']}"
        )
    return 0 if healthy else 1


def stop(settings: Any) -> int:
    processes = managed_processes(settings)
    if not processes:
        clear_state(settings)
        print("Astra is not running.")
        return 0

    remaining: dict[str, dict[str, Any]] = {}
    for name, info in reversed(list(processes.items())):
        pid = int(info["pid"])
        pgid = _recorded_pgid(info)
        port = command_port(info.get("command"))
        _reap_owned(pid, pgid)
        if _leader_live(pid):
            verdict = identify_process(info, pid)
            if verdict == "reused":
                print(f"[SKIP] {name} PID={pid} belongs to a different process; not stopping it")
                continue
            if verdict == "unknown":
                print(f"[KEEP] {name} PID={pid} could not be confirmed as the managed process")
                remaining[name] = info
                continue
            if verdict == "ours":
                print(f"[STOP] {name} (PID={pid})")
                if not stop_managed(info):
                    print(f"[KEEP] {name} PID={pid} is still running")
                    remaining[name] = info
                continue
        # 组长已退出。组号等于组长 PID，组内还有进程时这个组号不可能被新会话复用。
        _reap_owned(pid, pgid)
        group_live = pgid == pid and _group_alive(pid)
        listening = port is not None and port_in_use(port)
        if group_live:
            print(f"[STOP] {name} (PID={pid})")
            if not stop_managed(info):
                print(f"[KEEP] {name} PID={pid} is still running")
                remaining[name] = info
            continue
        if listening:
            print(f"[KEEP] {name} PID={pid} exited but port {port} is still in use")
            remaining[name] = info
    if remaining:
        mode = str(load_state(settings).get("mode") or "dev")
        save_state(settings, mode, remaining)
        print("Astra did not stop completely.")
        return 1
    clear_state(settings)
    print("Astra stopped.")
    return 0


def _blocks_start(info: dict[str, Any]) -> bool:
    pid = int(info["pid"])
    pgid = _recorded_pgid(info)
    _reap_owned(pid, pgid)
    if _leader_live(pid):
        return identify_process(info, pid) in {"ours", "unknown"}
    if pgid == pid and _group_alive(pid):
        return True
    port = command_port(info.get("command"))
    return port is not None and port_in_use(port)


def start(
    mode: str,
    settings: Any,
    OpenCodeServerManager: Any,
    AssistantOpenCodeServerManager: Any,
    local_command: Any,
) -> int:
    existing = managed_processes(settings)
    if any(_blocks_start(info) for info in existing.values()):
        print("Astra already has managed services running; use restart.")
        return status(settings)

    clear_state(settings)
    processes: dict[str, dict[str, Any]] = {}
    try:
        npm = find_npm()
        prepare(mode, settings, npm, local_command)
        start_opencode(settings, OpenCodeServerManager, AssistantOpenCodeServerManager, processes)
        start_core(mode, settings, npm, local_command, processes)
        save_state(settings, mode, processes)
    except KeyboardInterrupt:
        print("\n[ERROR] startup interrupted; rolling back...")
        rollback(processes)
        clear_state(settings)
        return 130
    except Exception as exc:
        print(f"[ERROR] Astra startup failed: {exc}")
        rollback(processes)
        clear_state(settings)
        return 1

    print()
    print("=" * 64)
    print(f"Astra {mode.upper()} started")
    print(f"Console : http://localhost:{FRONTEND_PORT}")
    print(f"API     : http://localhost:{BACKEND_PORT}/api/health")
    print(f"Docs    : http://localhost:{BACKEND_PORT}/docs")
    if settings.gateway_enabled:
        print(f"Gateway : http://localhost:{GATEWAY_PORT}/v1/models")
    print(f"Task MCP: http://127.0.0.1:{TASK_MCP_PORT}/mcp")
    print(f"Logs    : {settings.resolved_log_dir}")
    print("=" * 64)
    return status(settings)


def main() -> int:
    args = parse_args()
    try:
        settings, OpenCodeServerManager, AssistantOpenCodeServerManager, local_command = load_astra(
            args.mode
        )
    except Exception as exc:
        print(f"[ERROR] failed to load Astra environment: {exc}")
        return 1

    if args.action == "status":
        return status(settings)
    if args.action == "stop":
        return stop(settings)
    if args.action == "restart":
        stopped = stop(settings)
        if stopped != 0:
            return stopped
    return start(
        args.mode,
        settings,
        OpenCodeServerManager,
        AssistantOpenCodeServerManager,
        local_command,
    )


if __name__ == "__main__":
    raise SystemExit(main())

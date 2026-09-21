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
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

BACKEND_HOST = os.getenv("ASTRA_SERVICE_BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("ASTRA_SERVICE_BACKEND_PORT", "8100"))
FRONTEND_HOST = os.getenv("ASTRA_SERVICE_FRONTEND_HOST", "0.0.0.0")
FRONTEND_PORT = int(os.getenv("ASTRA_SERVICE_FRONTEND_PORT", "5173"))


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
    return {
        "pid": process.pid,
        "log": str(log_path),
        "command": command,
        "cwd": str(cwd),
    }


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
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def rollback(processes: dict[str, dict[str, Any]]) -> None:
    for info in reversed(list(processes.values())):
        try:
            stop_pid(int(info["pid"]))
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


def validate_start(mode: str, settings: Any) -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("Astra requires Python 3.11+")
    if not (ROOT / ".env").is_file():
        raise RuntimeError("root .env not found")
    if not (FRONTEND / "node_modules").is_dir():
        raise RuntimeError("frontend dependencies missing; run: cd frontend && npm ci")
    if not (FRONTEND / "public" / "opencode-workspace" / "index.html").is_file():
        raise RuntimeError(
            "workspace-ui bundle missing; rebuild with: node scripts/workspace_ui.mjs build"
        )

    if mode == "pro":
        database_url = (settings.database_url or "").lower()
        sqlite = database_url.startswith("sqlite") if database_url else settings.database_backend == "sqlite"
        if sqlite:
            raise RuntimeError("production mode requires MySQL")
        if settings.executor_type != "opencode_server":
            raise RuntimeError("production mode requires ASTRA_EXECUTOR_TYPE=opencode_server")


def prepare(mode: str, settings: Any, npm: str, local_command: Any) -> None:
    validate_start(mode, settings)
    run_checked([sys.executable, "-m", "alembic", "upgrade", "head"], BACKEND, "database migration")
    run_checked([sys.executable, str(ROOT / "scripts" / "preflight.py")], ROOT, "preflight")
    if mode == "pro":
        run_checked(local_command(npm, ["run", "build"]), FRONTEND, "frontend production build")
        if not (FRONTEND / "dist" / "index.html").is_file():
            raise RuntimeError("frontend/dist/index.html not found after build")


def http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def wait_http(name: str, url: str, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_ready(url):
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
            stop_pid(int(info["pid"]))
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


def frontend_command(mode: str, npm: str, local_command: Any) -> list[str]:
    script = "dev" if mode == "dev" else "preview"
    return local_command(
        npm,
        ["run", script, "--", "--host", FRONTEND_HOST, "--port", str(FRONTEND_PORT)],
    )


def start_core(
    mode: str,
    settings: Any,
    npm: str,
    local_command: Any,
    processes: dict[str, dict[str, Any]],
) -> None:
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

    if settings.mcp_transport == "streamable-http":
        services.append(("library-mcp", [sys.executable, "-m", "app.mcp_server"], BACKEND, None))

    frontend_env = os.environ.copy()
    frontend_env["VITE_PROXY_TARGET"] = f"http://127.0.0.1:{BACKEND_PORT}"
    services.append(
        ("frontend", frontend_command(mode, npm, local_command), FRONTEND, frontend_env)
    )

    for name, command, cwd, env in services:
        print(f"[START] {name}")
        processes[name] = spawn(settings, name, command, cwd, env=env)
        wait_process(name, processes[name])

    wait_http("backend", f"http://127.0.0.1:{BACKEND_PORT}/api/health")
    wait_worker("runtime-control", processes["runtime-control"])
    wait_worker("runtime-agent", processes["runtime-agent"])
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

    for name, info in reversed(list(processes.items())):
        pid = int(info["pid"])
        if process_exists(pid):
            print(f"[STOP] {name} (PID={pid})")
            stop_pid(pid)
    clear_state(settings)
    print("Astra stopped.")
    return 0


def start(
    mode: str,
    settings: Any,
    OpenCodeServerManager: Any,
    AssistantOpenCodeServerManager: Any,
    local_command: Any,
) -> int:
    existing = managed_processes(settings)
    if any(process_exists(int(info["pid"])) for info in existing.values()):
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
        stop(settings)
    return start(
        args.mode,
        settings,
        OpenCodeServerManager,
        AssistantOpenCodeServerManager,
        local_command,
    )


if __name__ == "__main__":
    raise SystemExit(main())

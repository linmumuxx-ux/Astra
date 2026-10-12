#!/usr/bin/env python3
"""Run Astra's isolated system E2E without shell wrappers."""

from __future__ import annotations

import ctypes
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
FIXTURES = ROOT / "scripts" / "fixtures"

BACKEND_PORT = int(os.getenv("ASTRA_E2E_BACKEND_PORT", "18100"))
FRONTEND_PORT = int(os.getenv("ASTRA_E2E_FRONTEND_PORT", "15173"))


def free_port() -> int:
    configured = os.getenv("ASTRA_E2E_REDIS_PORT")
    if configured:
        return int(configured)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
        if taskkill:
            subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def spawn(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log: IO[bytes],
) -> subprocess.Popen[bytes]:
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        **options,
    )


def wait_url(name: str, url: str, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    print(f"{name} ready: {url}")
                    return
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError(f"{name} not ready within {timeout}s: {url}")


def wait_worker(name: str, process: subprocess.Popen[bytes], log_path: Path, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited; log={log_path}")
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if "ready." in text:
            print(f"{name} ready")
            return
        time.sleep(1)
    raise RuntimeError(f"{name} not ready within {timeout}s; log={log_path}")


def ping_redis(url: str) -> bool:
    from redis import Redis

    try:
        Redis.from_url(url, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


def wait_redis(url: str, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ping_redis(url):
            return
        time.sleep(1)
    raise RuntimeError("Redis did not become ready")


def npm_command(local_command, *args: str) -> list[str]:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm not found")
    return local_command(npm, list(args))


def fixture_path(run_dir: Path) -> Path:
    source = FIXTURES / "opencode"
    if os.name != "nt":
        return FIXTURES

    # Windows PATH cannot resolve the extensionless fixture. Create an isolated
    # wrapper for E2E only; no platform-specific wrapper is kept in the repository.
    bin_dir = run_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "opencode.cmd"
    wrapper.write_text(
        f'@"{sys.executable}" "{source}" %*\r\n',
        encoding="utf-8",
    )
    return bin_dir


def tail(path: Path, lines: int) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    from app.executors.process import local_command

    redis_server = os.getenv("ASTRA_REDIS_SERVER_BINARY") or shutil.which("redis-server")
    if not redis_server:
        raise RuntimeError("redis-server not found")

    if not (FRONTEND / "node_modules" / "@playwright" / "test").is_dir():
        raise RuntimeError("frontend dependencies missing; run: cd frontend && npm ci")

    redis_port = free_port()

    with tempfile.TemporaryDirectory(prefix="astra-e2e.") as temp:
        run_dir = Path(temp)
        logs = {
            name: run_dir / f"{name}.log"
            for name in ("redis", "backend", "beat", "control", "agent", "frontend")
        }
        handles: dict[str, IO[bytes]] = {}
        processes: dict[str, subprocess.Popen[bytes]] = {}
        success = False

        redis_url = f"redis://127.0.0.1:{redis_port}/0"
        workspace = run_dir / "workspaces" / "e2e-employee"
        workspace.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "PATH": os.pathsep.join((str(fixture_path(run_dir)), env.get("PATH", ""))),
                "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{(run_dir / 'astra-e2e.db').as_posix()}",
                "ASTRA_WORKSPACE_ROOT": str(run_dir / "workspaces"),
                "ASTRA_SEED_DEMO": "true",
                "ASTRA_ASSISTANT_ENABLED": "false",
                "ASTRA_REDIS_URL": redis_url,
                "ASTRA_EXECUTOR_TYPE": "opencode_cli_fallback",
                "ASTRA_SCOUT_INTERVAL": "3600",
                "ASTRA_DISPATCHER_INTERVAL": "1",
                "ASTRA_HEARTBEAT_INTERVAL": "1",
                "ASTRA_HEARTBEAT_TIMEOUT": "30",
                "ASTRA_RECOVERY_INTERVAL": "3600",
            }
        )

        def start(name: str, command: list[str], cwd: Path, extra_env: dict[str, str] | None = None):
            handle = logs[name].open("ab")
            handles[name] = handle
            process_env = env.copy()
            if extra_env:
                process_env.update(extra_env)
            processes[name] = spawn(command, cwd=cwd, env=process_env, log=handle)

        try:
            print("Starting isolated Astra E2E environment...")
            start(
                "redis",
                [
                    redis_server,
                    "--bind", "127.0.0.1",
                    "--port", str(redis_port),
                    "--save", "",
                    "--appendonly", "no",
                    "--dir", str(run_dir),
                ],
                ROOT,
            )
            wait_redis(redis_url)
            print(f"Redis ready: 127.0.0.1:{redis_port}")

            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND,
                env=env,
                check=True,
            )

            start(
                "backend",
                [
                    sys.executable, "-m", "uvicorn", "app.main:app",
                    "--host", "127.0.0.1", "--port", str(BACKEND_PORT),
                ],
                BACKEND,
            )
            wait_url("Backend", f"http://127.0.0.1:{BACKEND_PORT}/api/health")

            start(
                "beat",
                [
                    sys.executable, "-m", "celery", "-A", "app.runtime.celery_app:celery",
                    "beat", "--loglevel=INFO",
                    f"--schedule={run_dir / 'celerybeat-schedule'}",
                ],
                BACKEND,
            )
            start(
                "control",
                [
                    sys.executable, "-m", "celery", "-A", "app.runtime.celery_app:celery",
                    "worker", "--loglevel=INFO", "--pool=solo", "--queues=control",
                    "--hostname=astra-e2e-control@%h",
                ],
                BACKEND,
            )
            start(
                "agent",
                [
                    sys.executable, "-m", "celery", "-A", "app.runtime.celery_app:celery",
                    "worker", "--loglevel=INFO", "--pool=solo", "--queues=agent",
                    "--hostname=astra-e2e-agent@%h",
                ],
                BACKEND,
            )
            wait_worker("Control Worker", processes["control"], logs["control"])
            wait_worker("Agent Worker", processes["agent"], logs["agent"])

            start(
                "frontend",
                npm_command(
                    local_command,
                    "run", "dev", "--",
                    "--host", "127.0.0.1",
                    "--port", str(FRONTEND_PORT),
                ),
                FRONTEND,
                {"VITE_PROXY_TARGET": f"http://127.0.0.1:{BACKEND_PORT}"},
            )
            wait_url("Frontend", f"http://127.0.0.1:{FRONTEND_PORT}/")

            print("Running Chromium E2E...")
            playwright_env = env.copy()
            playwright_env.update(
                {
                    "E2E_EMPLOYEE_WORKSPACE": str(workspace),
                    "E2E_BASE_URL": f"http://127.0.0.1:{FRONTEND_PORT}",
                }
            )
            result = subprocess.run(
                npm_command(local_command, "run", "test:e2e"),
                cwd=FRONTEND,
                env=playwright_env,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"Playwright E2E failed (exit={result.returncode})")

            success = True
            print("E2E passed.")
            print("HTML report: frontend/artifacts/playwright-report/index.html")
            print("Machine-readable report: frontend/artifacts/test-results/results.json")
            return 0
        finally:
            for process in reversed(list(processes.values())):
                stop_process(process)
            for process in processes.values():
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            for handle in handles.values():
                handle.close()

            if not success:
                print("\nE2E failure logs:")
                for name, lines in (
                    ("backend", 80),
                    ("frontend", 80),
                    ("agent", 120),
                    ("control", 120),
                    ("beat", 80),
                    ("redis", 40),
                ):
                    text = tail(logs[name], lines)
                    if text:
                        print(f"\n--- {name} ---\n{text}")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.config.settings import get_settings
from app.executors.process import local_command
from app.runtime.opencode_server import OpenCodeServerManager

settings = get_settings()
PID_FILE = settings.resolved_runtime_dir / "processes.json"


def process_exists(pid: int) -> bool:
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def load_processes() -> dict[str, dict]:
    if not PID_FILE.is_file():
        return {}
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_processes(processes: dict[str, dict]) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(
        json.dumps(processes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def spawn(
    name: str,
    argv: list[str],
    cwd: Path,
    *,
    environment: dict[str, str] | None = None,
) -> dict:
    settings.resolved_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = settings.resolved_log_dir / f"{name}.log"
    creation_options = {}
    if os.name == "nt":
        creation_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        creation_options["start_new_session"] = True
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment or os.environ.copy(),
            **creation_options,
        )
    return {"pid": process.pid, "log": str(log_path), "command": argv, "cwd": str(cwd)}


def stop_pid(pid: int) -> None:
    if not process_exists(pid):
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
        if not taskkill:
            raise RuntimeError("Windows 上未找到 taskkill.exe，无法停止进程树")
        subprocess.run(
            [taskkill, "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return


def command_status() -> int:
    processes = load_processes()
    if not processes:
        print("Astra 没有由本启动器记录的运行进程。")
        return 1
    all_running = True
    for name, info in processes.items():
        running = process_exists(int(info["pid"]))
        all_running = all_running and running
        print(
            f"[{'运行中' if running else '已停止'}] {name}: PID={info['pid']} "
            f"日志={info['log']}"
        )
    return 0 if all_running else 1


def command_stop() -> int:
    processes = load_processes()
    for name, info in reversed(list(processes.items())):
        pid = int(info["pid"])
        stop_pid(pid)
        print(f"已停止 {name} (PID={pid})")
    if PID_FILE.exists():
        PID_FILE.unlink()
    return 0


def command_start() -> int:
    active = {
        name: info
        for name, info in load_processes().items()
        if process_exists(int(info["pid"]))
    }
    if active:
        print("Astra 已在运行，请先执行 stop。")
        command_status()
        return 1

    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if not npm:
        print("启动失败：未找到 npm。建议：安装 Node.js 20+ 并加入 PATH。")
        return 1
    if not (FRONTEND_ROOT / "dist" / "index.html").is_file():
        print(
            "启动失败：缺少前端生产构建。建议：先运行 Windows 安装脚本或 npm run build。"
        )
        return 1

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
    )

    processes: dict[str, dict] = {}
    if settings.executor_type == "opencode_server":
        manager = OpenCodeServerManager(settings)
        if not settings.opencode_server_url:
            processes["opencode-server"] = spawn(
                "opencode-server",
                manager.command(),
                PROJECT_ROOT,
                environment=manager.process_environment(),
            )
        try:
            health = asyncio.run(manager.wait_until_ready())
        except TimeoutError as exc:
            for info in reversed(list(processes.values())):
                stop_pid(int(info["pid"]))
            print(f"启动失败：OpenCode Server 未就绪：{exc}")
            return 1
        print(f"OpenCode Server 已就绪：{health.version or '未知版本'}")

    schedule_path = settings.resolved_runtime_dir / "celerybeat-schedule"
    processes.update(
        {
            "backend": spawn(
                "backend",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8100",
                ],
                BACKEND_ROOT,
            ),
            "runtime": spawn(
                "runtime",
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "app.runtime.celery_app:celery",
                    "worker",
                    "--beat",
                    "--loglevel=INFO",
                    "--pool=solo",
                    "--hostname=astra-runtime@%h",
                    f"--schedule={schedule_path}",
                ],
                BACKEND_ROOT,
            ),
            "frontend": spawn(
                "frontend",
                local_command(
                    npm,
                    ["run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"],
                ),
                FRONTEND_ROOT,
            ),
        }
    )
    save_processes(processes)
    time.sleep(1)
    print("Astra 已启动：http://localhost:5173")
    return command_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Astra 本地进程启停器")
    parser.add_argument("action", choices=("start", "stop", "status"))
    args = parser.parse_args()
    if args.action == "start":
        return command_start()
    if args.action == "stop":
        return command_stop()
    return command_status()


if __name__ == "__main__":
    raise SystemExit(main())

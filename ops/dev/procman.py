"""Cross-platform process start/stop for Astra services.

Uses the Python standard library plus psutil. Process identity is pid,
process-group id, psutil create_time, and cwd. Signaling uses
``subprocess.Popen(start_new_session=True)`` and ``os.killpg``. Health checks
use urllib and accept only HTTP 2xx. Port checks use a TCP connect.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import psutil

_CREATE_TIME_PLACES = 3


def format_create_time(value: float | str) -> str:
    return f"{float(value):.{_CREATE_TIME_PLACES}f}"


def create_times_match(recorded: Any, live: Any) -> bool:
    if recorded is None or live is None:
        return False
    try:
        return format_create_time(recorded) == format_create_time(live)
    except (TypeError, ValueError):
        return False


def process_exists(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except (psutil.Error, OSError, ValueError):
        return False


def is_zombie(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def leader_live(pid: int) -> bool:
    return process_exists(pid) and not is_zombie(pid)


def reap(pid: int, pgid: int | None) -> None:
    """Reap children this process started and has not waited on."""

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


def read_process_identity(pid: int) -> dict[str, Any] | None:
    try:
        proc = psutil.Process(pid)
        create_time = format_create_time(proc.create_time())
        try:
            cwd = os.path.realpath(proc.cwd())
        except (psutil.Error, OSError):
            cwd = None
    except psutil.Error:
        return None
    pgid = None
    if os.name != "nt" and hasattr(os, "getpgid"):
        try:
            pgid = os.getpgid(pid)
        except (OSError, ProcessLookupError):
            pgid = None
    return {"pgid": pgid, "cwd": cwd, "create_time": create_time}


def identify_process(info: dict[str, Any], pid: int) -> str:
    """Return gone, ours, reused, or unknown. unknown is not signaled."""

    if not process_exists(pid):
        return "gone"
    live = read_process_identity(pid)
    if live is None or live.get("create_time") is None:
        return "unknown"
    if not create_times_match(info.get("create_time"), live.get("create_time")):
        return "reused" if info.get("create_time") else "unknown"
    return "ours"


def command_port(command: list[str] | None) -> int | None:
    if not command:
        return None
    for index, token in enumerate(command[1:]):
        raw = ""
        if token == "--port" and index + 1 < len(command[1:]):
            raw = command[1:][index + 1]
        elif token.startswith("--port="):
            raw = token.split("=", 1)[1]
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def listening_port(info: dict[str, Any]) -> int | None:
    raw = info.get("port")
    if raw is not None and raw != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return command_port(info.get("command"))


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def group_alive(pgid: int) -> bool:
    if os.name == "nt" or not hasattr(os, "getpgid"):
        return False
    for proc in psutil.process_iter(["pid", "status"]):
        try:
            info = proc.info
            member = info.get("pid")
            if member is None or info.get("status") == psutil.STATUS_ZOMBIE:
                continue
            if os.getpgid(int(member)) == pgid:
                return True
        except (psutil.Error, OSError, ProcessLookupError, ValueError):
            continue
    return False


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
        reap(pid, pgid)
        leader = leader_live(pid)
        grouped = pgid is not None and group_alive(pgid)
        listening = port is not None and port_in_use(port)
        if not leader and not grouped and not listening:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def spawn_process(
    command: list[str],
    cwd: Path,
    log_path: Path,
    *,
    env: dict[str, str] | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
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
    record: dict[str, Any] = {
        "pid": process.pid,
        "pgid": identity.get("pgid"),
        "create_time": identity.get("create_time"),
        "cwd": identity.get("cwd") or str(cwd),
        "log": str(log_path),
        "command": command,
    }
    if port is not None:
        record["port"] = int(port)
    return record


def stop_managed(info: dict[str, Any], *, term_timeout: float = 5, kill_timeout: float = 2) -> bool:
    """Signal the process group after the caller has matched pid and create_time."""

    pid = int(info["pid"])
    port = listening_port(info)
    if os.name == "nt":
        if process_exists(pid):
            taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
            if not taskkill:
                return False
            subprocess.run(
                [taskkill, "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return _wait_stopped(pid, None, port, timeout=term_timeout)
    recorded = info.get("pgid")
    pgid = int(recorded) if recorded is not None else pid
    reap(pid, pgid)
    if leader_live(pid) or group_alive(pgid):
        if not _signal_group(pgid, signal.SIGTERM):
            return False
        if _wait_stopped(pid, pgid, port, timeout=term_timeout):
            return True
        if not _signal_group(pgid, signal.SIGKILL):
            return False
    return _wait_stopped(pid, pgid, port, timeout=kill_timeout)


def release_record(info: dict[str, Any], *, label: str) -> str:
    """Drop a confirmed-stopped or reused record. Keep anything still unconfirmed.

    A live pid is signaled only when its create_time matches the launch record.
    """

    pid = int(info["pid"])
    raw_pgid = info.get("pgid")
    pgid = int(raw_pgid) if raw_pgid is not None else None
    reap(pid, pgid)
    port = listening_port(info)
    if leader_live(pid):
        verdict = identify_process(info, pid)
        if verdict == "reused":
            print(f"[SKIP] {label} PID={pid} belongs to a different process; not stopping it")
            return "drop"
        if verdict != "ours":
            print(f"[KEEP] {label} PID={pid} could not be confirmed as the managed process")
            return "keep"
        print(f"[STOP] {label} (PID={pid})")
        if stop_managed(info):
            return "drop"
        print(f"[KEEP] {label} PID={pid} is still running")
        return "keep"
    reap(pid, pgid)
    group_live = pgid == pid and group_alive(pid)
    listening = port is not None and port_in_use(port)
    if group_live or listening:
        print(f"[KEEP] {label} PID={pid} exited but its group or port is still in use")
        return "keep"
    return "drop"


def http_status(url: str, *, headers: dict[str, str] | None = None, timeout: float = 2) -> int | None:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def http_ready(url: str, *, headers: dict[str, str] | None = None, timeout: float = 2) -> bool:
    status = http_status(url, headers=headers, timeout=timeout)
    return status is not None and 200 <= status < 300


def wait_http(
    name: str,
    url: str,
    timeout: float = 45,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_ready(url, headers=headers):
            print(f"[READY] {name}: {url}")
            return
        time.sleep(0.25)
    raise RuntimeError(f"{name} not ready: {url}")

"""Maintenance switch from the SSH tunnels to the intranet Gateway and MCP.

The Worker reads the two addresses from its own environment. A command payload
cannot supply them. OpenCode is reloaded only from this operation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from app.worker_agent.jsonc import loads_jsonc
from app.worker_agent.process_env import child_environ

_GATEWAY_ENV = "ASTRA_REMOTE_GATEWAY_URL"
_MCP_ENV = "ASTRA_MCP_RESOURCE_URL"
_DEFAULT_GATEWAY = "http://127.0.0.1:8110"
_DEFAULT_MCP = "http://127.0.0.1:8201/mcp"
_HEALTH_WAIT_SECONDS = 15
_EXIT_WAIT_SECONDS = 5
_UNIT_NAME = re.compile(r"^[A-Za-z0-9_:.@-]+$")

Probe = Callable[[str], bool]
Reload = Callable[[], None]
ReadEffective = Callable[[], dict]


def global_config_path(environ: dict[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    explicit = (env.get("OPENCODE_CONFIG") or "").strip()
    if explicit:
        return Path(explicit)
    home = env.get("XDG_CONFIG_HOME")
    if home:
        root = Path(home) / "opencode"
    else:
        root = Path(env.get("HOME") or str(Path.home())) / ".config" / "opencode"
    jsonc = root / "opencode.jsonc"
    legacy = root / "opencode.json"
    if jsonc.is_file() or not legacy.is_file():
        return jsonc
    return legacy


def direct_urls(environ: dict[str, str] | None = None) -> tuple[str, str]:
    env = environ if environ is not None else os.environ
    return env.get(_GATEWAY_ENV) or _DEFAULT_GATEWAY, env.get(_MCP_ENV) or _DEFAULT_MCP


def probe_url(url: str, *, timeout: float = 3) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1)
            return True
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _read_config(path: Path) -> dict:
    try:
        config = loads_jsonc(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("全局 OpenCode 配置不是有效 JSON，请人工处理，未覆盖配置") from exc
    if not isinstance(config, dict):
        raise RuntimeError("全局配置必须是 JSON 对象")
    return config


def write_direct_config(path: Path, *, gateway_url: str, mcp_url: str) -> None:
    """Replace only the two direct addresses. Keep the Gateway key and MCP token.

    An existing opencode.jsonc is merged. It is not a reason to stop.
    """

    jsonc = path if path.suffix == ".jsonc" else path.with_suffix(".jsonc")
    if jsonc.is_file():
        config = _read_config(jsonc)
        target = jsonc
        gateway = _mapping(_mapping(_mapping(config, "provider"), "astra-gateway"), "options")
        legacy_path = jsonc.with_suffix(".json")
        if gateway is None and legacy_path.is_file():
            legacy = _read_config(legacy_path)
            provider = _mapping(_mapping(legacy, "provider"), "astra-gateway")
            if isinstance(provider, dict):
                providers = config.get("provider")
                if not isinstance(providers, dict):
                    providers = {}
                    config["provider"] = providers
                providers["astra-gateway"] = provider
            library = _mapping(_mapping(legacy, "mcp"), "nexus-library")
            if isinstance(library, dict):
                mcp = config.get("mcp")
                if not isinstance(mcp, dict):
                    mcp = {}
                    config["mcp"] = mcp
                mcp.setdefault("nexus-library", library)
    elif path.is_file():
        config = _read_config(path)
        target = path
    else:
        raise RuntimeError("全局 OpenCode 配置不存在，未重载")
    options = _mapping(_mapping(_mapping(config, "provider"), "astra-gateway"), "options")
    library = _mapping(_mapping(config, "mcp"), "nexus-library")
    if options is None or "apiKey" not in options or "baseURL" not in options:
        raise RuntimeError("全局配置缺少 astra-gateway，未重载")
    if library is None or "url" not in library:
        raise RuntimeError("全局配置缺少 nexus-library，未重载")
    backup = target.with_name(target.name + ".astra-backup-switch")
    shutil.copy2(target if target.is_file() else path, backup)
    os.chmod(backup, 0o600)
    options["baseURL"] = gateway_url
    library["url"] = mcp_url
    temporary = target.with_name(target.name + ".tmp-switch")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def read_effective_config(port: int, workspace: str, *, timeout: float = 5) -> dict:
    """Read the running merge. A project opencode.json can override the global file."""

    query = urllib.parse.urlencode({"directory": workspace})
    request = urllib.request.Request(f"http://127.0.0.1:{port}/config?{query}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("读取生效配置失败") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("生效配置不是 JSON 对象")
    return payload


def _listener_pid(port: int) -> int | None:
    needle = f"{_ipv4_hex('127.0.0.1')}:{port:04X}"
    tcp = Path("/proc/net/tcp")
    try:
        lines = tcp.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    inode = None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[1].upper() != needle or fields[3] != "0A":
            continue
        inode = fields[9]
        break
    if inode is None:
        return None
    wanted = f"socket:[{inode}]"
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            descriptors = list(fd_dir.iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if target == wanted:
                return int(entry.name)
    return None


def restart_local_opencode(workspace: str, port: int, *, environ: dict[str, str] | None = None) -> None:
    folder = Path(workspace)
    if not folder.is_dir():
        raise RuntimeError("Workspace 不存在，未重载 OpenCode")
    if port < 1 or port > 65535:
        raise RuntimeError("OpenCode 端口无效")
    env = environ if environ is not None else os.environ
    unit = (env.get("ASTRA_WORKER_OPENCODE_UNIT") or "").strip()
    if unit:
        if _UNIT_NAME.fullmatch(unit) is None:
            raise RuntimeError("OpenCode systemd 单元名无效")
        completed = subprocess.run(
            ["systemctl", "restart", unit],
            check=False,
            capture_output=True,
            text=True,
            env=child_environ(env),
        )
        if completed.returncode != 0:
            raise RuntimeError("systemd 重载 OpenCode 失败")
        _wait_until_healthy(port)
        return
    pid = _listener_pid(port)
    if pid == os.getpid():
        raise RuntimeError("拒绝结束当前进程")
    if pid is not None:
        if not _opencode_listener(pid):
            raise RuntimeError("端口上的进程不是 OpenCode，未重载")
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + _EXIT_WAIT_SECONDS
        while time.monotonic() < deadline:
            if _listener_pid(port) is None:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("OpenCode 没有在时限内退出")
    binary = env.get("ASTRA_WORKER_OPENCODE_BIN") or "opencode"
    subprocess.Popen(
        [binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=folder,
        env=child_environ(env),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_until_healthy(port)


def _wait_until_healthy(port: int) -> None:
    health = f"http://127.0.0.1:{port}/global/health"
    deadline = time.monotonic() + _HEALTH_WAIT_SECONDS
    while time.monotonic() < deadline:
        if probe_url(health, timeout=0.5):
            return
        time.sleep(0.2)
    raise RuntimeError("OpenCode 重载后健康检查失败")


def _cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "replace")


def _parent_pid(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("PPid:"):
            return int(line.split()[1])
    return None


def _opencode_listener(pid: int) -> bool:
    """The listener is OpenCode itself, or a process OpenCode started."""

    current = pid
    seen: set[int] = set()
    while current and current > 1 and current not in seen:
        seen.add(current)
        command = _cmdline(current)
        if "opencode" in command and "serve" in command:
            return True
        parent = _parent_pid(current)
        if parent is None:
            return False
        current = parent
    return False


def apply_channel_switch(
    *,
    workspace: str,
    port: int,
    config_path: Path | None = None,
    environ: dict[str, str] | None = None,
    probe: Probe | None = None,
    reload: Reload | None = None,
    read_effective: ReadEffective | None = None,
) -> dict[str, str | bool]:
    gateway_url, mcp_url = direct_urls(environ)
    probe_fn = probe or probe_url
    for url in (gateway_url, mcp_url):
        if not probe_fn(url):
            raise RuntimeError("内网 Gateway 或 MCP 探测失败")
    path = config_path or global_config_path(environ)
    write_direct_config(path, gateway_url=gateway_url, mcp_url=mcp_url)
    if reload is None:
        restart_local_opencode(workspace, port, environ=environ)
    else:
        reload()
    effective = read_effective() if read_effective is not None else read_effective_config(port, workspace)
    return {
        "gateway_url": _address(effective, ("provider", "astra-gateway", "options", "baseURL")),
        "mcp_url": _address(effective, ("mcp", "nexus-library", "url")),
        "reloaded": True,
    }


def _mapping(value: object, key: str) -> dict | None:
    if not isinstance(value, dict):
        return None
    child = value.get(key)
    return child if isinstance(child, dict) else None


def _address(config: dict, path: tuple[str, ...]) -> str:
    current: object = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise RuntimeError("生效配置缺少 Gateway 或 MCP 地址")
        current = current[key]
    if not isinstance(current, str) or not current:
        raise RuntimeError("生效配置缺少 Gateway 或 MCP 地址")
    return current


def _ipv4_hex(address: str) -> str:
    parts = [int(part) for part in address.split(".")]
    return "".join(f"{part:02X}" for part in reversed(parts))

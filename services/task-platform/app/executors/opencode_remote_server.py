from __future__ import annotations

import asyncio
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from app.config.settings import Settings
from app.executors.base import ExecutorResult
from app.executors.opencode_server import (
    EventCallback,
    OpenCodeServerCapabilityError,
    OpenCodeServerClient,
    OpenCodeServerExecutor,
    OpenCodeServerUnavailable,
    SessionCallback,
)
from app.models import OpenCodeExecutionEnvironment, Task
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.ssh_client import SSHReverseTunnel, SSHSession, SSHTunnel

ClientFactory = Callable[[str], OpenCodeServerClient]


@dataclass
class _PersistentMcpTunnel:
    session: SSHSession
    tunnel: SSHReverseTunnel


_mcp_tunnels: dict[tuple[str, int, str, int], _PersistentMcpTunnel] = {}
_mcp_tunnel_locks: dict[tuple[str, int, str, int], asyncio.Lock] = {}


def _mcp_tunnel_key(
    environment: OpenCodeExecutionEnvironment, settings: Settings
) -> tuple[str, int, str, int]:
    return (
        str(environment.host),
        int(environment.port),
        str(environment.username),
        int(settings.mcp_port),
    )


async def ensure_remote_mcp_tunnel(
    environment: OpenCodeExecutionEnvironment,
    settings: Settings,
    runtime: ExecutionEnvironmentRuntime,
) -> str:
    """Keep the reverse MCP tunnel alive beyond any one OpenCode request."""

    return await _ensure_service_tunnel(
        environment, runtime, port=settings.mcp_port,
        public_url=settings.mcp_public_url, path=settings.mcp_streamable_http_path,
    )


async def ensure_remote_gateway_tunnel(environment, settings, runtime) -> str:
    if settings.remote_gateway_public_url:
        return settings.remote_gateway_public_url.rstrip("/") + "/v1"
    parsed = urlparse(settings.remote_gateway_local_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("REMOTE_GATEWAY_LOCAL_URL 必须为本机回环 HTTP 地址")
    return await _ensure_service_tunnel(
        environment, runtime, port=parsed.port or 80, public_url=None,
        path=parsed.path.rstrip("/") + "/v1",
    )


async def _ensure_service_tunnel(environment, runtime, *, port, public_url, path) -> str:
    if public_url:
        return public_url

    key = (str(environment.host), int(environment.port), str(environment.username), int(port))
    lock = _mcp_tunnel_locks.setdefault(key, asyncio.Lock())
    async with lock:
        existing = _mcp_tunnels.get(key)
        if existing and existing.session.is_active():
            return f"http://127.0.0.1:{port}{path}"
        if existing:
            try:
                await existing.tunnel.close()
            finally:
                await existing.session.close()
            _mcp_tunnels.pop(key, None)

        session = await runtime.open_session(environment)
        try:
            tunnel = await session.open_reverse_tunnel(
                remote_port=port,
                local_port=port,
            )
        except Exception:
            # Backend and Celery are separate processes. If another Astra process
            # already owns the same reverse forward, do not fail Runtime access;
            # verify that the expected remote loopback port is actually listening.
            code, _, _ = await session.run_command(
                "command -v ss >/dev/null 2>&1 && "
                f"ss -ltn 'sport = :{port}' | sed '1d' | grep -q ."
            )
            await session.close()
            if code == 0:
                return f"http://127.0.0.1:{port}{path}"
            raise
        _mcp_tunnels[key] = _PersistentMcpTunnel(session=session, tunnel=tunnel)
        return f"http://127.0.0.1:{port}{path}"


async def close_remote_mcp_tunnels() -> None:
    """Close process-owned reverse tunnels during a graceful service shutdown."""

    entries = list(_mcp_tunnels.values())
    _mcp_tunnels.clear()
    _mcp_tunnel_locks.clear()
    for entry in entries:
        try:
            await entry.tunnel.close()
        finally:
            await entry.session.close()


class RemoteOpenCodeServerConnection:
    """Own one SSH connection and a loopback tunnel to a Linux OpenCode Server."""

    def __init__(
        self,
        environment: OpenCodeExecutionEnvironment,
        settings: Settings,
        runtime: ExecutionEnvironmentRuntime,
        *,
        client_factory: ClientFactory | None = None,
    ):
        self.environment = environment
        self.settings = settings
        self.runtime = runtime
        self.client_factory = client_factory or (
            lambda base_url: OpenCodeServerClient(settings, base_url=base_url)
        )
        self.session: SSHSession | None = None
        self.tunnel: SSHTunnel | None = None
        self.client: OpenCodeServerClient | None = None

    async def __aenter__(self) -> OpenCodeServerClient:
        try:
            self.session = await self.runtime.open_session(self.environment)
            self.tunnel = await self.session.open_tunnel(
                remote_host="127.0.0.1",
                remote_port=self.environment.opencode_server_port,
            )
            self.client = self.client_factory(self.tunnel.base_url)
            # Keep the reverse MCP tunnel alive even though the workspace, not
            # Astra, owns the OpenCode config that references it.
            await ensure_remote_mcp_tunnel(
                self.environment,
                self.settings,
                self.runtime,
            )
            if (self.environment.model_name or "").startswith("astra-gateway/"):
                await ensure_remote_gateway_tunnel(self.environment, self.settings, self.runtime)
            try:
                await self.client.health()
            except (OpenCodeServerUnavailable, OpenCodeServerCapabilityError):
                await self._require_workspace_config(self.session)
                await self._start_server(self.session)
                await self._wait_until_ready(self.client)
            return self.client
        except Exception as exc:
            await self.close()
            raise RuntimeError(
                f"员工 {self.environment.employee_id}；环境 {self.environment.name} (LINUX_REMOTE)；"
                f"Workspace={self.environment.workspace_root}；"
                f"Server Port={self.environment.opencode_server_port}；启动方式=SSH；{exc}"
            ) from exc

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.close()

    async def close(self) -> None:
        try:
            if self.tunnel:
                await self.tunnel.close()
        finally:
            self.tunnel = None
            if self.session:
                await self.session.close()
                self.session = None

    async def _require_workspace_config(self, session: SSHSession) -> None:
        """Fail loudly when the remote workspace owns no OpenCode config.

        Astra no longer writes a temporary config or exports ``OPENCODE_CONFIG``;
        the workspace must provide providers/models/MCP itself.
        """
        workspace = shlex.quote(self.environment.workspace_root)
        exit_code, _, _ = await session.run_command(
            f"test -f {workspace}/opencode.json || "
            f"test -f {workspace}/opencode.jsonc || "
            f"test -f {workspace}/.opencode/opencode.json || "
            'test -f "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json" || '
            'test -f "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc"'
        )
        if exit_code != 0:
            raise RuntimeError(
                f"远程 Workspace 未提供 OpenCode 配置：{self.environment.workspace_root} "
                "及用户全局目录下无 opencode.json；请配置或执行一键部署后重试"
            )

    async def _start_server(self, session: SSHSession) -> None:
        port = self.environment.opencode_server_port
        binary = shlex.quote(self.environment.opencode_path)
        workspace = shlex.quote(self.environment.workspace_root)
        runtime_dir = f"/tmp/astra-opencode-server-$(id -u)-{port}"
        command = (
            "set -eu; umask 077; "
            'export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"; '
            f"runtime_dir={runtime_dir}; "
            'mkdir -p "$runtime_dir"; '
            f"mkdir -p {workspace}; cd {workspace}; "
            'if test -f "$runtime_dir/server.pid"; then '
            'old_pid=$(cat "$runtime_dir/server.pid"); '
            'case "$old_pid" in (*[!0-9]*|"") ;; (*) '
            'old_args=$(ps -p "$old_pid" -o args= 2>/dev/null || true); '
            'old_cwd=$(readlink "/proc/$old_pid/cwd" 2>/dev/null || true); '
            f'case "$old_args" in (*"serve --hostname 127.0.0.1 --port {port}") '
            'if test "$old_cwd" = "$(pwd -P)"; then kill "$old_pid" 2>/dev/null || true; '
            'sleep 1; fi ;; esac ;; esac; fi; '
            'if command -v ss >/dev/null 2>&1; then '
            f'if ss -ltn "sport = :{port}" | sed "1d" | grep -q .; then '
            f'echo "端口冲突：{port} 已被占用" >&2; exit 1; fi; fi; '
            f'nohup {binary} serve '
            f"--hostname 127.0.0.1 --port {port} "
            '>>"$runtime_dir/server.log" 2>&1 </dev/null & '
            'server_pid=$!; printf "%s\\n" "$server_pid" >"$runtime_dir/server.pid"'
        )
        exit_code, stdout, stderr = await session.run_command(command)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or f"退出码 {exit_code}"
            raise RuntimeError(f"远程 OpenCode Server 启动失败: {detail}")

    async def _wait_until_ready(self, client: OpenCodeServerClient) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.opencode_server_start_timeout_seconds
        last_error = "尚未检查"
        while asyncio.get_running_loop().time() < deadline:
            try:
                await client.health()
                return
            except OpenCodeServerCapabilityError:
                raise
            except Exception as exc:
                last_error = str(exc)
                await asyncio.sleep(0.2)
        detail = ""
        if self.session:
            _, detail, _ = await self.session.run_command(
                f'tail -c 2000 /tmp/astra-opencode-server-$(id -u)-'
                f'{self.environment.opencode_server_port}/server.log'
            )
        raise TimeoutError(
            f"远程 OpenCode Server 未就绪（请检查端口冲突与启动日志）: {last_error}；{detail}"
        )


class RemoteOpenCodeServerExecutor(OpenCodeServerExecutor):
    """Run the structured Server runtime on Linux through an SSH tunnel."""

    def __init__(
        self,
        environment: OpenCodeExecutionEnvironment,
        settings: Settings,
        runtime: ExecutionEnvironmentRuntime | None = None,
        *,
        event_callback: EventCallback | None = None,
        session_callback: SessionCallback | None = None,
        client_factory: ClientFactory | None = None,
    ):
        super().__init__(
            settings,
            model_name=environment.model_name,
            event_callback=event_callback,
            session_callback=session_callback,
        )
        self.environment = environment
        self.runtime = runtime or ExecutionEnvironmentRuntime(settings)
        self.client_factory = client_factory

    @property
    def remote_workspace(self) -> PurePosixPath:
        return PurePosixPath(self.environment.workspace_root)

    def connection(self) -> RemoteOpenCodeServerConnection:
        return RemoteOpenCodeServerConnection(
            self.environment,
            self.settings,
            self.runtime,
            client_factory=self.client_factory,
        )

    async def start(self, task: Task, _workspace: Path) -> ExecutorResult:
        return await self._execute_remote(task)

    async def _execute_remote(
        self,
        task: Task,
        *,
        session_id: str | None = None,
    ) -> ExecutorResult:
        original_client = self.client
        async with self.connection() as client:
            self.client = client
            try:
                return await self._execute(task, self.remote_workspace, session_id=session_id)
            finally:
                self.client = original_client

    async def abort_session(self, session_id: str) -> bool:
        async with self.connection() as client:
            return await client.abort(self.remote_workspace, session_id)


async def test_remote_server(
    environment: OpenCodeExecutionEnvironment,
    settings: Settings,
    runtime: ExecutionEnvironmentRuntime,
) -> tuple[bool, str]:
    """Probe only: an absent Serve does not invalidate an SSH environment."""
    session = None
    tunnel = None
    try:
        session = await runtime.open_session(environment)
        tunnel = await session.open_tunnel(
            remote_host="127.0.0.1", remote_port=environment.opencode_server_port,
        )
        client = OpenCodeServerClient(settings, base_url=tunnel.base_url)
        health = await client.health()
        return True, f"OpenCode {health.get('version') or 'unknown'} · SSH loopback tunnel"
    except OpenCodeServerUnavailable:
        return True, "Serve 未启动或不可访问；任务执行时将自动检测并启动"
    except Exception as exc:
        return False, str(exc)
    finally:
        if tunnel:
            await tunnel.close()
        if session:
            await session.close()

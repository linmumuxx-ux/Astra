from __future__ import annotations

import asyncio
import shlex
from collections.abc import Callable
from pathlib import Path, PurePosixPath

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
from app.models import OpenCodeExecutionEnvironment, Run, Task
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.ssh_client import SSHSession, SSHTunnel

ClientFactory = Callable[[str], OpenCodeServerClient]


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
            try:
                await self.client.health()
            except (OpenCodeServerUnavailable, OpenCodeServerCapabilityError):
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

    async def _start_server(self, session: SSHSession) -> None:
        port = self.environment.opencode_server_port
        binary = shlex.quote(self.environment.opencode_path)
        workspace = shlex.quote(self.environment.workspace_root)
        command = (
            "set -eu; umask 077; "
            f"runtime_dir=/tmp/astra-opencode-server-$(id -u)-{port}; "
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
            f'if ss -ltnH "sport = :{port}" | grep -q .; then '
            f'echo "端口冲突：{port} 已被占用" >&2; exit 1; fi; fi; '
            f"nohup {binary} serve --hostname 127.0.0.1 --port {port} "
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

    async def resume(self, task: Task, run: Run, _workspace: Path) -> ExecutorResult:
        session_id = task.opencode_session_id or run.opencode_session_id
        return await self._execute_remote(task, session_id=session_id)

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

    async def abort(self, run: Run) -> None:
        active = self._active.get(run.task_id)
        if active:
            await self.client.abort(active[1], active[0])
        elif run.opencode_session_id:
            await self.abort_session(run.opencode_session_id)

    async def get_status(self, run: Run) -> str:
        if not run.opencode_session_id:
            return run.status
        async with self.connection() as client:
            status = await client.status(self.remote_workspace, run.opencode_session_id)
        return status.upper()

    async def collect_result(self, run: Run) -> dict:
        existing = run.result or {}
        if existing.get("work_result") or not run.opencode_session_id:
            return existing
        async with self.connection() as client:
            messages = await client.messages(self.remote_workspace, run.opencode_session_id)
        raw_text = self._last_assistant_message(messages)
        return {**existing, "raw_text": raw_text} if raw_text else existing


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

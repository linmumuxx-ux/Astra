"""Server transport and task directory binding; no execution state or message storage."""

from __future__ import annotations

import asyncio
import shlex
from contextlib import asynccontextmanager
from pathlib import Path

from app.config.settings import get_settings
from app.domain import ExecutionMode
from app.executors.opencode_local_server import LocalOpenCodeServerExecutor
from app.executors.opencode_remote_server import RemoteOpenCodeServerConnection
from app.executors.opencode_server import OpenCodeServerClient
from app.models import OpenCodeExecutionEnvironment, Task
from app.runtime.environment import ExecutionEnvironmentRuntime, environment_from_snapshot


async def session_tree(client, directory: Path, root: str) -> set[str]:
    """Return the native root Session plus all current descendants."""

    allowed, pending = {root}, [root]
    while pending:
        children = await client.children(directory, pending.pop())
        for child in children:
            child_id = child.get("id")
            if child_id and child_id not in allowed:
                allowed.add(child_id)
                pending.append(child_id)
    return allowed


async def resolve_environment(session, task: Task):
    snapshot = task.execution_environment_snapshot
    if not snapshot:
        raise ValueError("任务尚未绑定执行环境")
    environment = environment_from_snapshot(snapshot, task.employee_id)
    stored = await session.get(OpenCodeExecutionEnvironment, snapshot["environment_id"])
    if stored:
        environment.ssh_password = stored.ssh_password
    return environment


@asynccontextmanager
async def connect(environment, *, start: bool = False):
    settings = get_settings()
    if environment.mode == ExecutionMode.LOCAL:
        if start:
            await LocalOpenCodeServerExecutor(environment, settings).ensure_ready()
        yield OpenCodeServerClient(settings, base_url=f"http://127.0.0.1:{environment.opencode_server_port}")
        return
    runtime = ExecutionEnvironmentRuntime(settings)
    if start:
        async with RemoteOpenCodeServerConnection(environment, settings, runtime) as client:
            yield client
        return
    ssh = await runtime.open_session(environment)
    tunnel = None
    try:
        tunnel = await ssh.open_tunnel(remote_host="127.0.0.1", remote_port=environment.opencode_server_port)
        yield OpenCodeServerClient(settings, base_url=tunnel.base_url)
    finally:
        if tunnel:
            await tunnel.close()
        await ssh.close()


async def prepare_workspace(task: Task, environment) -> str:
    """Each task owns one directory; a repository gets a native Git worktree."""
    if task.workspace:
        return task.workspace
    settings = get_settings()
    root = (
        str(settings.employee_workspace_path(environment.workspace_root).resolve())
        if (environment.mode == ExecutionMode.LOCAL)
        else environment.workspace_root
    )
    target = str(Path(root).parent / ".astra-tasks" / environment.employee_id / task.id)
    if environment.mode == ExecutionMode.LOCAL:
        if not Path(root).is_dir():
            raise FileNotFoundError(f"Workspace 不存在：{root}")
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        probe = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            root,
            "rev-parse",
            "--show-toplevel",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await probe.communicate()
        if probe.returncode == 0:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                root,
                "worktree",
                "add",
                "--detach",
                target,
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, error = await process.communicate()
            if process.returncode:
                raise RuntimeError(error.decode(errors="replace"))
        else:
            Path(target).mkdir(exist_ok=False)
    else:
        command = (
            f"test -d {shlex.quote(root)} && mkdir -p {shlex.quote(str(Path(target).parent))} && "
            f"if git -C {shlex.quote(root)} rev-parse --show-toplevel >/dev/null 2>&1; then "
            f"git -C {shlex.quote(root)} worktree add --detach {shlex.quote(target)} HEAD; "
            f"else mkdir {shlex.quote(target)}; fi"
        )
        code, _, error = await ExecutionEnvironmentRuntime(settings).run_remote(environment, command)
        if code:
            raise RuntimeError(error)
    return target

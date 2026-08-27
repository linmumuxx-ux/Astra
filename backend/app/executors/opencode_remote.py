import asyncio
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.executors.base import ExecutorResult
from app.executors.opencode_cli import OpenCodeCLIExecutor
from app.models import OpenCodeExecutionEnvironment, Run, Task
from app.runtime.environment import ExecutionEnvironmentRuntime


class RemoteOpenCodeExecutor(OpenCodeCLIExecutor):
    def __init__(
        self,
        environment: OpenCodeExecutionEnvironment,
        settings: Settings,
        runtime: ExecutionEnvironmentRuntime | None = None,
        event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ):
        super().__init__(
            settings,
            opencode_binary=environment.opencode_path,
            event_callback=event_callback,
        )
        self.environment = environment
        self.runtime = runtime or ExecutionEnvironmentRuntime(settings)

    async def _execute(self, task: Task, workspace: Path, *, session_id: str | None = None) -> ExecutorResult:
        remote_command = shlex.join(self._command(task, workspace, session_id))
        process = await asyncio.create_subprocess_exec(
            *self.runtime.ssh_prefix(self.environment),
            remote_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return await self._communicate(task, process, session_id=session_id)

    async def resume(self, task: Task, run: Run, workspace: Path) -> ExecutorResult:
        return await super().resume(task, run, workspace)

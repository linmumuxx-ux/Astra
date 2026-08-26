import asyncio
import json
from pathlib import Path
from typing import Any

from app.config.settings import Settings, get_settings
from app.executors.base import ExecutorResult, OpenCodeExecutor
from app.models import Run, Task


class OpenCodeCLIExecutor(OpenCodeExecutor):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _prompt(self, task: Task, workspace: Path, *, retry: bool = False) -> str:
        dod = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(task.definition_of_done))
        retry_text = (
            "\n这是同一任务的修复重试。请基于当前 Workspace 和原 OpenCode Session 分析失败证据，"
            "做最小修复并重新执行。" if retry else ""
        )
        return f"""当前任务：
{task.id}

任务来源：
{task.source}

任务目标：
{task.title}

任务描述：
{task.description}

任务输入：
{json.dumps(task.input, ensure_ascii=False, indent=2)}

工作目录：
{workspace}

完成标准：
{dod or '按任务输入中的验证契约完成并产生真实执行证据。'}

请优先使用项目已有 Skill、Command 和工具完成实际操作。不要只输出分析或建议。
不得自行把任务标记为完成；Astra Verifier 会独立执行确定性验证。
无法继续时，请明确返回 BLOCKED 并说明需要人工补充的内容。{retry_text}
"""

    def _command(self, task: Task, workspace: Path, session_id: str | None = None) -> list[str]:
        source_dir = workspace / "source"
        command = [
            self.settings.opencode_binary,
            "run",
            "--format",
            "json",
            "--dir",
            str(source_dir),
            "--title",
            f"Astra {task.id}",
            "--agent",
            self.settings.opencode_agent,
        ]
        if self.settings.opencode_model:
            command.extend(["--model", self.settings.opencode_model])
        if session_id:
            command.extend(["--session", session_id])
        command.append(self._prompt(task, workspace, retry=bool(session_id)))
        return command

    @staticmethod
    def _extract_session(value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("sessionID", "session_id", "sessionId"):
                if value.get(key):
                    return str(value[key])
            for child in value.values():
                found = OpenCodeCLIExecutor._extract_session(child)
                if found:
                    return found
        if isinstance(value, list):
            for child in value:
                found = OpenCodeCLIExecutor._extract_session(child)
                if found:
                    return found
        return None

    async def _execute(
        self, task: Task, workspace: Path, *, session_id: str | None = None
    ) -> ExecutorResult:
        process = await asyncio.create_subprocess_exec(
            *self._command(task, workspace, session_id),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[task.id] = process
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self.settings.opencode_timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return ExecutorResult(status="BLOCKED", exit_code=124, stderr="OpenCode execution timeout")
        finally:
            self._processes.pop(task.id, None)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        output: list[dict[str, Any]] = []
        detected_session = session_id
        for line in stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"type": "text", "text": line}
            output.append(payload)
            detected_session = detected_session or self._extract_session(payload)

        combined = f"{stdout}\n{stderr}".upper()
        status = (
            "BLOCKED"
            if "BLOCKED" in combined
            else ("SUCCEEDED" if process.returncode == 0 else "FAILED")
        )
        return ExecutorResult(
            status=status,
            exit_code=process.returncode or 0,
            session_id=detected_session,
            output=output,
            stdout=stdout,
            stderr=stderr,
        )

    async def start(self, task: Task, workspace: Path) -> ExecutorResult:
        return await self._execute(task, workspace)

    async def resume(self, task: Task, run: Run, workspace: Path) -> ExecutorResult:
        session_id = task.opencode_session_id or run.opencode_session_id
        return await self._execute(task, workspace, session_id=session_id)

    async def get_status(self, run: Run) -> str:
        process = self._processes.get(run.task_id)
        if not process:
            return run.status
        return "RUNNING" if process.returncode is None else "FINISHED"

    async def abort(self, run: Run) -> None:
        process = self._processes.get(run.task_id)
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()

    async def collect_result(self, run: Run) -> dict[str, Any]:
        return run.result or {}

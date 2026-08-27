import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.config.settings import Settings, get_settings
from app.executors.base import ExecutorResult, OpenCodeExecutor
from app.executors.usage import parse_opencode_usage
from app.models import Run, Task


class OpenCodeCLIExecutor(OpenCodeExecutor):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        opencode_binary: str | None = None,
        model_name: str | None = None,
        event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ):
        self.settings = settings or get_settings()
        self.opencode_binary = opencode_binary or self.settings.opencode_binary
        self.model_name = model_name or self.settings.opencode_model
        self.event_callback = event_callback
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _prompt(self, task: Task, workspace: Path, *, retry: bool = False) -> str:
        criteria = "\n".join(
            f"{item.get('id', f'AC-{index + 1:02d}')}. {item.get('content', '')}"
            for index, item in enumerate(task.acceptance_criteria or [])
        )
        human_input = (task.human_intervention or {}).get("response")
        suspension = task.suspension or {}
        review = (task.review_history or [])[-1] if task.review_history else {}
        retry_text = ""
        if retry:
            retry_text = "\n这是同一任务继续处理，请使用当前执行会话中的已有上下文。"
            if human_input:
                retry_text += f"\n人工补充信息：\n{human_input}"
        context_text = ""
        if task.current_progress:
            context_text += f"\n已保留的当前进展：\n{task.current_progress}"
        if suspension.get("scene_context"):
            context_text += f"\n挂起时现场上下文：\n{suspension['scene_context']}"
        if review.get("feedback"):
            context_text += f"\n上次结果被退回的意见：\n{review['feedback']}"
        if human_input and not retry:
            context_text += f"\n人工补充信息：\n{human_input}"
        return f"""当前任务：
{task.id}

任务来源：
{task.source}

任务目标：
{task.title}

任务描述：
{task.description}

员工工作空间：
{workspace}

验收标准：
{criteria}

请在该工作空间内自主决定完成方式。Astra 不规定你使用的 Agent、Skill、Tool、命令、
检查方式或内部步骤。请在完成后如实说明处理结果，并逐项说明验收标准是否满足及相关证据。
当任务必须询问使用者、等待业务答案、权限或其他人工输入时，不要猜测或自行跳过。
请在可读说明后返回以下结构，`requested_input` 必须是一个可直接回答的具体问题：
ASTRA_INTERVENTION_JSON: {{"blocking_reason":"为什么需要人工输入",
"completed_work":"已完成的工作","current_state":"当前保留状态",
"requested_input":"需要请使用者回答的具体问题"}}
不要同时返回完成结果。其他无法继续的场景也使用该结构说明阻塞原因和所需输入。

最终回复末尾必须追加以下 JSON；ASTRA_RESULT_JSON 标记与 JSON 开头
保持在同一行，且每个验收项都必须选择一个确切结论：
ASTRA_RESULT_JSON: {{"summary":"面向使用者的结果摘要","changes":[],"files":[],"commits":[],
"logs":[],"attachments":[],"other":{{}},"acceptance_results":[{{"criterion_id":"AC-01",
"status":"SATISFIED 或 UNSATISFIED 或 UNCONFIRMED","description":"结论说明","evidence":[]}}]}}
不要省略或改写 ASTRA_RESULT_JSON 标记。{context_text}{retry_text}
"""

    def _command(self, task: Task, workspace: Path, session_id: str | None = None) -> list[str]:
        command = [
            self.opencode_binary,
            "run",
            "--format",
            "json",
            "--dir",
            str(workspace),
            "--title",
            f"Astra {task.id}",
        ]
        if self.settings.opencode_agent:
            command.extend(["--agent", self.settings.opencode_agent])
        if self.model_name:
            command.extend(["--model", self.model_name])
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

    async def _communicate(
        self,
        task: Task,
        process: asyncio.subprocess.Process,
        *,
        session_id: str | None = None,
    ) -> ExecutorResult:
        self._processes[task.id] = process
        stdout_lines: list[bytes] = []
        stderr_chunks: list[bytes] = []
        output: list[dict[str, Any]] = []
        detected_session = session_id

        async def read_stdout() -> None:
            nonlocal detected_session
            assert process.stdout is not None
            while line := await process.stdout.readline():
                stdout_lines.append(line)
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {"type": "text", "text": text}
                output.append(payload)
                detected_session = detected_session or self._extract_session(payload)
                if self.event_callback:
                    try:
                        await self.event_callback(payload)
                    except Exception:
                        # Observation must never interrupt the employee's work.
                        pass

        async def read_stderr() -> None:
            assert process.stderr is not None
            while chunk := await process.stderr.read(4096):
                stderr_chunks.append(chunk)

        try:
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr(), process.wait()),
                timeout=self.settings.opencode_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return ExecutorResult(status="BLOCKED", exit_code=124, stderr="Agent execution timeout")
        finally:
            self._processes.pop(task.id, None)

        stdout = b"".join(stdout_lines).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        combined = f"{stdout}\n{stderr}".upper()
        blocked_markers = (
            "BLOCKED",
            "ASTRA_INTERVENTION_JSON:",
            "PERMISSION REQUESTED",
            "PERMISSION DENIED",
            "AUTO-REJECTING",
        )
        status = (
            "BLOCKED"
            if any(marker in combined for marker in blocked_markers)
            else ("SUCCEEDED" if process.returncode == 0 else "FAILED")
        )
        token_usage, tool_usage, model_name = parse_opencode_usage(output)
        return ExecutorResult(
            status=status,
            exit_code=process.returncode or 0,
            session_id=detected_session,
            output=output,
            stdout=stdout,
            stderr=stderr,
            model_name=model_name,
            token_usage=token_usage,
            tool_usage=tool_usage,
        )

    async def _execute(self, task: Task, workspace: Path, *, session_id: str | None = None) -> ExecutorResult:
        process = await asyncio.create_subprocess_exec(
            *self._command(task, workspace, session_id),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return await self._communicate(task, process, session_id=session_id)

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

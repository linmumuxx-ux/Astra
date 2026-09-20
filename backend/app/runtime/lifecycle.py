"""Task business lifecycle backed by one native OpenCode Session.

There is no Run execution state machine, event mirror, or message database here.
The only retained outbound content is an unacknowledged submission, cleared on ACK.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from time import time_ns

from sqlalchemy import or_, select, update
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.domain import EmployeeStatus, RuntimeSessionStatus, SessionTerminalReason, TaskStatus
from app.event_bus import event_bus
from app.executors.errors import OpenCodeExecutionError, OpenCodeSessionNotFound
from app.executors.opencode_prompt import (
    bind_task_prompt_context,
    build_task_prompt,
    resolve_task_prompt_context,
)
from app.executors.usage import parse_opencode_usage
from app.models import DigitalEmployee, RuntimeSession, Task, TaskCategory
from app.runtime.environment import environment_snapshot
from app.runtime.runtime_context import (
    build_runtime_context_part,
    generate_runtime_context,
    hash_runtime_context,
    runtime_context_id,
)
from app.runtime.session_connection import connect, prepare_workspace, resolve_environment
from app.runtime.session_state import SessionState, derive_session_state
from app.runtime.summary import TaskSummaryService, extract_final_assistant_text
from app.runtime.workspace_files import materialize_task_attachments
from app.services import TaskService

logger = logging.getLogger(__name__)

_TERMINAL_SESSION_STATUSES = {
    RuntimeSessionStatus.SUCCEEDED.value,
    RuntimeSessionStatus.FAILED.value,
    RuntimeSessionStatus.INTERRUPTED.value,
}


def message_id():
    # Native OpenCode messages are ordered lexically by their 48-bit time prefix.
    stamp = ((time_ns() // 1_000_000) * 0x1000) & ((1 << 48) - 1)
    return f"msg_{stamp:012x}{token_hex(7)}"


class RuntimeStateError(ValueError):
    pass


class RuntimeService:
    def __init__(self, session):
        self.session = session

    async def lock_task(self, task_id):
        task = await self.session.scalar(
            select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True)
        )
        if not task:
            raise RuntimeStateError("任务不存在")
        return task

    async def project(self, task, status, *, detail=None):
        status = TaskStatus(status)
        if status == TaskStatus.RUNNING and task.status != status:
            task.turn_started_at = datetime.now(UTC)
        if task.status != status:
            await TaskService(self.session).transition(
                task,
                status,
                current_progress=detail,
                commit=False,
            )
        if task.employee_id:
            employee = await self.session.get(DigitalEmployee, task.employee_id)
            if employee:
                active = await self.session.scalar(
                    select(Task.id)
                    .where(
                        Task.employee_id == employee.id,
                        or_(
                            Task.status.in_([TaskStatus.RUNNING, TaskStatus.WAITING]),
                            Task.pending_message_id.is_not(None),
                        ),
                    )
                    .limit(1)
                )
                employee.current_task_count = int(bool(active))
                if active:
                    employee.status = (
                        EmployeeStatus.WAIT_HUMAN if status == TaskStatus.WAITING else EmployeeStatus.WORKING
                    )
                elif employee.status in {EmployeeStatus.WORKING, EmployeeStatus.WAIT_HUMAN}:
                    employee.status = EmployeeStatus.IDLE
        if status == TaskStatus.RUNNING:
            # A reopened task invalidates its previous final summary.
            await TaskSummaryService(self.session).mark_stale(task, commit=False)
        await self.session.commit()
        await event_bus.publish({"type": "TASK_STATUS", "task_id": task.id, "status": task.status})

    async def _runtime_session(self, task: Task) -> RuntimeSession | None:
        if not task.current_session_id:
            return None
        return await self.session.get(RuntimeSession, task.current_session_id)

    async def _sync_session_state(self, task: Task, state: SessionState) -> RuntimeSession | None:
        """Persist the derived OpenCode outcome on the bound RuntimeSession."""
        runtime_session = await self._runtime_session(task)
        if not runtime_session:
            return None
        now = datetime.now(UTC)
        runtime_session.status = state.status
        runtime_session.terminal_reason = state.terminal_reason
        runtime_session.finish_reason = state.finish_reason
        if state.last_message_id:
            runtime_session.last_message_id = state.last_message_id
        runtime_session.last_activity_at = now
        if state.status in _TERMINAL_SESSION_STATUSES:
            runtime_session.finished_at = state.finished_at or now
        elif state.status in {
            RuntimeSessionStatus.RUNNING.value,
            RuntimeSessionStatus.WAITING.value,
        }:
            # finished_at only ever holds the current terminal time.
            runtime_session.finished_at = None
        return runtime_session

    async def _update_session_usage(self, task: Task, messages: list[dict]) -> None:
        """Store aggregate token/tool counters derived from native messages."""
        runtime_session = await self._runtime_session(task)
        if not runtime_session:
            return
        # parse_opencode_usage consumes one event per message info (tokens/model)
        # plus one event per part (tool calls); native messages group both.
        events: list[dict] = []
        for message in messages:
            info = message.get("info") if isinstance(message.get("info"), dict) else {}
            events.append({"info": info})
            for part in message.get("parts", []):
                if isinstance(part, dict):
                    events.append({"part": part})
        token_usage, tools, model_name = parse_opencode_usage(events)
        runtime_session.input_tokens = token_usage.input_tokens
        runtime_session.output_tokens = token_usage.output_tokens
        runtime_session.cache_read_tokens = token_usage.cache_read_tokens
        runtime_session.cache_write_tokens = token_usage.cache_write_tokens
        runtime_session.total_tokens = token_usage.total_tokens
        runtime_session.llm_call_count = token_usage.llm_call_count
        if tools:
            runtime_session.tool_usage = [
                {
                    "tool_name": item.name,
                    "call_count": item.call_count,
                    "success_count": item.success_count,
                    "failure_count": item.failure_count,
                    "duration_ms": item.duration_ms,
                }
                for item in tools
            ]
            runtime_session.tool_call_count = sum(item.call_count for item in tools)
        if model_name:
            runtime_session.model_name = model_name

    async def apply_session_state(
        self, task: Task, state: SessionState, *, final_text: str | None = None
    ) -> None:
        """Persist one derived Session outcome, project it, and summarize terminals."""
        await self._sync_session_state(task, state)
        await self._project_session_state(task, state)
        if state.status in {
            RuntimeSessionStatus.SUCCEEDED.value,
            RuntimeSessionStatus.FAILED.value,
        } or state.terminal_reason == SessionTerminalReason.TIMEOUT.value:
            await TaskSummaryService(self.session).upsert(
                task,
                source_status=task.status,
                primary_session_id=task.current_session_id,
                summary_text=final_text or "",
            )
            if state.status == RuntimeSessionStatus.SUCCEEDED.value:
                await self._reconcile_experience(task)
            await self._extract_experience(task)

    async def _reconcile_experience(self, task: Task) -> None:
        """Only a successful source Session verifies its submitted candidates."""
        from app.library_service import KnowledgeService

        await KnowledgeService(self.session).reconcile_session_verification(
            task.current_session_id
        )

    async def _extract_experience(self, task: Task) -> None:
        """Terminal experience extraction is best-effort and never changes Task outcome."""
        from app.runtime.experience import ExperienceExtractionService

        try:
            await ExperienceExtractionService(self.session).extract(task.id)
        except Exception:
            logger.exception("Experience extraction failed for task %s", task.id)
            await self.session.rollback()

    async def _project_session_state(self, task: Task, state: SessionState) -> None:
        """The single Session -> Task mapping. Never changes status on UNKNOWN."""
        if state.status == RuntimeSessionStatus.RUNNING.value:
            task.failure_reason = None
            task.execution_error = None
            await self.project(task, TaskStatus.RUNNING)
        elif state.status == RuntimeSessionStatus.WAITING.value:
            await self.project(task, TaskStatus.WAITING)
        elif state.status == RuntimeSessionStatus.SUCCEEDED.value:
            task.failure_reason = None
            task.execution_error = None
            await self.project(task, TaskStatus.SUCCEEDED)
        elif state.status == RuntimeSessionStatus.FAILED.value:
            message = task.failure_reason or {
                SessionTerminalReason.ASSISTANT_ERROR.value: "OpenCode Assistant 返回原生执行错误",
                SessionTerminalReason.NO_REPLY.value: "OpenCode Session 已空闲且超过等待窗口，当前 Turn 无 Assistant 回复",
            }.get(state.terminal_reason, "OpenCode Session 执行失败")
            task.failure_reason = message
            task.execution_error = {
                "code": state.terminal_reason or "session_failed",
                "message": message,
                "source": "opencode_session",
                "session_id": task.current_session_id,
            }
            await self.project(task, TaskStatus.FAILED)
        elif state.status == RuntimeSessionStatus.INTERRUPTED.value:
            if state.terminal_reason == SessionTerminalReason.TIMEOUT.value:
                message = "执行达到配置的时间上限，已停止当前 OpenCode Session"
                task.failure_reason = message
                task.execution_error = {
                    "code": SessionTerminalReason.TIMEOUT.value,
                    "message": message,
                    "source": "opencode_session",
                    "session_id": task.current_session_id,
                }
                await self.project(task, TaskStatus.FAILED)
            else:
                await self.session.commit()
        else:
            await self.session.commit()

    async def _supersede_session(self, old_id: str | None, new_id: str, *, interrupted: bool) -> None:
        if not old_id or old_id == new_id:
            return
        old = await self.session.get(RuntimeSession, old_id)
        if not old:
            return
        if old.status not in _TERMINAL_SESSION_STATUSES:
            old.status = RuntimeSessionStatus.INTERRUPTED.value
            old.terminal_reason = SessionTerminalReason.ABORTED.value
            old.finished_at = datetime.now(UTC)
        old.superseded_by = new_id
        old.superseded_at = datetime.now(UTC)

    async def _wait_for_session_stop(self, client, directory: Path, session_id: str) -> None:
        """Abort, then wait until the old Session can no longer write the workspace."""
        timeout = get_settings().opencode_restart_abort_timeout_seconds
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                status = await client.status(directory, session_id)
            except OpenCodeSessionNotFound:
                return
            if status not in {"busy", "retry"}:
                return
            await asyncio.sleep(0.2)
        raise RuntimeStateError("旧 Session 未在超时时间内停止，未创建新 Session")

    async def start(self, task_id: str, *, restart: bool = False):
        task = await self.lock_task(task_id)
        if task.current_session_id and not restart:
            raise RuntimeStateError("任务已有 Session，请在 Workspace 中继续；重新开始需显式创建新 Session")
        if task.status == TaskStatus.RUNNING and not restart:
            raise RuntimeStateError("任务仍在运行，请在 Workspace 中继续；重新开始需显式创建新 Session")
        if task.pending_message_id:
            raise RuntimeStateError("任务有未确认的输入，请先停止或重连")
        employee = await self.session.scalar(
            select(DigitalEmployee)
            .where(
                DigitalEmployee.id == task.employee_id,
            )
            .options(selectinload(DigitalEmployee.execution_environment))
            .with_for_update()
        )
        if not employee or not employee.enabled or not employee.execution_environment:
            raise RuntimeStateError("请先分配已配置运行环境的员工")
        occupied = await self.session.scalar(
            select(Task.id)
            .where(
                Task.employee_id == employee.id,
                Task.id != task.id,
                or_(
                    Task.status.in_([TaskStatus.RUNNING, TaskStatus.WAITING]),
                    Task.pending_message_id.is_not(None),
                ),
            )
            .limit(1)
        )
        if occupied:
            raise RuntimeStateError("员工正在处理其他任务")
        environment = employee.execution_environment
        initial_id = message_id()
        reserved = await self.session.execute(
            update(Task)
            .where(Task.id == task.id, Task.pending_message_id.is_(None))
            .values(pending_message_id=initial_id)
        )
        if reserved.rowcount != 1:
            raise RuntimeStateError("任务正在启动，请先重连核对或停止")
        task.execution_environment_snapshot = environment_snapshot(environment)
        employee.current_task_count = 1
        employee.status = EmployeeStatus.WORKING
        await self.session.commit()
        try:
            workspace = await prepare_workspace(task, environment)
            task = await self.lock_task(task_id)
            if task.pending_message_id != initial_id:
                return task
            task.workspace = workspace
            if task.attachments:
                task.attachments = await materialize_task_attachments(
                    environment, workspace, task.attachments
                )
            await self.session.commit()
            async with connect(environment, start=True) as client:
                old_session_id = task.current_session_id if restart else None
                if old_session_id:
                    await client.abort(Path(workspace), old_session_id)
                    await self._wait_for_session_stop(client, Path(workspace), old_session_id)
                runtime_token = generate_runtime_context()
                created = await client.create_session(
                    Path(workspace),
                    title=task.title,
                    model_name=environment.model_name,
                    agent=get_settings().opencode_agent or "build",
                )
                task = await self.lock_task(task_id)
                if task.pending_message_id != initial_id:
                    await client.abort(Path(workspace), created["id"])
                    return task
                task.current_session_id = created["id"]
                now = datetime.now(UTC)
                context_digest = hash_runtime_context(runtime_token)
                self.session.add(
                    RuntimeSession(
                        id=created["id"],
                        task_id=task.id,
                        employee_id=employee.id,
                        workspace=workspace,
                        environment=task.execution_environment_snapshot,
                        status=RuntimeSessionStatus.RUNNING.value,
                        started_at=now,
                        last_activity_at=now,
                        model_name=environment.model_name,
                        runtime_context_hash=context_digest,
                        runtime_context_id=runtime_context_id(context_digest),
                    )
                )
                await self._supersede_session(old_session_id, created["id"], interrupted=True)
                category = (
                    await self.session.get(TaskCategory, task.category_id) if task.category_id else None
                )
                bind_task_prompt_context(task, resolve_task_prompt_context(task, category))
                task.pending_prompt = {
                    "action": "prompt_async",
                    "body": {
                        "messageID": initial_id,
                        "parts": [
                            {
                                "type": "text",
                                "text": build_task_prompt(
                                    task,
                                    Path(workspace),
                                    native_question=True,
                                ),
                            },
                            build_runtime_context_part(runtime_token),
                        ],
                    },
                }
                task.last_message_id = initial_id
                task.runtime_connection = "CONNECTED"
                task.runtime_error = None
                task.failure_reason = None
                task.finished_at = None
                # Bind and retain the first submission together before any prompt reaches OpenCode.
                await self.session.commit()
            return await self.retry_submission(task.id)
        except Exception as exc:
            await self.session.rollback()
            await self.disconnected(task_id, exc)
            raise

    async def send(self, task_id, body, *, native_action="prompt_async", expected_session_id=None):
        if native_action not in {"prompt_async", "command"}:
            raise RuntimeStateError("不支持的 Session 输入")
        task = await self.lock_task(task_id)
        if not task.current_session_id:
            raise RuntimeStateError("Session 不存在；请显式启动任务")
        if expected_session_id and task.current_session_id != expected_session_id:
            raise RuntimeStateError("当前 Session 已切换，请刷新 Workspace")
        submitted_session = task.current_session_id
        if task.pending_message_id:
            raise RuntimeStateError("上次输入尚未确认，请重连核对 Session 后再发送")
        environment = await resolve_environment(self.session, task)
        employee = await self.session.scalar(
            select(DigitalEmployee)
            .where(
                DigitalEmployee.id == task.employee_id,
            )
            .with_for_update()
        )
        occupied = await self.session.scalar(
            select(Task.id)
            .where(
                Task.employee_id == task.employee_id,
                Task.id != task.id,
                or_(
                    Task.status.in_([TaskStatus.RUNNING, TaskStatus.WAITING]),
                    Task.pending_message_id.is_not(None),
                ),
            )
            .limit(1)
        )
        if occupied:
            raise RuntimeStateError("员工正在处理其他任务")
        outbound_id = body.get("messageID") or message_id()
        if not re.fullmatch(r"msg_[a-zA-Z0-9]{8,100}", outbound_id):
            raise RuntimeStateError("消息 ID 无效")
        async with connect(environment) as client:
            pending = await client.questions(Path(task.workspace)) + await client.permissions(
                Path(task.workspace)
            )
            if any(item.get("sessionID") == task.current_session_id for item in pending):
                raise RuntimeStateError("请先在 Workspace 回答当前 Session 的问题或权限请求")
        employee.current_task_count = 1
        employee.status = EmployeeStatus.WORKING
        body = {**body, "messageID": outbound_id}
        task.last_message_id = outbound_id
        # Reserve before network I/O. A second sender cannot silently overwrite a pending submission.
        reserved = await self.session.execute(
            update(Task)
            .where(
                Task.id == task.id,
                Task.pending_message_id.is_(None),
            )
            .values(pending_message_id=outbound_id, pending_prompt={"action": native_action, "body": body})
        )
        if reserved.rowcount != 1:
            raise RuntimeStateError("已有待确认输入")
        await self.session.commit()
        try:
            async with connect(environment) as client:
                await client.session(Path(task.workspace), task.current_session_id)
                await client.request(
                    "POST",
                    f"/session/{task.current_session_id}/{native_action}",
                    directory=Path(task.workspace),
                    body=body,
                )
        except Exception as exc:
            task = await self.lock_task(task_id)
            if task.pending_message_id != outbound_id:
                raise
            if type(exc) is OpenCodeExecutionError or isinstance(exc, OpenCodeSessionNotFound):
                task.pending_message_id = None
                task.pending_prompt = None
            task.runtime_connection = "UNAVAILABLE"
            task.runtime_error = str(exc)
            await self.session.commit()
            raise
        task = await self.lock_task(task_id)
        if task.pending_message_id != outbound_id or task.current_session_id != submitted_session:
            async with connect(environment) as client:
                await client.abort(Path(task.workspace), submitted_session)
            return task
        task.pending_message_id = None
        task.pending_prompt = None
        task.runtime_connection = "CONNECTED"
        task.runtime_error = None
        task.failure_reason = None
        await self._mark_session_running(task)
        return task

    async def _mark_session_running(self, task: Task) -> None:
        await self.apply_session_state(
            task, SessionState(status=RuntimeSessionStatus.RUNNING.value)
        )

    async def retry_submission(self, task_id):
        task = await self.lock_task(task_id)
        if not task.pending_message_id or not task.pending_prompt:
            raise RuntimeStateError("没有待确认输入")
        environment = await resolve_environment(self.session, task)
        async with connect(environment) as client:
            messages = await client.messages(Path(task.workspace), task.current_session_id)
            acknowledged = any(item["info"]["id"] == task.pending_message_id for item in messages)
            if not acknowledged:
                await client.request(
                    "POST",
                    f"/session/{task.current_session_id}/{task.pending_prompt['action']}",
                    directory=Path(task.workspace),
                    body=task.pending_prompt["body"],
                )
            task.pending_message_id = None
            task.pending_prompt = None
            task.runtime_error = None
            await self._mark_session_running(task)
        return task

    async def stop(self, task_id):
        task = await self.lock_task(task_id)
        if task.current_session_id:
            environment = await resolve_environment(self.session, task)
            async with connect(environment) as client:
                await client.abort(Path(task.workspace), task.current_session_id)
            runtime_session = await self._runtime_session(task)
            if runtime_session and runtime_session.status not in _TERMINAL_SESSION_STATUSES:
                runtime_session.status = RuntimeSessionStatus.INTERRUPTED.value
                runtime_session.terminal_reason = SessionTerminalReason.ABORTED.value
                runtime_session.finished_at = datetime.now(UTC)
        task.pending_message_id = None
        task.pending_prompt = None
        task.runtime_error = None
        await self.project(task, TaskStatus.CANCELED)
        await TaskSummaryService(self.session).upsert(
            task,
            source_status=TaskStatus.CANCELED.value,
            primary_session_id=task.current_session_id,
            summary_text="用户或平台明确取消了任务，当前执行（如有）已停止。",
        )
        return task

    async def refresh(self, task_id, *, client=None):
        task = await self.lock_task(task_id)
        if not task.current_session_id:
            return task
        if task.pending_message_id and not task.pending_prompt:
            task.runtime_error = "Session 启动尚未确认；请先停止，再显式重新开始"
            await self.session.commit()
            return task
        if client is None:
            environment = await resolve_environment(self.session, task)
            async with connect(environment) as connection:
                return await self.refresh(task_id, client=connection)
        directory = Path(task.workspace)
        try:
            await client.session(directory, task.current_session_id)
        except OpenCodeSessionNotFound:
            runtime_session = await self._runtime_session(task)
            if runtime_session and runtime_session.status not in _TERMINAL_SESSION_STATUSES:
                runtime_session.status = RuntimeSessionStatus.UNKNOWN.value
                runtime_session.terminal_reason = SessionTerminalReason.SESSION_MISSING.value
                await self.session.commit()
            raise
        status = await client.status(directory, task.current_session_id)
        if task.runtime_connection != "CONNECTED":
            await TaskService(self.session).add_event(
                task, "RUNTIME_CONNECTED", "runtime", "OpenCode Runtime 已连接", commit=False
            )
        task.runtime_connection = "CONNECTED"
        task.runtime_error = None
        if task.status == TaskStatus.CANCELED:
            await self.session.commit()
            return task
        questions = await client.questions(directory)
        permissions = await client.permissions(directory)
        has_pending = any(
            item.get("sessionID") == task.current_session_id for item in questions + permissions
        )
        timed_out = False
        if status in {"busy", "retry"} and not has_pending:
            started = task.turn_started_at
            if (
                task.status == TaskStatus.RUNNING
                and started
                and (datetime.now(UTC) - started.replace(tzinfo=UTC)).total_seconds()
                >= get_settings().opencode_timeout_seconds
            ):
                await client.abort(directory, task.current_session_id)
                timed_out = True
        messages = await client.messages(directory, task.current_session_id)
        await self._update_session_usage(task, messages)
        if task.pending_message_id:
            if any(item["info"]["id"] == task.pending_message_id for item in messages):
                task.pending_message_id = None
                task.pending_prompt = None
            else:
                task.runtime_error = "输入尚未被 Session 确认，请核对后重试提交"
                await self.session.commit()
                return task
        state = derive_session_state(
            messages=messages,
            server_status=status,
            has_pending_question=has_pending,
            has_pending_permission=False,
            pending_ack=False,
            turn_anchor_id=task.last_message_id,
            turn_started_at=task.turn_started_at,
            timed_out=timed_out,
            grace_seconds=get_settings().opencode_no_reply_grace_seconds,
        )
        final_text, _ = extract_final_assistant_text(messages)
        await self.apply_session_state(task, state, final_text=final_text)
        return task

    async def disconnected(self, task_id, error):
        task = await self.lock_task(task_id)
        if task.runtime_connection != "UNAVAILABLE":
            await TaskService(self.session).add_event(
                task,
                "RUNTIME_DISCONNECTED",
                "runtime",
                "OpenCode Runtime 连接中断，保留任务状态",
                commit=False,
            )
        runtime_session = await self._runtime_session(task)
        if runtime_session and runtime_session.status not in _TERMINAL_SESSION_STATUSES:
            runtime_session.status = RuntimeSessionStatus.UNKNOWN.value
            runtime_session.terminal_reason = SessionTerminalReason.TRANSPORT_UNKNOWN.value
        task.runtime_connection = "UNAVAILABLE"
        task.runtime_error = str(error)
        await self.session.commit()

    async def refresh_employee_heartbeats(self):
        employees = (
            await self.session.scalars(
                select(DigitalEmployee)
                .options(selectinload(DigitalEmployee.execution_environment))
                .where(DigitalEmployee.enabled.is_(True))
            )
        ).all()
        healthy = []
        for employee in employees:
            environment = employee.execution_environment
            if not environment:
                continue
            try:
                async with connect(environment) as client:
                    await client.health()
            except Exception:
                if employee.status not in {EmployeeStatus.PAUSED, EmployeeStatus.ERROR}:
                    employee.status = EmployeeStatus.OFFLINE
                continue
            employee.last_heartbeat = datetime.now(UTC)
            healthy.append(employee.id)
            active = await self.session.scalar(
                select(Task)
                .where(
                    Task.employee_id == employee.id,
                    or_(
                        Task.status.in_([TaskStatus.RUNNING, TaskStatus.WAITING]),
                        Task.pending_message_id.is_not(None),
                    ),
                )
                .limit(1)
            )
            employee.current_task_count = int(active is not None)
            if employee.status not in {EmployeeStatus.PAUSED, EmployeeStatus.ERROR}:
                employee.status = (
                    (
                        EmployeeStatus.WAIT_HUMAN
                        if active.status == TaskStatus.WAITING
                        else EmployeeStatus.WORKING
                    )
                    if active
                    else EmployeeStatus.IDLE
                )
        await self.session.commit()
        return healthy

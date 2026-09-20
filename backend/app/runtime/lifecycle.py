"""Task business lifecycle backed by one native OpenCode Session.

There is no Run execution state machine, event mirror, or message database here.
The only retained outbound content is an unacknowledged submission, cleared on ACK.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from time import time_ns

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.domain import CompletionPolicy, EmployeeStatus, ExecutionMode, RuntimeSessionStatus, SessionTerminalReason, TaskStatus
from app.event_bus import event_bus
from app.executors.errors import OpenCodeExecutionError, OpenCodeSessionNotFound
from app.executors.opencode_prompt import (
    bind_task_prompt_context,
    build_task_prompt,
    resolve_task_prompt_context,
)
from app.executors.usage import parse_opencode_usage
from app.models import DigitalEmployee, RuntimeSession, Task, TaskCategory, TaskSummary
from app.runtime.environment import environment_snapshot
from app.runtime.runtime_context import (
    build_runtime_context_part,
    generate_runtime_context,
    hash_runtime_context,
    runtime_context_id,
)
from app.runtime.session_connection import (
    connect,
    prepare_workspace,
    resolve_environment,
    resolve_runtime_session_environment,
    session_tree,
)
from app.runtime.session_state import SessionState, derive_session_state
from app.runtime.summary import TaskSummaryService, extract_final_assistant_text
from app.runtime.workspace_changes import workspace_head_commit
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
                            Task.status == TaskStatus.RUNNING,
                            and_(Task.status == TaskStatus.WAITING, Task.submitted_at.is_(None)),
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
            # A reopened task starts a new business completion attempt.
            task.submitted_at = None
            task.confirmed_at = None
            task.human_required_reason = None
            task.human_intervention = None
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
        # Native message info is the single token/model source. Step-finish
        # parts may repeat the same usage and must not be counted a second time.
        # Tool parts are still consumed for call/status/duration aggregation.
        events: list[dict] = []
        for message in messages:
            info = message.get("info") if isinstance(message.get("info"), dict) else {}
            events.append({"info": info})
            for part in message.get("parts", []):
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type", "")).lower()
                if "tool" in part_type:
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
            summary = await TaskSummaryService(self.session).upsert(
                task,
                source_status=task.status,
                primary_session_id=task.current_session_id,
                summary_text=final_text or "",
            )
            if task.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
                await self.process_terminal_artifacts(task, summary)

    async def _reconcile_experience(self, task: Task) -> None:
        """Only a successful source Session verifies its submitted candidates."""
        from app.library_service import KnowledgeService

        await KnowledgeService(self.session).reconcile_session_verification(
            task.current_session_id
        )

    async def _extract_experience(self, task: Task) -> None:
        from app.runtime.experience import ExperienceExtractionService

        await ExperienceExtractionService(self.session).extract(task.id)

    async def process_terminal_artifacts(self, task: Task, summary: TaskSummary) -> None:
        """Idempotently finish post-terminal verification/extraction for one summary generation."""

        if summary.artifacts_processed_generation >= summary.generation:
            return
        try:
            if task.status == TaskStatus.SUCCEEDED:
                await self._reconcile_experience(task)
            if task.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
                await self._extract_experience(task)
            # Extraction may commit internally; reload before advancing the durable cursor.
            summary = await self.session.get(TaskSummary, summary.id)
            if summary:
                summary.artifacts_processed_generation = summary.generation
                await self.session.commit()
        except Exception:
            logger.exception(
                "Terminal artifact processing failed for task %s generation %s",
                task.id,
                summary.generation,
            )
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
            if task.completion_policy == CompletionPolicy.MANUAL_CONFIRM.value:
                now = datetime.now(UTC)
                task.submitted_at = task.submitted_at or now
                task.confirmed_at = None
                task.human_required_reason = "执行已完成，等待人工确认任务结果"
                task.human_intervention = {
                    "blocking_reason": "任务完成策略要求人工确认",
                    "completed_work": "OpenCode Session 已正常结束并生成结果摘要",
                    "current_state": "等待确认任务完成",
                    "requested_input": "确认结果后完成任务；如结果不符合预期，可重新执行或取消",
                    "kind": "completion_confirmation",
                }
                await self.project(
                    task,
                    TaskStatus.WAITING,
                    detail="执行已完成，等待人工确认",
                )
            else:
                task.confirmed_at = datetime.now(UTC)
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
            elif state.terminal_reason == SessionTerminalReason.INCOMPLETE.value:
                task.failure_reason = None
                task.execution_error = None
                task.human_required_reason = "OpenCode Session 已空闲，但当前轮次未形成完整结束结果"
                task.human_intervention = {
                    "blocking_reason": "当前轮次未完整结束",
                    "completed_work": "已保留当前 Session 和 Workspace，不自动创建替代执行",
                    "current_state": "等待人工决定继续或重新执行",
                    "requested_input": "可在 Workspace 检查后继续，或显式重新开始新 Session",
                    "kind": "runtime_recovery",
                }
                await self.project(task, TaskStatus.WAITING, detail="当前轮次未完整结束，等待处理")
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

        old_session_id = task.current_session_id if restart else None
        old_binding = (
            await self.session.get(RuntimeSession, old_session_id)
            if old_session_id
            else None
        )
        employee = await self.session.scalar(
            select(DigitalEmployee)
            .where(DigitalEmployee.id == task.employee_id)
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
                    Task.status == TaskStatus.RUNNING,
                    and_(Task.status == TaskStatus.WAITING, Task.submitted_at.is_(None)),
                    Task.pending_message_id.is_not(None),
                ),
            )
            .limit(1)
        )
        if occupied:
            raise RuntimeStateError("员工正在处理其他任务")
        if (
            old_session_id
            and old_binding is None
            and task.status in {TaskStatus.RUNNING, TaskStatus.WAITING}
            and task.submitted_at is None
        ):
            raise RuntimeStateError("旧 Session 绑定缺失，无法确认旧执行已停止")

        environment = employee.execution_environment
        new_snapshot = environment_snapshot(environment)
        initial_id = message_id()
        reserved = await self.session.execute(
            update(Task)
            .where(Task.id == task.id, Task.pending_message_id.is_(None))
            .values(pending_message_id=initial_id)
        )
        if reserved.rowcount != 1:
            raise RuntimeStateError("任务正在启动，请先重连核对或停止")
        employee.current_task_count = 1
        employee.status = EmployeeStatus.WORKING
        await self.session.commit()

        created_session_id: str | None = None
        new_workspace: str | None = None
        try:
            # Stop the previous execution using the immutable RuntimeSession binding,
            # never the employee's newly edited environment.
            if old_binding and old_binding.status not in _TERMINAL_SESSION_STATUSES:
                old_environment = await resolve_runtime_session_environment(
                    self.session, old_binding
                )
                await self.session.commit()
                try:
                    async with connect(old_environment, start=True) as old_client:
                        await old_client.abort(Path(old_binding.workspace), old_binding.id)
                        await self._wait_for_session_stop(
                            old_client,
                            Path(old_binding.workspace),
                            old_binding.id,
                        )
                except OpenCodeSessionNotFound:
                    stale = await self.session.get(RuntimeSession, old_binding.id)
                    if stale and stale.status not in _TERMINAL_SESSION_STATUSES:
                        stale.status = RuntimeSessionStatus.INTERRUPTED.value
                        stale.terminal_reason = SessionTerminalReason.SESSION_MISSING.value
                        stale.finished_at = datetime.now(UTC)
                        await self.session.commit()
                except Exception:
                    if (
                        old_environment.mode != ExecutionMode.LOCAL
                        or self._local_port_in_use(old_environment.opencode_server_port)
                    ):
                        raise
                    stale = await self.session.get(RuntimeSession, old_binding.id)
                    if stale and stale.status not in _TERMINAL_SESSION_STATUSES:
                        stale.status = RuntimeSessionStatus.INTERRUPTED.value
                        stale.terminal_reason = SessionTerminalReason.SESSION_MISSING.value
                        stale.finished_at = datetime.now(UTC)
                        await self.session.commit()

            old_location = old_binding.environment if old_binding else task.execution_environment_snapshot
            location_keys = ("mode", "host", "port", "username", "workspace_root")
            reuse_workspace = bool(
                task.workspace
                and old_location
                and all(old_location.get(key) == new_snapshot.get(key) for key in location_keys)
            )
            new_workspace = await prepare_workspace(
                task,
                environment,
                reuse_existing=reuse_workspace,
            )
            base_commit = await workspace_head_commit(environment, new_workspace)

            # New environment relocation cannot safely reuse materialized attachment
            # paths from the old host. Preserve metadata, but only materialize payloads
            # that still carry their original data URL.
            attachments = list(task.attachments or [])
            materialized_attachments = attachments
            if attachments and reuse_workspace:
                materialized_attachments = await materialize_task_attachments(
                    environment, new_workspace, attachments
                )
            elif attachments:
                materialized_attachments = []
                for item in attachments:
                    copied = dict(item)
                    if copied.get("content"):
                        materialized_attachments.extend(
                            await materialize_task_attachments(
                                environment, new_workspace, [copied]
                            )
                        )
                    else:
                        copied.pop("workspace_path", None)
                        materialized_attachments.append(copied)

            async with connect(environment, start=True) as client:
                runtime_token = generate_runtime_context()
                settings = get_settings()
                effective_model = environment.model_name or settings.opencode_model
                created = await client.create_session(
                    Path(new_workspace),
                    title=task.title,
                    model_name=effective_model,
                    agent=settings.opencode_agent or "build",
                )
                created_session_id = created["id"]

                task = await self.lock_task(task_id)
                if (
                    task.pending_message_id != initial_id
                    or task.current_session_id != old_session_id
                ):
                    await self.session.rollback()
                    await client.abort(Path(new_workspace), created_session_id)
                    return await self.session.get(Task, task_id)

                # Only now switch the business pointer to the new environment/session.
                task.workspace = new_workspace
                task.execution_environment_snapshot = new_snapshot
                task.attachments = materialized_attachments
                task.current_session_id = created_session_id
                now = datetime.now(UTC)
                context_digest = hash_runtime_context(runtime_token)
                self.session.add(
                    RuntimeSession(
                        id=created_session_id,
                        task_id=task.id,
                        employee_id=employee.id,
                        workspace=new_workspace,
                        workspace_base_commit=base_commit,
                        environment=new_snapshot,
                        status=RuntimeSessionStatus.RUNNING.value,
                        started_at=now,
                        last_activity_at=now,
                        model_name=effective_model,
                        runtime_context_hash=context_digest,
                        runtime_context_id=runtime_context_id(context_digest),
                    )
                )
                await self._supersede_session(
                    old_session_id,
                    created_session_id,
                    interrupted=True,
                )
                category = (
                    await self.session.get(TaskCategory, task.category_id)
                    if task.category_id
                    else None
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
                                    Path(new_workspace),
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
                await self.session.commit()
            return await self.retry_submission(task.id)
        except Exception as exc:
            await self.session.rollback()
            task = await self.lock_task(task_id)
            if task.pending_message_id == initial_id:
                task.pending_message_id = None
                task.pending_prompt = None
                task.runtime_error = str(exc)
                active = (
                    task.status == TaskStatus.RUNNING
                    or (task.status == TaskStatus.WAITING and task.submitted_at is None)
                )
                employee = await self.session.get(DigitalEmployee, task.employee_id)
                if employee and not active:
                    employee.current_task_count = 0
                    if employee.status in {EmployeeStatus.WORKING, EmployeeStatus.WAIT_HUMAN}:
                        employee.status = EmployeeStatus.IDLE
                await self.session.commit()
            else:
                await self.session.rollback()
            if created_session_id and new_workspace:
                try:
                    async with connect(environment, start=True) as client:
                        await client.abort(Path(new_workspace), created_session_id)
                except Exception:
                    logger.exception(
                        "Failed to abort unbound restart Session %s",
                        created_session_id,
                    )
            raise

    async def send(self, task_id, body, *, native_action="prompt_async", expected_session_id=None):
        if native_action not in {"prompt_async", "command"}:
            raise RuntimeStateError("不支持的 Session 输入")

        # Read the binding first, then release the DB transaction before touching
        # OpenCode. Runtime/network latency must never extend a row lock lifetime.
        task = await self.session.get(Task, task_id)
        if not task:
            raise RuntimeStateError("任务不存在")
        if not task.current_session_id:
            raise RuntimeStateError("Session 不存在；请显式启动任务")
        if expected_session_id and task.current_session_id != expected_session_id:
            raise RuntimeStateError("当前 Session 已切换，请刷新 Workspace")
        if task.pending_message_id:
            raise RuntimeStateError("上次输入尚未确认，请重连核对 Session 后再发送")
        if task.submitted_at and not task.confirmed_at:
            raise RuntimeStateError("任务结果正在等待人工确认；请确认完成或显式重新执行")
        submitted_session = task.current_session_id
        workspace = task.workspace
        employee_id = task.employee_id
        environment = await resolve_environment(self.session, task)
        await self.session.commit()

        outbound_id = body.get("messageID") or message_id()
        if not re.fullmatch(r"msg_[a-zA-Z0-9]{8,100}", outbound_id):
            raise RuntimeStateError("消息 ID 无效")
        body = {**body, "messageID": outbound_id}

        async with connect(environment, start=True) as client:
            allowed_sessions = await session_tree(client, Path(workspace), submitted_session)
            pending = await client.questions(Path(workspace)) + await client.permissions(Path(workspace))
            if any(item.get("sessionID") in allowed_sessions for item in pending):
                raise RuntimeStateError("请先在 Workspace 回答当前 Session 树中的问题或权限请求")

        # Short transaction: revalidate the binding and reserve this submission.
        task = await self.lock_task(task_id)
        if task.current_session_id != submitted_session:
            await self.session.rollback()
            raise RuntimeStateError("当前 Session 已切换，请刷新 Workspace")
        if task.pending_message_id:
            await self.session.rollback()
            raise RuntimeStateError("已有待确认输入")
        employee = await self.session.scalar(
            select(DigitalEmployee)
            .where(DigitalEmployee.id == employee_id)
            .with_for_update()
        )
        occupied = await self.session.scalar(
            select(Task.id)
            .where(
                Task.employee_id == employee_id,
                Task.id != task.id,
                or_(
                    Task.status == TaskStatus.RUNNING,
                    and_(Task.status == TaskStatus.WAITING, Task.submitted_at.is_(None)),
                    Task.pending_message_id.is_not(None),
                ),
            )
            .limit(1)
        )
        if occupied:
            await self.session.rollback()
            raise RuntimeStateError("员工正在处理其他任务")
        if employee:
            employee.current_task_count = 1
            employee.status = EmployeeStatus.WORKING
        task.last_message_id = outbound_id
        reserved = await self.session.execute(
            update(Task)
            .where(Task.id == task.id, Task.pending_message_id.is_(None))
            .values(
                pending_message_id=outbound_id,
                pending_prompt={"action": native_action, "body": body},
            )
        )
        if reserved.rowcount != 1:
            await self.session.rollback()
            raise RuntimeStateError("已有待确认输入")
        await self.session.commit()

        try:
            async with connect(environment, start=True) as client:
                await client.session(Path(workspace), submitted_session)
                await client.request(
                    "POST",
                    f"/session/{submitted_session}/{native_action}",
                    directory=Path(workspace),
                    body=body,
                )
        except Exception as exc:
            task = await self.lock_task(task_id)
            if task.pending_message_id != outbound_id:
                await self.session.rollback()
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
            await self.session.commit()
            async with connect(environment, start=True) as client:
                await client.abort(Path(workspace), submitted_session)
            return await self.session.get(Task, task_id)
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
        task = await self.session.get(Task, task_id)
        if not task:
            raise RuntimeStateError("任务不存在")
        if not task.pending_message_id or not task.pending_prompt:
            raise RuntimeStateError("没有待确认输入")
        pending_id = task.pending_message_id
        pending_prompt = dict(task.pending_prompt)
        session_id = task.current_session_id
        workspace = task.workspace
        environment = await resolve_environment(self.session, task)
        await self.session.commit()

        async with connect(environment, start=True) as client:
            messages = await client.messages(Path(workspace), session_id)
            acknowledged = any(item["info"]["id"] == pending_id for item in messages)
            sent_now = False
            if not acknowledged:
                await client.request(
                    "POST",
                    f"/session/{session_id}/{pending_prompt['action']}",
                    directory=Path(workspace),
                    body=pending_prompt["body"],
                )
                sent_now = True

            # Revalidate after the network write. stop/delete/restart may have
            # invalidated this reservation while the request was in flight.
            task = await self.lock_task(task_id)
            stale = (
                task.current_session_id != session_id
                or task.pending_message_id != pending_id
                or task.status == TaskStatus.CANCELED
            )
            if stale:
                await self.session.rollback()
                if sent_now or acknowledged:
                    try:
                        await client.abort(Path(workspace), session_id)
                    except Exception:
                        logger.exception(
                            "Failed to abort stale submission for task %s session %s",
                            task_id,
                            session_id,
                        )
                raise RuntimeStateError("待确认输入已被控制操作失效，当前 Session 已停止")

            task.pending_message_id = None
            task.pending_prompt = None
            task.runtime_error = None
            await self._mark_session_running(task)
            return task

    @staticmethod
    def _local_port_in_use(port: int) -> bool:
        with socket.socket() as probe:
            probe.settimeout(0.3)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    async def stop(self, task_id):
        task = await self.session.get(Task, task_id)
        if not task:
            raise RuntimeStateError("任务不存在")
        session_id = task.current_session_id
        workspace = task.workspace
        environment = await resolve_environment(self.session, task) if session_id else None
        await self.session.commit()

        forced_offline_cancel = False
        stop_error = None
        if session_id and environment:
            try:
                async with connect(environment, start=True) as client:
                    await client.abort(Path(workspace), session_id)
            except OpenCodeSessionNotFound:
                # A restarted Serve that cannot find the Session proves there is
                # no live execution attached to this binding.
                forced_offline_cancel = True
            except Exception as exc:
                stop_error = exc
                # Only LOCAL + no listener is safe to force-cancel. For remote
                # transport loss or an occupied-but-unhealthy local port we cannot
                # prove the Agent has stopped writing the Workspace.
                if (
                    environment.mode == ExecutionMode.LOCAL
                    and not self._local_port_in_use(environment.opencode_server_port)
                ):
                    forced_offline_cancel = True
                else:
                    await self.disconnected(task_id, exc)
                    raise

        task = await self.lock_task(task_id)
        if session_id and task.current_session_id != session_id:
            await self.session.rollback()
            raise RuntimeStateError("取消期间 Session 已切换，请刷新后重试")
        runtime_session = await self._runtime_session(task)
        if runtime_session and runtime_session.status not in _TERMINAL_SESSION_STATUSES:
            runtime_session.status = RuntimeSessionStatus.INTERRUPTED.value
            runtime_session.terminal_reason = SessionTerminalReason.ABORTED.value
            runtime_session.finished_at = datetime.now(UTC)
        if forced_offline_cancel:
            await TaskService(self.session).add_event(
                task,
                "RUNTIME_OFFLINE_CANCELED",
                "runtime",
                "Runtime 已不可执行，按明确取消意图收敛任务",
                {"error": str(stop_error) if stop_error else "session missing"},
                commit=False,
            )
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
        task = await self.session.get(Task, task_id)
        if not task:
            raise RuntimeStateError("任务不存在")
        if not task.current_session_id:
            return task
        if task.pending_message_id and not task.pending_prompt:
            task.runtime_error = "Session 启动尚未确认；请先停止，再显式重新开始"
            await self.session.commit()
            return task

        session_id = task.current_session_id
        workspace = task.workspace
        if client is None:
            environment = await resolve_environment(self.session, task)
            await self.session.commit()
            async with connect(environment, start=True) as connection:
                return await self.refresh(task_id, client=connection)

        # Do not keep even a read transaction open while waiting on Runtime I/O.
        await self.session.commit()
        directory = Path(workspace)
        try:
            await client.session(directory, session_id)
            status = await client.status(directory, session_id)
            allowed_sessions = await session_tree(client, directory, session_id)
            questions = await client.questions(directory)
            permissions = await client.permissions(directory)
        except OpenCodeSessionNotFound:
            task = await self.lock_task(task_id)
            if task.current_session_id == session_id:
                runtime_session = await self._runtime_session(task)
                if runtime_session and runtime_session.status not in _TERMINAL_SESSION_STATUSES:
                    runtime_session.status = RuntimeSessionStatus.UNKNOWN.value
                    runtime_session.terminal_reason = SessionTerminalReason.SESSION_MISSING.value
                await self.session.commit()
            else:
                await self.session.rollback()
            raise

        has_pending = any(
            item.get("sessionID") in allowed_sessions for item in questions + permissions
        )
        task_snapshot = await self.session.get(Task, task_id)
        turn_started = task_snapshot.turn_started_at
        task_status = task_snapshot.status
        await self.session.commit()

        timed_out = False
        if status in {"busy", "retry"} and not has_pending and task_status == TaskStatus.RUNNING and turn_started:
            started = turn_started if turn_started.tzinfo else turn_started.replace(tzinfo=UTC)
            if (datetime.now(UTC) - started).total_seconds() >= get_settings().opencode_timeout_seconds:
                await client.abort(directory, session_id)
                timed_out = True
        messages = await client.messages(directory, session_id)
        usage_messages = list(messages)
        for child_session_id in sorted(allowed_sessions - {session_id}):
            try:
                usage_messages.extend(
                    await client.messages(directory, child_session_id)
                )
            except OpenCodeSessionNotFound:
                continue

        task = await self.lock_task(task_id)
        if task.current_session_id != session_id:
            await self.session.rollback()
            return task
        if task.runtime_connection != "CONNECTED":
            await TaskService(self.session).add_event(
                task, "RUNTIME_CONNECTED", "runtime", "OpenCode Runtime 已连接", commit=False
            )
        task.runtime_connection = "CONNECTED"
        task.runtime_error = None
        if task.status == TaskStatus.CANCELED:
            await self.session.commit()
            return task

        await self._update_session_usage(task, usage_messages)
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
        final_text, _ = extract_final_assistant_text(messages, turn_anchor_id=task.last_message_id)
        await self.apply_session_state(task, state, final_text=final_text)
        return task

    async def confirm_completion(self, task_id: str):
        """Confirm a MANUAL_CONFIRM task after its Session completed."""

        task = await self.lock_task(task_id)
        if task.completion_policy != CompletionPolicy.MANUAL_CONFIRM.value:
            await self.session.rollback()
            raise RuntimeStateError("当前任务不是人工确认完成策略")
        if task.pending_message_id:
            await self.session.rollback()
            raise RuntimeStateError("仍有未确认输入，不能确认任务完成")
        if task.status != TaskStatus.WAITING or not task.submitted_at:
            await self.session.rollback()
            raise RuntimeStateError("任务当前不处于待完成确认状态")
        runtime_session = await self._runtime_session(task)
        if not runtime_session or runtime_session.status != RuntimeSessionStatus.SUCCEEDED.value:
            await self.session.rollback()
            raise RuntimeStateError("当前 Session 尚未正常完成")

        task.confirmed_at = datetime.now(UTC)
        task.human_required_reason = None
        task.human_intervention = None
        await self.project(task, TaskStatus.SUCCEEDED, detail="任务结果已人工确认")

        summary = await self.session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == task.id)
        )
        summary = await TaskSummaryService(self.session).upsert(
            task,
            source_status=TaskStatus.SUCCEEDED.value,
            primary_session_id=task.current_session_id,
            summary_text=summary.summary if summary else task.current_progress,
        )
        await self.process_terminal_artifacts(task, summary)
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
        # The initial SELECT starts a transaction. Close it before any network
        # probe so no autoflushed employee UPDATE can remain locked while a later
        # OpenCode health check stalls.
        await self.session.commit()

        healthy: list[str] = []
        for employee in employees:
            environment = employee.execution_environment
            if not environment:
                continue

            active = await self.session.scalar(
                select(Task)
                .where(
                    Task.employee_id == employee.id,
                    or_(
                        Task.status == TaskStatus.RUNNING,
                        and_(Task.status == TaskStatus.WAITING, Task.submitted_at.is_(None)),
                        Task.pending_message_id.is_not(None),
                    ),
                )
                .limit(1)
            )
            await self.session.commit()

            # Employee Serve is intentionally on-demand. No active task means an
            # absent OpenCode listener is normal; rely on the last explicit
            # environment check instead of marking the employee OFFLINE.
            if active is None:
                fresh = await self.session.get(DigitalEmployee, employee.id)
                if fresh and fresh.status not in {EmployeeStatus.PAUSED, EmployeeStatus.ERROR}:
                    fresh.current_task_count = 0
                    if environment.status == "AVAILABLE":
                        fresh.status = EmployeeStatus.IDLE
                        fresh.last_heartbeat = datetime.now(UTC)
                        healthy.append(fresh.id)
                    else:
                        fresh.status = EmployeeStatus.OFFLINE
                await self.session.commit()
                continue

            try:
                # Active work expects a Serve. Start/recover it if necessary,
                # then verify health without holding any database transaction.
                async with connect(environment, start=True) as client:
                    await client.health()
                probe_error = None
            except Exception as exc:
                probe_error = exc

            fresh = await self.session.get(DigitalEmployee, employee.id)
            current = await self.session.scalar(
                select(Task)
                .where(
                    Task.employee_id == employee.id,
                    or_(
                        Task.status == TaskStatus.RUNNING,
                        and_(Task.status == TaskStatus.WAITING, Task.submitted_at.is_(None)),
                        Task.pending_message_id.is_not(None),
                    ),
                )
                .limit(1)
            )
            if not fresh:
                await self.session.rollback()
                continue
            fresh.current_task_count = int(current is not None)
            if probe_error is not None:
                if fresh.status not in {EmployeeStatus.PAUSED, EmployeeStatus.ERROR}:
                    fresh.status = EmployeeStatus.OFFLINE
                await self.session.commit()
                continue

            fresh.last_heartbeat = datetime.now(UTC)
            healthy.append(fresh.id)
            if fresh.status not in {EmployeeStatus.PAUSED, EmployeeStatus.ERROR}:
                fresh.status = (
                    EmployeeStatus.WAIT_HUMAN
                    if current and current.status == TaskStatus.WAITING
                    else EmployeeStatus.WORKING
                    if current
                    else EmployeeStatus.IDLE
                )
            await self.session.commit()
        return healthy

from __future__ import annotations

import logging
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

from app.database import SessionLocal
from app.domain import EmployeeStatus, ExecutionMode, RunStatus, TaskStatus
from app.executors.errors import OpenCodeServerUnavailable, classify_exception
from app.executors.opencode_prompt import bind_task_prompt_context, resolve_task_prompt_context
from app.models import TaskCategory
from app.runtime.coordinator import TaskCoordinator
from app.runtime.environment import environment_snapshot
from app.runtime.lifecycle import RuntimeService
from app.services import TaskService
from app.structured_logging import runtime_log


class RunCoordinator(TaskCoordinator):
    """Run-only production coordinator.

    A Worker may execute only a queued Run with a valid runtime lease. Task ids are
    never accepted as execution identifiers; Task and Employee remain projections.
    """

    @staticmethod
    async def _resolve_prompt_context(session, task):
        category_id = getattr(task, "category_id", None)
        if not category_id:
            return None
        category = await session.get(TaskCategory, category_id)
        return resolve_task_prompt_context(task, category)

    async def process(self, run_id: str, *, worker_id: str | None = None) -> None:
        async with SessionLocal() as session:
            runtime_worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
            claimed = await RuntimeService(session).claim_run(
                run_id,
                worker_id=runtime_worker_id,
            )
            if not claimed:
                return

            task, employee, run, execution_token = claimed
            resume_existing_run = bool(
                run.started_at and (run.opencode_session_id or task.opencode_session_id)
            )
            service = TaskService(session)
            try:
                prompt_context = await self._resolve_prompt_context(session, task)
                bind_task_prompt_context(task, prompt_context)
                environment = self._resolve_environment(task, employee)
                task.execution_environment_snapshot = (
                    task.execution_environment_snapshot or environment_snapshot(environment)
                )
                workspace = Path(environment.workspace_root).expanduser()
                if environment.mode == ExecutionMode.LOCAL:
                    workspace = self.settings.employee_workspace_path(environment.workspace_root)
                    if not workspace.is_dir():
                        raise OpenCodeServerUnavailable(f"员工工作空间不存在: {workspace}")

                task.current_progress = "Agent 正在自主处理任务"
                await service.add_event(
                    task,
                    "WORK_STARTED",
                    "work",
                    f"{employee.name} 开始处理任务",
                    {"workspace": str(workspace), "environment": environment.name},
                    run.id,
                )
                executor = self.executor or self._executor_for_environment(
                    task,
                    environment,
                    service,
                )
                await self._execute_once(
                    task,
                    employee,
                    environment,
                    workspace,
                    executor,
                    session,
                    prepared_run=run,
                    resume_existing_run=resume_existing_run,
                    execution_token=execution_token,
                )
            except Exception as exc:
                runtime_log(
                    logging.ERROR,
                    "任务运行异常",
                    employee_id=employee.id,
                    task_id=task.id,
                    phase="work",
                    error=str(exc),
                )
                task_id, employee_id, claimed_run_id = task.id, employee.id, run.id
                failure = classify_exception(exc)
                await session.rollback()
                runtime = RuntimeService(session)
                locked_task = await runtime.lock_task(task_id)
                locked_employee = await runtime.lock_employee(employee_id)
                if not locked_task or not locked_employee:
                    await session.rollback()
                    return

                task = locked_task
                employee = locked_employee
                active_run = await runtime.active_run(task.id)
                if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                    await session.commit()
                    return

                execution_error = {
                    "reason": str(exc),
                    "current_progress": task.current_progress,
                    "environment": task.execution_environment_snapshot,
                    "session_id": task.opencode_session_id,
                    "last_activity_at": (
                        task.last_activity_at.isoformat() if task.last_activity_at else None
                    ),
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
                if (
                    active_run
                    and active_run.id == claimed_run_id
                    and active_run.execution_token == execution_token
                ):
                    task.execution_error = execution_error
                    active_run.result = {
                        "status": "FAILED",
                        "summary": "运行时启动或执行异常",
                        "stderr": str(exc),
                    }
                    await runtime.finalize_run(
                        task,
                        employee,
                        active_run,
                        run_status=RunStatus.FAILED,
                        task_status=TaskStatus.EXECUTION_ERROR,
                        current_progress="执行发生异常，等待恢复",
                        message="任务执行发生异常",
                        execution_token=execution_token,
                        failure_code=failure.failure_code,
                        employee_status=EmployeeStatus.ERROR,
                    )
                else:
                    # Another Worker owns the current Run lease; stale workers cannot
                    # mutate the newer execution projection.
                    await session.commit()

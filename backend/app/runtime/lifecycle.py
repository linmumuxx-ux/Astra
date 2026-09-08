from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.domain import EmployeeStatus, ExecutionMode, RunStatus, RunTriggerReason, TaskStatus
from app.event_bus import event_bus
from app.models import (
    DigitalEmployee,
    Event,
    OpenCodeExecutionEnvironment,
    Run,
    RunDispatchOutbox,
    RunInquiry,
    Task,
    TaskSession,
)
from app.runtime.environment import environment_snapshot
from app.runtime.failure import FailureCode, failure_for, record_failure
from app.services import EmployeeService, TaskService, ensure_task_session

ACTIVE_RUN_STATUSES = {
    RunStatus.QUEUED.value,
    RunStatus.STARTING.value,
    RunStatus.RUNNING.value,
    RunStatus.WAITING_INPUT.value,
}
TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.TIMEOUT.value,
    RunStatus.LOST.value,
    RunStatus.SUSPENDED.value,
    RunStatus.CANCELLED.value,
}


class RuntimeStateError(ValueError):
    pass


def executor_type_for_snapshot(snapshot: dict | None) -> str:
    settings = get_settings()
    if str((snapshot or {}).get("mode") or "").upper() == ExecutionMode.LINUX_REMOTE:
        return (
            "opencode_server_ssh"
            if settings.executor_type == "opencode_server"
            else "opencode_cli_fallback_ssh"
        )
    return settings.executor_type


class RuntimeService:
    """Transactional owner of Task, Run and Employee execution state."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _resolve_trigger_reason(
        task: Task,
        detail: dict | None,
        explicit: RunTriggerReason | str | None,
    ) -> str:
        if explicit is not None:
            return RunTriggerReason(str(explicit)).value
        detail = detail or {}
        if detail.get("rerun"):
            return RunTriggerReason.USER_CONTINUE.value
        if detail.get("continue"):
            return RunTriggerReason.USER_CONTINUE.value
        if detail.get("dispatch") == "manual":
            return RunTriggerReason.INITIAL.value
        if task.status == TaskStatus.WAIT_HUMAN:
            return RunTriggerReason.HUMAN_RESUME.value
        if task.status == TaskStatus.SUSPENDED:
            return RunTriggerReason.USER_CONTINUE.value
        if task.status == TaskStatus.EXECUTION_ERROR or detail.get("recovery"):
            return RunTriggerReason.WORKER_RECOVERY.value
        return RunTriggerReason.INITIAL.value

    @staticmethod
    def reset_session(task: Task) -> None:
        task.opencode_session_id = None
        if task.human_intervention:
            task.human_intervention = {
                key: value for key, value in task.human_intervention.items() if not key.startswith("runtime_")
            }

    async def lock_task(self, task_id: str) -> Task | None:
        return await self.session.scalar(
            select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True)
        )

    async def lock_employee(self, employee_id: str) -> DigitalEmployee | None:
        return await self.session.scalar(
            select(DigitalEmployee)
            .where(DigitalEmployee.id == employee_id)
            .options(selectinload(DigitalEmployee.execution_environment))
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def active_run(self, task_id: str) -> Run | None:
        task = await self.session.get(Task, task_id)
        if task and task.active_run_id:
            linked = await self.session.scalar(
                select(Run).where(Run.id == task.active_run_id).with_for_update()
            )
            if linked and linked.task_id == task_id and linked.status in ACTIVE_RUN_STATUSES:
                return linked
        return await self.session.scalar(
            select(Run)
            .where(Run.task_id == task_id, Run.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(Run.run_number.desc())
            .with_for_update()
        )

    async def _assert_slot_available(
        self,
        task: Task,
        employee: DigitalEmployee,
    ) -> None:
        if task.active_run_id:
            linked = await self.session.get(Run, task.active_run_id)
            if linked and linked.task_id == task.id and linked.status in ACTIVE_RUN_STATUSES:
                raise RuntimeStateError(f"任务已有活动运行：{linked.id}")
            task.active_run_id = None
        if employee.active_run_id:
            linked = await self.session.get(Run, employee.active_run_id)
            if linked and linked.employee_id == employee.id and linked.status in ACTIVE_RUN_STATUSES:
                raise RuntimeStateError(f"员工已有活动运行：{linked.id}")
            employee.active_run_id = None
        reserved_for_task = task.status in {TaskStatus.ASSIGNED, TaskStatus.WAIT_HUMAN} or (
            task.status == TaskStatus.READY and bool(task.claimed_at) and task.employee_id == employee.id
        )
        if employee.current_task_count > 0 and not reserved_for_task:
            raise RuntimeStateError("员工执行槽已被其他任务占用")

        active = await self.session.scalar(
            select(Run)
            .where(Run.task_id == task.id, Run.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(Run.run_number.desc())
            .with_for_update()
        )
        if active:
            task.active_run_id = active.id
            raise RuntimeStateError(f"任务已有活动运行：{active.id}")
        employee_active = await self.session.scalar(
            select(Run)
            .where(
                Run.employee_id == employee.id,
                Run.status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(Run.created_at.desc())
            .with_for_update()
        )
        if employee_active:
            employee.active_run_id = employee_active.id
            raise RuntimeStateError(f"员工已有活动运行：{employee_active.id}")

    async def validate_invariants(self) -> list[str]:
        """Read-only audit, including missing pointers and duplicate active executions."""
        runs = (await self.session.scalars(select(Run).where(Run.status.in_(ACTIVE_RUN_STATUSES)))).all()
        tasks = {task.id: task for task in (await self.session.scalars(select(Task))).all()}
        employees = {
            employee.id: employee for employee in (await self.session.scalars(select(DigitalEmployee))).all()
        }
        violations = []
        for run in runs:
            task, employee = tasks.get(run.task_id), employees.get(run.employee_id)
            expected_task = {
                "QUEUED": "QUEUED",
                "STARTING": "QUEUED",
                "RUNNING": "RUNNING",
                "WAITING_INPUT": "WAIT_HUMAN",
            }[run.status]
            expected_employee = "WAIT_HUMAN" if run.status == "WAITING_INPUT" else "WORKING"
            if not task or task.active_run_id != run.id or task.status != expected_task:
                violations.append(f"task-run:{run.id}")
            if (
                not employee
                or employee.active_run_id != run.id
                or employee.status != expected_employee
                or employee.current_task_count != 1
            ):
                violations.append(f"employee-run:{run.id}")
        active_ids = {run.id for run in runs}
        for task in tasks.values():
            if task.status in {"QUEUED", "RUNNING", "WAIT_HUMAN"} and task.active_run_id not in active_ids:
                violations.append(f"task-orphan:{task.id}")
            if task.active_run_id and task.active_run_id not in active_ids:
                violations.append(f"task-pointer:{task.id}")
        for employee in employees.values():
            if employee.status in {"WORKING", "WAIT_HUMAN"} and employee.active_run_id not in active_ids:
                violations.append(f"employee-orphan:{employee.id}")
            if employee.active_run_id and employee.active_run_id not in active_ids:
                violations.append(f"employee-pointer:{employee.id}")
        return violations

    async def _prepare_outbox(self, run: Run, *, reset: bool = False) -> RunDispatchOutbox:
        await self.session.flush()
        outbox = await self.session.scalar(
            select(RunDispatchOutbox).where(RunDispatchOutbox.run_id == run.id).with_for_update()
        )
        now = datetime.now(UTC)
        if not outbox:
            outbox = RunDispatchOutbox(
                id=f"OUT-{uuid4().hex[:12].upper()}",
                run_id=run.id,
                status="PENDING",
                next_retry_at=now,
            )
            self.session.add(outbox)
        elif reset:
            outbox.status = "PENDING"
            outbox.next_retry_at = now
            outbox.sent_at = None
            outbox.last_error = None
        return outbox

    async def _cancel_open_inquiries(self, task_id: str) -> None:
        session_ids = select(TaskSession.id).where(TaskSession.task_id == task_id)
        inquiries = (
            (
                await self.session.execute(
                    select(RunInquiry)
                    .where(
                        RunInquiry.session_id.in_(session_ids),
                        RunInquiry.status.in_(["OPEN", "PENDING"]),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for inquiry in inquiries:
            inquiry.status = "CANCELLED"

    async def queue_new_run(
        self,
        task: Task,
        employee: DigitalEmployee,
        *,
        current_progress: str,
        message: str,
        detail: dict | None = None,
        trigger_reason: RunTriggerReason | str | None = None,
        reset_runtime_session: bool = False,
        commit: bool = True,
    ) -> Run:
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(employee.id)
        if not locked_task or not locked_employee:
            raise RuntimeStateError("任务或员工不存在")
        task = locked_task
        employee = locked_employee
        pending_abort = await self.session.scalar(
            select(Run.id)
            .where(
                Run.task_id == task.id,
                Run.executor_status == "ABORT_PENDING",
            )
            .limit(1)
        )
        if pending_abort:
            raise RuntimeStateError("原 Agent 会话正在停止，Runtime 将自动重试，请稍后继续")
        await self._assert_slot_available(task, employee)

        previous_run = await self.session.scalar(
            select(Run).where(Run.task_id == task.id).order_by(Run.run_number.desc()).limit(1)
        )
        run_number = (
            await self.session.scalar(select(func.max(Run.run_number)).where(Run.task_id == task.id)) or 0
        ) + 1
        if reset_runtime_session:
            self.reset_session(task)
        snapshot = task.execution_environment_snapshot
        if not snapshot:
            environment = employee.execution_environment
            if not environment:
                environment = await self.session.scalar(
                    select(OpenCodeExecutionEnvironment).where(
                        OpenCodeExecutionEnvironment.employee_id == employee.id
                    )
                )
            snapshot = environment_snapshot(environment) if environment else {}
        task.execution_environment_snapshot = snapshot
        now = datetime.now(UTC)
        resolved_trigger = self._resolve_trigger_reason(task, detail, trigger_reason)
        run = Run(
            id=f"RUN-{uuid4().hex[:10].upper()}",
            task_id=task.id,
            employee_id=employee.id,
            previous_run_id=previous_run.id if previous_run else None,
            run_number=run_number,
            trigger_reason=resolved_trigger,
            retry_index=0,
            status=RunStatus.QUEUED,
            executor_type=executor_type_for_snapshot(snapshot),
            opencode_session_id=task.opencode_session_id,
            queued_at=now,
            execution_environment_snapshot=snapshot,
        )
        self.session.add(run)
        await self.session.flush()
        task.active_run_id = run.id
        employee.active_run_id = run.id
        work_session = await ensure_task_session(self.session, task)
        work_session.current_run_id = run.id
        work_session.status = "ACTIVE"
        EmployeeService.reserve(employee)
        task.finished_at = None
        await self._prepare_outbox(run)
        service = TaskService(self.session)
        event_detail = {**(detail or {}), "trigger_reason": run.trigger_reason, "retry_index": 0}
        if TaskStatus(task.status) in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            await service.reopen(
                task,
                TaskStatus.QUEUED,
                current_progress=current_progress,
                message=message,
                detail=event_detail,
                run_id=run.id,
                commit=False,
            )
        else:
            await service.transition(
                task,
                TaskStatus.QUEUED,
                current_progress=current_progress,
                message=message,
                detail=event_detail,
                run_id=run.id,
                commit=False,
            )
        if commit:
            await self.session.commit()
            await self.session.refresh(run)
            await event_bus.publish({"type": "TASK_QUEUED", "task_id": task.id, "status": task.status})
        return run

    async def queue_waiting_run(
        self,
        task: Task,
        employee: DigitalEmployee,
        *,
        current_progress: str,
        message: str,
        detail: dict | None = None,
        commit: bool = True,
    ) -> Run:
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(employee.id)
        if not locked_task or not locked_employee:
            raise RuntimeStateError("任务或员工不存在")
        task = locked_task
        employee = locked_employee
        run = await self.active_run(task.id)
        if not run or run.status != RunStatus.WAITING_INPUT:
            raise RuntimeStateError("任务没有可继续的等待中运行")
        if employee.active_run_id not in {None, run.id}:
            raise RuntimeStateError(f"员工已有活动运行：{employee.active_run_id}")
        run.status = RunStatus.QUEUED
        run.trigger_reason = RunTriggerReason.HUMAN_RESUME
        run.queued_at = datetime.now(UTC)
        run.dispatched_at = None
        run.finished_at = None
        record_failure(run, None)
        task.active_run_id = run.id
        employee.active_run_id = run.id
        EmployeeService.reserve(employee)
        await self._prepare_outbox(run, reset=True)
        await TaskService(self.session).transition(
            task,
            TaskStatus.QUEUED,
            current_progress=current_progress,
            message=message,
            detail=detail,
            run_id=run.id,
            commit=False,
        )
        if commit:
            await self.session.commit()
            await self.session.refresh(run)
            await event_bus.publish({"type": "TASK_QUEUED", "task_id": task.id, "status": task.status})
        return run

    async def claim_run(
        self,
        run_id: str,
        *,
        worker_id: str,
    ) -> tuple[Task, DigitalEmployee, Run, str] | None:
        reference = await self.session.get(Run, run_id)
        if not reference:
            return None
        task = await self.lock_task(reference.task_id)
        employee = await self.lock_employee(reference.employee_id)
        run = await self.session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if not task or not employee or not run or run.status != RunStatus.QUEUED:
            return None
        if task.status != TaskStatus.QUEUED:
            return None
        if task.active_run_id not in {None, run.id} or employee.active_run_id not in {None, run.id}:
            return None
        token = uuid4().hex
        now = datetime.now(UTC)
        task.active_run_id = run.id
        employee.active_run_id = run.id
        EmployeeService.reserve(employee)
        record_failure(run, None)
        run.status = RunStatus.STARTING
        run.worker_id = worker_id[:160]
        run.execution_token = token
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        run.executor_status = "STARTING"
        await self.session.commit()
        return task, employee, run, token

    async def bind_session(self, task: Task, run: Run, session_id: str, execution_token: str) -> bool:
        task = await self.lock_task(task.id)
        employee = await self.lock_employee(run.employee_id)
        run = await self.session.scalar(
            select(Run).where(Run.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
        if (
            not task
            or not employee
            or not run
            or run.execution_token != execution_token
            or run.status not in {RunStatus.STARTING, RunStatus.RUNNING}
            or task.active_run_id != run.id
            or employee.active_run_id != run.id
        ):
            await self.session.rollback()
            return False
        task.opencode_session_id = run.opencode_session_id = session_id
        await TaskService(self.session).add_event(
            task,
            "OPENCODE_SESSION_BOUND",
            "metadata",
            "OpenCode Session 已绑定",
            {"session_id": session_id, "runtime": run.executor_type},
            run.id,
        )
        return True

    async def mark_running(
        self,
        task: Task,
        run: Run,
        execution_token: str,
    ) -> bool:
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(run.employee_id)
        locked_run = await self.session.scalar(
            select(Run).where(Run.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
        if (
            not locked_task
            or not locked_employee
            or not locked_run
            or locked_task.status != TaskStatus.QUEUED
            or locked_task.active_run_id != locked_run.id
            or locked_employee.active_run_id != locked_run.id
            or locked_run.status != RunStatus.STARTING
            or locked_run.execution_token != execution_token
        ):
            return False
        task = locked_task
        run = locked_run
        now = datetime.now(UTC)
        run.status = RunStatus.RUNNING
        run.heartbeat_at = now
        run.executor_status = "RUNNING"
        await TaskService(self.session).transition(
            task,
            TaskStatus.RUNNING,
            current_progress="Agent 正在自主处理任务",
            message="Agent Worker 已取得运行租约并开始处理",
            run_id=run.id,
            commit=False,
        )
        await self.session.commit()
        await event_bus.publish({"type": "TASK_RUNNING", "task_id": task.id, "status": task.status})
        return True

    async def defer_session_probe(self, run: Run, execution_token: str, failure) -> bool:
        await self.lock_task(run.task_id)
        await self.lock_employee(run.employee_id)
        run = await self.session.scalar(
            select(Run).where(Run.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
        if (
            not run
            or run.execution_token != execution_token
            or run.status
            not in {
                RunStatus.STARTING,
                RunStatus.RUNNING,
            }
        ):
            await self.session.rollback()
            return False
        record_failure(run, failure.failure_code, failure.raw_error)
        run.executor_status = "PROBE_ERROR"
        timeout = max(get_settings().runtime_heartbeat_timeout, get_settings().runtime_startup_timeout)
        run.heartbeat_at = datetime.now(UTC) - timedelta(seconds=timeout + 1)
        await self.session.commit()
        return True

    async def heartbeat(
        self,
        run_id: str,
        execution_token: str,
        *,
        executor_status: str = "RUNNING",
    ) -> bool:
        result = await self.session.execute(
            update(Run)
            .where(
                Run.id == run_id,
                Run.execution_token == execution_token,
                Run.status.in_([RunStatus.STARTING, RunStatus.RUNNING]),
            )
            .values(
                heartbeat_at=datetime.now(UTC),
                executor_status=executor_status[:64],
            )
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def mark_waiting(
        self,
        task: Task,
        employee: DigitalEmployee,
        run: Run,
        *,
        current_progress: str,
        message: str,
        execution_token: str | None = None,
    ) -> bool:
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(employee.id)
        locked_run = await self.session.scalar(
            select(Run).where(Run.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
        if not locked_task or not locked_employee or not locked_run:
            return False
        if execution_token and locked_run.execution_token != execution_token:
            return False
        if (
            locked_run.status not in {RunStatus.STARTING, RunStatus.RUNNING}
            or locked_task.active_run_id not in {None, locked_run.id}
            or locked_employee.active_run_id not in {None, locked_run.id}
        ):
            return False
        task = locked_task
        employee = locked_employee
        run = locked_run
        run.status = RunStatus.WAITING_INPUT
        run.finished_at = None
        run.executor_status = "WAITING_INPUT"
        run.heartbeat_at = datetime.now(UTC)
        task.active_run_id = run.id
        employee.active_run_id = run.id
        employee.status = EmployeeStatus.WAIT_HUMAN
        employee.current_task_count = 1
        await TaskService(self.session).transition(
            task,
            TaskStatus.WAIT_HUMAN,
            current_progress=current_progress,
            message=message,
            run_id=run.id,
            commit=False,
        )
        await self.session.commit()
        await event_bus.publish({"type": "WAIT_HUMAN", "task_id": task.id, "status": task.status})
        return True

    async def finalize_run(
        self,
        task: Task,
        employee: DigitalEmployee,
        run: Run,
        *,
        run_status: RunStatus,
        task_status: TaskStatus | None,
        current_progress: str,
        message: str,
        execution_token: str | None = None,
        failure_code: str | None = None,
        employee_status: EmployeeStatus = EmployeeStatus.IDLE,
    ) -> bool:
        if run_status.value not in TERMINAL_RUN_STATUSES:
            raise RuntimeStateError(f"非终态 Run 不能 finalize：{run_status}")
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(employee.id)
        locked_run = await self.session.scalar(
            select(Run).where(Run.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
        if not locked_task or not locked_employee or not locked_run:
            return False
        task = locked_task
        employee = locked_employee
        run = locked_run
        if execution_token and run.execution_token != execution_token:
            return False
        if run.status in TERMINAL_RUN_STATUSES:
            return False
        if task.active_run_id not in {None, run.id}:
            return False
        if employee.active_run_id not in {None, run.id}:
            return False
        run.status = run_status
        run.finished_at = run.finished_at or datetime.now(UTC)
        run.heartbeat_at = datetime.now(UTC)
        run.executor_status = run_status.value
        record_failure(run, failure_code, str((run.result or {}).get("stderr") or message))
        if failure_code:
            task.execution_error = {
                **(task.execution_error or {}),
                "failure": failure_for(failure_code, run.raw_error or "").as_dict(),
            }
        elif run_status == RunStatus.COMPLETED:
            task.execution_error = None
        if task_status and task.status != task_status:
            await TaskService(self.session).transition(
                task,
                task_status,
                current_progress=current_progress,
                message=message,
                run_id=run.id,
                commit=False,
            )
        await self._cancel_open_inquiries(task.id)
        task.active_run_id = None
        employee.active_run_id = None
        EmployeeService.release(employee, status=employee_status)
        outbox = await self.session.scalar(
            select(RunDispatchOutbox).where(RunDispatchOutbox.run_id == run.id)
        )
        if outbox and outbox.status != "SENT":
            outbox.status = "CANCELLED"
            outbox.next_retry_at = None
        await self.session.commit()
        event_type = {
            TaskStatus.COMPLETED: "TASK_COMPLETED",
            TaskStatus.PENDING_CONFIRMATION: "RESULT_SUBMITTED",
            TaskStatus.EXECUTION_ERROR: "EXECUTION_ERROR",
            TaskStatus.FAILED: "TASK_FAILED",
            TaskStatus.CANCELLED: "TASK_CANCELLED",
            TaskStatus.SUSPENDED: "TASK_SUSPENDED",
        }.get(task_status, "RUN_FINALIZED")
        await event_bus.publish({"type": event_type, "task_id": task.id, "status": task.status})
        return True

    async def stop_task(
        self,
        task: Task,
        *,
        target: TaskStatus,
        current_progress: str,
        message: str,
        detail: dict | None = None,
    ) -> Task:
        locked_task = await self.lock_task(task.id)
        if not locked_task:
            raise RuntimeStateError("任务不存在")
        task = locked_task
        employee = await self.lock_employee(task.employee_id) if task.employee_id else None
        runs = (
            (
                await self.session.execute(
                    select(Run)
                    .where(
                        Run.task_id == task.id,
                        Run.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .order_by(Run.run_number.desc())
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        run = next((item for item in runs if item.id == task.active_run_id), None)
        run = run or (runs[0] if runs else None)
        await TaskService(self.session).transition(
            task,
            target,
            current_progress=current_progress,
            message=message,
            detail=detail,
            run_id=run.id if run else None,
            commit=False,
        )
        run_status = RunStatus.SUSPENDED if target == TaskStatus.SUSPENDED else RunStatus.CANCELLED
        now = datetime.now(UTC)
        for active_run in runs:
            active_run.status = run_status
            active_run.finished_at = now
            active_run.heartbeat_at = now
            active_run.executor_status = (
                "ABORT_PENDING"
                if active_run.opencode_session_id and active_run.executor_type.startswith("opencode_server")
                else run_status.value
            )
            record_failure(
                active_run,
                (
                    FailureCode.USER_SUSPENDED
                    if target == TaskStatus.SUSPENDED
                    else FailureCode.USER_CANCELLED
                ),
                message,
            )
        if runs:
            outboxes = (
                (
                    await self.session.execute(
                        select(RunDispatchOutbox).where(
                            RunDispatchOutbox.run_id.in_([item.id for item in runs])
                        )
                    )
                )
                .scalars()
                .all()
            )
            for outbox in outboxes:
                if outbox.status != "SENT":
                    outbox.status = "CANCELLED"
                    outbox.next_retry_at = None
        await self._cancel_open_inquiries(task.id)
        stopped_run_ids = {item.id for item in runs}
        linked_task_run = await self.session.get(Run, task.active_run_id) if task.active_run_id else None
        if (
            task.active_run_id in stopped_run_ids
            or not linked_task_run
            or linked_task_run.status in TERMINAL_RUN_STATUSES
        ):
            task.active_run_id = None
        if employee:
            linked_employee_run = (
                await self.session.get(Run, employee.active_run_id) if employee.active_run_id else None
            )
            other_active = await self.session.scalar(
                select(Run).where(
                    Run.employee_id == employee.id,
                    Run.id.not_in(stopped_run_ids) if stopped_run_ids else True,
                    Run.status.in_(ACTIVE_RUN_STATUSES),
                )
            )
            if (
                employee.active_run_id in stopped_run_ids
                or not linked_employee_run
                or linked_employee_run.status in TERMINAL_RUN_STATUSES
            ) and not other_active:
                employee.active_run_id = None
                EmployeeService.release(employee)
        await self.session.commit()
        await event_bus.publish(
            {
                "type": "TASK_SUSPENDED" if target == TaskStatus.SUSPENDED else "TASK_CANCELLED",
                "task_id": task.id,
                "status": task.status,
            }
        )
        return task

    async def continue_run(
        self,
        task: Task,
        employee: DigitalEmployee,
        previous_run: Run,
        *,
        previous_status: RunStatus,
        failure_code: str | None,
        message: str,
        execution_token: str | None = None,
        trigger_reason: RunTriggerReason = RunTriggerReason.USER_CONTINUE,
    ) -> Run:
        """Close the old execution and queue its continuation in the same transaction."""

        if previous_status.value not in TERMINAL_RUN_STATUSES:
            raise RuntimeStateError(f"继续运行的前置状态必须是终态：{previous_status}")
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(employee.id)
        locked_previous = await self.session.scalar(
            select(Run)
            .where(Run.id == previous_run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not locked_task or not locked_employee or not locked_previous:
            raise RuntimeStateError("任务、员工或前置运行不存在")
        task = locked_task
        employee = locked_employee
        previous_run = locked_previous
        if execution_token and previous_run.execution_token != execution_token:
            raise RuntimeStateError("前置运行的执行租约已变更")
        if previous_run.status in TERMINAL_RUN_STATUSES and previous_run.status != previous_status:
            raise RuntimeStateError(f"前置运行已终结：{previous_run.status}")
        if previous_run.status not in {
            RunStatus.STARTING,
            RunStatus.RUNNING,
            previous_status,
        }:
            raise RuntimeStateError(f"前置运行不可继续：{previous_run.status}")
        if task.active_run_id not in {None, previous_run.id}:
            raise RuntimeStateError(f"任务租约已指向其他运行：{task.active_run_id}")
        if employee.active_run_id not in {None, previous_run.id}:
            raise RuntimeStateError(f"员工租约已指向其他运行：{employee.active_run_id}")

        now = datetime.now(UTC)
        previous_run.status = previous_status
        previous_run.finished_at = previous_run.finished_at or now
        previous_run.heartbeat_at = now
        previous_run.executor_status = previous_status.value
        record_failure(previous_run, failure_code, str((previous_run.result or {}).get("stderr") or message))
        run_number = (
            await self.session.scalar(select(func.max(Run.run_number)).where(Run.task_id == task.id)) or 0
        ) + 1
        retry_index = (
            (previous_run.retry_index or 0) + 1
            if trigger_reason == RunTriggerReason.AUTO_RETRY
            else (previous_run.retry_index or 0)
            if trigger_reason == RunTriggerReason.SESSION_RECOVERY
            else 0
        )
        run = Run(
            id=f"RUN-{uuid4().hex[:10].upper()}",
            task_id=task.id,
            employee_id=employee.id,
            previous_run_id=previous_run.id,
            run_number=run_number,
            trigger_reason=trigger_reason,
            retry_index=retry_index,
            status=RunStatus.QUEUED,
            executor_type=previous_run.executor_type,
            opencode_session_id=task.opencode_session_id,
            queued_at=now,
            executor_status="QUEUED",
            execution_environment_snapshot=task.execution_environment_snapshot or {},
        )
        self.session.add(run)
        await self.session.flush()
        task.status = TaskStatus.QUEUED
        task.active_run_id = run.id
        employee.active_run_id = run.id
        EmployeeService.reserve(employee)
        work_session = await ensure_task_session(self.session, task)
        work_session.current_run_id = run.id
        work_session.status = "ACTIVE"
        await TaskService(self.session).add_event(
            task,
            "RUN_CONTINUED",
            "runtime",
            message,
            {
                "previous_run_id": previous_run.id,
                "failure_code": failure_code,
                "trigger_reason": trigger_reason,
                "retry_index": retry_index,
            },
            run.id,
            commit=False,
        )
        await self._prepare_outbox(run)
        await self.session.commit()
        await event_bus.publish({"type": "RUN_CONTINUED", "task_id": task.id, "status": task.status})
        return run

    async def enqueue(self, task: Task, run: Run) -> bool:
        """Publish a transactional Outbox row for one queued Run."""

        outbox = await self.session.scalar(
            select(RunDispatchOutbox).where(RunDispatchOutbox.run_id == run.id)
        )
        if not outbox:
            if run.status != RunStatus.QUEUED:
                return False
            outbox = await self._prepare_outbox(run)
            await self.session.commit()
        return await self.publish_outbox(outbox.id)

    async def redeliver(self, task: Task, run: Run) -> bool:
        locked_task = await self.lock_task(task.id)
        locked_run = await self.session.scalar(
            select(Run).where(Run.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
        if (
            not locked_task
            or not locked_run
            or locked_run.status != RunStatus.QUEUED
            or locked_task.status != TaskStatus.QUEUED
            or locked_task.active_run_id not in {None, locked_run.id}
        ):
            await self.session.commit()
            return False
        task = locked_task
        run = locked_run
        run.dispatched_at = None
        await self._prepare_outbox(run, reset=True)
        await self.session.commit()
        return await self.enqueue(task, run)

    async def publish_outbox(self, outbox_id: str) -> bool:
        reference = await self.session.get(RunDispatchOutbox, outbox_id)
        if not reference:
            return False
        run_reference = await self.session.get(Run, reference.run_id)
        if not run_reference:
            return False
        task = await self.lock_task(run_reference.task_id)
        run = await self.session.scalar(select(Run).where(Run.id == run_reference.id).with_for_update())
        outbox = await self.session.scalar(
            select(RunDispatchOutbox).where(RunDispatchOutbox.id == outbox_id).with_for_update()
        )
        if not task or not run or not outbox:
            return False
        if run.status != RunStatus.QUEUED or task.status != TaskStatus.QUEUED:
            if outbox.status != "SENT":
                outbox.status = "CANCELLED"
                outbox.next_retry_at = None
                await self.session.commit()
            return False
        if outbox.status == "SENT":
            return True

        settings = get_settings()
        celery_task_id = f"run-{run.id}"
        run.dispatch_attempt = (run.dispatch_attempt or 0) + 1
        outbox.attempts = (outbox.attempts or 0) + 1
        try:
            from app.runtime.celery_app import process_task

            result = process_task.apply_async(
                args=[run.id],
                queue="agent",
                task_id=celery_task_id,
            )
        except Exception as exc:
            now = datetime.now(UTC)
            task.current_progress = "运行已排队，消息队列恢复后将自动重试"
            outbox.status = "PENDING"
            outbox.next_retry_at = now + timedelta(seconds=settings.outbox_retry_seconds)
            outbox.last_error = str(exc)[:4000]
            record_failure(run, FailureCode.DISPATCH_FAILED, str(exc))
            event = await TaskService(self.session).add_event(
                task,
                "RUN_DISPATCH_FAILED",
                "runtime",
                "运行消息投递失败，将通过 Outbox 自动重试",
                {"run_id": run.id, "attempt": run.dispatch_attempt, "error": str(exc)},
                run.id,
                commit=False,
            )
            await self.session.commit()
            await event_bus.publish(
                {
                    "type": "RUN_DISPATCH_FAILED",
                    "task_id": task.id,
                    "event_id": event.id,
                }
            )
            return False

        now = datetime.now(UTC)
        record_failure(run, None)
        run.celery_task_id = result.id or celery_task_id
        run.dispatched_at = now
        outbox.status = "SENT"
        outbox.sent_at = now
        outbox.next_retry_at = None
        outbox.last_error = None
        event = await TaskService(self.session).add_event(
            task,
            "RUN_DISPATCHED",
            "runtime",
            "Outbox 已将运行发送至 Agent 队列",
            {
                "run_id": run.id,
                "celery_task_id": run.celery_task_id,
                "attempt": run.dispatch_attempt,
            },
            run.id,
            commit=False,
        )
        await self.session.commit()
        await event_bus.publish({"type": "RUN_DISPATCHED", "task_id": task.id, "event_id": event.id})
        return True

    async def publish_pending_outbox(self, *, limit: int = 50) -> list[str]:
        now = datetime.now(UTC)
        ids = (
            (
                await self.session.execute(
                    select(RunDispatchOutbox.id)
                    .where(
                        RunDispatchOutbox.status == "PENDING",
                        or_(
                            RunDispatchOutbox.next_retry_at.is_(None),
                            RunDispatchOutbox.next_retry_at <= now,
                        ),
                    )
                    .order_by(RunDispatchOutbox.created_at)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        sent: list[str] = []
        for outbox_id in ids:
            if await self.publish_outbox(outbox_id):
                sent.append(outbox_id)
        return sent

    @staticmethod
    def release_employee(
        employee: DigitalEmployee,
        *,
        status: EmployeeStatus = EmployeeStatus.IDLE,
    ) -> None:
        EmployeeService.release(employee, status=status)

    async def reconcile(self) -> list[str]:
        session = self.session
        """Repair safe pointer projections and surface irreconcilable fake-running tasks."""

        changed: list[str] = []
        tasks_with_leases = (
            (await session.execute(select(Task).where(Task.active_run_id.is_not(None)))).scalars().all()
        )
        for candidate in tasks_with_leases:
            task = await RuntimeService(session).lock_task(candidate.id)
            if not task or not task.active_run_id:
                continue
            run = await session.get(Run, task.active_run_id)
            if run and run.task_id == task.id and run.status in ACTIVE_RUN_STATUSES:
                continue
            stale_run_id = task.active_run_id
            if run and run.task_id == task.id and task.status in {"QUEUED", "RUNNING", "WAIT_HUMAN"}:
                task.status = {
                    "COMPLETED": (
                        TaskStatus.PENDING_CONFIRMATION
                        if task.completion_policy == "MANUAL_CONFIRM"
                        else TaskStatus.COMPLETED
                    ),
                    "CANCELLED": TaskStatus.CANCELLED,
                    "SUSPENDED": TaskStatus.SUSPENDED,
                }.get(run.status, TaskStatus.EXECUTION_ERROR)
                if (run.result or {}).get("work_result"):
                    task.result = run.result["work_result"]
                task.finished_at = run.finished_at
            task.active_run_id = None
            session.add(
                Event(
                    task_id=task.id,
                    employee_id=task.employee_id,
                    run_id=stale_run_id if run else None,
                    event_type="STATE_RECONCILED",
                    phase="runtime",
                    message="已清理指向终态或缺失 Run 的任务租约",
                    detail={"stale_run_id": stale_run_id},
                )
            )
            changed.append(f"task-lease:{task.id}")

        employees = (
            (await session.execute(select(DigitalEmployee).where(DigitalEmployee.active_run_id.is_not(None))))
            .scalars()
            .all()
        )
        for candidate in employees:
            employee = await RuntimeService(session).lock_employee(candidate.id)
            if not employee or not employee.active_run_id:
                continue
            run = await session.get(Run, employee.active_run_id)
            if run and run.employee_id == employee.id and run.status in ACTIVE_RUN_STATUSES:
                continue
            stale_run_id = employee.active_run_id
            employee.active_run_id = None
            current_status = EmployeeStatus(employee.status)
            release_status = (
                current_status
                if current_status in {EmployeeStatus.OFFLINE, EmployeeStatus.PAUSED, EmployeeStatus.ERROR}
                else EmployeeStatus.IDLE
            )
            EmployeeService.release(employee, status=release_status)
            session.add(
                Event(
                    employee_id=employee.id,
                    run_id=stale_run_id if run else None,
                    event_type="STATE_RECONCILED",
                    phase="runtime",
                    message="已释放指向终态或缺失 Run 的员工占用",
                    detail={"stale_run_id": stale_run_id},
                )
            )
            changed.append(f"employee:{employee.id}")

        # Release pointer-cleanup locks before the next pass starts acquiring
        # Task -> Employee -> Run leases for active executions.
        await session.commit()

        active_runs = (
            (
                await session.execute(
                    select(Run).where(Run.status.in_(ACTIVE_RUN_STATUSES)).order_by(Run.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        runtime = RuntimeService(session)
        for candidate in active_runs:
            task = await runtime.lock_task(candidate.task_id)
            employee = await runtime.lock_employee(candidate.employee_id)
            run = await session.scalar(
                select(Run)
                .where(Run.id == candidate.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not task or not employee or not run or run.status not in ACTIVE_RUN_STATUSES:
                continue
            if task.active_run_id in {None, run.id} and employee.active_run_id in {None, run.id}:
                projected_task = {
                    RunStatus.QUEUED: TaskStatus.QUEUED,
                    RunStatus.STARTING: TaskStatus.QUEUED,
                    RunStatus.RUNNING: TaskStatus.RUNNING,
                    RunStatus.WAITING_INPUT: TaskStatus.WAIT_HUMAN,
                }[run.status]
                projected_employee = (
                    EmployeeStatus.WAIT_HUMAN
                    if run.status == RunStatus.WAITING_INPUT
                    else EmployeeStatus.WORKING
                )
                repaired = (
                    task.active_run_id != run.id
                    or employee.active_run_id != run.id
                    or task.status != projected_task
                    or employee.status != projected_employee
                    or employee.current_task_count != 1
                    or task.employee_id != employee.id
                )
                task.status = projected_task
                task.employee_id = employee.id
                task.active_run_id = run.id
                employee.active_run_id = run.id
                employee.current_task_count = 1
                employee.status = (
                    EmployeeStatus.WAIT_HUMAN
                    if run.status in {RunStatus.WAITING_INPUT}
                    else EmployeeStatus.WORKING
                )
                if repaired:
                    session.add(
                        Event(
                            task_id=task.id,
                            employee_id=employee.id,
                            run_id=run.id,
                            event_type="STATE_RECONCILED",
                            phase="runtime",
                            message="已按活动 Run 恢复 Task/Employee 租约指针",
                            detail={"run_status": run.status},
                        )
                    )
                    changed.append(f"run:{run.id}")
            else:
                run.status = RunStatus.LOST
                run.finished_at = datetime.now(UTC)
                run.executor_status = "LEASE_CONFLICT"
                record_failure(run, FailureCode.INVARIANT_VIOLATION, "活动运行租约冲突")
                session.add(
                    Event(
                        task_id=task.id,
                        employee_id=employee.id,
                        run_id=run.id,
                        event_type="STATE_CONFLICT",
                        phase="runtime",
                        message="活动 Run 与现有租约指针冲突，已保留现场等待处理",
                        detail={
                            "task_active_run_id": task.active_run_id,
                            "employee_active_run_id": employee.active_run_id,
                        },
                    )
                )
                changed.append(f"conflict:{run.id}")

        await session.commit()

        orphan_tasks = (
            (
                await session.execute(
                    select(Task).where(
                        Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAIT_HUMAN]),
                        Task.active_run_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for candidate in orphan_tasks:
            task = await runtime.lock_task(candidate.id)
            if (
                not task
                or task.active_run_id
                or task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAIT_HUMAN}
            ):
                continue
            active = await session.scalar(
                select(Run).where(
                    Run.task_id == task.id,
                    Run.status.in_(ACTIVE_RUN_STATUSES),
                )
            )
            if active:
                continue
            task.execution_error = {
                "reason": "任务处于执行态但没有活动 Run",
                "occurred_at": datetime.now(UTC).isoformat(),
            }
            await TaskService(session).transition(
                task,
                TaskStatus.EXECUTION_ERROR,
                current_progress="状态已校正：缺少活动运行",
                message="检测到假运行状态，已转为执行异常",
                detail={"reconciliation": "missing_active_run"},
                commit=False,
            )
            if task.employee_id:
                employee = await runtime.lock_employee(task.employee_id)
                if employee and not employee.active_run_id:
                    EmployeeService.release(employee, status=EmployeeStatus.ERROR)
            changed.append(f"task:{task.id}")

        orphan_employees = (
            await session.scalars(
                select(DigitalEmployee).where(
                    DigitalEmployee.active_run_id.is_(None),
                    or_(
                        DigitalEmployee.status.in_([EmployeeStatus.WORKING, EmployeeStatus.WAIT_HUMAN]),
                        DigitalEmployee.current_task_count > 0,
                    ),
                )
            )
        ).all()
        for candidate in orphan_employees:
            employee = await self.lock_employee(candidate.id)
            assigned = await session.scalar(
                select(Task.id)
                .where(
                    Task.employee_id == candidate.id,
                    Task.status == TaskStatus.ASSIGNED,
                )
                .limit(1)
            )
            if employee and not employee.active_run_id and not assigned:
                EmployeeService.release(employee)
                changed.append(f"employee:{employee.id}")
        await session.commit()
        return changed

    async def refresh_employee_heartbeats(self) -> list[str]:
        employees = (
            await self.session.scalars(
                select(DigitalEmployee).where(
                    DigitalEmployee.status.not_in([EmployeeStatus.PAUSED, EmployeeStatus.ERROR]),
                )
            )
        ).all()
        now = datetime.now(UTC)
        for candidate in employees:
            employee = await self.lock_employee(candidate.id)
            run = await self.session.get(Run, employee.active_run_id) if employee.active_run_id else None
            if run and run.employee_id == employee.id and run.status in ACTIVE_RUN_STATUSES:
                employee.status = (
                    EmployeeStatus.WAIT_HUMAN
                    if run.status == RunStatus.WAITING_INPUT
                    else EmployeeStatus.WORKING
                )
                employee.current_task_count = 1
            elif employee.status == EmployeeStatus.OFFLINE:
                employee.status = EmployeeStatus.IDLE
            employee.last_heartbeat = now
            employee.online_since = employee.online_since or now
        await self.session.commit()
        return [employee.id for employee in employees]

    async def confirm_session_aborted(self, task_id: str, session_id: str | None) -> None:
        await self.lock_task(task_id)
        rows = (
            await self.session.scalars(
                select(Run)
                .where(
                    Run.task_id == task_id,
                    Run.executor_status == "ABORT_PENDING",
                )
                .with_for_update()
            )
        ).all()
        for run in rows:
            run.executor_status = run.status
        await self.session.commit()

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.domain import EmployeeStatus, ExecutionMode, RunStatus, TaskStatus
from app.event_bus import event_bus
from app.models import (
    DigitalEmployee,
    OpenCodeExecutionEnvironment,
    Run,
    RunDispatchOutbox,
    RunInquiry,
    Task,
    TaskSession,
)
from app.runtime.environment import environment_snapshot
from app.services import EmployeeService, TaskService, ensure_task_session

ACTIVE_RUN_STATUSES = {
    RunStatus.QUEUED.value,
    RunStatus.STARTING.value,
    RunStatus.RUNNING.value,
    RunStatus.WAITING_INPUT.value,
}
TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.PASSED.value,
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

    async def lock_task(self, task_id: str) -> Task | None:
        return await self.session.scalar(
            select(Task)
            .where(Task.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
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
            if (
                linked
                and linked.task_id == task_id
                and linked.status in ACTIVE_RUN_STATUSES
            ):
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
            if (
                linked
                and linked.task_id == task.id
                and linked.status in ACTIVE_RUN_STATUSES
            ):
                raise RuntimeStateError(f"任务已有活动运行：{linked.id}")
            task.active_run_id = None
        if employee.active_run_id:
            linked = await self.session.get(Run, employee.active_run_id)
            if (
                linked
                and linked.employee_id == employee.id
                and linked.status in ACTIVE_RUN_STATUSES
            ):
                raise RuntimeStateError(f"员工已有活动运行：{linked.id}")
            employee.active_run_id = None
        reserved_for_task = task.status in {TaskStatus.ASSIGNED, TaskStatus.WAIT_HUMAN} or (
            task.status == TaskStatus.READY
            and bool(task.claimed_at)
            and task.employee_id == employee.id
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

    async def _prepare_outbox(self, run: Run, *, reset: bool = False) -> RunDispatchOutbox:
        await self.session.flush()
        outbox = await self.session.scalar(
            select(RunDispatchOutbox)
            .where(RunDispatchOutbox.run_id == run.id)
            .with_for_update()
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
        reset_runtime_session: bool = False,
        commit: bool = True,
    ) -> Run:
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(employee.id)
        if not locked_task or not locked_employee:
            raise RuntimeStateError("任务或员工不存在")
        task = locked_task
        employee = locked_employee
        await self._assert_slot_available(task, employee)

        previous_run = await self.session.scalar(
            select(Run).where(Run.task_id == task.id).order_by(Run.run_number.desc()).limit(1)
        )
        run_number = (
            await self.session.scalar(select(func.max(Run.run_number)).where(Run.task_id == task.id))
            or 0
        ) + 1
        if reset_runtime_session:
            task.opencode_session_id = None
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
        run = Run(
            id=f"RUN-{uuid4().hex[:10].upper()}",
            task_id=task.id,
            employee_id=employee.id,
            previous_run_id=previous_run.id if previous_run else None,
            run_number=run_number,
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
        if TaskStatus(task.status) in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            await service.reopen(
                task,
                TaskStatus.QUEUED,
                current_progress=current_progress,
                message=message,
                detail=detail,
                run_id=run.id,
                commit=False,
            )
        else:
            await service.transition(
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
            await event_bus.publish(
                {"type": "TASK_QUEUED", "task_id": task.id, "status": task.status}
            )
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
        run.queued_at = datetime.now(UTC)
        run.dispatched_at = None
        run.finished_at = None
        run.failure_type = None
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
            await event_bus.publish(
                {"type": "TASK_QUEUED", "task_id": task.id, "status": task.status}
            )
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
        run.status = RunStatus.STARTING
        run.worker_id = worker_id[:160]
        run.execution_token = token
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        run.executor_status = "STARTING"
        await self.session.commit()
        return task, employee, run, token

    async def mark_running(
        self,
        task: Task,
        run: Run,
        execution_token: str,
    ) -> bool:
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(run.employee_id)
        locked_run = await self.session.scalar(
            select(Run)
            .where(Run.id == run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
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
        await event_bus.publish(
            {"type": "TASK_RUNNING", "task_id": task.id, "status": task.status}
        )
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
            select(Run)
            .where(Run.id == run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
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
        await event_bus.publish(
            {"type": "WAIT_HUMAN", "task_id": task.id, "status": task.status}
        )
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
        failure_type: str | None = None,
        employee_status: EmployeeStatus = EmployeeStatus.IDLE,
    ) -> bool:
        if run_status.value not in TERMINAL_RUN_STATUSES:
            raise RuntimeStateError(f"非终态 Run 不能 finalize：{run_status}")
        locked_task = await self.lock_task(task.id)
        locked_employee = await self.lock_employee(employee.id)
        locked_run = await self.session.scalar(
            select(Run)
            .where(Run.id == run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
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
        run.failure_type = failure_type
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
        await event_bus.publish(
            {"type": event_type, "task_id": task.id, "status": task.status}
        )
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
        run_status = (
            RunStatus.SUSPENDED if target == TaskStatus.SUSPENDED else RunStatus.CANCELLED
        )
        now = datetime.now(UTC)
        for active_run in runs:
            active_run.status = run_status
            active_run.finished_at = now
            active_run.heartbeat_at = now
            active_run.executor_status = run_status.value
            active_run.failure_type = (
                "USER_SUSPENDED" if target == TaskStatus.SUSPENDED else "USER_CANCELLED"
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
        linked_task_run = (
            await self.session.get(Run, task.active_run_id) if task.active_run_id else None
        )
        if (
            task.active_run_id in stopped_run_ids
            or not linked_task_run
            or linked_task_run.status in TERMINAL_RUN_STATUSES
        ):
            task.active_run_id = None
        if employee:
            linked_employee_run = (
                await self.session.get(Run, employee.active_run_id)
                if employee.active_run_id
                else None
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
        failure_type: str | None,
        message: str,
        execution_token: str | None = None,
    ) -> tuple[Run, str]:
        """Atomically close one execution segment and start its in-worker continuation."""

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
        previous_run.failure_type = failure_type
        run_number = (
            await self.session.scalar(
                select(func.max(Run.run_number)).where(Run.task_id == task.id)
            )
            or 0
        ) + 1
        token = uuid4().hex
        run = Run(
            id=f"RUN-{uuid4().hex[:10].upper()}",
            task_id=task.id,
            employee_id=employee.id,
            previous_run_id=previous_run.id,
            run_number=run_number,
            status=RunStatus.RUNNING,
            executor_type=previous_run.executor_type,
            opencode_session_id=task.opencode_session_id,
            queued_at=now,
            dispatched_at=now,
            started_at=now,
            heartbeat_at=now,
            worker_id=previous_run.worker_id,
            execution_token=token,
            executor_status="RUNNING",
            execution_environment_snapshot=task.execution_environment_snapshot or {},
        )
        self.session.add(run)
        await self.session.flush()
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
            {"previous_run_id": previous_run.id, "failure_type": failure_type},
            run.id,
            commit=False,
        )
        await self.session.commit()
        await event_bus.publish(
            {"type": "RUN_CONTINUED", "task_id": task.id, "status": task.status}
        )
        return run, token

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
            select(Run)
            .where(Run.id == run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
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
        run = await self.session.scalar(
            select(Run).where(Run.id == run_reference.id).with_for_update()
        )
        outbox = await self.session.scalar(
            select(RunDispatchOutbox)
            .where(RunDispatchOutbox.id == outbox_id)
            .with_for_update()
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
        await event_bus.publish(
            {"type": "RUN_DISPATCHED", "task_id": task.id, "event_id": event.id}
        )
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

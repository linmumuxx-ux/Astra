import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import Settings
from app.domain import EmployeeStatus, EnvironmentStatus, RunStatus, TaskStatus
from app.models import DigitalEmployee, Event, Run, Task
from app.runtime.coordinator import TaskCoordinator
from app.runtime.lifecycle import ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, RuntimeService
from app.runtime.result_parser import build_work_result
from app.services import EmployeeService, TaskService

RECOVERABLE_STATUSES = {
    TaskStatus.RUNNING,
    TaskStatus.WAIT_HUMAN,
    TaskStatus.SUSPENDED,
    TaskStatus.EXECUTION_ERROR,
}


def environment_checked_after_error(task: Task, employee: DigitalEmployee) -> bool:
    environment = employee.execution_environment
    if not environment or environment.status != EnvironmentStatus.AVAILABLE:
        return False
    checked_at = environment.last_checked_at
    occurred_at = (task.execution_error or {}).get("occurred_at")
    if not checked_at or not occurred_at:
        return False
    checked_at = checked_at if checked_at.tzinfo else checked_at.replace(tzinfo=UTC)
    try:
        error_at = datetime.fromisoformat(str(occurred_at))
        error_at = error_at if error_at.tzinfo else error_at.replace(tzinfo=UTC)
    except ValueError:
        return False
    return checked_at > error_at


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def audit_incomplete_tasks(session: AsyncSession, settings: Settings) -> list[str]:
    """Preserve interrupted work and flag inactive executions without losing context."""
    now = datetime.now(UTC)
    inactive_before = now - timedelta(seconds=settings.inactivity_timeout)
    tasks = (
        (
            await session.execute(
                select(Task).where(Task.status.in_([status.value for status in RECOVERABLE_STATUSES]))
            )
        )
        .scalars()
        .all()
    )
    changed: list[str] = []
    for task in tasks:
        if task.status == TaskStatus.RUNNING and task.last_activity_at:
            if _utc(task.last_activity_at) < inactive_before and not task.inactivity_alert:
                task.inactivity_alert = True
                task.inactivity_alert_since = now
                session.add(
                    Event(
                        task_id=task.id,
                        employee_id=task.employee_id,
                        event_type="INACTIVITY_ALERT",
                        phase="observation",
                        message="任务长时间没有新的可观察活动",
                        detail={
                            "last_activity_at": task.last_activity_at.isoformat(),
                            "timeout_seconds": settings.inactivity_timeout,
                        },
                    )
                )
                changed.append(task.id)
    await session.commit()
    return changed


async def recover_available_tasks(session: AsyncSession) -> list[str]:
    """Resume execution-error tasks only after their recorded environment is available."""
    tasks = (
        (
            await session.execute(
                select(Task)
                .where(
                    Task.status == TaskStatus.EXECUTION_ERROR,
                    Task.employee_id.is_not(None),
                )
                .options(selectinload(Task.employee).selectinload(DigitalEmployee.execution_environment))
            )
        )
        .scalars()
        .all()
    )
    resumed: list[str] = []
    runtime = RuntimeService(session)
    for task in tasks:
        employee = task.employee
        if not employee or not employee.enabled:
            continue
        if employee.current_task_count or employee.status in {
            EmployeeStatus.OFFLINE,
            EmployeeStatus.PAUSED,
        }:
            continue
        if not environment_checked_after_error(task, employee):
            continue
        task.execution_error = {
            **(task.execution_error or {}),
            "auto_recovered_at": datetime.now(UTC).isoformat(),
        }
        run = await runtime.queue_new_run(
            task,
            employee,
            current_progress="执行环境已恢复，正在继续原任务",
            message="执行环境恢复，自动继续原 Agent 会话",
            detail={"recovery": "environment"},
        )
        resumed.append(run.id)
    return resumed


async def retry_stale_queued_runs(session: AsyncSession, settings: Settings) -> list[str]:
    """Redeliver durable queued runs that were never started."""

    retry_before = datetime.now(UTC) - timedelta(seconds=settings.recovery_interval)
    rows = (
        (
            await session.execute(
                select(Run, Task)
                .join(Task, Run.task_id == Task.id)
                .where(
                    Run.status == RunStatus.QUEUED,
                    Task.status == TaskStatus.QUEUED,
                    or_(Run.dispatched_at.is_(None), Run.dispatched_at < retry_before),
                )
                .order_by(Run.queued_at)
            )
        )
        .all()
    )
    retried: list[str] = []
    runtime = RuntimeService(session)
    for run, task in rows:
        run_id = run.id
        if await runtime.redeliver(task, run):
            retried.append(run_id)
    return retried


async def _probe_executor_status(
    task: Task,
    employee: DigitalEmployee,
    run: Run,
    settings: Settings,
) -> tuple[str, dict | None]:
    if (
        not run.executor_type.startswith("opencode_server")
        or not run.opencode_session_id
        or not (run.execution_environment_snapshot or {}).get("workspace_root")
    ):
        return "MISSING", None
    try:
        coordinator = TaskCoordinator()
        environment = coordinator._resolve_environment(task, employee)
        executor = coordinator._executor_for_environment(task, environment, None)
        status = await asyncio.wait_for(
            executor.get_status(run),
            timeout=max(5, min(30, settings.ssh_connect_timeout_seconds + 5)),
        )
        normalized = str(status or "UNKNOWN").upper()
        result = None
        if normalized in {"IDLE", "FINISHED", "COMPLETED", "DONE"}:
            result = await executor.collect_result(run)
        return normalized, result
    except Exception as exc:
        return "PROBE_ERROR", {"error": str(exc)[:2000]}


async def watchdog_stale_runs(
    session: AsyncSession,
    settings: Settings,
    *,
    status_probe=None,
) -> list[str]:
    """Conservatively reconcile Worker lease loss without replaying side effects."""

    now = datetime.now(UTC)
    startup_before = now - timedelta(seconds=settings.runtime_startup_timeout)
    heartbeat_before = now - timedelta(seconds=settings.runtime_heartbeat_timeout)
    rows = (
        (
            await session.execute(
                select(Run)
                .where(
                    or_(
                        (
                            (Run.status == RunStatus.STARTING)
                            & (Run.started_at < startup_before)
                            & or_(Run.heartbeat_at.is_(None), Run.heartbeat_at < startup_before)
                        ),
                        (
                            (Run.status == RunStatus.RUNNING)
                            & or_(Run.heartbeat_at.is_(None), Run.heartbeat_at < heartbeat_before)
                        ),
                    )
                )
                .order_by(Run.started_at)
            )
        )
        .scalars()
        .all()
    )
    reconciled: list[str] = []
    await session.commit()
    for candidate in rows:
        runtime = RuntimeService(session)
        if candidate.status == RunStatus.STARTING:
            task = await runtime.lock_task(candidate.task_id)
            employee = await runtime.lock_employee(candidate.employee_id)
            run = await session.scalar(
                select(Run)
                .where(Run.id == candidate.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not task or not employee or not run:
                await session.commit()
                continue
            heartbeat_at = run.heartbeat_at or run.started_at
            if (
                run.status != RunStatus.STARTING
                or not run.started_at
                or _utc(run.started_at) >= startup_before
                or (heartbeat_at and _utc(heartbeat_at) >= startup_before)
            ):
                await session.commit()
                continue
            task.execution_error = {
                "reason": "Agent Worker 在启动阶段丢失",
                "run_id": run.id,
                "worker_id": run.worker_id,
                "occurred_at": now.isoformat(),
            }
            await runtime.finalize_run(
                task,
                employee,
                run,
                run_status=RunStatus.LOST,
                task_status=TaskStatus.EXECUTION_ERROR,
                current_progress="运行启动超时，工作现场已保留",
                message="Agent Worker 启动租约已超时",
                failure_type="STARTUP_LEASE_LOST",
                employee_status=EmployeeStatus.ERROR,
            )
            reconciled.append(run.id)
            continue

        task_snapshot = await session.get(Task, candidate.task_id)
        employee_snapshot = await session.scalar(
            select(DigitalEmployee)
            .where(DigitalEmployee.id == candidate.employee_id)
            .options(selectinload(DigitalEmployee.execution_environment))
        )
        await session.commit()
        if not task_snapshot or not employee_snapshot:
            continue
        probe = status_probe or _probe_executor_status
        status, collected = await probe(task_snapshot, employee_snapshot, candidate, settings)
        status = str(status or "UNKNOWN").upper()

        task = await runtime.lock_task(candidate.task_id)
        employee = await runtime.lock_employee(candidate.employee_id)
        run = await session.scalar(
            select(Run)
            .where(Run.id == candidate.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not task or not employee or not run:
            await session.commit()
            continue
        heartbeat_at = run.heartbeat_at or run.started_at or run.created_at
        if run.status != RunStatus.RUNNING or _utc(heartbeat_at) >= heartbeat_before:
            await session.commit()
            continue
        if status in {"BUSY", "RUNNING", "WORKING"}:
            if run.executor_status != "ORPHANED_BUSY":
                run.executor_status = "ORPHANED_BUSY"
                session.add(
                    Event(
                        task_id=task.id,
                        employee_id=employee.id,
                        run_id=run.id,
                        event_type="RUN_ORPHANED_BUSY",
                        phase="runtime",
                        message="Worker 心跳丢失，但 OpenCode Session 仍在运行；未重复执行",
                        detail={"worker_id": run.worker_id, "session_id": run.opencode_session_id},
                    )
                )
            await session.commit()
            continue
        work_result = (collected or {}).get("work_result") if isinstance(collected, dict) else None
        raw_text = (collected or {}).get("raw_text") if isinstance(collected, dict) else None
        if not work_result and raw_text:
            work_result = build_work_result(str(raw_text), task.acceptance_criteria, "")
        if status in {"IDLE", "FINISHED", "COMPLETED", "DONE"} and work_result:
            task.result = work_result
            run.result = {**(run.result or {}), "work_result": work_result, "recovered": True}
            await runtime.finalize_run(
                task,
                employee,
                run,
                run_status=RunStatus.COMPLETED,
                task_status=(
                    TaskStatus.PENDING_CONFIRMATION
                    if task.completion_policy == "MANUAL_CONFIRM"
                    else TaskStatus.COMPLETED
                ),
                current_progress="已从 OpenCode Session 恢复执行结果",
                message="Worker 丢失后已收集并恢复运行结果",
                failure_type="WORKER_LOST_RESULT_RECOVERED",
            )
            reconciled.append(run.id)
            continue
        if status == "PROBE_ERROR":
            heartbeat_at = _utc(run.heartbeat_at or run.started_at or run.created_at)
            if heartbeat_at > now - timedelta(seconds=settings.runtime_heartbeat_timeout * 2):
                run.executor_status = "PROBE_ERROR"
                await session.commit()
                continue

        reason = (
            "Worker 心跳丢失，OpenCode Session 已结束但没有可收集结果"
            if status in {"IDLE", "FINISHED", "COMPLETED", "DONE"}
            else "Worker 心跳丢失且执行 Session 不可恢复"
        )
        task.execution_error = {
            "reason": reason,
            "run_id": run.id,
            "worker_id": run.worker_id,
            "executor_status": status,
            "probe": collected or {},
            "occurred_at": now.isoformat(),
        }
        await runtime.finalize_run(
            task,
            employee,
            run,
            run_status=RunStatus.LOST,
            task_status=TaskStatus.EXECUTION_ERROR,
            current_progress="Worker 运行租约丢失，等待人工恢复",
            message=reason,
            failure_type="WORKER_LEASE_LOST",
            employee_status=EmployeeStatus.ERROR,
        )
        reconciled.append(run.id)
    return reconciled


async def reconcile_runtime_state(session: AsyncSession) -> list[str]:
    """Repair safe pointer projections and surface irreconcilable fake-running tasks."""

    changed: list[str] = []
    tasks_with_leases = (
        (
            await session.execute(select(Task).where(Task.active_run_id.is_not(None)))
        )
        .scalars()
        .all()
    )
    for candidate in tasks_with_leases:
        task = await RuntimeService(session).lock_task(candidate.id)
        if not task or not task.active_run_id:
            continue
        run = await session.get(Run, task.active_run_id)
        if (
            run
            and run.task_id == task.id
            and run.status not in TERMINAL_RUN_STATUSES
        ):
            continue
        stale_run_id = task.active_run_id
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
        (
            await session.execute(
                select(DigitalEmployee).where(DigitalEmployee.active_run_id.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    for candidate in employees:
        employee = await RuntimeService(session).lock_employee(candidate.id)
        if not employee or not employee.active_run_id:
            continue
        run = await session.get(Run, employee.active_run_id)
        if (
            run
            and run.employee_id == employee.id
            and run.status not in TERMINAL_RUN_STATUSES
        ):
            continue
        stale_run_id = employee.active_run_id
        employee.active_run_id = None
        current_status = EmployeeStatus(employee.status)
        release_status = (
            current_status
            if current_status
            in {EmployeeStatus.OFFLINE, EmployeeStatus.PAUSED, EmployeeStatus.ERROR}
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
                select(Run)
                .where(Run.status.in_(ACTIVE_RUN_STATUSES))
                .order_by(Run.created_at.desc())
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
            repaired = task.active_run_id != run.id or employee.active_run_id != run.id
            task.active_run_id = run.id
            employee.active_run_id = run.id
            employee.current_task_count = 1
            employee.status = (
                EmployeeStatus.WAIT_HUMAN
                if run.status in {RunStatus.WAITING_INPUT, RunStatus.BLOCKED}
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
        elif run.executor_status != "LEASE_CONFLICT":
            run.executor_status = "LEASE_CONFLICT"
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
                    Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING]),
                    Task.active_run_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for candidate in orphan_tasks:
        task = await runtime.lock_task(candidate.id)
        if not task or task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
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

    if changed:
        await session.commit()
    return changed

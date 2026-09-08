import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import Settings
from app.domain import EmployeeStatus, EnvironmentStatus, RunStatus, RunTriggerReason, TaskStatus
from app.executors.errors import OpenCodeSessionNotFound
from app.models import DigitalEmployee, Event, Run, Task
from app.runtime.coordinator import TaskCoordinator
from app.runtime.failure import FailureCode
from app.runtime.lifecycle import RuntimeService
from app.runtime.result_parser import build_work_result
from app.services import WorkbenchService

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
        previous = await session.scalar(
            select(Run).where(Run.task_id == task.id).order_by(Run.run_number.desc()).limit(1)
        )
        if not previous or not previous.retryable:
            continue
        if previous.recovery_action == "WAIT_ENVIRONMENT":
            if not environment_checked_after_error(task, employee):
                continue
        elif (previous.retry_index or 0) >= employee.max_auto_retries:
            continue
        task.execution_error = {
            **(task.execution_error or {}),
            "auto_recovered_at": datetime.now(UTC).isoformat(),
        }
        run = await runtime.queue_new_run(
            task,
            employee,
            current_progress="正在恢复原任务",
            message="Runtime 自动创建恢复运行",
            detail={"recovery": previous.failure_code},
            trigger_reason=(
                RunTriggerReason.WORKER_RECOVERY
                if previous.failure_scope == "WORKER"
                else RunTriggerReason.AUTO_RETRY
            ),
            reset_runtime_session=previous.recovery_action == "CREATE_SESSION",
            commit=False,
        )
        run.retry_index = (previous.retry_index or 0) + 1
        await session.commit()
        resumed.append(run.id)
    return resumed


async def retry_stale_queued_runs(session: AsyncSession, settings: Settings) -> list[str]:
    """Redeliver durable queued runs that were never started."""

    retry_before = datetime.now(UTC) - timedelta(seconds=settings.recovery_interval)
    rows = (
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
    ).all()
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
    if not run.opencode_session_id:
        return "MISSING", None
    if not run.executor_type.startswith("opencode_server") or not (
        run.execution_environment_snapshot or {}
    ).get("workspace_root"):
        return "PROBE_ERROR", {"error": "执行现场缺少可探测的 Server 环境"}
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
        if normalized in {"IDLE", "FINISHED", "COMPLETED", "DONE", "WAITING_INPUT"}:
            result = await executor.collect_result(run)
        return normalized, result
    except OpenCodeSessionNotFound:
        return "MISSING", None
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
                            & or_(Run.started_at.is_(None), Run.started_at < startup_before)
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
        stale_before = startup_before if run.status == RunStatus.STARTING else heartbeat_before
        if run.status not in {RunStatus.STARTING, RunStatus.RUNNING} or _utc(heartbeat_at) >= stale_before:
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
        if status == "WAITING_INPUT" and (collected or {}).get("inquiry"):
            inquiry = collected["inquiry"]
            task.human_intervention = inquiry
            task.human_required_reason = inquiry["blocking_reason"]
            await WorkbenchService(session).create_inquiry(
                task,
                question=inquiry["requested_input"],
                description=inquiry["blocking_reason"],
                options=inquiry.get("options") or [],
                run_id=run.id,
                commit=False,
            )
            await runtime.mark_waiting(
                task, employee, run, current_progress="等待人工输入", message="已恢复 Agent 人工请求"
            )
            reconciled.append(run.id)
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
            )
            reconciled.append(run.id)
            continue
        if status not in {"MISSING", "LOST", "IDLE", "FINISHED", "COMPLETED", "DONE"}:
            # Unreachable is not missing. Keep the lease and probe on the next tick.
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
            failure_code=(
                FailureCode.WORKER_STARTUP_LOST
                if run.status == RunStatus.STARTING
                else FailureCode.WORKER_LEASE_LOST
            ),
            employee_status=EmployeeStatus.ERROR,
        )
        reconciled.append(run.id)
    return reconciled


async def reconcile_runtime_state(session: AsyncSession) -> list[str]:
    return await RuntimeService(session).reconcile()


async def recover_session_cleanup(session: AsyncSession, settings: Settings) -> list[str]:
    """Retry terminal session aborts durably, before allowing reuse of their session."""
    runs = (await session.scalars(select(Run).where(Run.executor_status == "ABORT_PENDING"))).all()
    cleaned = []
    for run in runs:
        task = await session.get(Task, run.task_id)
        employee = await RuntimeService(session).lock_employee(run.employee_id)
        await session.commit()
        if not task or not employee:
            continue
        try:
            coordinator = TaskCoordinator()
            environment = coordinator._resolve_environment(task, employee)
            executor = coordinator._executor_for_environment(task, environment, None)
            await asyncio.wait_for(
                executor.abort(run), timeout=max(5, settings.ssh_connect_timeout_seconds + 5)
            )
        except OpenCodeSessionNotFound:
            pass
        except Exception:
            continue
        await RuntimeService(session).confirm_session_aborted(task.id, run.opencode_session_id)
        cleaned.append(run.id)
    return cleaned

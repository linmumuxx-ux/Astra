from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import Settings
from app.domain import EmployeeStatus, EnvironmentStatus, TaskStatus
from app.models import DigitalEmployee, Event, Task
from app.services import TaskService

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
    service = TaskService(session)
    for task in tasks:
        employee = task.employee
        if not employee or not employee.enabled:
            continue
        if not environment_checked_after_error(task, employee):
            continue
        employee.status = EmployeeStatus.WORKING
        employee.current_task_count = 1
        task.execution_error = {
            **(task.execution_error or {}),
            "auto_recovered_at": datetime.now(UTC).isoformat(),
        }
        await service.transition(
            task,
            TaskStatus.RUNNING,
            current_progress="执行环境已恢复，正在继续原任务",
            message="执行环境恢复，自动继续原 OpenCode Session",
        )
        resumed.append(task.id)
    return resumed

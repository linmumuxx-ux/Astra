from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain import EmployeeStatus, TaskStatus
from app.models import DigitalEmployee, Task


async def heartbeat_active_employees(session: AsyncSession) -> list[str]:
    employees = (
        (
            await session.execute(
                select(DigitalEmployee).where(
                    DigitalEmployee.status.not_in([EmployeeStatus.PAUSED, EmployeeStatus.ERROR])
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for employee in employees:
        if employee.status == EmployeeStatus.OFFLINE:
            active_task_status = await session.scalar(
                select(Task.status)
                .where(
                    Task.employee_id == employee.id,
                    Task.status.in_(
                        [
                            TaskStatus.ASSIGNED,
                            TaskStatus.QUEUED,
                            TaskStatus.RUNNING,
                            TaskStatus.WAIT_HUMAN,
                            TaskStatus.EXECUTION_ERROR,
                        ]
                    ),
                )
                .order_by(Task.updated_at.desc())
                .limit(1)
            )
            if active_task_status == TaskStatus.WAIT_HUMAN:
                employee.status = EmployeeStatus.WAIT_HUMAN
            elif active_task_status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                employee.status = EmployeeStatus.WORKING
            else:
                employee.status = EmployeeStatus.IDLE
        employee.last_heartbeat = now
        employee.online_since = employee.online_since or now
    if employees:
        await session.commit()
    return [employee.id for employee in employees]


async def mark_stale_employees_offline(session: AsyncSession, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    threshold = datetime.now(UTC) - timedelta(seconds=settings.heartbeat_timeout)
    employees = (
        (
            await session.execute(
                select(DigitalEmployee).where(
                    DigitalEmployee.last_heartbeat.is_not(None),
                    DigitalEmployee.last_heartbeat < threshold,
                    DigitalEmployee.status.not_in(
                        [EmployeeStatus.OFFLINE, EmployeeStatus.PAUSED, EmployeeStatus.ERROR]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for employee in employees:
        employee.status = EmployeeStatus.OFFLINE
    if employees:
        await session.commit()
    return [employee.id for employee in employees]

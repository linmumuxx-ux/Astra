from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import EmployeeStatus, EnvironmentStatus, TaskStatus
from app.event_bus import event_bus
from app.models import DigitalEmployee, Task
from app.runtime.environment import environment_snapshot
from app.services import TaskService


class Dispatcher:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim_once(self) -> Task | None:
        employees = (
            (
                await self.session.execute(
                    select(DigitalEmployee)
                    .options(selectinload(DigitalEmployee.execution_environment))
                    .where(
                        DigitalEmployee.status == EmployeeStatus.IDLE,
                        DigitalEmployee.enabled.is_(True),
                        DigitalEmployee.auto_claim.is_(True),
                        DigitalEmployee.current_task_count < DigitalEmployee.max_concurrency,
                    )
                    .order_by(DigitalEmployee.id)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for employee in employees:
            if (
                not employee.execution_environment
                or employee.execution_environment.status != EnvironmentStatus.AVAILABLE
            ):
                continue
            candidates = (
                (
                    await self.session.execute(
                        select(Task)
                        .where(Task.status == TaskStatus.READY)
                        .order_by(Task.priority_weight.desc(), Task.created_at.asc())
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            task = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.task_type in employee.capabilities
                    and candidate.source in employee.source_scope
                ),
                None,
            )
            if not task:
                continue
            task.employee_id = employee.id
            task.execution_environment_snapshot = environment_snapshot(employee.execution_environment)
            task.max_retry_count = employee.max_auto_retries
            await TaskService(self.session).transition(
                task,
                TaskStatus.CLAIMED,
                phase="claimed",
                progress=8,
                message=f"任务已由 {employee.name} 领取",
                commit=False,
            )
            employee.status = EmployeeStatus.WORKING
            employee.current_task_count += 1
            await self.session.commit()
            await self.session.refresh(task)
            await event_bus.publish({"type": "TASK_CLAIMED", "task_id": task.id, "employee_id": employee.id})
            return task
        await self.session.rollback()
        return None

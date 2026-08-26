from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import EmployeeStatus, TaskStatus
from app.event_bus import event_bus
from app.models import DigitalEmployee, Task
from app.services import TaskService


class Dispatcher:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim_once(self) -> Task | None:
        employees = (
            (
                await self.session.execute(
                    select(DigitalEmployee)
                    .where(
                        DigitalEmployee.status == EmployeeStatus.IDLE,
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
            await event_bus.publish(
                {"type": "TASK_CLAIMED", "task_id": task.id, "employee_id": employee.id}
            )
            return task
        await self.session.rollback()
        return None

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import EmployeeStatus, EnvironmentStatus, TaskStatus
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
                        DigitalEmployee.current_task_count < 1,
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
            compatible = [
                candidate
                for candidate in candidates
                if candidate.claimed_at is None
                and candidate.task_type in employee.task_types
                and candidate.category_id in employee.category_ids
            ]
            task = next(
                (candidate for candidate in compatible if candidate.employee_id == employee.id),
                None,
            ) or next((candidate for candidate in compatible if not candidate.employee_id), None)
            if not task:
                continue
            task.employee_id = employee.id
            task.execution_environment_snapshot = environment_snapshot(employee.execution_environment)
            task.claimed_at = datetime.now(UTC)
            service = TaskService(self.session)
            await service.add_event(
                task,
                "TASK_ASSIGNED",
                "work",
                f"任务已分配给 {employee.name}",
                {"auto_execute": employee.auto_execute},
            )
            if employee.auto_execute:
                await service.transition(
                    task,
                    TaskStatus.RUNNING,
                    current_progress=f"{employee.name} 已开始处理",
                    message=f"{employee.name} 开始处理任务",
                    commit=False,
                )
                employee.status = EmployeeStatus.WORKING
                employee.current_task_count = 1
            else:
                task.current_progress = f"已分配给 {employee.name}，等待启动"
                employee.current_task_count = 1
            await self.session.commit()
            await self.session.refresh(task)
            return task
        await self.session.rollback()
        return None

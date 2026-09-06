from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import EmployeeStatus, EnvironmentStatus, TaskStatus
from app.event_bus import event_bus
from app.models import DigitalEmployee, Task
from app.runtime.environment import environment_snapshot
from app.runtime.lifecycle import RuntimeService
from app.services import TaskService


class Dispatcher:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim_once(self) -> Task | None:
        candidates = (
            (
                await self.session.execute(
                    select(Task)
                    .where(Task.status == TaskStatus.READY, Task.claimed_at.is_(None))
                    .order_by(Task.priority_weight.desc(), Task.created_at.asc())
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for task in candidates:
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
                            DigitalEmployee.active_run_id.is_(None),
                        )
                        .order_by(DigitalEmployee.id)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            compatible = [
                employee
                for employee in employees
                if employee.execution_environment
                and employee.execution_environment.status == EnvironmentStatus.AVAILABLE
                and task.task_type in employee.task_types
                and task.category_id in employee.category_ids
            ]
            employee = next(
                (item for item in compatible if item.id == task.employee_id),
                None,
            ) or next((item for item in compatible if not task.employee_id), None)
            if not employee:
                continue
            task.employee_id = employee.id
            task.execution_environment_snapshot = environment_snapshot(employee.execution_environment)
            task.claimed_at = datetime.now(UTC)
            service = TaskService(self.session)
            if employee.auto_execute:
                await service.add_event(
                    task,
                    "TASK_ASSIGNED",
                    "work",
                    f"任务已分配给 {employee.name}",
                    {"auto_execute": True},
                    commit=False,
                )
                await RuntimeService(self.session).queue_new_run(
                    task,
                    employee,
                    current_progress=f"{employee.name} 的运行已排队",
                    message=f"{employee.name} 的运行已进入 Agent 队列",
                    detail={"dispatch": "automatic"},
                    commit=False,
                )
            else:
                await service.transition(
                    task,
                    TaskStatus.ASSIGNED,
                    current_progress=f"已分配给 {employee.name}，等待启动",
                    message=f"任务已分配给 {employee.name}，等待人工启动",
                    detail={"auto_execute": False},
                    commit=False,
                )
                employee.current_task_count = 1
            await self.session.commit()
            await self.session.refresh(task)
            await event_bus.publish(
                {"type": "TASK_ASSIGNED", "task_id": task.id, "status": task.status}
            )
            return task
        await self.session.rollback()
        return None

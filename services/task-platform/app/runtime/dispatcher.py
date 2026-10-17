from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import EmployeeStatus, EnvironmentStatus, TaskStatus
from app.event_bus import event_bus
from app.models import DigitalEmployee, Task
from app.runtime.capability import dispatch_allowed
from app.runtime.environment import environment_snapshot
from app.runtime.occupancy import occupying_exists, sync_employee_occupancy
from app.runtime.repository import read_base_commit
from app.services import TaskService


class Dispatcher:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim_once(self) -> Task | None:
        # Recover a committed assignment if a worker exited before starting its Session.
        assigned = await self.session.scalar(
            select(Task)
            .join(DigitalEmployee, DigitalEmployee.id == Task.employee_id)
            .where(
                Task.status == TaskStatus.PENDING,
                Task.claimed_at.is_not(None),
                Task.current_session_id.is_(None),
                Task.pending_message_id.is_(None),
                Task.runtime_error.is_(None),
                DigitalEmployee.auto_execute.is_(True),
                DigitalEmployee.enabled.is_(True),
            )
            .order_by(Task.claimed_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if assigned:
            return assigned
        candidates = (
            (
                await self.session.execute(
                    select(Task)
                    .where(Task.status == TaskStatus.PENDING, Task.claimed_at.is_(None))
                    .order_by(Task.priority_weight.desc(), Task.created_at.asc())
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for task in candidates:
            if not task.repository_id:
                continue
            conditions = [
                DigitalEmployee.status == EmployeeStatus.IDLE,
                DigitalEmployee.enabled.is_(True),
                ~occupying_exists(DigitalEmployee.id),
            ]
            if task.employee_id:
                # 指定员工由人工分配，auto_claim 只约束无人认领的任务池。
                conditions.append(DigitalEmployee.id == task.employee_id)
            else:
                conditions.append(DigitalEmployee.auto_claim.is_(True))
            employees = (
                (
                    await self.session.execute(
                        select(DigitalEmployee)
                        .options(selectinload(DigitalEmployee.execution_environment))
                        .where(*conditions)
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
                and employee.execution_environment.repository_id == task.repository_id
                and dispatch_allowed(employee.execution_environment.status_detail)
                and task.task_type in employee.task_types
                and task.category_id in employee.category_ids
            ]
            employee = compatible[0] if compatible else None
            if not employee:
                continue
            task.employee_id = employee.id
            snapshot = environment_snapshot(employee.execution_environment)
            snapshot["base_commit"] = read_base_commit(employee.execution_environment.workspace_root)
            task.base_commit = snapshot["base_commit"] or None
            task.execution_environment_snapshot = snapshot
            task.claimed_at = datetime.now(UTC)
            service = TaskService(self.session)
            await service.add_event(
                task,
                "TASK_ASSIGNED",
                "work",
                f"任务已分配给 {employee.name}",
                {"auto_execute": employee.auto_execute},
                commit=False,
            )
            task.current_progress = f"已分配给 {employee.name}，等待启动"
            await sync_employee_occupancy(self.session, employee.id, preferred=task)
            await self.session.commit()
            await self.session.refresh(task)
            await event_bus.publish({"type": "TASK_ASSIGNED", "task_id": task.id, "status": task.status})
            return task
        await self.session.rollback()
        return None

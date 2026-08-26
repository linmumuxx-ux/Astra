from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain import PRIORITY_WEIGHT, EmployeeStatus, TaskStatus
from app.event_bus import event_bus
from app.models import DigitalEmployee, Event, Task
from app.schemas import TaskCreate
from app.state_machine import TaskStateMachine

STATUS_EVENT = {
    TaskStatus.READY: "TASK_READY",
    TaskStatus.CLAIMED: "TASK_CLAIMED",
    TaskStatus.RUNNING: "TASK_RUNNING",
    TaskStatus.VERIFYING: "VERIFY_STARTED",
    TaskStatus.RETRY: "RETRY_STARTED",
    TaskStatus.WAIT_HUMAN: "WAIT_HUMAN",
    TaskStatus.PAUSED: "TASK_PAUSED",
    TaskStatus.COMPLETED: "TASK_COMPLETED",
    TaskStatus.FAILED: "TASK_FAILED",
    TaskStatus.CANCELLED: "TASK_CANCELLED",
}


def new_task_id() -> str:
    now = datetime.now(UTC)
    return f"T-{now:%Y%m%d}-{uuid4().hex[:6].upper()}"


class TaskService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, payload: TaskCreate, *, ready: bool = True) -> Task:
        task = Task(
            id=new_task_id(),
            source=payload.source,
            external_task_id=payload.external_task_id,
            task_type=payload.task_type,
            title=payload.title,
            description=payload.description,
            input=payload.input,
            definition_of_done=payload.definition_of_done,
            priority=payload.priority.value,
            priority_weight=PRIORITY_WEIGHT[payload.priority],
            max_retry_count=payload.max_retry_count,
        )
        self.session.add(task)
        await self._record(
            task,
            "TASK_CREATED",
            "created",
            "任务已创建",
            {"source": task.source, "external_task_id": task.external_task_id},
        )
        if ready:
            TaskStateMachine.validate(TaskStatus.CREATED, TaskStatus.READY)
            task.status = TaskStatus.READY
            task.current_phase = "waiting_dispatch"
            task.progress = 3
            await self._record(task, "TASK_READY", task.current_phase, "任务已进入待领取队列")
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise
        await self.session.refresh(task)
        await event_bus.publish({"type": "TASK_CREATED", "task_id": task.id})
        return task

    async def transition(
        self,
        task: Task,
        target: TaskStatus,
        *,
        phase: str,
        progress: int | None = None,
        message: str | None = None,
        detail: dict | None = None,
        run_id: str | None = None,
        commit: bool = True,
    ) -> Task:
        previous = TaskStatus(task.status)
        TaskStateMachine.validate(previous, target)
        now = datetime.now(UTC)
        task.status = target.value
        task.current_phase = phase
        if progress is not None:
            task.progress = max(0, min(100, progress))
        if target is TaskStatus.CLAIMED:
            task.claimed_at = now
        if target is TaskStatus.RUNNING and task.started_at is None:
            task.started_at = now
        if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            task.finished_at = now
        event_type = STATUS_EVENT[target]
        await self._record(
            task,
            event_type,
            phase,
            message or f"任务状态从 {previous.value} 变更为 {target.value}",
            {"from": previous.value, "to": target.value, **(detail or {})},
            run_id=run_id,
        )
        if commit:
            await self.session.commit()
            await self.session.refresh(task)
            await event_bus.publish({"type": event_type, "task_id": task.id, "status": target.value})
        return task

    async def add_event(
        self,
        task: Task,
        event_type: str,
        phase: str,
        message: str,
        detail: dict | None = None,
        run_id: str | None = None,
    ) -> Event:
        event = await self._record(task, event_type, phase, message, detail, run_id)
        await self.session.commit()
        await self.session.refresh(event)
        await event_bus.publish({"type": event_type, "task_id": task.id, "event_id": event.id})
        return event

    async def _record(
        self,
        task: Task,
        event_type: str,
        phase: str,
        message: str,
        detail: dict | None = None,
        run_id: str | None = None,
    ) -> Event:
        event = Event(
            task_id=task.id,
            employee_id=task.employee_id,
            run_id=run_id,
            event_type=event_type,
            phase=phase,
            message=message,
            detail=detail or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event


class EmployeeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def set_status(self, employee: DigitalEmployee, status: EmployeeStatus) -> None:
        employee.status = status.value
        if status is not EmployeeStatus.OFFLINE:
            now = datetime.now(UTC)
            employee.last_heartbeat = now
            employee.online_since = employee.online_since or now
        await self.session.commit()
        await event_bus.publish(
            {"type": "EMPLOYEE_STATUS_CHANGED", "employee_id": employee.id, "status": status.value}
        )

    async def heartbeat(self, employee: DigitalEmployee) -> None:
        now = datetime.now(UTC)
        employee.last_heartbeat = now
        employee.online_since = employee.online_since or now
        if employee.status == EmployeeStatus.OFFLINE:
            employee.status = EmployeeStatus.IDLE
        await self.session.commit()


async def dashboard_metrics(session: AsyncSession) -> dict:
    task_counts = dict(
        (
            await session.execute(select(Task.status, func.count(Task.id)).group_by(Task.status))
        ).all()
    )
    employee_counts = dict(
        (
            await session.execute(
                select(DigitalEmployee.status, func.count(DigitalEmployee.id)).group_by(
                    DigitalEmployee.status
                )
            )
        ).all()
    )
    timezone = ZoneInfo(get_settings().timezone)
    today = datetime.now(timezone).date()
    day_start = datetime.combine(today, time.min, tzinfo=timezone).astimezone(UTC)
    day_end = day_start + timedelta(days=1)
    completed_today = (
        await session.scalar(
            select(func.count(Task.id)).where(
                Task.status == TaskStatus.COMPLETED,
                Task.finished_at >= day_start,
                Task.finished_at < day_end,
            )
        )
        or 0
    )
    failed_today = (
        await session.scalar(
            select(func.count(Task.id)).where(
                Task.status == TaskStatus.FAILED,
                Task.finished_at >= day_start,
                Task.finished_at < day_end,
            )
        )
        or 0
    )
    return {
        "online_employees": sum(
            count
            for status, count in employee_counts.items()
            if status not in {EmployeeStatus.OFFLINE, EmployeeStatus.ERROR}
        ),
        "running_tasks": sum(
            task_counts.get(status, 0)
            for status in [TaskStatus.CLAIMED, TaskStatus.RUNNING, TaskStatus.VERIFYING, TaskStatus.RETRY]
        ),
        "ready_tasks": task_counts.get(TaskStatus.READY, 0),
        "wait_human_tasks": task_counts.get(TaskStatus.WAIT_HUMAN, 0),
        "completed_today": completed_today,
        "failed_today": failed_today,
        "task_status_distribution": task_counts,
        "employee_status_distribution": employee_counts,
    }

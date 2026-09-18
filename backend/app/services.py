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
from app.usage import load_runs, summarize_runs

STATUS_EVENT = {status: f"TASK_{status.value}" for status in TaskStatus}


def new_task_id() -> str:
    now = datetime.now(UTC)
    return f"T-{now:%Y%m%d}-{uuid4().hex[:6].upper()}"


class TaskService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, payload: TaskCreate) -> Task:
        criteria = [
            {
                "id": criterion.id or f"AC-{index:02d}",
                "content": criterion.content,
            }
            for index, criterion in enumerate(payload.acceptance_criteria, start=1)
        ]
        task = Task(
            id=new_task_id(),
            source=payload.source,
            external_task_id=payload.external_task_id,
            task_type=payload.task_type.value,
            category_id=payload.category_id,
            title=payload.title,
            description=payload.description,
            acceptance_criteria=criteria,
            attachments=payload.attachments,
            priority=payload.priority.value,
            priority_weight=PRIORITY_WEIGHT[payload.priority],
            completion_policy=payload.completion_policy.value,
            employee_id=payload.employee_id,
            status=TaskStatus.PENDING,
            current_progress="等待领取",
            last_activity_at=datetime.now(UTC),
        )
        self.session.add(task)
        await self._record(
            task,
            "TASK_CREATED",
            "work",
            "任务已创建",
            {
                "source": task.source,
                "external_task_id": task.external_task_id,
                "employee_id": task.employee_id,
            },
        )
        await self._record(task, "TASK_PENDING", "work", "任务已进入待领取队列")
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
        current_progress: str | None = None,
        message: str | None = None,
        detail: dict | None = None,
        run_id: str | None = None,
        commit: bool = True,
    ) -> Task:
        previous = TaskStatus(task.status)
        TaskStateMachine.validate(previous, target)
        return await self._apply_transition(
            task,
            previous,
            target,
            current_progress=current_progress,
            message=message,
            detail=detail,
            run_id=run_id,
            commit=commit,
        )

    async def _apply_transition(
        self,
        task: Task,
        previous: TaskStatus,
        target: TaskStatus,
        *,
        current_progress: str | None,
        message: str | None,
        detail: dict | None,
        run_id: str | None = None,
        commit: bool = True,
    ) -> Task:
        now = datetime.now(UTC)
        task.status = target.value
        if current_progress is not None:
            task.current_progress = current_progress
        if target is TaskStatus.RUNNING and task.started_at is None:
            task.claimed_at = task.claimed_at or now
            task.started_at = now
        if target is TaskStatus.RUNNING:
            task.inactivity_alert = False
            task.inactivity_alert_since = None
            task.finished_at = None
        if target in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED}:
            task.finished_at = now
        event_type = STATUS_EVENT[target]
        await self._record(
            task,
            event_type,
            "work",
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
        *,
        commit: bool = True,
    ) -> Event:
        event = await self._record(task, event_type, phase, message, detail, run_id)
        if commit:
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
        task.last_activity_at = event.created_at or datetime.now(UTC)
        task.inactivity_alert = False
        task.inactivity_alert_since = None
        self.session.add(event)
        await self.session.flush()
        return event


class EmployeeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def reserve(employee: DigitalEmployee) -> None:
        """Reserve the employee's single execution slot."""

        employee.current_task_count = 1
        employee.status = EmployeeStatus.WORKING

    @staticmethod
    def release(
        employee: DigitalEmployee,
        *,
        status: EmployeeStatus = EmployeeStatus.IDLE,
    ) -> None:
        """Release the single execution slot idempotently."""

        employee.current_task_count = 0
        employee.status = status

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
        (await session.execute(select(Task.status, func.count(Task.id)).group_by(Task.status))).all()
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
                Task.status == TaskStatus.SUCCEEDED,
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
    usage_runs = await load_runs(session, start=day_start, end=day_end)
    usage = await summarize_runs(session, usage_runs)
    return {
        "online_employees": sum(
            count
            for status, count in employee_counts.items()
            if status not in {EmployeeStatus.OFFLINE, EmployeeStatus.ERROR}
        ),
        "running_tasks": sum(task_counts.get(status, 0) for status in [TaskStatus.RUNNING]),
        "idle_employees": employee_counts.get(EmployeeStatus.IDLE, 0),
        "error_employees": employee_counts.get(EmployeeStatus.ERROR, 0),
        "pending_tasks": task_counts.get(TaskStatus.PENDING, 0),
        "waiting_tasks": task_counts.get(TaskStatus.WAITING, 0),
        "failed_tasks": task_counts.get(TaskStatus.FAILED, 0),
        "completed_today": completed_today,
        "failed_today": failed_today,
        "today_tokens": usage["total_tokens"],
        "today_tool_calls": usage["tool_call_count"],
        "task_status_distribution": task_counts,
        "employee_status_distribution": employee_counts,
    }

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain import PRIORITY_WEIGHT, EmployeeStatus, TaskStatus
from app.event_bus import event_bus
from app.models import DigitalEmployee, Event, RunInquiry, SessionMessage, Task, TaskSession
from app.schemas import TaskCreate
from app.state_machine import TaskStateMachine
from app.usage import load_runs, summarize_runs

STATUS_EVENT = {
    TaskStatus.READY: "TASK_READY",
    TaskStatus.RUNNING: "TASK_RUNNING",
    TaskStatus.WAIT_HUMAN: "WAIT_HUMAN",
    TaskStatus.SUSPENDED: "TASK_SUSPENDED",
    TaskStatus.PENDING_CONFIRMATION: "RESULT_SUBMITTED",
    TaskStatus.COMPLETED: "TASK_COMPLETED",
    TaskStatus.FAILED: "TASK_FAILED",
    TaskStatus.EXECUTION_ERROR: "EXECUTION_ERROR",
    TaskStatus.CANCELLED: "TASK_CANCELLED",
}


def new_task_id() -> str:
    now = datetime.now(UTC)
    return f"T-{now:%Y%m%d}-{uuid4().hex[:6].upper()}"


def new_session_id() -> str:
    return f"SES-{uuid4().hex[:12].upper()}"


def initial_task_message(task: Task) -> str:
    description = task.description.strip()
    return description if description else task.title.strip()


def session_status(task_status: str | TaskStatus) -> str:
    return {
        TaskStatus.WAIT_HUMAN: "WAITING_INPUT",
        TaskStatus.SUSPENDED: "PAUSED",
        TaskStatus.COMPLETED: "COMPLETED",
        TaskStatus.FAILED: "FAILED",
        TaskStatus.CANCELLED: "CANCELLED",
    }.get(TaskStatus(task_status), "ACTIVE")


async def ensure_task_session(session: AsyncSession, task: Task) -> TaskSession:
    work_session = await session.scalar(select(TaskSession).where(TaskSession.task_id == task.id))
    if work_session:
        return work_session
    work_session = TaskSession(
        id=new_session_id(),
        task_id=task.id,
        status=session_status(task.status),
    )
    session.add(work_session)
    await session.flush()
    return work_session


class WorkbenchService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_message(
        self,
        task: Task,
        content: str,
        *,
        role: str = "user",
        status: str = "PENDING",
        run_id: str | None = None,
        commit: bool = True,
    ) -> SessionMessage:
        work_session = await ensure_task_session(self.session, task)
        message = SessionMessage(
            id=f"MSG-{uuid4().hex[:12].upper()}",
            session_id=work_session.id,
            run_id=run_id,
            role=role,
            content=content.strip(),
            status=status,
        )
        self.session.add(message)
        await TaskService(self.session)._record(
            task,
            "MESSAGE_USER" if role == "user" else "MESSAGE_AGENT",
            "message",
            content.strip()[:2000],
            {"message_id": message.id, "role": role, "status": status},
            run_id=run_id,
        )
        if commit:
            await self.session.commit()
            await self.session.refresh(message)
            await event_bus.publish({"type": "MESSAGE_USER", "task_id": task.id, "message_id": message.id})
        return message

    async def create_inquiry(
        self,
        task: Task,
        *,
        question: str,
        description: str = "",
        options: list[dict] | None = None,
        agent_name: str | None = None,
        run_id: str | None = None,
        commit: bool = True,
    ) -> RunInquiry:
        work_session = await ensure_task_session(self.session, task)
        existing = await self.session.scalar(
            select(RunInquiry).where(
                RunInquiry.session_id == work_session.id,
                RunInquiry.status.in_(["OPEN", "PENDING"]),
            )
        )
        if existing:
            return existing
        inquiry = RunInquiry(
            id=f"INQ-{uuid4().hex[:12].upper()}",
            session_id=work_session.id,
            run_id=run_id,
            agent_name=agent_name,
            question=question.strip(),
            description=description.strip(),
            options=options or [],
            status="OPEN",
        )
        self.session.add(inquiry)
        await TaskService(self.session)._record(
            task,
            "INQUIRY_CREATED",
            "inquiry",
            question.strip()[:2000],
            {"inquiry_id": inquiry.id, "options": inquiry.options},
            run_id=run_id,
        )
        if commit:
            await self.session.commit()
            await self.session.refresh(inquiry)
            await event_bus.publish({"type": "INQUIRY_CREATED", "task_id": task.id, "inquiry_id": inquiry.id})
        return inquiry

    async def answer_inquiry(
        self, task: Task, answer: str, *, run_id: str | None = None, commit: bool = False
    ) -> RunInquiry | None:
        work_session = await ensure_task_session(self.session, task)
        inquiry = await self.session.scalar(
            select(RunInquiry)
            .where(
                RunInquiry.session_id == work_session.id,
                RunInquiry.status.in_(["OPEN", "PENDING"]),
            )
            .order_by(RunInquiry.created_at.desc())
        )
        if inquiry:
            inquiry.answer = answer.strip()
            inquiry.status = "ANSWERED"
            inquiry.answered_at = datetime.now(UTC)
            await TaskService(self.session)._record(
                task,
                "INQUIRY_ANSWERED",
                "inquiry",
                "用户已回答确认问题",
                {"inquiry_id": inquiry.id, "answer": answer.strip()},
                run_id=run_id or inquiry.run_id,
            )
        if commit:
            await self.session.commit()
        return inquiry


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
            status=TaskStatus.READY,
            current_progress="等待领取",
            last_activity_at=datetime.now(UTC),
        )
        self.session.add(task)
        work_session = TaskSession(
            id=new_session_id(),
            task_id=task.id,
            status="ACTIVE",
        )
        self.session.add(work_session)
        self.session.add(
            SessionMessage(
                id=f"MSG-{uuid4().hex[:12].upper()}",
                session_id=work_session.id,
                role="user",
                content=initial_task_message(task),
                status="APPLIED",
            )
        )
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
        await self._record(task, "TASK_READY", "work", "任务已进入待领取队列")
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

    async def reopen(
        self,
        task: Task,
        target: TaskStatus,
        *,
        current_progress: str,
        message: str,
        detail: dict | None = None,
        commit: bool = True,
    ) -> Task:
        previous = TaskStatus(task.status)
        if previous not in {TaskStatus.COMPLETED, TaskStatus.FAILED} or target not in {
            TaskStatus.READY,
            TaskStatus.RUNNING,
        }:
            raise ValueError(f"不允许从 {previous} 重新打开为 {target}")
        return await self._apply_transition(
            task,
            previous,
            target,
            current_progress=current_progress,
            message=message,
            detail={"reopened": True, **(detail or {})},
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
        if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
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
        work_session = await ensure_task_session(self.session, task)
        work_session.status = session_status(target)
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
        task.last_activity_at = event.created_at or datetime.now(UTC)
        task.inactivity_alert = False
        task.inactivity_alert_since = None
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
        "ready_tasks": task_counts.get(TaskStatus.READY, 0),
        "wait_human_tasks": task_counts.get(TaskStatus.WAIT_HUMAN, 0),
        "pending_confirmation_tasks": task_counts.get(TaskStatus.PENDING_CONFIRMATION, 0),
        "execution_error_tasks": task_counts.get(TaskStatus.EXECUTION_ERROR, 0),
        "completed_today": completed_today,
        "failed_today": failed_today,
        "today_tokens": usage["total_tokens"],
        "today_tool_calls": usage["tool_call_count"],
        "task_status_distribution": task_counts,
        "employee_status_distribution": employee_counts,
    }

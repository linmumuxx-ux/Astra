from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain import EmployeeStatus, TaskStatus
from app.models import DigitalEmployee, Event, Task
from app.services import dashboard_metrics
from app.usage import day_bounds

ATTENTION_STATUSES = {
    TaskStatus.WAIT_HUMAN,
    TaskStatus.SUSPENDED,
    TaskStatus.PENDING_CONFIRMATION,
    TaskStatus.FAILED,
    TaskStatus.EXECUTION_ERROR,
}
ACTIVE_TASK_STATUSES = {
    TaskStatus.READY,
    TaskStatus.ASSIGNED,
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.WAIT_HUMAN,
    TaskStatus.SUSPENDED,
    TaskStatus.EXECUTION_ERROR,
}
ACTIVITY_EVENT_TYPES = {
    "TASK_CREATED",
    "TASK_RUNNING",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "EXECUTION_ERROR",
    "WAIT_HUMAN",
    "EMPLOYEE_CREATED",
}
TASK_PRIORITY = {
    TaskStatus.EXECUTION_ERROR: 0,
    TaskStatus.WAIT_HUMAN: 1,
    TaskStatus.RUNNING: 2,
    TaskStatus.QUEUED: 3,
    TaskStatus.SUSPENDED: 4,
    TaskStatus.ASSIGNED: 5,
    TaskStatus.READY: 6,
}
KNOWN_TEAMS = (
    ("automation", "自动化工程", 10, re.compile(r"自动化|集成|接口"), {"automation", "integration"}),
    ("testing-platform", "测试平台", 20, re.compile(r"测试平台|平台开发|平台测试"), {"testing-platform"}),
    (
        "defense-operation",
        "防线运营",
        30,
        re.compile(r"防线|质量运营|质量保障|安全运营"),
        {"defense-operation", "incident"},
    ),
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _local_date(value: datetime) -> str:
    timezone = ZoneInfo(get_settings().timezone)
    return _aware(value).astimezone(timezone).date().isoformat()


def _team_identity(employee: DigitalEmployee) -> tuple[str, str, int]:
    role = (employee.role or "").strip()
    category_ids = set(employee.category_ids or [])
    for team_id, name, order, pattern, categories in KNOWN_TEAMS:
        if pattern.search(role) or category_ids.intersection(categories):
            return team_id, name, order
    name = re.sub(r"(?:数字)?员工$|工程师$|专家$|专员$|开发$|测试$", "", role).strip() or "综合协作"
    digest = hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"team-{digest}", name, 100


def _employee_state(status: str) -> tuple[str, str]:
    if status == EmployeeStatus.WORKING:
        return "working", "执行中"
    if status in {EmployeeStatus.WAIT_HUMAN, EmployeeStatus.PAUSED}:
        return "waiting", "等待"
    if status == EmployeeStatus.ERROR:
        return "error", "异常"
    return "idle", "空闲"


def _attention_condition():
    return or_(
        Task.status.in_([status.value for status in ATTENTION_STATUSES]),
        Task.inactivity_alert.is_(True),
    )


async def dashboard_overview(session: AsyncSession) -> dict:
    metrics = await dashboard_metrics(session)
    employees = (await session.scalars(select(DigitalEmployee))).all()
    team_count = len({_team_identity(employee)[0] for employee in employees})
    attention_total = await session.scalar(select(func.count(Task.id)).where(_attention_condition()))
    return {
        "employee_total": len(employees),
        "team_count": team_count,
        "working_employees": metrics["employee_status_distribution"].get(EmployeeStatus.WORKING, 0),
        "running_tasks": metrics["running_tasks"],
        "completed_today": metrics["completed_today"],
        "attention_total": attention_total or 0,
    }


async def dashboard_employees(session: AsyncSession) -> dict:
    employees = (
        await session.scalars(
            select(DigitalEmployee).order_by(DigitalEmployee.created_at, DigitalEmployee.id)
        )
    ).all()
    active_tasks = (
        await session.scalars(
            select(Task)
            .where(Task.status.in_([status.value for status in ACTIVE_TASK_STATUSES]))
            .order_by(Task.updated_at.desc())
        )
    ).all()
    current_tasks: dict[str, Task] = {}
    for task in active_tasks:
        if not task.employee_id:
            continue
        existing = current_tasks.get(task.employee_id)
        if (
            existing is None
            or TASK_PRIORITY[TaskStatus(task.status)] < TASK_PRIORITY[TaskStatus(existing.status)]
        ):
            current_tasks[task.employee_id] = task

    teams: dict[str, dict] = {}
    for employee in employees:
        team_id, team_name, order = _team_identity(employee)
        team = teams.setdefault(
            team_id,
            {"id": team_id, "name": team_name, "order": order, "employee_count": 0, "employees": []},
        )
        task = current_tasks.get(employee.id)
        state, state_label = _employee_state(employee.status)
        team["employees"].append(
            {
                "id": employee.id,
                "name": employee.name,
                "role": employee.role,
                "status": employee.status,
                "state": state,
                "state_label": state_label,
                "current_task": (
                    {"id": task.id, "title": task.title, "status": task.status} if task else None
                ),
            }
        )
        team["employee_count"] += 1
    return {"teams": sorted(teams.values(), key=lambda team: (team["order"], team["name"]))}


def _attention_status(task: Task) -> tuple[str, str]:
    if task.status == TaskStatus.EXECUTION_ERROR:
        return "execution_failed", "执行失败"
    if task.inactivity_alert or task.status == TaskStatus.SUSPENDED:
        return "blocked", "任务阻塞"
    if task.status in {TaskStatus.WAIT_HUMAN, TaskStatus.PENDING_CONFIRMATION}:
        return "waiting", "等待处理"
    return "exception", "异常"


async def dashboard_attention(session: AsyncSession) -> dict:
    rows = (
        await session.execute(
            select(Task, DigitalEmployee.name)
            .outerjoin(DigitalEmployee, Task.employee_id == DigitalEmployee.id)
            .where(_attention_condition())
            .order_by(Task.updated_at.desc())
            .limit(5)
        )
    ).all()
    items = []
    for task, employee_name in rows:
        status, status_label = _attention_status(task)
        occurred_at = task.inactivity_alert_since or task.finished_at or task.updated_at
        items.append(
            {
                "task_id": task.id,
                "task_title": task.title,
                "employee_id": task.employee_id,
                "employee_name": employee_name or "未分配",
                "status": status,
                "status_label": status_label,
                "occurred_at": occurred_at,
            }
        )
    return {"items": items}


async def dashboard_tasks(session: AsyncSession) -> dict:
    metrics = await dashboard_metrics(session)
    start, end = day_bounds(7)
    today_start, today_end = day_bounds()
    execution_errors_today = await session.scalar(
        select(func.count(Task.id)).where(
            Task.status == TaskStatus.EXECUTION_ERROR,
            Task.updated_at >= today_start,
            Task.updated_at < today_end,
        )
    )
    rows = (
        await session.execute(
            select(Task.created_at, Task.finished_at, Task.status).where(
                or_(Task.created_at >= start, Task.finished_at >= start)
            )
        )
    ).all()
    timezone = ZoneInfo(get_settings().timezone)
    first_day = start.astimezone(timezone).date()
    today = (end - timedelta(microseconds=1)).astimezone(timezone).date()
    trend = []
    points: dict[str, dict[str, int | str]] = {}
    current = first_day
    while current <= today:
        key = current.isoformat()
        points[key] = {"date": key, "total": 0, "completed": 0}
        trend.append(points[key])
        current += timedelta(days=1)
    for created_at, finished_at, status in rows:
        created_key = _local_date(created_at)
        if created_key in points:
            points[created_key]["total"] += 1
        if status == TaskStatus.COMPLETED and finished_at:
            finished_key = _local_date(finished_at)
            if finished_key in points:
                points[finished_key]["completed"] += 1
    recent_rows = (
        await session.execute(
            select(Task, DigitalEmployee.name)
            .outerjoin(DigitalEmployee, Task.employee_id == DigitalEmployee.id)
            .order_by(Task.updated_at.desc())
            .limit(6)
        )
    ).all()
    return {
        "running": metrics["running_tasks"],
        "waiting": metrics["wait_human_tasks"]
        + metrics["pending_confirmation_tasks"]
        + metrics["task_status_distribution"].get(TaskStatus.SUSPENDED, 0),
        "completed_today": metrics["completed_today"],
        "failed_today": metrics["failed_today"] + (execution_errors_today or 0),
        "trend": trend,
        "recent": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "employee_id": task.employee_id,
                "employee_name": employee_name or "未分配",
                "updated_at": task.updated_at,
            }
            for task, employee_name in recent_rows
        ],
    }


def _activity_copy(
    event: Event,
    task_title: str | None,
    task_source: str | None,
    employee_name: str | None,
) -> tuple[str, str]:
    title = task_title or "任务"
    if event.event_type == "EMPLOYEE_CREATED":
        return "employee_created", f"新增数字员工：{employee_name or '数字员工'}"
    if event.event_type == "TASK_CREATED":
        if task_source == "nr_test_system":
            return "schedule_triggered", f"定时任务触发：{title}"
        return "task_created", f"创建任务：{title}"
    if event.event_type == "TASK_RUNNING":
        return "task_started", f"开始执行：{title}"
    if event.event_type == "TASK_COMPLETED":
        return "task_completed", f"完成任务：{title}"
    if event.event_type in {"TASK_FAILED", "EXECUTION_ERROR"}:
        return "task_failed", f"任务失败：{title}"
    return "waiting_human", f"等待人工确认：{title}"


async def dashboard_activity(session: AsyncSession) -> dict:
    rows = (
        await session.execute(
            select(Event, DigitalEmployee.name, Task.title, Task.source)
            .outerjoin(DigitalEmployee, Event.employee_id == DigitalEmployee.id)
            .outerjoin(Task, Event.task_id == Task.id)
            .where(Event.event_type.in_(ACTIVITY_EVENT_TYPES))
            .order_by(Event.created_at.desc())
            .limit(8)
        )
    ).all()
    items = []
    for event, employee_name, task_title, task_source in rows:
        kind, description = _activity_copy(event, task_title, task_source, employee_name)
        target_type = "task" if event.task_id else "employee" if event.employee_id else None
        target_id = event.task_id or event.employee_id
        items.append(
            {
                "id": event.id,
                "employee_id": event.employee_id,
                "employee_name": employee_name or "系统",
                "kind": kind,
                "description": description,
                "created_at": event.created_at,
                "target_type": target_type,
                "target_id": target_id,
            }
        )
    return {"items": items}

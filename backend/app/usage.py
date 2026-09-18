from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain import TaskStatus
from app.models import RuntimeSession, Task

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "llm_call_count",
    "tool_call_count",
)


def day_bounds(days: int = 1) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(get_settings().timezone)
    today = datetime.now(timezone).date()
    start_date = today - timedelta(days=max(1, days) - 1)
    start = datetime.combine(start_date, time.min, tzinfo=timezone).astimezone(UTC)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC)
    return start, end


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def load_sessions(
    session: AsyncSession,
    *,
    employee_id: str | None = None,
    task_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[RuntimeSession]:
    query = select(RuntimeSession)
    if employee_id:
        query = query.where(RuntimeSession.employee_id == employee_id)
    if task_id:
        query = query.where(RuntimeSession.task_id == task_id)
    if start:
        query = query.where(RuntimeSession.started_at >= start)
    if end:
        query = query.where(RuntimeSession.started_at < end)
    return (await session.execute(query.order_by(RuntimeSession.started_at))).scalars().all()


async def summarize_sessions(session: AsyncSession, sessions: list[RuntimeSession]) -> dict:
    summary = {field: None for field in TOKEN_FIELDS}
    for field in TOKEN_FIELDS:
        values = [getattr(item, field) for item in sessions if getattr(item, field) is not None]
        if values:
            summary[field] = sum(values)

    duration_seconds = 0
    now = datetime.now(UTC)
    for item in sessions:
        if not item.started_at:
            continue
        end = _aware(item.finished_at) if item.finished_at else now
        duration_seconds += max(0, int((end - _aware(item.started_at)).total_seconds()))

    tool_success = 0
    tool_failure = 0
    for item in sessions:
        for tool in item.tool_usage or []:
            tool_success += int(tool.get("success_count", 0))
            tool_failure += int(tool.get("failure_count", 0))

    task_ids = {item.task_id for item in sessions}
    completed_tasks = 0
    if task_ids:
        completed_tasks = len(
            (
                await session.execute(
                    select(Task.id).where(
                        Task.id.in_(task_ids), Task.status == TaskStatus.SUCCEEDED
                    )
                )
            )
            .scalars()
            .all()
        )
    return {
        **summary,
        "tool_success_count": tool_success,
        "tool_failure_count": tool_failure,
        "duration_seconds": duration_seconds,
        "completed_tasks": completed_tasks,
        "task_count": len(task_ids),
    }


async def tool_breakdown(session: AsyncSession, sessions: list[RuntimeSession]) -> list[dict]:
    grouped: dict[str, dict[str, int]] = defaultdict(
        lambda: {"call_count": 0, "success_count": 0, "failure_count": 0, "duration_ms": 0}
    )
    for item in sessions:
        for tool in item.tool_usage or []:
            name = str(tool.get("tool_name") or "其他")
            entry = grouped[name]
            entry["call_count"] += int(tool.get("call_count", 0))
            entry["success_count"] += int(tool.get("success_count", 0))
            entry["failure_count"] += int(tool.get("failure_count", 0))
            entry["duration_ms"] += int(tool.get("duration_ms", 0))
    return [
        {"tool_name": name, **values}
        for name, values in sorted(grouped.items(), key=lambda item: item[1]["call_count"], reverse=True)
    ]


async def employee_usage(session: AsyncSession, employee_id: str, days: int) -> dict:
    start, end = day_bounds(days)
    sessions = await load_sessions(session, employee_id=employee_id, start=start, end=end)
    summary = await summarize_sessions(session, sessions)
    tools = await tool_breakdown(session, sessions)
    timezone = ZoneInfo(get_settings().timezone)
    trend: list[dict] = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).astimezone(timezone).date()
        day_sessions = [
            item
            for item in sessions
            if item.started_at and _aware(item.started_at).astimezone(timezone).date() == day
        ]
        trend.append({"date": day.isoformat(), **await summarize_sessions(session, day_sessions)})
    return {
        "period_days": days,
        "summary": summary,
        "trend": trend,
        "tools": tools,
    }


async def task_usage(session: AsyncSession, task_id: str) -> dict:
    sessions = await load_sessions(session, task_id=task_id)
    return {
        "summary": await summarize_sessions(session, sessions),
        "tools": await tool_breakdown(session, sessions),
        "sessions": len(sessions),
    }
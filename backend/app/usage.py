from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain import TaskStatus
from app.models import Run, Task, ToolUsage

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


async def load_runs(
    session: AsyncSession,
    *,
    employee_id: str | None = None,
    task_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Run]:
    query = select(Run)
    if employee_id:
        query = query.where(Run.employee_id == employee_id)
    if task_id:
        query = query.where(Run.task_id == task_id)
    if start:
        query = query.where(Run.started_at >= start)
    if end:
        query = query.where(Run.started_at < end)
    return (await session.execute(query.order_by(Run.started_at))).scalars().all()


async def summarize_runs(session: AsyncSession, runs: list[Run]) -> dict:
    summary = {field: None for field in TOKEN_FIELDS}
    for field in TOKEN_FIELDS:
        values = [getattr(run, field) for run in runs if getattr(run, field) is not None]
        if values:
            summary[field] = sum(values)

    duration_seconds = 0
    now = datetime.now(UTC)
    for run in runs:
        if not run.started_at:
            continue
        end = _aware(run.finished_at) if run.finished_at else now
        duration_seconds += max(0, int((end - _aware(run.started_at)).total_seconds()))

    run_ids = [run.id for run in runs]
    tools = (
        (await session.execute(select(ToolUsage).where(ToolUsage.run_id.in_(run_ids)))).scalars().all()
        if run_ids
        else []
    )
    tool_success = sum(item.success_count for item in tools)
    tool_failure = sum(item.failure_count for item in tools)
    if summary["tool_call_count"] is None and tools:
        summary["tool_call_count"] = sum(item.call_count for item in tools)

    task_ids = {run.task_id for run in runs}
    completed_tasks = 0
    if task_ids:
        tasks = (
            (
                await session.execute(
                    select(Task).where(Task.id.in_(task_ids), Task.status == TaskStatus.COMPLETED)
                )
            )
            .scalars()
            .all()
        )
        completed_tasks = len(tasks)
    return {
        **summary,
        "tool_success_count": tool_success,
        "tool_failure_count": tool_failure,
        "duration_seconds": duration_seconds,
        "completed_tasks": completed_tasks,
        "task_count": len(task_ids),
    }


async def tool_breakdown(session: AsyncSession, runs: list[Run]) -> list[dict]:
    run_ids = [run.id for run in runs]
    if not run_ids:
        return []
    rows = (await session.execute(select(ToolUsage).where(ToolUsage.run_id.in_(run_ids)))).scalars().all()
    grouped: dict[str, dict[str, int]] = defaultdict(
        lambda: {"call_count": 0, "success_count": 0, "failure_count": 0, "duration_ms": 0}
    )
    for row in rows:
        item = grouped[row.tool_name]
        item["call_count"] += row.call_count
        item["success_count"] += row.success_count
        item["failure_count"] += row.failure_count
        item["duration_ms"] += row.duration_ms
    return [
        {"tool_name": name, **values}
        for name, values in sorted(grouped.items(), key=lambda item: item[1]["call_count"], reverse=True)
    ]


async def employee_usage(session: AsyncSession, employee_id: str, days: int) -> dict:
    start, end = day_bounds(days)
    runs = await load_runs(session, employee_id=employee_id, start=start, end=end)
    summary = await summarize_runs(session, runs)
    tools = await tool_breakdown(session, runs)
    timezone = ZoneInfo(get_settings().timezone)
    trend: list[dict] = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).astimezone(timezone).date()
        day_runs = [
            run
            for run in runs
            if run.started_at and _aware(run.started_at).astimezone(timezone).date() == day
        ]
        day_summary = await summarize_runs(session, day_runs)
        trend.append({"date": day.isoformat(), **day_summary})
    return {
        "period_days": days,
        "summary": summary,
        "trend": trend,
        "tools": tools,
    }


async def task_usage(session: AsyncSession, task_id: str) -> dict:
    runs = await load_runs(session, task_id=task_id)
    return {
        "summary": await summarize_runs(session, runs),
        "tools": await tool_breakdown(session, runs),
        "runs": len(runs),
    }

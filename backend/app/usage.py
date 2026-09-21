from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain import RuntimeSessionStatus, TaskStatus
from app.models import RuntimeSession, Task

# "任务成功率" 的已完成口径与 Experience 自动验证同源：Task.status == SUCCEEDED
# 表示业务签收完成（执行事实仍在 RuntimeSession），两处必须保持一致。
COMPLETED_TASK_STATUS = TaskStatus.SUCCEEDED

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


def _attributed_column():
    # Terminal Sessions belong to finished_at; live Sessions still use started_at.
    return func.coalesce(
        RuntimeSession.finished_at,
        RuntimeSession.started_at,
        RuntimeSession.created_at,
    )


def session_attributed_at(runtime_session: RuntimeSession) -> datetime:
    return _aware(
        runtime_session.finished_at
        or runtime_session.started_at
        or runtime_session.created_at
    )


def session_local_date(runtime_session: RuntimeSession) -> date:
    timezone = ZoneInfo(get_settings().timezone)
    return session_attributed_at(runtime_session).astimezone(timezone).date()


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
    attributed = _attributed_column()
    if start:
        query = query.where(attributed >= start)
    if end:
        query = query.where(attributed < end)
    return (await session.execute(query.order_by(attributed))).scalars().all()


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
                        Task.id.in_(task_ids), Task.status == COMPLETED_TASK_STATUS
                    )
                )
            )
            .scalars()
            .all()
        )

    execution_seconds = sum(item.execution_seconds or 0 for item in sessions)
    session_statuses = [item.status for item in sessions]
    return {
        **summary,
        "tool_success_count": tool_success,
        "tool_failure_count": tool_failure,
        "duration_seconds": duration_seconds,
        "execution_seconds": execution_seconds,
        "idle_seconds": max(0, duration_seconds - execution_seconds),
        "completed_tasks": completed_tasks,
        "task_count": len(task_ids),
        "session_count": len(sessions),
        "native_session_count": sum(item.native_session_count or 1 for item in sessions),
        "completed_sessions": session_statuses.count(RuntimeSessionStatus.SUCCEEDED.value),
        "failed_sessions": session_statuses.count(RuntimeSessionStatus.FAILED.value),
        "interrupted_sessions": session_statuses.count(RuntimeSessionStatus.INTERRUPTED.value),
    }


def model_breakdown(sessions: list[RuntimeSession]) -> list[dict]:
    grouped: dict[str, dict[str, int | str]] = {}
    for item in sessions:
        name = item.model_name or "未知"
        entry = grouped.setdefault(
            name,
            {
                "model_name": name,
                "session_count": 0,
                "total_tokens": 0,
                "llm_call_count": 0,
                "tool_call_count": 0,
            },
        )
        entry["session_count"] += 1
        entry["total_tokens"] += item.total_tokens or 0
        entry["llm_call_count"] += item.llm_call_count or 0
        entry["tool_call_count"] += item.tool_call_count or 0
    return sorted(grouped.values(), key=lambda item: item["total_tokens"], reverse=True)


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
        day_sessions = [item for item in sessions if session_local_date(item) == day]
        trend.append({"date": day.isoformat(), **await summarize_sessions(session, day_sessions)})
    return {
        "period_days": days,
        "summary": summary,
        "trend": trend,
        "tools": tools,
        "models": model_breakdown(sessions),
    }


async def task_usage(session: AsyncSession, task_id: str) -> dict:
    sessions = await load_sessions(session, task_id=task_id)
    return {
        "summary": await summarize_sessions(session, sessions),
        "tools": await tool_breakdown(session, sessions),
        "sessions": len(sessions),
        "root_session_count": len(sessions),
        "native_session_count": sum(item.native_session_count or 1 for item in sessions),
    }

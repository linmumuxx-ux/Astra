from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import get_settings
from app.models import Base, DigitalEmployee, RuntimeSession, Task
from app.services import dashboard_metrics
from app.usage import day_bounds, employee_usage, load_sessions, summarize_sessions, task_usage


def _local_datetime(days_ago: int, hour: int = 12) -> datetime:
    timezone = ZoneInfo(get_settings().timezone)
    target = datetime.now(timezone).date() - timedelta(days=days_ago)
    return datetime.combine(target, time(hour=hour), tzinfo=timezone).astimezone(UTC)


def _local_date(days_ago: int) -> str:
    timezone = ZoneInfo(get_settings().timezone)
    return (datetime.now(timezone).date() - timedelta(days=days_ago)).isoformat()


@pytest.fixture
async def usage_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(DigitalEmployee(id="E1", name="Engineer", role="build", status="IDLE"))
        await session.commit()
        yield session
    await engine.dispose()


async def test_finished_session_is_attributed_to_finished_day(usage_db):
    session = usage_db
    session.add(Task(id="T1", title="ok", task_type="ISSUE", status="SUCCEEDED", employee_id="E1"))
    session.add(
        RuntimeSession(
            id="ses_1",
            task_id="T1",
            employee_id="E1",
            workspace="/tmp/ws",
            environment={},
            status="SUCCEEDED",
            started_at=_local_datetime(1, hour=22),
            finished_at=_local_datetime(0, hour=1),
            total_tokens=100,
        )
    )
    await session.commit()

    result = await employee_usage(session, "E1", 3)
    trend = {point["date"]: point for point in result["trend"]}
    assert trend[_local_date(0)]["total_tokens"] == 100
    assert trend[_local_date(0)]["session_count"] == 1
    assert not trend[_local_date(1)]["total_tokens"]
    assert trend[_local_date(1)]["session_count"] == 0

    metrics = await dashboard_metrics(session)
    assert metrics["completed_today"] == 1


async def test_restart_keeps_terminal_history_but_task_count_follows_status(usage_db):
    session = usage_db
    # Yesterday's Session succeeded; today the Task was explicitly restarted so it
    # is RUNNING again while the immutable old Session stays terminal.
    session.add(Task(id="T1", title="ok", task_type="ISSUE", status="RUNNING", employee_id="E1"))
    session.add_all(
        [
            RuntimeSession(
                id="ses_old",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
                started_at=_local_datetime(1, hour=9),
                finished_at=_local_datetime(1, hour=10),
                total_tokens=100,
                model_name="provider/model-a",
            ),
            RuntimeSession(
                id="ses_new",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="RUNNING",
                started_at=_local_datetime(0, hour=9),
                total_tokens=20,
                model_name="provider/model-a",
            ),
        ]
    )
    await session.commit()

    result = await employee_usage(session, "E1", 3)
    trend = {point["date"]: point for point in result["trend"]}
    assert trend[_local_date(1)]["completed_sessions"] == 1
    assert trend[_local_date(0)]["completed_sessions"] == 0
    # History is immutable, but business completion follows the current Task.status.
    assert result["summary"]["completed_sessions"] == 1
    assert result["summary"]["completed_tasks"] == 0

    metrics = await dashboard_metrics(session)
    assert metrics["completed_today"] == 0


async def test_task_usage_counts_root_and_native_sessions(usage_db):
    session = usage_db
    session.add(Task(id="T1", title="ok", task_type="ISSUE", status="RUNNING", employee_id="E1"))
    session.add_all(
        [
            RuntimeSession(
                id="ses_1",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
                started_at=_local_datetime(0, hour=9),
                finished_at=_local_datetime(0, hour=10),
                native_session_count=1,
            ),
            RuntimeSession(
                id="ses_2",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
                started_at=_local_datetime(0, hour=11),
                finished_at=_local_datetime(0, hour=12),
                native_session_count=3,
            ),
        ]
    )
    await session.commit()

    result = await task_usage(session, "T1")
    assert result["sessions"] == 2
    assert result["root_session_count"] == 2
    assert result["native_session_count"] == 4


async def test_model_breakdown_groups_distinct_models(usage_db):
    session = usage_db
    session.add_all(
        [
            Task(id="T1", title="ok", task_type="ISSUE", status="SUCCEEDED", employee_id="E1"),
            Task(id="T2", title="ok", task_type="ISSUE", status="SUCCEEDED", employee_id="E1"),
        ]
    )
    await session.commit()
    session.add_all(
        [
            RuntimeSession(
                id="ses_a",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
                started_at=_local_datetime(0, hour=9),
                finished_at=_local_datetime(0, hour=10),
                model_name="provider/model-a",
                total_tokens=100,
                llm_call_count=2,
                tool_call_count=3,
            ),
            RuntimeSession(
                id="ses_b",
                task_id="T2",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
                started_at=_local_datetime(0, hour=9),
                finished_at=_local_datetime(0, hour=10),
                model_name="provider/model-b",
                total_tokens=40,
                llm_call_count=1,
                tool_call_count=1,
            ),
        ]
    )
    await session.commit()

    result = await employee_usage(session, "E1", 1)
    models = {item["model_name"]: item for item in result["models"]}
    assert set(models) == {"provider/model-a", "provider/model-b"}
    assert models["provider/model-a"]["session_count"] == 1
    assert models["provider/model-a"]["total_tokens"] == 100
    assert models["provider/model-a"]["llm_call_count"] == 2
    assert models["provider/model-a"]["tool_call_count"] == 3
    assert models["provider/model-b"]["total_tokens"] == 40


async def test_dashboard_completed_today_matches_session_attribution(usage_db):
    session = usage_db
    session.add(Task(id="T1", title="ok", task_type="ISSUE", status="SUCCEEDED", employee_id="E1"))
    session.add_all(
        [
            RuntimeSession(
                id="ses_today",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
                started_at=_local_datetime(0, hour=8),
                finished_at=_local_datetime(0, hour=9),
            ),
            RuntimeSession(
                id="ses_yesterday",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
                started_at=_local_datetime(1, hour=8),
                finished_at=_local_datetime(1, hour=9),
            ),
        ]
    )
    await session.commit()

    start, end = day_bounds(1)
    today_sessions = await load_sessions(session, start=start, end=end)
    summary = await summarize_sessions(session, today_sessions)
    metrics = await dashboard_metrics(session)
    assert summary["completed_sessions"] == 1
    assert metrics["completed_today"] == summary["completed_sessions"]
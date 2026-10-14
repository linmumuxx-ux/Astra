import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain import TaskStatus
from app.models import Base, Event, Task, TaskWakeOutbox
from app.runtime.opencode_model import direct_model, gateway_model, route_model_id
from app.schemas import TaskCreate
from app.services import TaskService
from app.task_tools import TaskTools
from tests.test_runtime import new_task


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def _create(**overrides) -> TaskCreate:
    return new_task(**overrides)


async def test_same_idempotency_key_returns_the_existing_task(session):
    service = TaskService(session)
    first = await service.create(
        _create(responsible_employee_id="emp_1", source_session_id="ses_1", idempotency_key="same-request")
    )
    second = await service.create(
        _create(title="另一标题", responsible_employee_id="emp_1", idempotency_key="same-request")
    )

    assert second.id == first.id
    assert second.title == first.title
    events = (await session.scalars(select(Event).where(Event.task_id == first.id))).all()
    assert [event.event_type for event in events] == ["TASK_CREATED", "TASK_PENDING"]


async def test_failure_and_recovery_coalesce_pending_wakes(session):
    task = await TaskService(session).create(
        _create(responsible_employee_id="emp_1", source_session_id="ses_1")
    )
    await TaskService(session).transition(task, TaskStatus.FAILED)
    pending = list(
        (await session.scalars(select(TaskWakeOutbox).where(TaskWakeOutbox.status == "pending"))).all()
    )
    assert len(pending) == 1
    assert "nexus_task_get" in pending[0].hint

    await TaskService(session).transition(task, TaskStatus.RUNNING)
    rows = list((await session.scalars(select(TaskWakeOutbox))).all())
    assert sorted(row.status for row in rows) == ["pending", "superseded"]
    assert task.status == TaskStatus.RUNNING


async def test_task_without_responsible_employee_does_not_wake(session):
    task = await TaskService(session).create(_create())
    await TaskService(session).transition(task, TaskStatus.FAILED)
    rows = list((await session.scalars(select(TaskWakeOutbox))).all())
    assert rows == []


async def test_illegal_control_leaves_concluded_status(session):
    task = await TaskService(session).create(_create(responsible_employee_id="emp_1"))
    task.status = TaskStatus.SUCCEEDED.value
    await session.commit()
    tools = TaskTools(session)

    paused = await tools.pause(task.id)
    terminated = await tools.terminate(task.id)
    retried = await tools.retry(task.id)

    assert paused["ok"] is False
    assert terminated["ok"] is False
    assert retried["ok"] is False
    current = await session.get(Task, task.id)
    assert current.status == TaskStatus.SUCCEEDED.value


async def test_retry_pending_does_not_start(session):
    task = await TaskService(session).create(_create())
    result = await TaskTools(session).retry(task.id)
    assert result["ok"] is False
    current = await session.get(Task, task.id)
    assert current.status == TaskStatus.PENDING.value


def test_opencode_model_names():
    assert route_model_id("deepseek/deepseek-flash") == "deepseek-flash"
    assert route_model_id("astra-gateway/deepseek-flash") == "deepseek-flash"
    assert gateway_model("deepseek/deepseek-flash") == "astra-gateway/deepseek-flash"
    assert direct_model("opencode/glm-5.1", None) == "opencode/glm-5.1"
    assert direct_model(None, "deepseek/deepseek-flash") == "deepseek/deepseek-flash"

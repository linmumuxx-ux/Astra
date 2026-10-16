from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain import RuntimeSessionStatus, TaskStatus
from app.models import Base, DigitalEmployee, Event, RuntimeSession, Task, TaskWakeOutbox
from app.runtime.lifecycle import RuntimeService
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


async def test_refused_start_returns_ok_false_after_rollback(session):
    task = await TaskService(session).create(_create())
    result = await TaskTools(session).start(task.id)

    assert result["ok"] is False
    assert result["task_id"] == task.id
    assert "请先分配已配置运行环境的员工" in result["error"]
    current = await session.get(Task, task.id)
    assert current.status == TaskStatus.PENDING.value


async def test_paused_finished_turn_stays_waiting(session):
    started = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    session.add(DigitalEmployee(id="worker-1", name="执行员工", role="工程"))
    session.add(
        Task(
            id="T-paused",
            task_type="ISSUE",
            title="登录修复",
            status=TaskStatus.WAITING.value,
            employee_id="worker-1",
            workspace="/tmp/task-ws",
            current_session_id="ses_done",
            last_message_id="msg_done",
            turn_started_at=started,
        )
    )
    session.add(
        RuntimeSession(
            id="ses_done",
            task_id="T-paused",
            employee_id="worker-1",
            workspace="/tmp/task-ws",
            environment={},
            status=RuntimeSessionStatus.SUCCEEDED.value,
        )
    )
    await session.commit()

    class IdleClient:
        def __init__(self) -> None:
            self.history_reads = 0

        async def status(self, _directory, _session_id):
            return "idle"

        async def children(self, _directory, _session_id):
            return []

        async def questions(self, _directory):
            return []

        async def permissions(self, _directory):
            return []

        async def messages(self, _directory, _session_id):
            self.history_reads += 1
            raise AssertionError("暂停后的已完成回合不应再读历史")

    client = IdleClient()
    refreshed = await RuntimeService(session).refresh("T-paused", client=client)

    assert client.history_reads == 0
    assert refreshed.status == TaskStatus.WAITING.value


def test_task_mcp_structured_output_accepts_dict_annotations():
    from app.task_mcp import build_mcp_server

    server = build_mcp_server()
    tools = server._tool_manager.list_tools()
    assert {tool.name for tool in tools} >= {"nexus_task_create", "nexus_task_get", "nexus_task_start"}
    assert all(tool.output_schema for tool in tools)


def test_opencode_model_names():
    assert route_model_id(None) == "cat-jam-free"
    assert route_model_id("opencode/cat-jam-free") == "cat-jam-free"
    assert gateway_model("opencode/cat-jam-free") == "astra-gateway/cat-jam-free"
    assert route_model_id("deepseek/deepseek-flash") == "deepseek-flash"
    assert route_model_id("astra-gateway/deepseek-flash") == "deepseek-flash"
    assert gateway_model("deepseek/deepseek-flash") == "astra-gateway/deepseek-flash"
    assert direct_model("opencode/glm-5.1", None) == "opencode/glm-5.1"
    assert direct_model(None, "opencode/cat-jam-free") == "opencode/cat-jam-free"

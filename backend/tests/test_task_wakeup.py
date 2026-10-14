import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain import TaskStatus
from app.models import Base, Task, TaskWakeOutbox
from app.runtime.task_wakeup import WakeRetry, deliver_pending
from app.services import TaskService
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


class RecordingSender:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.sent: list[str] = []

    async def send(self, row: TaskWakeOutbox) -> None:
        if self.error:
            raise self.error
        self.sent.append(row.task_id)


async def test_delivery_marks_row_without_changing_task_status(session):
    task = await TaskService(session).create(new_task(responsible_employee_id="emp_1"))
    await TaskService(session).transition(task, TaskStatus.FAILED)
    sender = RecordingSender()

    delivered = await deliver_pending(session, sender)

    assert delivered == 1
    assert sender.sent == [task.id]
    current = await session.get(Task, task.id)
    assert current.status == TaskStatus.FAILED.value
    row = await session.scalar(select(TaskWakeOutbox))
    assert row.status == "delivered"


async def test_missing_session_stays_pending_for_retry(session):
    task = await TaskService(session).create(
        new_task(responsible_employee_id="emp_1", source_session_id="missing")
    )
    await TaskService(session).transition(task, TaskStatus.WAITING)
    sender = RecordingSender(WakeRetry("没有可唤醒的会话"))

    delivered = await deliver_pending(session, sender)

    assert delivered == 0
    row = await session.scalar(select(TaskWakeOutbox))
    assert row.status == "pending"
    assert row.attempts == 1
    current = await session.get(Task, task.id)
    assert current.status == TaskStatus.WAITING.value

import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import SessionLocal, init_database
from app.domain import EmployeeStatus, Priority, TaskStatus
from app.executors.base import ExecutorResult, OpenCodeExecutor
from app.models import Base, DigitalEmployee, Event, Evidence, Run, Task
from app.runtime.coordinator import TaskCoordinator
from app.runtime.dispatcher import Dispatcher
from app.runtime.scout import TaskScout
from app.runtime.verifier import TaskVerifier
from app.schemas import TaskCreate
from app.services import TaskService
from app.sources.base import ExternalTask, TaskSource


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def test_create_task_records_ready_event(session):
    task = await TaskService(session).create(
        TaskCreate(task_type="script_generate", title="生成脚本", priority=Priority.P1)
    )

    assert task.status == TaskStatus.READY
    events = (
        (await session.execute(select(Event).where(Event.task_id == task.id).order_by(Event.id)))
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["TASK_CREATED", "TASK_READY"]


async def test_dispatcher_matches_capability_and_source_atomically(session):
    employee = DigitalEmployee(
        id="astra-test",
        name="Astra Test",
        role="测试员工",
        status=EmployeeStatus.IDLE,
        capabilities=["script_generate"],
        source_scope=["manual"],
        max_concurrency=1,
    )
    session.add(employee)
    await session.commit()
    task = await TaskService(session).create(
        TaskCreate(task_type="script_generate", title="匹配任务")
    )

    claimed = await Dispatcher(session).claim_once()

    assert claimed and claimed.id == task.id
    assert claimed.status == TaskStatus.CLAIMED
    assert claimed.employee_id == employee.id
    await session.refresh(employee)
    assert employee.status == EmployeeStatus.WORKING
    assert employee.current_task_count == 1


class FakeSource(TaskSource):
    id = "nr_test_system"

    async def discover_tasks(self):
        return [
            ExternalTask(
                external_task_id="EXT-1",
                task_type="script_generate",
                title="外部任务",
            )
        ]

    async def get_task(self, external_task_id):
        return (await self.discover_tasks())[0]

    async def update_task(self, external_task_id, result):
        return None

    async def heartbeat(self):
        return True


async def test_scout_is_idempotent(session):
    scout = TaskScout(session, [FakeSource()])
    first = await scout.poll_once()
    second = await scout.poll_once()

    assert len(first) == 1
    assert second == []
    assert await session.scalar(select(func.count(Task.id))) == 1


async def test_verifier_runs_real_command_and_saves_evidence(tmp_path: Path):
    workspace = tmp_path / "task"
    source = workspace / "source"
    evidence = workspace / "evidence"
    source.mkdir(parents=True)
    evidence.mkdir()
    (source / "test_target.py").write_text("assert True\n", encoding="utf-8")
    (evidence / "opencode_output.json").write_text("{}", encoding="utf-8")
    task = Task(
        id="T-VERIFY",
        task_type="script_generate",
        title="验证任务",
        input={
            "verification": {
                "required_files": ["test_target.py"],
                "test_command": [sys.executable, "-c", "print('PASS')"],
            }
        },
    )

    result = await TaskVerifier().verify(task, workspace)

    assert result.passed is True
    assert (evidence / "execution.log").read_text().strip() == "PASS"
    assert (evidence / "test_result.json").is_file()
    assert (evidence / "verify_report.json").is_file()


async def test_verifier_rejects_model_only_completion(tmp_path: Path):
    workspace = tmp_path / "task"
    (workspace / "source").mkdir(parents=True)
    (workspace / "evidence").mkdir()
    task = Task(id="T-NO-COMMAND", task_type="script_generate", title="无验证命令", input={})

    result = await TaskVerifier().verify(task, workspace)

    assert result.passed is False
    assert result.repairable is False
    assert "不能程序化证明完成" in result.items[0].detail


class FailThenPassExecutor(OpenCodeExecutor):
    def __init__(self):
        self.attempt = 0

    async def start(self, task, workspace):
        self.attempt += 1
        return ExecutorResult(
            status="FAILED",
            exit_code=1,
            session_id="ses-e2e",
            output=[{"type": "result", "status": "failed"}],
            stderr="generated test failed",
        )

    async def resume(self, task, run, workspace):
        self.attempt += 1
        (workspace / "source" / "result.txt").write_text("PASS", encoding="utf-8")
        return ExecutorResult(
            status="SUCCEEDED",
            exit_code=0,
            session_id="ses-e2e",
            output=[{"type": "result", "status": "completed"}],
        )

    async def get_status(self, run):
        return run.status

    async def abort(self, run):
        return None

    async def collect_result(self, run):
        return run.result or {}


async def test_complete_runtime_closure_retries_same_session_and_verifies(tmp_path: Path):
    await init_database()
    project = tmp_path / "project"
    project.mkdir()
    async with SessionLocal() as global_session:
        employee = DigitalEmployee(
            id="astra-e2e",
            name="Astra E2E",
            role="测试员工",
            status=EmployeeStatus.WORKING,
            capabilities=["script_generate"],
            source_scope=["manual"],
            current_task_count=1,
        )
        global_session.add(employee)
        await global_session.commit()
        task = await TaskService(global_session).create(
            TaskCreate(
                task_type="script_generate",
                title="闭环验收任务",
                input={
                    "project_path": str(project),
                    "verification": {
                        "required_files": ["result.txt"],
                        "test_command": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; assert Path('result.txt').read_text() == 'PASS'",
                        ],
                    },
                },
                max_retry_count=2,
            )
        )
        task.employee_id = employee.id
        await TaskService(global_session).transition(
            task, TaskStatus.CLAIMED, phase="claimed", progress=8
        )
        task_id = task.id

    executor = FailThenPassExecutor()
    await TaskCoordinator(executor=executor).process(task_id)

    async with SessionLocal() as global_session:
        task = await global_session.get(Task, task_id)
        employee = await global_session.get(DigitalEmployee, "astra-e2e")
        runs = (
            (await global_session.execute(select(Run).where(Run.task_id == task_id)))
            .scalars()
            .all()
        )
        evidence = (
            (await global_session.execute(select(Evidence).where(Evidence.task_id == task_id)))
            .scalars()
            .all()
        )

    assert executor.attempt == 2
    assert task and task.status == TaskStatus.COMPLETED
    assert task.opencode_session_id == "ses-e2e"
    assert task.retry_count == 1
    assert employee and employee.status == EmployeeStatus.IDLE
    assert len(runs) == 2
    assert {item.name for item in evidence} >= {
        "opencode_output.json",
        "execution.log",
        "test_result.json",
        "verify_report.json",
    }

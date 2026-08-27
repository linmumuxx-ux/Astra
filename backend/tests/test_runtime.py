from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import SessionLocal, init_database
from app.domain import EmployeeStatus, EnvironmentStatus, Priority, TaskStatus, TaskType
from app.executors.base import ExecutorResult, OpenCodeExecutor, TokenUsage, ToolUsageResult
from app.executors.usage import parse_opencode_usage
from app.models import (
    Base,
    DigitalEmployee,
    Event,
    Evidence,
    OpenCodeExecutionEnvironment,
    Run,
    Task,
    TaskCategory,
    ToolUsage,
)
from app.runtime.coordinator import TaskCoordinator
from app.runtime.dispatcher import Dispatcher
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.scout import TaskScout
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


def new_task(**overrides) -> TaskCreate:
    payload = {
        "task_type": TaskType.ISSUE,
        "category_id": "testing-platform",
        "title": "修复接口问题",
        "description": "定位并解决接口异常",
        "acceptance_criteria": [{"content": "接口恢复正常"}],
        "priority": Priority.HIGH,
        "completion_policy": "AUTO",
    }
    payload.update(overrides)
    return TaskCreate(**payload)


async def test_create_task_records_ready_event(session):
    task = await TaskService(session).create(new_task())

    assert task.status == TaskStatus.READY
    assert task.current_progress == "等待领取"
    events = (
        (await session.execute(select(Event).where(Event.task_id == task.id).order_by(Event.id)))
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["TASK_CREATED", "TASK_READY"]


async def test_dispatcher_matches_type_and_category_and_limits_one_task(session, tmp_path):
    workspace = tmp_path / "employee-workspace"
    workspace.mkdir()
    employee = DigitalEmployee(
        id="astra-test",
        name="Astra Test",
        role="测试平台员工",
        status=EmployeeStatus.IDLE,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
        auto_execute=False,
    )
    session.add(employee)
    session.add(
        OpenCodeExecutionEnvironment(
            employee_id=employee.id,
            mode="LOCAL",
            name="员工固定工作空间",
            opencode_path="opencode",
            workspace_root=str(workspace),
            status=EnvironmentStatus.AVAILABLE,
        )
    )
    await session.commit()
    first = await TaskService(session).create(new_task(title="匹配任务"))
    await TaskService(session).create(new_task(title="第二个任务"))

    claimed = await Dispatcher(session).claim_once()
    second_claim = await Dispatcher(session).claim_once()

    assert claimed and claimed.id == first.id
    assert claimed.status == TaskStatus.READY
    assert claimed.employee_id == employee.id
    assert claimed.claimed_at is not None
    assert claimed.execution_environment_snapshot["workspace_root"] == str(workspace)
    assert second_claim is None
    await session.refresh(employee)
    assert employee.current_task_count == 1


class FakeSource(TaskSource):
    id = "nr_test_system"

    async def discover_tasks(self):
        return [
            ExternalTask(
                external_task_id="EXT-1",
                title="外部需求",
                task_type="REQUIREMENT",
                category_id="testing-platform",
                description="处理外部系统需求",
                acceptance_criteria=["提供处理结果"],
            )
        ]

    async def get_task(self, external_task_id):
        return (await self.discover_tasks())[0]

    async def update_task(self, external_task_id, result):
        return None

    async def heartbeat(self):
        return True


async def test_scout_is_idempotent(session):
    session.add(
        TaskCategory(
            id="testing-platform",
            name="测试平台",
            description="测试平台相关任务",
        )
    )
    await session.commit()
    scout = TaskScout(session, [FakeSource()])
    first = await scout.poll_once()
    second = await scout.poll_once()

    assert len(first) == 1
    assert second == []
    assert await session.scalar(select(func.count(Task.id))) == 1


class FailThenPassExecutor(OpenCodeExecutor):
    def __init__(self):
        self.attempt = 0
        self.workspaces: list[Path] = []

    async def start(self, task, workspace):
        self.attempt += 1
        self.workspaces.append(workspace)
        return ExecutorResult(
            status="FAILED",
            exit_code=1,
            session_id="ses-v04",
            output=[{"type": "text", "part": {"text": "首次处理遇到可恢复异常"}}],
            stderr="temporary failure",
            token_usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            tool_usage=[ToolUsageResult(name="bash", call_count=1, failure_count=1)],
        )

    async def resume(self, task, run, workspace):
        self.attempt += 1
        self.workspaces.append(workspace)
        return ExecutorResult(
            status="SUCCEEDED",
            exit_code=0,
            session_id="ses-v04",
            output=[{"type": "text", "part": {"text": "接口问题已处理"}}],
            token_usage=TokenUsage(input_tokens=80, output_tokens=10, total_tokens=90),
            tool_usage=[ToolUsageResult(name="read", call_count=2, success_count=2)],
        )

    async def get_status(self, run):
        return run.status

    async def abort(self, run):
        return None

    async def collect_result(self, run):
        return run.result or {}


async def test_coordinator_reuses_employee_workspace_and_same_session(tmp_path):
    await init_database()
    workspace = tmp_path / "persistent-employee-workspace"
    workspace.mkdir()
    employee_id = "astra-runtime-v03"
    async with SessionLocal() as global_session:
        employee = DigitalEmployee(
            id=employee_id,
            name="Astra Runtime V0.4",
            role="测试平台员工",
            status=EmployeeStatus.WORKING,
            task_types=["ISSUE"],
            category_ids=["testing-platform"],
            max_auto_retries=1,
            current_task_count=1,
        )
        global_session.add(employee)
        global_session.add(
            OpenCodeExecutionEnvironment(
                employee_id=employee.id,
                mode="LOCAL",
                name="长期工作空间",
                opencode_path="opencode",
                workspace_root=str(workspace),
                status=EnvironmentStatus.AVAILABLE,
            )
        )
        await global_session.commit()
        task = await TaskService(global_session).create(new_task(employee_id=employee.id))
        await TaskService(global_session).transition(task, TaskStatus.RUNNING)
        task_id = task.id

    executor = FailThenPassExecutor()
    await TaskCoordinator(executor=executor).process(task_id)

    async with SessionLocal() as global_session:
        task = await global_session.get(Task, task_id)
        employee = await global_session.get(DigitalEmployee, employee_id)
        runs = (await global_session.execute(select(Run).where(Run.task_id == task_id))).scalars().all()
        evidence = (
            (await global_session.execute(select(Evidence).where(Evidence.task_id == task_id)))
            .scalars()
            .all()
        )
        tools = (
            (await global_session.execute(select(ToolUsage).join(Run).where(Run.task_id == task_id)))
            .scalars()
            .all()
        )

    assert executor.attempt == 2
    assert executor.workspaces == [workspace, workspace]
    assert task and task.status == TaskStatus.COMPLETED
    assert task.opencode_session_id == "ses-v04"
    assert task.result["summary"] == "接口问题已处理"
    assert task.result["acceptance_results"][0]["status"] == "UNCONFIRMED"
    assert employee and employee.status == EmployeeStatus.IDLE
    assert employee.current_task_count == 0
    assert len(runs) == 2
    assert sum(run.total_tokens or 0 for run in runs) == 210
    assert sum(item.call_count for item in tools) == 3
    assert len(evidence) == 2


def test_opencode_usage_parser_uses_actual_json_events():
    tokens, tools, model = parse_opencode_usage(
        [
            {
                "type": "step_finish",
                "part": {
                    "modelID": "deepseek/deepseek-v4-flash",
                    "tokens": {
                        "input": 120,
                        "output": 30,
                        "cache": {"read": 400, "write": 5},
                    },
                },
            },
            {
                "type": "tool",
                "part": {
                    "id": "call-1",
                    "tool": "bash",
                    "state": {"status": "completed", "time": {"start": 100, "end": 145}},
                },
            },
        ]
    )

    assert tokens.total_tokens == 555
    assert tokens.llm_call_count == 1
    assert model == "deepseek/deepseek-v4-flash"
    assert tools == [
        ToolUsageResult(
            name="bash",
            call_count=1,
            success_count=1,
            failure_count=0,
            duration_ms=45,
        )
    ]


async def test_local_environment_check_reports_binary_and_workspace(tmp_path: Path):
    binary = tmp_path / "fake-opencode"
    binary.write_text("#!/bin/sh\necho fake-opencode-1.0\n", encoding="utf-8")
    binary.chmod(0o755)
    environment = OpenCodeExecutionEnvironment(
        employee_id="astra-check",
        mode="LOCAL",
        name="本地检查",
        opencode_path=str(binary),
        workspace_root=str(tmp_path / "workspaces"),
    )

    checks = await ExecutionEnvironmentRuntime().test(environment)

    assert [item.name for item in checks] == [
        "OpenCode 存在",
        "OpenCode 可启动",
        "Workspace 可用",
    ]
    assert all(item.passed for item in checks)

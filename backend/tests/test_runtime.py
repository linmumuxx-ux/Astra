import io
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import _cancel_active_runs
from app.database import SessionLocal, init_database
from app.domain import EmployeeStatus, EnvironmentStatus, Priority, RunStatus, TaskStatus, TaskType
from app.executors.base import ExecutorResult, OpenCodeExecutor, TokenUsage, ToolUsageResult
from app.executors.opencode_cli import OpenCodeCLIExecutor
from app.executors.process import windows_batch_command
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
from app.runtime.environment import ExecutionEnvironmentRuntime, environment_snapshot
from app.runtime.heartbeat import heartbeat_active_employees
from app.runtime.scout import TaskScout
from app.runtime.ssh_client import SSHSession
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


def fake_agent_launcher(tmp_path: Path, python_source: str, name: str) -> Path:
    script = tmp_path / f"{name}.py"
    script.write_text(python_source, encoding="utf-8")
    if os.name == "nt":
        launcher = tmp_path / f"{name}.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = tmp_path / name
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return launcher


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


async def test_cancel_active_runs_finishes_running_and_blocked_rows(session):
    employee = DigitalEmployee(
        id="astra-cancel-runs",
        name="取消测试员工",
        role="测试员工",
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    session.add(employee)
    task = await TaskService(session).create(new_task(employee_id=employee.id))
    session.add_all(
        [
            Run(
                id="RUN-CANCEL-RUNNING",
                task_id=task.id,
                employee_id=employee.id,
                run_number=1,
                status=RunStatus.RUNNING,
            ),
            Run(
                id="RUN-CANCEL-BLOCKED",
                task_id=task.id,
                employee_id=employee.id,
                run_number=2,
                status=RunStatus.BLOCKED,
            ),
        ]
    )
    await session.commit()

    await _cancel_active_runs(task.id, session)

    runs = (
        (await session.execute(select(Run).where(Run.task_id == task.id).order_by(Run.run_number)))
        .scalars()
        .all()
    )
    assert [run.status for run in runs] == [RunStatus.CANCELLED, RunStatus.CANCELLED]
    assert all(run.finished_at is not None for run in runs)


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
            model_name="deepseek/deepseek-v4-flash",
            workspace_root=str(workspace),
            status=EnvironmentStatus.AVAILABLE,
        )
    )
    await session.commit()
    first = await TaskService(session).create(new_task(title="匹配任务"))
    first_id = first.id
    await TaskService(session).create(new_task(title="第二个任务"))

    claimed = await Dispatcher(session).claim_once()
    claimed_id = claimed.id if claimed else None
    second_claim = await Dispatcher(session).claim_once()
    if claimed:
        await session.refresh(claimed)

    assert claimed_id == first_id
    assert claimed.status == TaskStatus.READY
    assert claimed.employee_id == "astra-test"
    assert claimed.claimed_at is not None
    assert claimed.execution_environment_snapshot["workspace_root"] == str(workspace)
    assert claimed.execution_environment_snapshot["model_name"] == "deepseek/deepseek-v4-flash"
    assert second_claim is None
    await session.refresh(employee)
    assert employee.current_task_count == 1


async def test_heartbeat_recovers_offline_employee_then_dispatches_ready_task(session, tmp_path):
    workspace = tmp_path / "recoverable-workspace"
    workspace.mkdir()
    employee = DigitalEmployee(
        id="astra-recovered",
        name="Astra Recovered",
        role="测试员工",
        status=EmployeeStatus.OFFLINE,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
        auto_claim=True,
        auto_execute=True,
    )
    session.add(employee)
    session.add(
        OpenCodeExecutionEnvironment(
            employee_id=employee.id,
            mode="LOCAL",
            name="可恢复环境",
            opencode_path="opencode",
            workspace_root=str(workspace),
            status=EnvironmentStatus.AVAILABLE,
        )
    )
    await session.commit()
    task = await TaskService(session).create(new_task(title="重启后应被领取"))

    heartbeat_ids = await heartbeat_active_employees(session)
    await session.refresh(employee)
    assert employee.status == EmployeeStatus.IDLE
    claimed = await Dispatcher(session).claim_once()

    await session.refresh(employee)
    assert heartbeat_ids == [employee.id]
    assert employee.status == EmployeeStatus.WORKING
    assert claimed and claimed.id == task.id
    assert claimed.employee_id == employee.id


async def test_heartbeat_restores_waiting_employee_from_active_task(session, tmp_path):
    employee = DigitalEmployee(
        id="astra-waiting-recovered",
        name="Astra Waiting",
        role="测试员工",
        status=EmployeeStatus.OFFLINE,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
        current_task_count=1,
    )
    session.add(employee)
    await session.commit()
    task = await TaskService(session).create(new_task(employee_id=employee.id))
    await TaskService(session).transition(task, TaskStatus.RUNNING)
    await TaskService(session).transition(task, TaskStatus.WAIT_HUMAN)

    await heartbeat_active_employees(session)

    await session.refresh(employee)
    assert employee.status == EmployeeStatus.WAIT_HUMAN


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


class RaisingExecutor(OpenCodeExecutor):
    async def start(self, task, workspace):
        raise RuntimeError("stream reader failed")

    async def resume(self, task, run, workspace):
        raise RuntimeError("stream reader failed")

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


async def test_coordinator_finishes_run_when_executor_raises(tmp_path):
    await init_database()
    workspace = tmp_path / "exception-workspace"
    workspace.mkdir()
    employee_id = "astra-runtime-exception"
    async with SessionLocal() as global_session:
        employee = DigitalEmployee(
            id=employee_id,
            name="异常回收员工",
            role="测试员工",
            status=EmployeeStatus.WORKING,
            task_types=["ISSUE"],
            category_ids=["testing-platform"],
            current_task_count=1,
        )
        global_session.add(employee)
        global_session.add(
            OpenCodeExecutionEnvironment(
                employee_id=employee.id,
                mode="LOCAL",
                name="异常测试环境",
                opencode_path="opencode",
                workspace_root=str(workspace),
                status=EnvironmentStatus.AVAILABLE,
            )
        )
        await global_session.commit()
        task = await TaskService(global_session).create(new_task(employee_id=employee.id))
        await TaskService(global_session).transition(task, TaskStatus.RUNNING)
        task_id = task.id

    await TaskCoordinator(executor=RaisingExecutor()).process(task_id)

    async with SessionLocal() as global_session:
        task = await global_session.get(Task, task_id)
        employee = await global_session.get(DigitalEmployee, employee_id)
        run = await global_session.scalar(select(Run).where(Run.task_id == task_id))

    assert task and task.status == TaskStatus.EXECUTION_ERROR
    assert employee and employee.status == EmployeeStatus.ERROR
    assert run and run.status == RunStatus.FAILED
    assert run.finished_at is not None
    assert run.result["stderr"] == "stream reader failed"


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
    binary_dir = tmp_path / "Agent Program Files"
    binary_dir.mkdir()
    binary = fake_agent_launcher(binary_dir, 'print("fake-opencode-1.0")\n', "fake-opencode")
    environment = OpenCodeExecutionEnvironment(
        employee_id="astra-check",
        mode="LOCAL",
        name="本地检查",
        opencode_path=str(binary),
        workspace_root=str(tmp_path / "workspaces"),
    )

    checks = await ExecutionEnvironmentRuntime().test(environment)

    assert [item.name for item in checks] == [
        "Agent 命令存在",
        "Agent 命令可启动",
        "Workspace 可用",
    ]
    assert all(item.passed for item in checks)


async def test_paramiko_exec_channel_closes_stdin_and_streams_output():
    class FakeChannel:
        closed = False

        def __init__(self):
            self.command = ""
            self.stdin_closed = False

        def exec_command(self, command):
            self.command = command

        def shutdown_write(self):
            self.stdin_closed = True

        def makefile(self, mode, size):
            return io.BytesIO(b'{"type":"text","text":"ok"}\n')

        def makefile_stderr(self, mode, size):
            return io.BytesIO(b"")

        def recv_exit_status(self):
            return 0

        def close(self):
            self.closed = True

    channel = FakeChannel()

    class FakeTransport:
        def is_active(self):
            return True

        def open_session(self, timeout):
            return channel

    class FakeClient:
        def get_transport(self):
            return FakeTransport()

        def close(self):
            return None

    ssh = SSHSession(
        host="example.internal",
        port=22,
        username="nexus",
        password="secret",
    )
    ssh._client = FakeClient()

    process = await ssh.open_exec("agent run")
    stdout = await process.stdout.readline()
    exit_code = await process.wait()

    assert channel.command == "agent run"
    assert channel.stdin_closed is True
    assert stdout.endswith(b"\n")
    assert exit_code == 0


def test_windows_batch_command_quotes_paths_and_arguments():
    command = windows_batch_command(
        r"C:\Program Files\OpenCode\opencode.cmd",
        ["run", "--dir", r"D:\中文项目\workspace with spaces"],
        r"C:\Windows\System32\cmd.exe",
    )

    assert command[:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
    assert '"C:\\Program Files\\OpenCode\\opencode.cmd"' in command[4]
    assert '"D:\\中文项目\\workspace with spaces"' in command[4]


def test_windows_batch_command_quotes_multiline_prompt_and_shell_characters():
    command = windows_batch_command(
        r"C:\OpenCode\opencode.cmd",
        ["run", "第一行\n第二行 & 不应被 cmd 拆分"],
    )

    assert command[4].endswith('"第一行\n第二行 & 不应被 cmd 拆分"')


async def test_opencode_permission_rejection_is_blocked_even_with_zero_exit(tmp_path: Path):
    binary = fake_agent_launcher(
        tmp_path,
        "import sys\n"
        'print(\'{"type":"text","part":{"text":"无法写入目标文件"}}\')\n'
        'print("permission requested: external_directory; auto-rejecting", file=sys.stderr)\n',
        "permission-rejected-opencode",
    )
    task = Task(
        id="T-PERMISSION-REJECTED",
        source="manual",
        task_type="ISSUE",
        category_id="testing-platform",
        title="验证权限拒绝识别",
        description="创建文件",
        acceptance_criteria=[{"id": "AC-01", "content": "文件已创建"}],
        priority="LOW",
        completion_policy="AUTO",
        status=TaskStatus.RUNNING,
    )

    result = await OpenCodeCLIExecutor(opencode_binary=str(binary)).start(task, tmp_path)

    assert result.exit_code == 0
    assert result.status == "BLOCKED"


def test_employee_model_is_passed_to_agent_command(tmp_path: Path):
    task = Task(
        id="T-EMPLOYEE-MODEL",
        source="manual",
        task_type="REQUIREMENT",
        category_id="testing-platform",
        title="验证员工模型配置",
        description="模型应作为 Agent 启动参数",
        acceptance_criteria=[{"id": "AC-01", "content": "使用指定模型"}],
        priority="LOW",
        completion_policy="AUTO",
        status=TaskStatus.RUNNING,
    )
    executor = OpenCodeCLIExecutor(
        opencode_binary="opencode",
        model_name="deepseek/deepseek-v4-flash",
    )

    command = executor._command(task, tmp_path)

    model_index = command.index("--model")
    assert command[model_index + 1] == "deepseek/deepseek-v4-flash"


def test_legacy_task_snapshot_inherits_employee_model():
    employee = DigitalEmployee(
        id="astra-legacy-model",
        name="Astra Legacy",
        role="测试员工",
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    employee.execution_environment = OpenCodeExecutionEnvironment(
        employee_id=employee.id,
        mode="LOCAL",
        name="员工 Agent 环境",
        opencode_path="opencode",
        model_name="deepseek/deepseek-v4-flash",
        workspace_root="./workspaces/astra-legacy-model",
    )
    task = Task(
        id="T-LEGACY-MODEL",
        source="manual",
        task_type="ISSUE",
        category_id="testing-platform",
        title="旧任务快照",
        description="快照创建时尚无模型字段",
        acceptance_criteria=[],
        priority="LOW",
        completion_policy="AUTO",
        status=TaskStatus.RUNNING,
        execution_environment_snapshot={
            "environment_id": 1,
            "mode": "LOCAL",
            "name": "旧 Agent 环境",
            "opencode_path": "opencode",
            "workspace_root": "./workspaces/astra-legacy-model",
        },
    )

    environment = TaskCoordinator._resolve_environment(task, employee)

    assert environment.model_name == "deepseek/deepseek-v4-flash"


def test_remote_password_is_not_stored_in_task_snapshot_and_is_resolved_at_runtime():
    employee = DigitalEmployee(
        id="astra-remote-password",
        name="远程员工",
        role="测试员工",
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    employee.execution_environment = OpenCodeExecutionEnvironment(
        employee_id=employee.id,
        mode="LINUX_REMOTE",
        name="远程环境",
        host="example.internal",
        port=22,
        username="nexus",
        ssh_password="database-only-secret",
        opencode_path="/opt/agent/start-agent.sh",
        workspace_root="/srv/workspace",
    )
    snapshot = environment_snapshot(employee.execution_environment)
    task = Task(
        id="T-REMOTE-PASSWORD",
        source="manual",
        task_type="ISSUE",
        category_id="testing-platform",
        title="验证远程密码边界",
        description="密码不进入任务记录",
        acceptance_criteria=[],
        priority="LOW",
        completion_policy="AUTO",
        status=TaskStatus.RUNNING,
        execution_environment_snapshot=snapshot,
    )

    resolved = TaskCoordinator._resolve_environment(task, employee)

    assert "ssh_password" not in snapshot
    assert snapshot["has_ssh_password"] is True
    assert resolved.ssh_password == "database-only-secret"

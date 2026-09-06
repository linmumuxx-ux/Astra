import io
import json
import os
import socket
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.database import SessionLocal, init_database
from app.domain import EmployeeStatus, EnvironmentStatus, Priority, RunStatus, TaskStatus, TaskType
from app.executors.base import ExecutorResult, OpenCodeExecutor, TokenUsage, ToolUsageResult
from app.executors.opencode_cli import OpenCodeCLIExecutor
from app.executors.opencode_remote import RemoteOpenCodeExecutor
from app.executors.opencode_remote_server import RemoteOpenCodeServerExecutor
from app.executors.process import windows_batch_command
from app.executors.usage import parse_opencode_usage
from app.models import (
    Base,
    DigitalEmployee,
    Event,
    Evidence,
    OpenCodeExecutionEnvironment,
    Run,
    RunDispatchOutbox,
    RunInquiry,
    SessionMessage,
    Task,
    TaskCategory,
    TaskSession,
    ToolUsage,
)
from app.runtime.coordinator import TaskCoordinator
from app.runtime.dispatcher import Dispatcher
from app.runtime.environment import ExecutionEnvironmentRuntime, environment_snapshot
from app.runtime.heartbeat import heartbeat_active_employees
from app.runtime.lifecycle import RuntimeService
from app.runtime.recovery import reconcile_runtime_state, watchdog_stale_runs
from app.runtime.scout import TaskScout
from app.runtime.ssh_client import SSHSession
from app.schemas import TaskCreate
from app.services import TaskService, WorkbenchService
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


async def queued_runtime(session, suffix: str) -> tuple[DigitalEmployee, Task, Run]:
    employee = DigitalEmployee(
        id=f"astra-runtime-{suffix}",
        name=f"Runtime {suffix}",
        role="运行时测试员工",
        status=EmployeeStatus.IDLE,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    session.add(employee)
    await session.commit()
    task = await TaskService(session).create(
        new_task(employee_id=employee.id, title=f"运行时测试 {suffix}")
    )
    run = await RuntimeService(session).queue_new_run(
        task,
        employee,
        current_progress="运行已排队",
        message="测试运行排队",
    )
    return employee, task, run


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


async def test_add_event_can_join_caller_transaction_without_implicit_commit(session):
    task = await TaskService(session).create(new_task())
    task_id = task.id

    await TaskService(session).add_event(
        task,
        "TASK_ASSIGNED",
        "work",
        "尚未提交的领取事件",
        commit=False,
    )
    await session.rollback()

    events = (
        (await session.execute(select(Event).where(Event.task_id == task_id).order_by(Event.id)))
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["TASK_CREATED", "TASK_READY"]


async def test_runtime_observer_persists_tool_and_subagent_semantics(session):
    task = await TaskService(session).create(new_task(title="调用结构化子 Agent"))
    raw_event = {
        "type": "tool_use",
        "sessionID": "ses_parent",
        "part": {
            "type": "tool",
            "tool": "task",
            "callID": "call_subagent_1",
            "state": {
                "status": "completed",
                "input": {
                    "description": "Print hello world",
                    "prompt": "打印 hello world",
                    "subagent_type": "general",
                },
                "output": "<task_result>hello world</task_result>",
                "metadata": {
                    "parentSessionId": "ses_parent",
                    "sessionId": "ses_child",
                },
                "title": "Print hello world",
            },
        },
    }

    await TaskCoordinator._observe_event(task, None, raw_event, TaskService(session))
    events = (
        (await session.execute(select(Event).where(Event.task_id == task.id).order_by(Event.id)))
        .scalars()
        .all()
    )

    assert [item.event_type for item in events[-2:]] == ["TOOL_ACTIVITY", "SUBAGENT_COMPLETED"]
    assert events[-2].detail["call_id"] == "call_subagent_1"
    assert events[-1].detail["agent_name"] == "general"
    assert events[-1].detail["child_session_id"] == "ses_child"


async def test_stop_task_finishes_all_legacy_active_runs_and_inquiries(session):
    employee = DigitalEmployee(
        id="astra-cancel-runs",
        name="取消测试员工",
        role="测试员工",
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    session.add(employee)
    task = await TaskService(session).create(new_task(employee_id=employee.id))
    runs = [
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
    session.add_all(runs)
    await session.flush()
    task.status = TaskStatus.RUNNING
    task.active_run_id = runs[-1].id
    employee.status = EmployeeStatus.WORKING
    employee.current_task_count = 1
    employee.active_run_id = runs[-1].id
    inquiry = await WorkbenchService(session).create_inquiry(
        task,
        question="请补充信息",
        run_id=runs[-1].id,
        commit=False,
    )
    await session.commit()

    await RuntimeService(session).stop_task(
        task,
        target=TaskStatus.CANCELLED,
        current_progress="任务已取消",
        message="测试停止",
    )

    stored_runs = (
        (await session.execute(select(Run).where(Run.task_id == task.id).order_by(Run.run_number)))
        .scalars()
        .all()
    )
    await session.refresh(task)
    await session.refresh(employee)
    await session.refresh(inquiry)
    assert [run.status for run in stored_runs] == [RunStatus.CANCELLED, RunStatus.CANCELLED]
    assert all(run.finished_at is not None for run in stored_runs)
    assert task.active_run_id is None
    assert employee.active_run_id is None
    assert employee.current_task_count == 0
    assert inquiry.status == "CANCELLED"


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
    assert claimed.status == TaskStatus.ASSIGNED
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
    run = await session.scalar(select(Run).where(Run.task_id == task.id))

    await session.refresh(employee)
    assert heartbeat_ids == [employee.id]
    assert employee.status == EmployeeStatus.WORKING
    assert claimed and claimed.id == task.id
    assert claimed.status == TaskStatus.QUEUED
    assert claimed.employee_id == employee.id
    assert run and run.status == RunStatus.QUEUED
    assert run.started_at is None


async def test_failed_queue_publish_keeps_run_durably_queued(session, tmp_path, monkeypatch):
    workspace = tmp_path / "queue-failure-workspace"
    workspace.mkdir()
    employee = DigitalEmployee(
        id="astra-queue-failure",
        name="队列失败员工",
        role="测试员工",
        status=EmployeeStatus.IDLE,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    employee.execution_environment = OpenCodeExecutionEnvironment(
        employee_id=employee.id,
        mode="LOCAL",
        name="队列失败环境",
        workspace_root=str(workspace),
        status=EnvironmentStatus.AVAILABLE,
    )
    session.add(employee)
    await session.commit()
    task = await TaskService(session).create(new_task(employee_id=employee.id))
    task.execution_environment_snapshot = environment_snapshot(employee.execution_environment)
    runtime = RuntimeService(session)
    run = await runtime.queue_new_run(
        task,
        employee,
        current_progress="运行已排队",
        message="测试运行排队",
    )

    from app.runtime.celery_app import process_task

    def fail_publish(*_args, **_kwargs):
        raise OSError("redis unavailable")

    monkeypatch.setattr(process_task, "apply_async", fail_publish)
    published = await runtime.enqueue(task, run)
    await session.refresh(task)
    await session.refresh(run)
    await session.refresh(employee)
    outbox = await session.scalar(
        select(RunDispatchOutbox).where(RunDispatchOutbox.run_id == run.id)
    )

    assert published is False
    assert task.status == TaskStatus.QUEUED
    assert task.active_run_id == run.id
    assert run.status == RunStatus.QUEUED
    assert run.dispatch_attempt == 1
    assert employee.current_task_count == 1
    assert employee.active_run_id == run.id
    assert outbox and outbox.status == "PENDING"
    assert outbox.attempts == 1
    assert outbox.next_retry_at is not None
    assert outbox.last_error == "redis unavailable"
    event = await session.scalar(
        select(Event).where(Event.run_id == run.id, Event.event_type == "RUN_DISPATCH_FAILED")
    )
    assert event and event.detail["error"] == "redis unavailable"


async def test_outbox_success_and_duplicate_worker_delivery_are_idempotent(session, monkeypatch):
    employee, task, run = await queued_runtime(session, "outbox-success")

    from app.runtime.celery_app import process_task

    published: list[dict] = []

    class Result:
        id = "run-celery-fixed"

    def publish(*args, **kwargs):
        published.append({"args": args, "kwargs": kwargs})
        return Result()

    monkeypatch.setattr(process_task, "apply_async", publish)
    runtime = RuntimeService(session)
    assert await runtime.enqueue(task, run) is True
    outbox = await session.scalar(
        select(RunDispatchOutbox).where(RunDispatchOutbox.run_id == run.id)
    )
    await session.refresh(run)
    assert outbox and outbox.status == "SENT"
    assert outbox.attempts == 1
    assert run.celery_task_id == "run-celery-fixed"
    assert published[0]["kwargs"] == {
        "args": [run.id],
        "queue": "agent",
        "task_id": f"run-{run.id}",
    }

    claimed = await runtime.claim_run(run.id, worker_id="worker-a")
    assert claimed is not None
    _, _, claimed_run, token = claimed
    assert claimed_run.status == RunStatus.STARTING
    assert claimed_run.worker_id == "worker-a"
    assert claimed_run.execution_token == token
    assert await runtime.claim_run(run.id, worker_id="worker-b") is None


async def test_execution_lease_heartbeat_and_finalize_clear_all_pointers(session):
    employee, task, run = await queued_runtime(session, "lease-finalize")
    runtime = RuntimeService(session)
    claimed = await runtime.claim_run(run.id, worker_id="worker-finalize")
    assert claimed is not None
    task, employee, run, token = claimed

    assert await runtime.mark_running(task, run, token) is True
    assert await runtime.heartbeat(run.id, "wrong-token") is False
    assert await runtime.heartbeat(run.id, token, executor_status="BUSY") is True
    assert await runtime.finalize_run(
        task,
        employee,
        run,
        run_status=RunStatus.COMPLETED,
        task_status=TaskStatus.COMPLETED,
        current_progress="任务已完成",
        message="测试终结",
        execution_token=token,
    )
    await session.refresh(task)
    await session.refresh(employee)
    await session.refresh(run)
    outbox = await session.scalar(
        select(RunDispatchOutbox).where(RunDispatchOutbox.run_id == run.id)
    )

    assert task.status == TaskStatus.COMPLETED
    assert task.active_run_id is None
    assert employee.status == EmployeeStatus.IDLE
    assert employee.current_task_count == 0
    assert employee.active_run_id is None
    assert run.status == RunStatus.COMPLETED
    assert run.executor_status == RunStatus.COMPLETED
    assert run.finished_at is not None
    assert outbox and outbox.status == "CANCELLED"
    assert not await runtime.finalize_run(
        task,
        employee,
        run,
        run_status=RunStatus.COMPLETED,
        task_status=TaskStatus.COMPLETED,
        current_progress="任务已完成",
        message="重复终结",
        execution_token=token,
    )


async def test_watchdog_marks_stale_starting_run_lost(session):
    employee, task, run = await queued_runtime(session, "starting-lost")
    claimed = await RuntimeService(session).claim_run(run.id, worker_id="lost-worker")
    assert claimed is not None
    stale_at = datetime.now(UTC) - timedelta(minutes=10)
    run.started_at = stale_at
    run.heartbeat_at = stale_at
    await session.commit()

    changed = await watchdog_stale_runs(
        session,
        Settings(runtime_startup_timeout=10, runtime_heartbeat_timeout=10),
    )
    await session.refresh(task)
    await session.refresh(employee)
    await session.refresh(run)

    assert changed == [run.id]
    assert run.status == RunStatus.LOST
    assert run.failure_type == "STARTUP_LEASE_LOST"
    assert task.status == TaskStatus.EXECUTION_ERROR
    assert task.active_run_id is None
    assert employee.status == EmployeeStatus.ERROR
    assert employee.active_run_id is None


async def test_watchdog_never_replays_busy_session_then_marks_missing_session_lost(session):
    employee, task, run = await queued_runtime(session, "running-lost")
    runtime = RuntimeService(session)
    claimed = await runtime.claim_run(run.id, worker_id="orphan-worker")
    assert claimed is not None
    task, employee, run, token = claimed
    assert await runtime.mark_running(task, run, token)
    run.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
    run.opencode_session_id = "ses-orphan"
    await session.commit()

    async def busy_probe(*_args):
        return "BUSY", None

    settings = Settings(runtime_startup_timeout=10, runtime_heartbeat_timeout=10)
    assert await watchdog_stale_runs(session, settings, status_probe=busy_probe) == []
    await session.refresh(run)
    await session.refresh(task)
    assert run.status == RunStatus.RUNNING
    assert run.executor_status == "ORPHANED_BUSY"
    assert task.status == TaskStatus.RUNNING
    assert task.active_run_id == run.id

    async def missing_probe(*_args):
        return "MISSING", None

    assert await watchdog_stale_runs(session, settings, status_probe=missing_probe) == [run.id]
    await session.refresh(run)
    await session.refresh(task)
    await session.refresh(employee)
    assert run.status == RunStatus.LOST
    assert run.failure_type == "WORKER_LEASE_LOST"
    assert task.status == TaskStatus.EXECUTION_ERROR
    assert employee.status == EmployeeStatus.ERROR


async def test_watchdog_collects_idle_session_result_without_reexecution(session):
    employee, task, run = await queued_runtime(session, "idle-result")
    runtime = RuntimeService(session)
    claimed = await runtime.claim_run(run.id, worker_id="result-worker")
    assert claimed is not None
    task, employee, run, token = claimed
    assert await runtime.mark_running(task, run, token)
    run.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
    run.opencode_session_id = "ses-finished"
    await session.commit()

    async def idle_probe(*_args):
        return "IDLE", {"raw_text": "修复已完成"}

    changed = await watchdog_stale_runs(
        session,
        Settings(runtime_startup_timeout=10, runtime_heartbeat_timeout=10),
        status_probe=idle_probe,
    )
    await session.refresh(run)
    await session.refresh(task)
    await session.refresh(employee)

    assert changed == [run.id]
    assert run.status == RunStatus.COMPLETED
    assert run.failure_type == "WORKER_LOST_RESULT_RECOVERED"
    assert run.result["recovered"] is True
    assert task.status == TaskStatus.COMPLETED
    assert task.result["summary"] == "修复已完成"
    assert task.active_run_id is None
    assert employee.active_run_id is None


async def test_reconciliation_repairs_leases_and_fake_running_projection(session):
    employee = DigitalEmployee(
        id="astra-reconcile",
        name="Reconcile",
        role="恢复测试员工",
        status=EmployeeStatus.IDLE,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    orphan_employee = DigitalEmployee(
        id="astra-reconcile-orphan",
        name="Orphan",
        role="恢复测试员工",
        status=EmployeeStatus.WORKING,
        current_task_count=1,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
    )
    session.add_all([employee, orphan_employee])
    await session.commit()
    task = await TaskService(session).create(new_task(employee_id=employee.id, title="租约修复"))
    task.status = TaskStatus.QUEUED
    run = Run(
        id="RUN-RECONCILE",
        task_id=task.id,
        employee_id=employee.id,
        run_number=1,
        status=RunStatus.QUEUED,
        queued_at=datetime.now(UTC),
    )
    orphan_task = await TaskService(session).create(
        new_task(employee_id=orphan_employee.id, title="假运行修复")
    )
    orphan_task.status = TaskStatus.RUNNING
    session.add(run)
    await session.commit()

    changed = await reconcile_runtime_state(session)
    await session.refresh(task)
    await session.refresh(employee)
    await session.refresh(orphan_task)
    await session.refresh(orphan_employee)

    assert f"run:{run.id}" in changed
    assert task.active_run_id == run.id
    assert employee.active_run_id == run.id
    assert employee.status == EmployeeStatus.WORKING
    assert f"task:{orphan_task.id}" in changed
    assert orphan_task.status == TaskStatus.EXECUTION_ERROR
    assert orphan_employee.status == EmployeeStatus.ERROR


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


class AskThenCompleteExecutor(OpenCodeExecutor):
    def __init__(self):
        self.started = 0
        self.resumed_run_ids: list[str] = []

    async def start(self, task, workspace):
        self.started += 1
        question = "请告诉我需要打印的具体答案是什么？"
        return ExecutorResult(
            status="BLOCKED",
            exit_code=0,
            session_id="ses-hitl-same-run",
            output=[{"type": "text", "part": {"text": f"需要你的回答后才能继续：{question}"}}],
            inquiry={
                "blocking_reason": "任务要求使用用户提供的答案",
                "completed_work": "已准备打印步骤",
                "current_state": "等待回答",
                "requested_input": question,
                "options": [],
            },
            token_usage=TokenUsage(input_tokens=20, output_tokens=5, total_tokens=25),
        )

    async def resume(self, task, run, workspace):
        self.resumed_run_ids.append(run.id)
        answer = task.human_intervention["response"]
        result = {
            "summary": f"已打印用户答案：{answer}",
            "changes": [],
            "files": [],
            "commits": [],
            "logs": [answer],
            "attachments": [],
            "other": {"printed_answer": answer},
            "acceptance_results": [
                {
                    "criterion_id": "AC-01",
                    "status": "SATISFIED",
                    "description": f"已打印 {answer}",
                    "evidence": [answer],
                }
            ],
        }
        return ExecutorResult(
            status="SUCCEEDED",
            exit_code=0,
            session_id="ses-hitl-same-run",
            output=[
                {
                    "type": "text",
                    "part": {
                        "text": (
                            f"已打印用户答案：{answer}\nASTRA_RESULT_JSON: "
                            f"{json.dumps(result, ensure_ascii=False)}"
                        )
                    },
                }
            ],
            token_usage=TokenUsage(input_tokens=15, output_tokens=5, total_tokens=20),
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
        runs = (
            (
                await global_session.execute(
                    select(Run).where(Run.task_id == task_id).order_by(Run.run_number)
                )
            )
            .scalars()
            .all()
        )
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
    assert task.active_run_id is None
    assert employee.active_run_id is None
    assert len(runs) == 2
    assert runs[0].status == RunStatus.FAILED
    assert runs[0].failure_type == "AUTO_RETRY"
    assert runs[1].status == RunStatus.COMPLETED
    assert runs[1].previous_run_id == runs[0].id
    assert runs[0].execution_token != runs[1].execution_token
    assert sum(run.total_tokens or 0 for run in runs) == 210
    assert sum(item.call_count for item in tools) == 3
    assert len(evidence) == 2


async def test_inquiry_answer_resumes_the_same_run_and_session(tmp_path):
    await init_database()
    workspace = tmp_path / "hitl-same-run-workspace"
    workspace.mkdir()
    employee_id = "astra-hitl-same-run"
    async with SessionLocal() as global_session:
        employee = DigitalEmployee(
            id=employee_id,
            name="HITL 同 Run 员工",
            role="测试员工",
            status=EmployeeStatus.WORKING,
            task_types=["REQUIREMENT"],
            category_ids=["testing-platform"],
            current_task_count=1,
        )
        global_session.add(employee)
        global_session.add(
            OpenCodeExecutionEnvironment(
                employee_id=employee.id,
                mode="LOCAL",
                name="HITL 测试环境",
                opencode_path="opencode",
                workspace_root=str(workspace),
                status=EnvironmentStatus.AVAILABLE,
            )
        )
        await global_session.commit()
        task = await TaskService(global_session).create(
            new_task(
                employee_id=employee.id,
                task_type=TaskType.REQUIREMENT,
                title="先问后打印",
                description="先向使用者询问要打印的答案，收到回答后打印该答案。",
                acceptance_criteria=[{"content": "打印使用者回答的具体答案"}],
            )
        )
        await TaskService(global_session).transition(task, TaskStatus.RUNNING)
        task_id = task.id

    executor = AskThenCompleteExecutor()
    await TaskCoordinator(executor=executor).process(task_id)

    async with SessionLocal() as global_session:
        task = await global_session.get(Task, task_id)
        task_session = await global_session.scalar(select(TaskSession).where(TaskSession.task_id == task_id))
        runs = (await global_session.execute(select(Run).where(Run.task_id == task_id))).scalars().all()
        inquiry = await global_session.scalar(
            select(RunInquiry).where(RunInquiry.session_id == task_session.id)
        )
        assert task and task.status == TaskStatus.WAIT_HUMAN
        assert task_session and task_session.current_run_id == runs[0].id
        assert len(runs) == 1
        assert runs[0].status == RunStatus.WAITING_INPUT
        assert runs[0].finished_at is None
        assert inquiry and inquiry.status == "OPEN"
        assert inquiry.run_id == runs[0].id

        await WorkbenchService(global_session).add_message(
            task,
            "自动化验收答案",
            status="ANSWERED",
            run_id=runs[0].id,
            commit=False,
        )
        await WorkbenchService(global_session).answer_inquiry(
            task,
            "自动化验收答案",
            commit=False,
        )
        task.human_intervention = {
            **(task.human_intervention or {}),
            "response": "自动化验收答案",
        }
        await TaskService(global_session).transition(task, TaskStatus.RUNNING)
        employee = await global_session.get(DigitalEmployee, employee_id)
        employee.status = EmployeeStatus.WORKING
        employee.current_task_count = 1
        await global_session.commit()

    await TaskCoordinator(executor=executor).process(task_id)

    async with SessionLocal() as global_session:
        task = await global_session.get(Task, task_id)
        task_session = await global_session.scalar(select(TaskSession).where(TaskSession.task_id == task_id))
        runs = (await global_session.execute(select(Run).where(Run.task_id == task_id))).scalars().all()
        inquiry = await global_session.scalar(
            select(RunInquiry).where(RunInquiry.session_id == task_session.id)
        )
        messages = (
            (
                await global_session.execute(
                    select(SessionMessage)
                    .where(SessionMessage.session_id == task_session.id)
                    .order_by(SessionMessage.created_at)
                )
            )
            .scalars()
            .all()
        )

    assert task and task.status == TaskStatus.COMPLETED
    assert task.result["summary"] == "已打印用户答案：自动化验收答案"
    assert len(runs) == 1
    assert runs[0].status == RunStatus.COMPLETED
    assert runs[0].total_tokens == 45
    assert executor.started == 1
    assert executor.resumed_run_ids == [runs[0].id]
    assert task_session and task_session.current_run_id == runs[0].id
    assert inquiry and inquiry.status == "ANSWERED"
    assert [message.role for message in messages] == ["user", "agent", "user", "agent"]


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
            status=EmployeeStatus.IDLE,
            task_types=["ISSUE"],
            category_ids=["testing-platform"],
            current_task_count=0,
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
        run = await RuntimeService(global_session).queue_new_run(
            task,
            employee,
            current_progress="运行已排队",
            message="异常测试运行已排队",
        )
        task_id = task.id
        run_id = run.id

    await TaskCoordinator(executor=RaisingExecutor()).process(run_id)
    await TaskCoordinator(executor=RaisingExecutor()).process(run_id)

    async with SessionLocal() as global_session:
        task = await global_session.get(Task, task_id)
        employee = await global_session.get(DigitalEmployee, employee_id)
        run = await global_session.scalar(select(Run).where(Run.task_id == task_id))

    assert task and task.status == TaskStatus.EXECUTION_ERROR
    assert employee and employee.status == EmployeeStatus.ERROR
    assert employee.current_task_count == 0
    assert run and run.status == RunStatus.FAILED
    assert run.started_at is not None
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


async def test_ssh_tunnel_forwards_local_loopback_traffic():
    class FakeTransport:
        def is_active(self):
            return True

        def open_channel(self, kind, destination, source):
            assert kind == "direct-tcpip"
            assert destination == ("127.0.0.1", 4096)
            assert source[0] == "127.0.0.1"
            handler_side, echo_side = socket.socketpair()

            def echo() -> None:
                try:
                    while payload := echo_side.recv(65536):
                        echo_side.sendall(payload)
                finally:
                    echo_side.close()

            threading.Thread(target=echo, daemon=True).start()
            return handler_side

    class FakeClient:
        def __init__(self):
            self.transport = FakeTransport()

        def get_transport(self):
            return self.transport

        def close(self):
            return None

    ssh = SSHSession(
        host="example.internal",
        port=22,
        username="nexus",
        password="secret",
    )
    ssh._client = FakeClient()
    tunnel = await ssh.open_tunnel(remote_port=4096)
    client = socket.create_connection(("127.0.0.1", tunnel.local_port), timeout=2)
    try:
        client.sendall(b"GET /global/health HTTP/1.0\r\n\r\n")
        assert client.recv(65536) == b"GET /global/health HTTP/1.0\r\n\r\n"
    finally:
        client.close()
        await tunnel.close()


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
        opencode_server_port=4196,
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
    assert snapshot["opencode_server_port"] == 4196
    assert resolved.ssh_password == "database-only-secret"


def test_remote_environment_uses_server_runtime_unless_cli_fallback_is_explicit():
    environment = OpenCodeExecutionEnvironment(
        employee_id="astra-remote-runtime",
        mode="LINUX_REMOTE",
        name="远程 Server 环境",
        host="linux.internal",
        port=22,
        username="astra",
        ssh_password="secret",
        opencode_path="/usr/local/bin/opencode",
        workspace_root="/srv/astra/workspace",
    )
    task = Task(id="T-REMOTE-RUNTIME", source="manual", task_type="ISSUE", title="runtime")
    coordinator = TaskCoordinator()
    coordinator.settings = Settings(executor_type="opencode_server", seed_demo=False)
    coordinator.environment_runtime = ExecutionEnvironmentRuntime(coordinator.settings)

    primary = coordinator._executor_for_environment(task, environment, None)

    assert isinstance(primary, RemoteOpenCodeServerExecutor)

    coordinator.settings = Settings(executor_type="opencode_cli_fallback", seed_demo=False)
    coordinator.environment_runtime = ExecutionEnvironmentRuntime(coordinator.settings)
    fallback = coordinator._executor_for_environment(task, environment, None)

    assert isinstance(fallback, RemoteOpenCodeExecutor)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import pytest

from app.domain import EmployeeStatus, RunStatus, RunTriggerReason, TaskStatus
from app.models import Base, DigitalEmployee, Run, Task
from app.runtime.lifecycle import RuntimeService


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def task_with_status(status: TaskStatus) -> Task:
    return Task(
        id=f"T-{status.value}",
        source="manual",
        task_type="ISSUE",
        title="Runtime trigger test",
        description="test",
        acceptance_criteria=[],
        attachments=[],
        priority="MEDIUM",
        completion_policy="AUTO",
        status=status,
    )


def test_run_trigger_reason_is_classified_at_runtime_boundary():
    resolve = RuntimeService._resolve_trigger_reason

    assert resolve(task_with_status(TaskStatus.READY), None, None) == RunTriggerReason.INITIAL
    assert resolve(
        task_with_status(TaskStatus.READY), {"dispatch": "manual"}, None
    ) == RunTriggerReason.MANUAL_START
    assert resolve(
        task_with_status(TaskStatus.WAIT_HUMAN), {}, None
    ) == RunTriggerReason.HUMAN_RESUME
    assert resolve(
        task_with_status(TaskStatus.SUSPENDED), {}, None
    ) == RunTriggerReason.HUMAN_RESUME
    assert resolve(
        task_with_status(TaskStatus.EXECUTION_ERROR), {}, None
    ) == RunTriggerReason.RECOVERY
    assert resolve(
        task_with_status(TaskStatus.READY), {"recovery": "environment"}, None
    ) == RunTriggerReason.RECOVERY
    assert resolve(
        task_with_status(TaskStatus.COMPLETED), {"rerun": True}, None
    ) == RunTriggerReason.USER_RERUN
    assert resolve(
        task_with_status(TaskStatus.COMPLETED), {"continue": True}, None
    ) == RunTriggerReason.USER_CONTINUE
    assert resolve(
        task_with_status(TaskStatus.READY), {"rerun": True}, RunTriggerReason.RECOVERY
    ) == RunTriggerReason.RECOVERY


async def test_retry_index_is_scoped_to_current_run_chain(session):
    employee = DigitalEmployee(
        id="astra-run-semantics",
        name="Run semantics",
        role="test",
        status=EmployeeStatus.WORKING,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
        current_task_count=1,
    )
    task = Task(
        id="T-RUN-SEMANTICS",
        source="manual",
        task_type="ISSUE",
        category_id="testing-platform",
        title="Run semantics",
        description="test",
        acceptance_criteria=[],
        attachments=[],
        priority="MEDIUM",
        completion_policy="AUTO",
        status=TaskStatus.RUNNING,
        employee_id=employee.id,
        execution_environment_snapshot={},
    )
    initial = Run(
        id="RUN-SEMANTICS-1",
        task_id=task.id,
        employee_id=employee.id,
        run_number=1,
        trigger_reason=RunTriggerReason.INITIAL,
        retry_index=0,
        status=RunStatus.RUNNING,
        executor_type="opencode_server",
        execution_token="token-1",
        execution_environment_snapshot={},
    )
    session.add_all([employee, task, initial])
    await session.commit()

    runtime = RuntimeService(session)
    retry_one, retry_token = await runtime.continue_run(
        task,
        employee,
        initial,
        previous_status=RunStatus.FAILED,
        failure_type="AUTO_RETRY",
        message="retry",
        execution_token="token-1",
    )
    assert retry_one.trigger_reason == RunTriggerReason.AUTO_RETRY
    assert retry_one.retry_index == 1

    user_continue, continue_token = await runtime.continue_run(
        task,
        employee,
        retry_one,
        previous_status=RunStatus.COMPLETED,
        failure_type=None,
        message="user continue",
        execution_token=retry_token,
    )
    assert user_continue.trigger_reason == RunTriggerReason.USER_CONTINUE
    assert user_continue.retry_index == 0

    fresh_retry, _ = await runtime.continue_run(
        task,
        employee,
        user_continue,
        previous_status=RunStatus.FAILED,
        failure_type="AUTO_RETRY",
        message="fresh retry budget",
        execution_token=continue_token,
    )
    assert fresh_retry.trigger_reason == RunTriggerReason.AUTO_RETRY
    assert fresh_retry.retry_index == 1


async def test_session_recovery_does_not_consume_auto_retry_budget(session):
    employee = DigitalEmployee(
        id="astra-session-semantics",
        name="Session semantics",
        role="test",
        status=EmployeeStatus.WORKING,
        task_types=["ISSUE"],
        category_ids=["testing-platform"],
        current_task_count=1,
    )
    task = Task(
        id="T-SESSION-SEMANTICS",
        source="manual",
        task_type="ISSUE",
        category_id="testing-platform",
        title="Session semantics",
        description="test",
        acceptance_criteria=[],
        attachments=[],
        priority="MEDIUM",
        completion_policy="AUTO",
        status=TaskStatus.RUNNING,
        employee_id=employee.id,
        execution_environment_snapshot={},
    )
    initial = Run(
        id="RUN-SESSION-1",
        task_id=task.id,
        employee_id=employee.id,
        run_number=1,
        trigger_reason=RunTriggerReason.INITIAL,
        retry_index=0,
        status=RunStatus.RUNNING,
        executor_type="opencode_server",
        execution_token="session-token-1",
        execution_environment_snapshot={},
    )
    session.add_all([employee, task, initial])
    await session.commit()

    recovered, _ = await RuntimeService(session).continue_run(
        task,
        employee,
        initial,
        previous_status=RunStatus.FAILED,
        failure_type="SESSION_NOT_FOUND",
        message="recover session",
        execution_token="session-token-1",
    )
    assert recovered.trigger_reason == RunTriggerReason.SESSION_RECOVERY
    assert recovered.retry_index == 0

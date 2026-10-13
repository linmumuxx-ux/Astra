"""员工验收使用真实领域事务与明确协议模拟；不冒充真实模型验收。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from domains.core import DomainError
from domains.identity.models import Actor, WorkspaceGrant
from domains.organization.models import Employee, Role
from domains.personas.models import EmployeeState, InboxAdmission
from domains.runtime.errors import OpenCodeUnavailable
from domains.work.models import Task, TaskReview

from . import test_executions as execution_tests
from .test_personas import DecidingRuntime, runner_for

dispatch_db = execution_tests.dispatch_db
execution_env = execution_tests.execution_env
pytestmark = pytest.mark.asyncio


async def employee_reviewer(env, tmp_path, *, outcome="COMPLETED", disconnect=False, tool_failure=False):
    database, _, engineering, native, execution_id, factory = env
    if tool_failure:
        native.tool_exit, native.tool_output = 1, "1 original test failed"
    result = await engineering.run(execution_id, poll_seconds=0.001)
    async with database.sessions.begin() as session:
        employee = await session.get(Employee, "employee")
        employee.permissions = [*employee.permissions, "task.review"]
        actor = await session.get(Actor, employee.id)
        actor.permissions = employee.permissions
        role = await session.get(Role, "role")
        role.permissions = [*role.permissions, "task.review"]
        grant = await session.scalar(select(WorkspaceGrant).where(WorkspaceGrant.actor_id == "employee"))
        grant.permissions = [*grant.permissions, "task.review"]
        session.add(EmployeeState(employee_id=employee.id))
        revision = (await session.get(Task, "task-0")).revision
    deciding = DecidingRuntime("review", disconnect=disconnect)
    deciding.extra_payload = {
        "task_id": "task-0",
        "review": {
            "execution_id": execution_id,
            "expected_task_revision": revision,
            "outcome": outcome,
            "criteria_results": [
                {
                    "criterion_index": 0,
                    "passed": outcome == "COMPLETED",
                    "reason": "独立读取原生工具结果核对标准",
                    "evidence": [
                        {
                            "native_session_id": result["native_session_id"],
                            "message_id": "msg_final",
                            "part_id": "prt_test",
                            "excerpt": native.tool_output,
                        }
                    ],
                }
            ],
        },
    }
    reviewer = await runner_for(
        SimpleNamespace(state=SimpleNamespace(db=database)), {"id": "team"}, tmp_path, deciding
    )
    reviewer.execution_settings = engineering.settings
    reviewer.execution_client_factory = factory
    return reviewer, deciding, native


@pytest.mark.parametrize(
    "outcome,status", [("COMPLETED", "COMPLETED"), ("REWORK", "QUEUED"), ("WAIT_HUMAN", "WAIT_HUMAN")]
)
async def test_employee_independent_review_atomic_and_recoverable(execution_env, tmp_path, outcome, status):
    database = execution_env[0]
    reviewer, deciding, _ = await employee_reviewer(execution_env, tmp_path, outcome=outcome, disconnect=True)
    with pytest.raises(OpenCodeUnavailable):
        await reviewer.run("employee")
    snapshot = deciding.snapshots[0]
    evidence = snapshot["inbox"][0]["native_evidence"]["items"][0]
    assert evidence["matches_submission"] and evidence["exit_code"] == 0
    assert evidence["output"] == "5 tests passed"
    assert (await reviewer.run("employee"))["status"] == "FINISHED"
    async with database.sessions() as session:
        review = await session.scalar(select(TaskReview))
        assert review.reviewer_id == "employee" and review.outcome == outcome
        assert (await session.get(Task, "task-0")).status == status
        assert await session.scalar(select(func.count(TaskReview.id))) == 1
        admissions = (await session.scalars(select(InboxAdmission))).all()
        assert sum(item.disposition == "HANDLED" for item in admissions) == 1
        assert len(admissions) == 2
    assert len([call for call in deciding.calls if call.url.path.endswith("/prompt_async")]) == 1


async def test_failed_native_test_can_support_rework_but_not_completion(execution_env, tmp_path):
    reviewer, _, _ = await employee_reviewer(execution_env, tmp_path, outcome="REWORK", tool_failure=True)
    assert (await reviewer.run("employee"))["status"] == "FINISHED"
    async with execution_env[0].sessions() as session:
        task = await session.get(Task, "task-0")
        review = await session.scalar(select(TaskReview))
        assert task.status == "QUEUED" and review.outcome == "REWORK"
        assert review.criteria_results[0]["evidence"][0]["excerpt"] == "1 original test failed"


@pytest.mark.parametrize("fault", ["other_task", "changed_native", "revoked_grant"])
async def test_employee_review_rechecks_source_native_and_current_authority(execution_env, tmp_path, fault):
    database = execution_env[0]
    reviewer, deciding, native = await employee_reviewer(execution_env, tmp_path)
    if fault == "other_task":
        deciding.extra_payload["task_id"] = "task-1"
    elif fault == "changed_native":

        async def change():
            page = next(iter(native.pages.values()))
            page[1]["parts"][0]["state"]["output"] += " changed after submission"

        deciding.before_messages = change
    else:

        async def revoke():
            async with database.sessions.begin() as session:
                grant = await session.scalar(
                    select(WorkspaceGrant).where(WorkspaceGrant.actor_id == "employee")
                )
                grant.permissions = ["task.dispatch"]

        deciding.before_messages = revoke
    with pytest.raises(DomainError):
        await reviewer.run("employee")
    async with database.sessions() as session:
        assert (await session.get(Task, "task-0")).status == "REVIEW"
        assert await session.scalar(select(func.count(TaskReview.id))) == 0
        admission = await session.scalar(select(InboxAdmission))
        assert admission.disposition == "DEFERRED"

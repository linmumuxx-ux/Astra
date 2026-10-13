"""真实 SQLite 事务验证租约、并发、撤权与过期恢复；不模拟模型执行。"""

import asyncio

import pytest
from sqlalchemy import func, select

from domains.core import DomainError, now
from domains.database import Database
from domains.governance.service import mutate
from domains.identity.models import Actor, WorkspaceGrant
from domains.identity.service import Principal
from domains.organization.models import Employee, Role, Team, TeamMember
from domains.runtime.models import Worker, WorkerLease
from domains.runtime.service import (
    assert_current_execution,
    dispatch_task,
    expire_worker_leases,
    release_reconciled_execution,
    renew_lease,
    validate_execution_authority,
)
from domains.work.models import Task, TaskExecution

from .database_support import isolated_database_url

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dispatch_db(tmp_path):
    async with isolated_database_url(tmp_path, "dispatch.sqlite") as url:
        database = Database(url)
        await database.create_for_tests()
        async with database.sessions.begin() as session:
            session.add_all(
                [
                    Actor(id="human", name="管理者", kind="HUMAN", permissions=["*"]),
                    Actor(id="employee", name="工程员工", kind="EMPLOYEE", permissions=["task.dispatch"]),
                    Team(id="team", name="工程团队"),
                ]
            )
            await session.flush()
            session.add(Role(id="role", team_id="team", name="工程岗位", permissions=["task.dispatch"]))
            session.add(TeamMember(team_id="team", actor_id="employee"))
            await session.flush()
            session.add(
                Employee(
                    id="employee",
                    name="工程员工",
                    team_id="team",
                    role_id="role",
                    manager_id="human",
                    permissions=["task.dispatch"],
                    scope={"projects": ["project"]},
                )
            )
            session.add_all(
                [
                    WorkspaceGrant(
                        actor_id=actor,
                        team_id="team",
                        project_id="project",
                        expires_at=now() + 3600,
                        permissions=["task.dispatch", "task.reconcile", "runtime.recover"],
                    )
                    for actor in ["human", "employee"]
                ]
            )
            session.add(
                Worker(
                    id="worker",
                    name="本地执行资源",
                    base_url="http://runtime.invalid",
                    runtime_version="1.18.35",
                    capabilities=["python"],
                    allowed_projects=["project"],
                    workspace_roots=["/workspaces"],
                    health="HEALTHY",
                    last_seen_at=now(),
                    concurrent_slots=2,
                )
            )
            await session.flush()
            for index in range(3):
                session.add(
                    Task(
                        id=f"task-{index}",
                        team_id="team",
                        owner_employee_id="employee",
                        created_by_actor="human",
                        title=f"任务 {index}",
                        objective="完成可验收工作",
                        acceptance_criteria=["测试通过"],
                        required_capabilities=["python"],
                        asset_scope={"project_id": "project"},
                        continuity_key=f"continuity-{index}",
                    )
                )
            session.add_all([WorkerLease(worker_id="worker", slot=index) for index in range(2)])
        yield database, Principal("human", "HUMAN", "管理者", frozenset(["*"]))
        await database.engine.dispose()


async def dispatch(database, principal, task_id, *, key=None):
    async with database.sessions() as session:
        try:
            return await mutate(
                session,
                principal,
                key or f"dispatch-{task_id}",
                f"tasks/{task_id}/dispatch",
                {"task_id": task_id},
                lambda fresh: dispatch_task(session, fresh, task_id, "worker"),
            )
        except Exception:
            await session.rollback()
            raise


async def test_one_employee_can_hold_two_task_leases_without_fake_running(dispatch_db):
    database, principal = dispatch_db
    first = await dispatch(database, principal, "task-0")
    second = await dispatch(database, principal, "task-1")
    assert first["lease"]["slot"] != second["lease"]["slot"]
    for result in [first, second]:
        assert result["execution"]["state"] == "BOUND"
        assert result["execution"]["native_session_id"] is None
        assert result["execution"]["lease_fence"] == result["lease"]["fence"]
        assert result["execution"]["grant_snapshot"]["owner_employee_id"] == "employee"
    async with database.sessions() as session:
        task = await session.get(Task, "task-0")
        assert task.status == "DISPATCHED"
    with pytest.raises(DomainError, match="没有可用"):
        await dispatch(database, principal, "task-2")
    async with database.sessions() as session:
        assert (await session.get(Task, "task-2")).status == "QUEUED"


async def test_idempotent_dispatch_and_concurrent_requests_cannot_double_dispatch(dispatch_db):
    database, principal = dispatch_db
    first, duplicate = await asyncio.gather(
        dispatch(database, principal, "task-0"), dispatch(database, principal, "task-0")
    )
    assert first == duplicate
    with pytest.raises(DomainError, match="排队"):
        await dispatch(database, principal, "task-0", key="different-key")
    async with database.sessions() as session:
        assert await session.scalar(select(func.count(TaskExecution.id))) == 1
        assert (
            await session.scalar(select(func.count(WorkerLease.id)).where(WorkerLease.state == "ACTIVE")) == 1
        )


@pytest.mark.parametrize(
    "failure",
    [
        "employee_paused",
        "owner_grant_revoked",
        "capability_missing",
        "project_denied",
        "stale_health",
        "unverified_version",
    ],
)
async def test_dispatch_requires_owner_grant_current_health_and_worker_scope(dispatch_db, failure):
    database, principal = dispatch_db
    async with database.sessions.begin() as session:
        worker = await session.get(Worker, "worker")
        if failure == "employee_paused":
            (await session.get(Employee, "employee")).lifecycle = "PAUSED"
        elif failure == "owner_grant_revoked":
            grant = await session.scalar(select(WorkspaceGrant).where(WorkspaceGrant.actor_id == "employee"))
            grant.expires_at = now() - 1
        elif failure == "capability_missing":
            worker.capabilities = []
        elif failure == "project_denied":
            worker.allowed_projects = []
        elif failure == "stale_health":
            worker.last_seen_at = now() - 121
        elif failure == "unverified_version":
            worker.runtime_version = "1.18.99"
    with pytest.raises(DomainError):
        await dispatch(database, principal, "task-0")
    async with database.sessions() as session:
        assert await session.scalar(select(func.count(TaskExecution.id))) == 0
        assert (await session.get(Task, "task-0")).status == "QUEUED"


async def test_expired_lease_is_reconciliation_required_never_reclaimed(dispatch_db):
    database, principal = dispatch_db
    result = await dispatch(database, principal, "task-0")
    async with database.sessions.begin() as session:
        lease = await session.get(WorkerLease, result["lease"]["id"])
        lease.expires_at = now() - 1
    async with database.sessions.begin() as session:
        assert await expire_worker_leases(session, principal) == [result["lease"]["id"]]
    async with database.sessions.begin() as session:
        assert await expire_worker_leases(session, principal) == []
    async with database.sessions() as session:
        lease = await session.get(WorkerLease, result["lease"]["id"])
        task = await session.get(Task, "task-0")
        execution = await session.get(TaskExecution, result["execution"]["id"])
        assert lease.state == task.status == execution.state == "RECONCILE_REQUIRED"
        assert lease.task_id == task.id
        with pytest.raises(DomainError):
            await assert_current_execution(session, execution.id, expected_fence=lease.fence)
    await dispatch(database, principal, "task-1")
    with pytest.raises(DomainError, match="没有可用"):
        await dispatch(database, principal, "task-2")


async def test_revoked_grant_or_policy_blocks_execution_start_and_renewal(dispatch_db):
    database, principal = dispatch_db
    result = await dispatch(database, principal, "task-0")
    async with database.sessions.begin() as session:
        grant = await session.scalar(select(WorkspaceGrant).where(WorkspaceGrant.actor_id == "employee"))
        grant.permissions = []
        grant.revision += 1
    async with database.sessions() as session:
        with pytest.raises(DomainError):
            await validate_execution_authority(
                session, result["execution"]["id"], expected_fence=result["lease"]["fence"]
            )
        with pytest.raises(DomainError):
            await renew_lease(session, result["execution"]["id"], expected_fence=result["lease"]["fence"])


async def test_old_execution_fence_and_superseded_result_cannot_release_new_lease(dispatch_db):
    database, principal = dispatch_db
    first = await dispatch(database, principal, "task-0")
    async with database.sessions.begin() as session:
        await release_reconciled_execution(
            session,
            principal,
            first["execution"]["id"],
            expected_fence=first["lease"]["fence"],
            outcome="ABORTED",
            reconciliation_ref="human-decision/test-fixture",
        )
        (await session.get(Task, "task-0")).status = "QUEUED"
    second = await dispatch(database, principal, "task-0", key="second-attempt")
    assert second["execution"]["attempt_no"] == 2
    assert second["lease"]["fence"] > first["lease"]["fence"]
    async with database.sessions() as session:
        assert (await session.get(TaskExecution, first["execution"]["id"])).superseded_by == second[
            "execution"
        ]["id"]
        with pytest.raises(DomainError):
            await release_reconciled_execution(
                session,
                principal,
                first["execution"]["id"],
                expected_fence=first["lease"]["fence"],
                outcome="ABORTED",
                reconciliation_ref="stale-confirmation",
            )
        with pytest.raises(DomainError):
            await assert_current_execution(
                session, second["execution"]["id"], expected_fence=first["lease"]["fence"]
            )


async def test_shared_assets_lock_across_tasks_but_isolated_worktrees_allow_parallelism(dispatch_db):
    database, principal = dispatch_db
    async with database.sessions.begin() as session:
        for task_id in ["task-0", "task-1"]:
            (await session.get(Task, task_id)).asset_scope = {
                "project_id": "project",
                "shared_assets": ["production-db"],
            }
    await dispatch(database, principal, "task-0")
    with pytest.raises(DomainError, match="共享资产"):
        await dispatch(database, principal, "task-1")
    async with database.sessions() as session:
        assert (await session.get(Task, "task-1")).status == "QUEUED"


async def test_worker_submission_needs_native_evidence_and_never_completes_task(dispatch_db):
    database, principal = dispatch_db
    result = await dispatch(database, principal, "task-0")
    async with database.sessions() as session:
        with pytest.raises(DomainError, match="证据"):
            await release_reconciled_execution(
                session,
                principal,
                result["execution"]["id"],
                expected_fence=result["lease"]["fence"],
                outcome="SUBMITTED",
                reconciliation_ref="report/ref",
            )
    async with database.sessions.begin() as session:
        execution = await session.get(TaskExecution, result["execution"]["id"])
        execution.native_session_id = "ses_verified_fixture"
        await release_reconciled_execution(
            session,
            principal,
            execution.id,
            expected_fence=result["lease"]["fence"],
            outcome="SUBMITTED",
            reconciliation_ref="report/ref",
            evidence_refs=["opencode://ses_verified_fixture/tool-result"],
        )
    async with database.sessions() as session:
        assert (await session.get(Task, "task-0")).status == "REVIEW"

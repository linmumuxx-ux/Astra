"""真实业务数据库 + HTTP 协议故障注入；不把协议模拟当作真实模型验收。"""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.schemas import TaskReviewInput
from apps.services.executions import ExecutionRunner
from apps.services.reviews import read_evidence, review_snapshot
from domains.core import DomainError, now
from domains.governance.models import BudgetUsage
from domains.identity.models import Actor, WorkspaceGrant
from domains.identity.service import issue_credential
from domains.personas.models import InboxAdmission, SourceEvent
from domains.runtime import OpenCodeClient, OpenCodeConfig, RuntimePurpose
from domains.runtime.errors import OpenCodeUnavailable
from domains.runtime.execution_config import ExecutionSettings
from domains.runtime.models import Worker, WorkerLease
from domains.work.models import Task, TaskExecution
from domains.work.review import apply_review, validate_review

from . import test_dispatch as dispatch_tests
from .test_dispatch import dispatch
from .test_runtime_client import native_contract

dispatch_db = dispatch_tests.dispatch_db
pytestmark = pytest.mark.asyncio


class NativeProtocol:
    def __init__(self, database):
        self.database = database
        self.sessions = {}
        self.pages = {}
        self.create_count = self.prompt_count = self.abort_count = 0
        self.lose_prompt = self.lose_create = self.no_final = self.revoke = False
        self.tool_exit, self.tool_output = 0, "5 tests passed"

    async def handle(self, request):
        path, method = request.url.path, request.method
        if path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "1.19.0"})
        if path == "/doc":
            return httpx.Response(200, json=native_contract())
        if path == "/session" and method == "POST":
            self.create_count += 1
            body = json.loads(request.content)
            session_id = "ses_fixture_" + str(self.create_count)
            self.sessions[session_id] = {
                **body,
                "id": session_id,
                "directory": request.url.params["directory"],
            }
            if self.lose_create:
                raise httpx.ReadError("injected creation receipt loss", request=request)
            return httpx.Response(200, json=self.sessions[session_id])
        if path == "/session/status":
            return httpx.Response(200, json={})
        session_id = path.split("/")[2]
        if path.endswith("/children"):
            return httpx.Response(200, json=[])
        if path.endswith("/prompt_async"):
            self.prompt_count += 1
            body = json.loads(request.content)
            info = {
                "id": "msg_final",
                "sessionID": session_id,
                "role": "assistant",
                "parentID": body["messageID"],
                "time": {"completed": now() * 1000},
                "finish": "stop",
                "providerID": "fixture",
                "modelID": "fixture",
                "tokens": {"total": 42},
                "cost": 0.0002,
            }
            self.pages[session_id] = [
                {"info": {"id": body["messageID"], "role": "user", "sessionID": session_id}, "parts": []},
                {
                    "info": info,
                    "parts": [
                        {
                            "id": "prt_test",
                            "messageID": "msg_final",
                            "sessionID": session_id,
                            "type": "tool",
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "output": self.tool_output,
                                "metadata": {"exit": self.tool_exit},
                            },
                        }
                    ],
                },
            ]
            if self.no_final:
                self.pages[session_id][1]["info"]["finish"] = "tool-calls"
            if self.revoke:
                async with self.database.sessions.begin() as session:
                    grant = await session.scalar(
                        select(WorkspaceGrant).where(WorkspaceGrant.actor_id == "employee")
                    )
                    grant.expires_at = now() - 1
            if self.lose_prompt:
                self.lose_prompt = False
                raise httpx.ReadError("injected prompt receipt loss", request=request)
            return httpx.Response(204)
        if path.endswith("/message"):
            return httpx.Response(200, json=self.pages.get(session_id, []))
        if path.endswith("/abort"):
            self.abort_count += 1
            return httpx.Response(200, json=True)
        return httpx.Response(200, json=self.sessions[session_id])


@pytest.fixture
async def execution_env(dispatch_db, tmp_path):
    database, principal = dispatch_db
    repository = tmp_path.resolve() / "repo"
    storage = tmp_path.resolve() / "workspaces"
    repository.mkdir()
    storage.mkdir()
    for args in [
        ("init", "-q"),
        (
            "-c",
            "user.name=Astra Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        ),
    ]:
        process = await asyncio.create_subprocess_exec("git", "-C", str(repository), *args)
        assert await process.wait() == 0
    settings = ExecutionSettings.model_validate(
        {
            "projects": {
                "worker": {
                    "project": {
                        "transport": "local",
                        "repository": str(repository),
                        "workspace_root": str(storage),
                        "base_ref": "HEAD",
                        "model": "fixture/fixture",
                        "permission_rules": [
                            {"permission": "*", "pattern": "*", "action": "deny"},
                            {"permission": "bash", "pattern": "python3 -m unittest -v", "action": "allow"},
                        ],
                    }
                }
            }
        }
    )
    async with database.sessions.begin() as session:
        worker = await session.get(Worker, "worker")
        worker.workspace_roots = [str(storage)]
        actor = Actor(
            id="executor", name="工程服务", kind="SYSTEM", permissions=["runtime.execute", "task.reconcile"]
        )
        session.add(actor)
        await session.flush()
        from domains.organization.models import TeamMember

        session.add(TeamMember(team_id="team", actor_id=actor.id))
        session.add(
            WorkspaceGrant(
                actor_id=actor.id,
                team_id="team",
                project_id="project",
                permissions=["task.reconcile"],
                expires_at=now() + 3600,
            )
        )
        grant = await session.scalar(select(WorkspaceGrant).where(WorkspaceGrant.actor_id == "human"))
        grant.permissions = [*grant.permissions, "task.review"]
        token = await issue_credential(session, actor)
    result = await dispatch(database, principal, "task-0")
    native = NativeProtocol(database)

    def factory(worker, execution, config):
        return OpenCodeClient(
            OpenCodeConfig(
                "http://runtime.invalid", "worker", RuntimePurpose.TASK, (str(storage),), model=config.model
            ),
            transport=httpx.MockTransport(native.handle),
        )

    runner = ExecutionRunner(database, token, settings, client_factory=factory)
    return database, principal, runner, native, result["execution"]["id"], factory


async def test_real_business_submission_event_usage_release_and_independent_review(execution_env):
    db, principal, runner, native, eid, factory = execution_env
    result = await runner.run(eid, poll_seconds=0.001)
    assert result["state"] == "SUBMITTED" and native.create_count == native.prompt_count == 1
    async with db.sessions() as session:
        task = await session.get(Task, "task-0")
        assert task.status == "REVIEW" and task.completed_at is None
        lease = await session.get(WorkerLease, result["lease_id"])
        assert lease.state == "FREE"
        assert await session.scalar(select(func.count(BudgetUsage.id))) == 1
        event = await session.scalar(select(SourceEvent).where(SourceEvent.source == "task"))
        assert event.payload_ref["execution_id"] == eid
        assert await session.scalar(select(func.count(InboxAdmission.id))) == 1
    # 重启/重复投递不创建新 Session，不重复记账或投递结果。
    assert (await runner.run(eid))["state"] == "SUBMITTED"
    assert native.create_count == native.prompt_count == 1
    async with db.sessions.begin() as session:
        snapshot = await review_snapshot(session, principal, eid, runner.settings)
    messages = await read_evidence(snapshot, client_factory=factory)
    data = TaskReviewInput(
        execution_id=eid,
        expected_task_revision=snapshot[0]["revision"],
        outcome="COMPLETED",
        criteria_results=[
            {
                "criterion_index": 0,
                "passed": True,
                "reason": "独立检查实际测试工具结果",
                "evidence": [
                    {
                        "native_session_id": result["native_session_id"],
                        "message_id": "msg_final",
                        "part_id": "prt_test",
                        "excerpt": "5 tests passed",
                    }
                ],
            }
        ],
    )
    refs = validate_review(data, snapshot[0], snapshot[1], messages)
    async with db.sessions.begin() as session:
        review = await apply_review(session, principal, "task-0", data, snapshot, refs)
        assert review.reviewer_id == "human"
    async with db.sessions() as session:
        assert (await session.get(Task, "task-0")).status == "COMPLETED"
        assert await session.scalar(select(func.count(SourceEvent.id))) == 2
    async with db.sessions.begin() as session:
        historical = await review_snapshot(session, principal, eid, runner.settings, for_review=False)
    assert await read_evidence(historical, client_factory=factory)


async def test_lost_prompt_receipt_recovers_original_session_without_resubmission(execution_env):
    db, _, runner, native, eid, _ = execution_env
    native.lose_prompt = True
    with pytest.raises(OpenCodeUnavailable):
        await runner.run(eid)
    async with db.sessions() as session:
        attempt = await session.get(TaskExecution, eid)
        assert attempt.submission_started_at and attempt.native_session_id
        assert (await session.get(Task, "task-0")).status == "DISPATCHED"
    result = await runner.run(eid, poll_seconds=0.001)
    assert result["state"] == "SUBMITTED"
    assert native.create_count == native.prompt_count == 1


async def test_creation_receipt_unknown_never_creates_another_session(execution_env):
    db, _, runner, native, eid, _ = execution_env
    native.lose_create = True
    with pytest.raises(OpenCodeUnavailable):
        await runner.run(eid)
    with pytest.raises(DomainError, match="准备结果未知"):
        await runner.run(eid)
    assert native.create_count == 1 and native.prompt_count == 0
    async with db.sessions() as session:
        assert (await session.get(TaskExecution, eid)).preparation_started_at


async def test_grant_revocation_aborts_once_and_preserves_unknown_side_effects_and_slot(execution_env):
    db, _, runner, native, eid, _ = execution_env
    native.revoke = True
    with pytest.raises(DomainError):
        await runner.run(eid)
    with pytest.raises(DomainError):
        await runner.run(eid)
    assert native.abort_count == 1 and native.prompt_count == 1
    async with db.sessions() as session:
        task = await session.get(Task, "task-0")
        attempt = await session.get(TaskExecution, eid)
        lease = await session.get(WorkerLease, attempt.lease_id)
        assert task.status == attempt.state == lease.state == "RECONCILE_REQUIRED"
        assert lease.task_id == task.id and attempt.abort_started_at
        assert await session.scalar(select(func.count(BudgetUsage.id))) == 0


async def test_idle_without_original_final_is_not_submission(execution_env):
    db, _, runner, native, eid, _ = execution_env
    native.no_final = True
    with pytest.raises(DomainError, match="观察超时"):
        await runner.run(eid, timeout_seconds=0.02, poll_seconds=0.001)
    async with db.sessions() as session:
        assert (await session.get(Task, "task-0")).status == "RUNNING"
        assert (await session.get(TaskExecution, eid)).finished_at is None
    assert native.prompt_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "forged",
        "failed_exit",
        "missing_exit",
        "wrong_session",
        "omitted_standard",
        "changed_output",
    ],
)
async def test_worker_claim_or_invalid_citation_never_completes_business_task(execution_env, failure):
    db, principal, runner, native, eid, factory = execution_env
    result = await runner.run(eid, poll_seconds=0.001)
    async with db.sessions.begin() as session:
        snapshot = await review_snapshot(session, principal, eid, runner.settings)
    messages = await read_evidence(snapshot, client_factory=factory)
    criterion = {
        "criterion_index": 0,
        "passed": True,
        "reason": "审查实际结果",
        "evidence": [
            {
                "native_session_id": result["native_session_id"],
                "message_id": "msg_final",
                "part_id": "prt_test",
                "excerpt": "5 tests passed",
            }
        ],
    }
    if failure == "missing":
        criterion["evidence"] = []
    if failure == "forged":
        criterion["evidence"][0]["excerpt"] = "fake success"
    if failure == "failed_exit":
        messages[result["native_session_id"]][1]["parts"][0]["state"]["metadata"]["exit"] = 1
    if failure == "missing_exit":
        messages[result["native_session_id"]][1]["parts"][0]["state"]["metadata"] = {}
    if failure == "wrong_session":
        criterion["evidence"][0]["native_session_id"] = "ses_other_task"
    if failure == "changed_output":
        messages[result["native_session_id"]][1]["parts"][0]["state"]["output"] += " changed after submission"
    if failure == "omitted_standard":
        snapshot[0]["acceptance_criteria"].append("原始标准二")
    data = TaskReviewInput(
        execution_id=eid,
        expected_task_revision=snapshot[0]["revision"],
        outcome="COMPLETED",
        criteria_results=[criterion],
    )
    with pytest.raises(DomainError):
        validate_review(data, snapshot[0], snapshot[1], messages)
    async with db.sessions() as session:
        assert (await session.get(Task, "task-0")).status == "REVIEW"


@pytest.mark.parametrize("kind", ["SYSTEM", "WORKER", "HUMAN"])
async def test_execution_identity_and_unrelated_administrator_cannot_self_review(execution_env, kind):
    from domains.identity.service import Principal
    from domains.organization.models import TeamMember

    db, principal, runner, native, eid, _ = execution_env
    await runner.run(eid, poll_seconds=0.001)
    async with db.sessions.begin() as session:
        actor = Actor(
            id="unrelated-reviewer", kind=kind, name="非业务主责审核者", permissions=["task.review"]
        )
        session.add(actor)
        await session.flush()
        session.add(TeamMember(actor_id=actor.id, team_id="team"))
        session.add(
            WorkspaceGrant(
                actor_id=actor.id,
                team_id="team",
                project_id="project",
                permissions=["task.review"],
                expires_at=now() + 3600,
            )
        )
    attacker = Principal("unrelated-reviewer", kind, "非业务主责审核者", frozenset(["task.review"]))
    async with db.sessions.begin() as session:
        with pytest.raises(DomainError, match="不能自行|只有业务主责"):
            await review_snapshot(session, attacker, eid, runner.settings)
    async with db.sessions() as session:
        assert (await session.get(Task, "task-0")).status == "REVIEW"


async def test_permission_revocation_between_evidence_read_and_review_commit_blocks_completion(execution_env):
    db, principal, runner, native, eid, factory = execution_env
    result = await runner.run(eid, poll_seconds=0.001)
    async with db.sessions.begin() as session:
        snapshot = await review_snapshot(session, principal, eid, runner.settings)
    messages = await read_evidence(snapshot, client_factory=factory)
    data = TaskReviewInput(
        execution_id=eid,
        expected_task_revision=snapshot[0]["revision"],
        outcome="COMPLETED",
        criteria_results=[
            {
                "criterion_index": 0,
                "passed": True,
                "reason": "复验原生工具结果",
                "evidence": [
                    {
                        "native_session_id": result["native_session_id"],
                        "message_id": "msg_final",
                        "part_id": "prt_test",
                        "excerpt": "5 tests passed",
                    }
                ],
            }
        ],
    )
    refs = validate_review(data, snapshot[0], snapshot[1], messages)
    async with db.sessions.begin() as session:
        grant = await session.scalar(select(WorkspaceGrant).where(WorkspaceGrant.actor_id == "human"))
        grant.expires_at = now() - 1
    async with db.sessions.begin() as session:
        with pytest.raises(DomainError, match="Workspace Grant"):
            await apply_review(session, principal, "task-0", data, snapshot, refs)
    async with db.sessions() as session:
        assert (await session.get(Task, "task-0")).status == "REVIEW"

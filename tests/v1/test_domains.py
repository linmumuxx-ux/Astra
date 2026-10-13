from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from apps.api.main import create_app
from domains.core import DomainError, new_id, now
from domains.governance.models import AuditEvent
from domains.identity.models import Actor, Credential, WorkspaceGrant
from domains.identity.service import issue_credential
from domains.messaging.models import ChannelMember
from domains.organization.models import Employee, TeamMember
from domains.personas.models import EmployeeState, InboxAdmission, SourceEvent
from domains.personas.service import acquire_turn, finish_turn

from .database_support import isolated_database_url


@pytest_asyncio.fixture
async def api(tmp_path):
    async with isolated_database_url(tmp_path, "test.db") as url:
        app = create_app(url)
        await app.state.db.create_for_tests()
        async with app.state.db.sessions() as session:
            admin = Actor(id=new_id(), kind="HUMAN", name="测试授权人", permissions=["*"])
            session.add(admin)
            await session.flush()
            token = await issue_credential(session, admin)
            await session.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield app, client, admin.id
        await app.state.db.engine.dispose()


async def post(client, path, body=None, *, key=None):
    return await client.post(f"/api/v1/{path}", json=body, headers={"Idempotency-Key": key or str(uuid4())})


async def setup_team(client):
    team = (await post(client, "teams", {"name": "测试团队"})).json()
    role = (
        await post(
            client,
            "roles",
            {
                "name": "工程",
                "team_id": team["id"],
                "permissions": ["task.create", "task.handoff", "channel.send", "routine.manage"],
            },
        )
    ).json()
    employees = []
    for name in ["甲", "乙"]:
        res = await post(
            client,
            "employees",
            {"name": name, "team_id": team["id"], "role_id": role["id"], "permissions": role["permissions"]},
        )
        assert res.status_code == 200, res.text
        employees.append(res.json())
    return team, role, employees


async def task_for(client, team, employee):
    response = await post(
        client,
        "tasks",
        {
            "team_id": team["id"],
            "owner_employee_id": employee["id"],
            "title": "验证真实业务规则",
            "objective": "验证",
            "acceptance_criteria": ["证据可核验"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def another_human(app, team_id):
    async with app.state.db.sessions() as session:
        actor = Actor(id=new_id(), kind="HUMAN", name="另一成员", permissions=["channel.send"])
        session.add(actor)
        await session.flush()
        session.add(TeamMember(team_id=team_id, actor_id=actor.id))
        token = await issue_credential(session, actor)
        await session.commit()
    return actor.id, token


async def test_authentication_and_no_self_reported_actor(api):
    app, client, _ = api
    assert (await client.get("/api/v1/me", headers={"Authorization": "Bearer forged"})).status_code == 401
    assert (await post(client, "teams", {"name": "x", "actor_id": "admin"})).status_code == 422
    async with app.state.db.sessions() as session:
        credential = await session.scalar(select(Credential))
        assert len(credential.digest) == 64
        credential.revoked = True
        await session.commit()
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_employee_identity_is_not_worker_and_permission_ceiling(api):
    app, client, _ = api
    team, role, employees = await setup_team(client)
    assert employees[0]["id"] != employees[1]["id"]
    assert "worker_id" not in employees[0]
    assert (await client.get("/api/v1/workers")).json() == []
    res = await post(
        client,
        "employees",
        {
            "name": "越权",
            "team_id": team["id"],
            "role_id": role["id"],
            "permissions": ["organization.manage"],
        },
    )
    assert res.status_code == 403
    async with app.state.db.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Employee)) == 2


async def test_atomic_idempotency_and_key_payload_conflict(api):
    _, client, _ = api
    key = str(uuid4())
    first = await post(client, "teams", {"name": "同一个团队"}, key=key)
    second = await post(client, "teams", {"name": "同一个团队"}, key=key)
    assert first.json() == second.json()
    assert len((await client.get("/api/v1/teams")).json()) == 1
    assert (await post(client, "teams", {"name": "不同内容"}, key=key)).status_code == 409


async def test_dm_private_and_message_durable_inbox_admission(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    dm = (await post(client, f"employees/{employees[0]['id']}/dm")).json()
    message = await post(client, f"channels/{dm['id']}/messages", {"content": "长期对话"})
    assert message.status_code == 200, message.text
    other_id, other_token = await another_human(app, team["id"])
    assert other_id not in {employees[0]["id"], employees[1]["id"]}
    headers = {"Authorization": f"Bearer {other_token}"}
    assert (await client.get(f"/api/v1/channels/{dm['id']}/messages", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/channels", headers=headers)).json() == []
    events = (await client.get("/api/v1/audit-events", headers=headers)).json()
    assert not any(x["type"] == "message.created" for x in events)
    async with app.state.db.sessions() as session:
        inbox = await session.scalar(select(InboxAdmission))
        assert inbox.employee_id == employees[0]["id"]
        assert inbox.observed_at is None and inbox.disposition is None
    messages = (await client.get(f"/api/v1/channels/{dm['id']}/messages")).json()
    assert len(messages) == 1 and messages[0]["content"] == "长期对话"


async def test_cached_message_replay_rechecks_membership(api):
    app, client, admin_id = api
    _, _, employees = await setup_team(client)
    dm = (await post(client, f"employees/{employees[0]['id']}/dm")).json()
    key = str(uuid4())
    result = await post(client, f"channels/{dm['id']}/messages", {"content": "私密"}, key=key)
    assert result.status_code == 200
    async with app.state.db.sessions() as session:
        member = await session.scalar(
            select(ChannelMember).where(
                ChannelMember.channel_id == dm["id"], ChannelMember.actor_id == admin_id
            )
        )
        await session.delete(member)
        await session.commit()
    replay = await post(client, f"channels/{dm['id']}/messages", {"content": "私密"}, key=key)
    assert replay.status_code == 403


async def test_formal_handoff_changes_owner_only_after_acceptance(api):
    _, client, _ = api
    team, _, employees = await setup_team(client)
    task = await task_for(client, team, employees[0])
    handoff = await post(client, f"tasks/{task['id']}/handoff", {"target_employee_id": employees[1]["id"]})
    assert handoff.status_code == 200, handoff.text
    before = (await client.get(f"/api/v1/tasks/{task['id']}")).json()
    assert before["owner_employee_id"] == employees[0]["id"]
    accepted = await post(client, f"handoffs/{handoff.json()['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    after = (await client.get(f"/api/v1/tasks/{task['id']}")).json()
    assert after["owner_employee_id"] == employees[1]["id"]
    assert (await post(client, f"handoffs/{handoff.json()['id']}/accept")).status_code == 409


async def test_archive_rejects_unfinished_responsibility(api):
    _, client, _ = api
    team, _, employees = await setup_team(client)
    await task_for(client, team, employees[0])
    assert (await post(client, f"employees/{employees[0]['id']}/archive")).status_code == 409
    assert (await post(client, f"employees/{employees[1]['id']}/archive")).json()["lifecycle"] == "ARCHIVED"
    assert (await post(client, f"employees/{employees[1]['id']}/resume")).status_code == 409


async def test_operation_rechecks_revision_and_duplicate_approval(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    task = await task_for(client, team, employees[0])
    operation = (
        await post(
            client, "operations", {"team_id": team["id"], "target_id": task["id"], "action": "task.cancel"}
        )
    ).json()
    key = str(uuid4())
    approved = await post(client, f"operations/{operation['id']}/approve", key=key)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "EXECUTED"
    assert (await post(client, f"operations/{operation['id']}/approve", key=key)).json() == approved.json()
    async with app.state.db.sessions() as session:
        count = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.type == "operation.executed")
        )
        assert count == 1
    task2 = await task_for(client, team, employees[0])
    operation2 = (
        await post(
            client, "operations", {"team_id": team["id"], "target_id": task2["id"], "action": "task.cancel"}
        )
    ).json()
    await post(client, f"tasks/{task2['id']}/pause")
    assert (await post(client, f"operations/{operation2['id']}/approve")).status_code == 409


async def test_source_event_dedup_and_no_invented_processing(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    payload = {
        "team_id": team["id"],
        "source": "test-connector",
        "source_id": "source-1",
        "object_ref": "issue/1",
        "causal_root": "issue/1",
        "recipients": [employees[0]["id"]],
    }
    first = await post(client, "source-events", payload)
    second = await post(client, "source-events", payload)
    assert first.json()["id"] == second.json()["id"]
    assert (
        await post(client, "source-events", {**payload, "payload_ref": {"changed": True}})
    ).status_code == 409
    async with app.state.db.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SourceEvent)) == 1
        assert await session.scalar(select(func.count()).select_from(InboxAdmission)) == 1


async def test_persona_lease_fences_late_decisions(api):
    app, client, _ = api
    _, _, employees = await setup_team(client)
    async with app.state.db.sessions() as session:
        first = await acquire_turn(session, employees[0]["id"])
        await session.commit()
        first_id = first.id
        with pytest.raises(DomainError, match="已有有效"):
            await acquire_turn(session, employees[0]["id"])
        await session.rollback()
        state = await session.scalar(
            select(EmployeeState).where(EmployeeState.employee_id == employees[0]["id"])
        )
        state.lease_until = now() - 1
        await session.commit()
        second = await acquire_turn(session, employees[0]["id"])
        await session.commit()
        second_id = second.id
        with pytest.raises(DomainError, match="停止或失效"):
            await finish_turn(session, first_id, [{"type": "no_action"}])
        await session.rollback()
        final = await finish_turn(session, second_id, [{"type": "no_action"}])
        assert final.status == "FINISHED"
        await session.commit()


async def test_project_workspace_grant_required_even_for_admin(api):
    app, client, admin_id = api
    team, _, employees = await setup_team(client)
    payload = {
        "team_id": team["id"],
        "owner_employee_id": employees[0]["id"],
        "title": "工程工作",
        "objective": "修改工程",
        "acceptance_criteria": ["验证"],
        "asset_scope": {"project_id": "project-a"},
    }
    assert (await post(client, "tasks", payload)).status_code == 403
    async with app.state.db.sessions() as session:
        session.add(
            WorkspaceGrant(
                actor_id=admin_id,
                team_id=team["id"],
                project_id="project-a",
                permissions=["task.create"],
                expires_at=now() + 3600,
            )
        )
        await session.commit()
    assert (await post(client, "tasks", payload)).status_code == 200


async def test_routine_run_now_only_admits_event_and_paused_employee_cannot_wake(api):
    app, client, _ = api
    _, _, employees = await setup_team(client)
    routine = (
        await post(
            client,
            "routines",
            {
                "employee_id": employees[0]["id"],
                "title": "防线职责",
                "schedule": "3600",
            },
        )
    ).json()
    result = await post(client, f"routines/{routine['id']}/run-now")
    assert result.status_code == 200, result.text
    assert (await client.get("/api/v1/tasks")).json() == []
    await post(client, f"employees/{employees[0]['id']}/pause")
    assert (await post(client, f"routines/{routine['id']}/run-now")).status_code == 409

"""安全评审的真实 API/数据库复现；断言目标不变量，不伪装已修复。"""

import asyncio

import httpx
import pytest
from sqlalchemy import select

from domains.core import DomainError, new_id, now
from domains.identity.models import Actor, WorkspaceGrant
from domains.identity.service import issue_credential
from domains.knowledge.models import KnowledgeItem
from domains.messaging.models import ChannelMember
from domains.organization.models import Employee, TeamMember
from domains.personas.models import EmployeeTurn
from domains.personas.service import acquire_turn, finish_turn
from domains.work.service import accept_handoff

from . import test_domains
from .test_domains import post, setup_team, task_for

pytestmark = pytest.mark.asyncio
api = test_domains.api


async def test_approval_rechecks_initiator_project_grant_after_revocation(api):
    app, client, admin_id = api
    team, _, employees = await setup_team(client)
    async with app.state.db.sessions.begin() as session:
        approver = Actor(
            id=new_id(), kind="HUMAN", name="独立审批人", permissions=["operation.approve", "task.cancel"]
        )
        session.add(approver)
        await session.flush()
        session.add(TeamMember(team_id=team["id"], actor_id=approver.id))
        token = await issue_credential(session, approver)
        for actor_id in [admin_id, approver.id]:
            session.add(
                WorkspaceGrant(
                    actor_id=actor_id,
                    team_id=team["id"],
                    project_id="project-review",
                    permissions=["task.create", "task.cancel"],
                    expires_at=now() + 3600,
                )
            )
    task_response = await post(
        client,
        "tasks",
        {
            "team_id": team["id"],
            "owner_employee_id": employees[0]["id"],
            "title": "受工程授权约束",
            "objective": "验证发起人撤权",
            "acceptance_criteria": ["撤权后具体操作不得执行"],
            "asset_scope": {"project_id": "project-review"},
        },
    )
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()
    prepared = await post(
        client, "operations", {"team_id": team["id"], "target_id": task["id"], "action": "task.cancel"}
    )
    assert prepared.status_code == 200, prepared.text
    async with app.state.db.sessions.begin() as session:
        grant = await session.scalar(select(WorkspaceGrant).where(WorkspaceGrant.actor_id == admin_id))
        grant.expires_at = now() - 1
        grant.revision += 1
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as approver_client:
        approved = await post(approver_client, f"operations/{prepared.json()['id']}/approve")
    assert approved.status_code == 403, approved.text


async def test_new_dm_operation_cannot_return_removed_members_private_channel(api):
    app, client, admin_id = api
    team, _, employees = await setup_team(client)
    dm = (
        await post(
            client,
            "channels",
            {
                "team_id": team["id"],
                "kind": "DM",
                "name": "已撤权的私密标题",
                "member_ids": [employees[0]["id"]],
            },
        )
    ).json()
    async with app.state.db.sessions.begin() as session:
        membership = await session.scalar(
            select(ChannelMember).where(
                ChannelMember.channel_id == dm["id"], ChannelMember.actor_id == admin_id
            )
        )
        await session.delete(membership)
    assert (await client.get(f"/api/v1/channels/{dm['id']}")).status_code == 403
    recreated = await post(
        client,
        "channels",
        {"team_id": team["id"], "kind": "DM", "name": "新请求", "member_ids": [employees[0]["id"]]},
    )
    assert recreated.status_code == 403, recreated.text


async def test_verified_draft_edit_invalidates_prior_content_verification(api):
    app, client, admin_id = api
    team, _, _ = await setup_team(client)
    async with app.state.db.sessions.begin() as session:
        knowledge = KnowledgeItem(
            id=new_id(),
            team_id=team["id"],
            title="已经验证的候选知识",
            kind="WIKI",
            content="原已验证内容",
            source_refs=["verified-source/v1"],
            verification="VERIFIED",
            created_by_actor=admin_id,
        )
        session.add(knowledge)
        await session.flush()
        object_id, revision = knowledge.id, knowledge.revision
    changed = await client.patch(
        f"/api/v1/knowledge/{object_id}",
        json={"revision": revision, "content": "修改后的未验证内容", "source_refs": ["unverified-source/v2"]},
        headers={"Idempotency-Key": new_id()},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["verification"] != "VERIFIED", changed.text


async def test_external_ingest_cannot_forge_internal_channel_source_and_break_listing(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    forged = await post(
        client,
        "source-events",
        {
            "team_id": team["id"],
            "source": "channel",
            "source_id": "forged-channel-source",
            "object_ref": "messages/forged",
            "causal_root": "forged",
            "payload_ref": {},
            "recipients": [employees[0]["id"]],
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers=client.headers,
    ) as observer:
        listing = await observer.get("/api/v1/source-events")
    assert forged.status_code in {400, 403, 422}, f"ingest={forged.status_code}, list={listing.status_code}"
    assert listing.status_code == 200


async def test_pause_between_persona_lifecycle_read_and_lease_write_blocks_turn(api, monkeypatch):
    app, client, _ = api
    _, _, employees = await setup_team(client)
    employee_id = employees[0]["id"]
    from domains.personas import service as persona_service

    original = persona_service.get_required
    read_done, continue_acquire = asyncio.Event(), asyncio.Event()

    async def pause_after_employee_read(session, model, object_id):
        obj = await original(session, model, object_id)
        if model is Employee and object_id == employee_id:
            read_done.set()
            await continue_acquire.wait()
        return obj

    monkeypatch.setattr(persona_service, "get_required", pause_after_employee_read)

    async def acquire():
        async with app.state.db.sessions.begin() as session:
            return await acquire_turn(session, employee_id)

    pending = asyncio.create_task(acquire())
    await asyncio.wait_for(read_done.wait(), timeout=5)
    try:
        paused = await post(client, f"employees/{employee_id}/pause")
        assert paused.status_code == 200, paused.text
    finally:
        continue_acquire.set()
    try:
        result = await asyncio.wait_for(pending, timeout=5)
    except DomainError:
        result = None
    assert result is None, "已暂停员工仍取得新的 RUNNING Persona Turn"
    async with app.state.db.sessions() as session:
        assert (
            await session.scalar(
                select(EmployeeTurn.id).where(
                    EmployeeTurn.employee_id == employee_id, EmployeeTurn.status == "RUNNING"
                )
            )
            is None
        )


async def test_pause_between_persona_lifecycle_read_and_finish_blocks_decision(api, monkeypatch):
    app, client, _ = api
    _, _, employees = await setup_team(client)
    employee_id = employees[0]["id"]
    async with app.state.db.sessions.begin() as session:
        turn = await acquire_turn(session, employee_id)
        turn_id = turn.id
    from domains.personas import service as persona_service

    original = persona_service.get_required
    read_done, continue_finish = asyncio.Event(), asyncio.Event()

    async def pause_after_employee_read(session, model, object_id):
        obj = await original(session, model, object_id)
        if model is Employee and object_id == employee_id:
            read_done.set()
            await continue_finish.wait()
        return obj

    monkeypatch.setattr(persona_service, "get_required", pause_after_employee_read)

    async def finish():
        async with app.state.db.sessions.begin() as session:
            return await finish_turn(session, turn_id, [{"type": "dispatch", "task_id": "late-decision"}])

    pending = asyncio.create_task(finish())
    await asyncio.wait_for(read_done.wait(), timeout=5)
    try:
        paused = await post(client, f"employees/{employee_id}/pause")
        assert paused.status_code == 200, paused.text
    finally:
        continue_finish.set()
    try:
        result = await asyncio.wait_for(pending, timeout=5)
    except DomainError:
        result = None
    assert result is None, "已暂停员工仍写入 FINISHED Persona 决策"


async def test_handoff_cannot_assign_task_to_target_paused_after_lifecycle_read(api, monkeypatch):
    app, client, admin_id = api
    team, _, employees = await setup_team(client)
    task = await task_for(client, team, employees[0])
    proposed = await post(client, f"tasks/{task['id']}/handoff", {"target_employee_id": employees[1]["id"]})
    assert proposed.status_code == 200, proposed.text
    from domains.identity.service import current_principal
    from domains.work import service as work_service

    target_id = employees[1]["id"]
    original = work_service.get_required
    read_done, continue_accept = asyncio.Event(), asyncio.Event()

    async def pause_after_target_read(session, model, object_id):
        obj = await original(session, model, object_id)
        if model is Employee and object_id == target_id:
            read_done.set()
            await continue_accept.wait()
        return obj

    monkeypatch.setattr(work_service, "get_required", pause_after_target_read)

    async def accept():
        async with app.state.db.sessions.begin() as authentication:
            # 在身份读取事务结束后开始领域操作，避免持有同一管理员的写锁再等待其并发请求。
            principal = await current_principal(authentication, admin_id)
        async with app.state.db.sessions.begin() as session:
            # 模拟可信内部调用；业务服务仍须独立保证目标生命周期。
            return await accept_handoff(session, principal, proposed.json()["id"])

    pending = asyncio.create_task(accept())
    await asyncio.wait_for(read_done.wait(), timeout=5)
    try:
        paused = await post(client, f"employees/{target_id}/pause")
        assert paused.status_code == 200, paused.text
    finally:
        continue_accept.set()
    try:
        result = await asyncio.wait_for(pending, timeout=5)
    except DomainError:
        result = None
    assert result is None, "正式交接把 Task 主责转给已暂停员工"


async def test_archive_requires_disposition_of_pending_incoming_handoff(api):
    _, client, _ = api
    team, _, employees = await setup_team(client)
    task = await task_for(client, team, employees[0])
    proposed = await post(client, f"tasks/{task['id']}/handoff", {"target_employee_id": employees[1]["id"]})
    assert proposed.status_code == 200, proposed.text
    archived = await post(client, f"employees/{employees[1]['id']}/archive")
    assert archived.status_code == 409, "存在待签收正式交接的员工未经处理即被归档"


async def test_handoff_requires_current_project_grant_and_employee_project_scope(api):
    app, client, admin_id = api
    team, _, employees = await setup_team(client)
    async with app.state.db.sessions.begin() as session:
        session.add(
            WorkspaceGrant(
                actor_id=admin_id,
                team_id=team["id"],
                project_id="restricted-project",
                permissions=["task.create"],
                expires_at=now() + 3600,
            )
        )
        employee_actor = await session.get(Actor, employees[0]["id"])
        token = await issue_credential(session, employee_actor)
    created = await post(
        client,
        "tasks",
        {
            "team_id": team["id"],
            "owner_employee_id": employees[0]["id"],
            "title": "受工程授权约束的交接",
            "objective": "交接动作不得跳过当前工程授权",
            "acceptance_criteria": ["无工程授权时拒绝转移业务责任"],
            "asset_scope": {"project_id": "restricted-project"},
        },
    )
    assert created.status_code == 200, created.text
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as employee_client:
        proposed = await post(
            employee_client,
            f"tasks/{created.json()['id']}/handoff",
            {"target_employee_id": employees[1]["id"]},
        )
    assert proposed.status_code == 403, "工程不在员工 scope 且无 Workspace Grant，仍可提出正式交接"


async def test_handoff_acceptance_rechecks_receivers_current_project_authority(api):
    app, client, admin_id = api
    team, _, employees = await setup_team(client)
    async with app.state.db.sessions.begin() as session:
        session.add(
            WorkspaceGrant(
                actor_id=admin_id,
                team_id=team["id"],
                project_id="restricted-project",
                permissions=["task.create", "task.handoff"],
                expires_at=now() + 3600,
            )
        )
        target_actor = await session.get(Actor, employees[1]["id"])
        token = await issue_credential(session, target_actor)
    created = await post(
        client,
        "tasks",
        {
            "team_id": team["id"],
            "owner_employee_id": employees[0]["id"],
            "title": "签收权限复验",
            "objective": "签收方必须拥有当前工程授权",
            "acceptance_criteria": ["缺工程授权的接收员工不能签收"],
            "asset_scope": {"project_id": "restricted-project"},
        },
    )
    assert created.status_code == 200, created.text
    proposed = await post(
        client, f"tasks/{created.json()['id']}/handoff", {"target_employee_id": employees[1]["id"]}
    )
    assert proposed.status_code == 200, proposed.text
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as receiver:
        accepted = await post(receiver, f"handoffs/{proposed.json()['id']}/accept")
    assert accepted.status_code == 403, "接收员工缺当前工程授权仍签收并获得 Task 主责"

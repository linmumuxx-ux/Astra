"""Persona 领域和协议故障注入。模型响应为契约模拟，不是模型 E2E 证据。"""

import json

import httpx
import pytest
from sqlalchemy import func, select

from apps.services.personas import PersonaRunner, begin_turn
from domains.core import DomainError, now
from domains.governance.models import BudgetUsage
from domains.identity.models import Actor, Credential
from domains.identity.service import issue_credential
from domains.knowledge.memory import GitMemory
from domains.messaging.models import Message
from domains.organization.models import TeamMember
from domains.personas.models import EmployeeState, EmployeeTurn, InboxAdmission
from domains.runtime import OpenCodeClient, OpenCodeConfig, RuntimePurpose
from domains.runtime.errors import OpenCodeUnavailable

from . import test_domains
from .test_domains import post, setup_team
from .test_runtime_client import NativeRuntime

api = test_domains.api


class DecidingRuntime(NativeRuntime):
    def __init__(self, action="reply", *, bad_actor=False, disconnect=False):
        super().__init__()
        self.action, self.bad_actor, self.disconnect = action, bad_actor, disconnect
        self.outputs = {}
        self.before_messages = None
        self.extra_payload = {}
        self.snapshots = []

    async def __call__(self, request):
        if request.url.path.endswith("/prompt_async"):
            body = json.loads(request.content)
            prompt = body["parts"][0]["text"]
            snapshot = json.loads(prompt[prompt.index("{") :])
            self.snapshots.append(snapshot)
            admission = snapshot["inbox"][0]["admission"]["id"]
            action = {"type": self.action, "admission_id": admission}
            if self.action == "reply":
                action["content"] = "契约模拟输出"
            elif self.action == "remember":
                action.update(content="持续关注防线", reason="记录承诺")
            elif self.action == "follow_up":
                action.update(after_seconds=60, reason="等待新证据")
            elif self.action == "no_action":
                action["reason"] = "本事件无需操作"
            if self.bad_actor:
                action["admission_id"] = "other-private-inbox"
            action.update(self.extra_payload)
            self.outputs[request.url.path.split("/")[2]] = [
                {
                    "info": {
                        "id": "msg_result",
                        "role": "assistant",
                        "time": {"completed": now() * 1000},
                        "parentID": body["messageID"],
                        "providerID": "test",
                        "modelID": "contract",
                        "finish": "stop",
                        "tokens": {"total": 23, "input": 18, "output": 5},
                        "cost": 0.00012,
                    },
                    "parts": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"plan": "处理有效关注事项", "actions": [action]}, ensure_ascii=False
                            ),
                        }
                    ],
                }
            ]
            response = super().__call__(request)
            if self.disconnect:
                self.disconnect = False
                raise httpx.ReadTimeout("已提交但回执断开", request=request)
            return response
        if request.url.path.endswith("/message"):
            self.calls.append(request)
            if self.before_messages:
                callback, self.before_messages = self.before_messages, None
                await callback()
            return httpx.Response(200, json=self.outputs.get(request.url.path.split("/")[2], []))
        return super().__call__(request)


async def runner_for(app, team, tmp_path, runtime, *, permissions=None):
    async with app.state.db.sessions() as session:
        service = Actor(kind="SYSTEM", name="可信 Persona 服务", permissions=permissions or ["persona.run"])
        session.add(service)
        await session.flush()
        session.add(TeamMember(team_id=team["id"], actor_id=service.id))
        token = await issue_credential(session, service)
        await session.commit()
    client = OpenCodeClient(
        OpenCodeConfig(
            "http://native.invalid",
            "persona-test",
            RuntimePurpose.PERSONA,
            (str(tmp_path / "decision"),),
            model="test/contract",
        ),
        transport=httpx.MockTransport(runtime),
    )
    return PersonaRunner(app.state.db, token, client, GitMemory(str(tmp_path / "memory")))


async def dm_input(client, employee):
    dm = (await post(client, f"employees/{employee['id']}/dm")).json()
    result = await post(client, f"channels/{dm['id']}/messages", {"content": "请检查当前职责"})
    assert result.status_code == 200
    return dm, result.json()


async def test_persona_reply_real_domain_effect_and_restart_no_duplicate(api, tmp_path):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    dm, message = await dm_input(client, employees[0])
    native = DecidingRuntime(disconnect=True)
    runner = await runner_for(app, team, tmp_path, native)
    with pytest.raises(OpenCodeUnavailable):
        await runner.run(employees[0]["id"])
    async with app.state.db.sessions() as session:
        admission = await session.scalar(select(InboxAdmission))
        assert admission.observed_at is None and admission.disposition is None
    # 新实例模拟进程重启；恢复原生结果并经业务服务发一条消息。
    restarted = PersonaRunner(app.state.db, runner.token, runner.client, runner.memory)
    result = await restarted.run(employees[0]["id"])
    assert result["status"] == "FINISHED"
    assert (await restarted.run(employees[0]["id"]))["status"] == "NO_PENDING_INPUT"
    messages = (await client.get(f"/api/v1/channels/{dm['id']}/messages")).json()
    assert len(messages) == 2 and messages[1]["reply_to"] == message["id"]
    assert messages[1]["sender_id"] == employees[0]["id"]
    prompts = [call for call in native.calls if call.url.path.endswith("/prompt_async")]
    assert len(prompts) == 1
    async with app.state.db.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BudgetUsage)) == 1
        usage = await session.scalar(select(BudgetUsage))
        assert usage.purpose == "PERSONA" and usage.tokens == 23 and usage.cost_micros == 120
        admission = await session.scalar(select(InboxAdmission))
        assert admission.observed_at and admission.disposition == "HANDLED"
    assert native.sessions["ses_1"]["permission"] == [{"permission": "*", "pattern": "*", "action": "deny"}]


async def test_persona_observation_does_not_close_unauthorized_decision(api, tmp_path):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    dm, _ = await dm_input(client, employees[0])
    native = DecidingRuntime(bad_actor=True)
    runner = await runner_for(app, team, tmp_path, native)
    with pytest.raises(DomainError, match="每条关注事项"):
        await runner.run(employees[0]["id"])
    async with app.state.db.sessions() as session:
        admission = await session.scalar(select(InboxAdmission))
        assert admission.observed_at and admission.disposition is None
        assert await session.scalar(select(func.count()).select_from(Message)) == 1
    assert len((await client.get(f"/api/v1/channels/{dm['id']}/messages")).json()) == 1


@pytest.mark.parametrize("intervention", ["credential", "pause"])
async def test_persona_pause_or_credential_revoke_during_model_prevents_effect(api, tmp_path, intervention):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    await dm_input(client, employees[0])
    native = DecidingRuntime()
    runner = await runner_for(app, team, tmp_path, native)

    async def revoke():
        if intervention == "pause":
            assert (await post(client, f"employees/{employees[0]['id']}/pause")).status_code == 200
            return
        async with app.state.db.sessions() as session:
            from domains.identity.service import digest

            credential = await session.scalar(
                select(Credential).where(Credential.digest == digest(runner.token))
            )
            credential.revoked = True
            await session.commit()

    native.before_messages = revoke
    with pytest.raises(DomainError, match="认证失效|停止主动履职"):
        await runner.run(employees[0]["id"])
    async with app.state.db.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Message)) == 1


async def test_persona_no_task_for_no_action_and_deferred_wakeup(api, tmp_path):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    await dm_input(client, employees[0])
    native = DecidingRuntime("follow_up")
    runner = await runner_for(app, team, tmp_path, native)
    assert (await runner.run(employees[0]["id"]))["status"] == "FINISHED"
    assert (await runner.run(employees[0]["id"]))["status"] == "NO_PENDING_INPUT"
    async with app.state.db.sessions() as session:
        admission = await session.scalar(select(InboxAdmission))
        assert admission.disposition == "DEFERRED" and admission.observed_at
        state = await session.scalar(
            select(EmployeeState).where(EmployeeState.employee_id == employees[0]["id"])
        )
        state.next_review = now() - 1
        await session.commit()
    native.action = "no_action"
    assert (await runner.run(employees[0]["id"]))["status"] == "FINISHED"
    assert (await client.get("/api/v1/tasks")).json() == []
    assert len(native.sessions) == 2


async def test_persona_budget_reserves_unknown_usage_and_no_credential_forgery(api, tmp_path):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    await dm_input(client, employees[0])
    runner = await runner_for(app, team, tmp_path, DecidingRuntime())
    async with app.state.db.sessions.begin() as session:
        from domains.organization.models import Employee

        employee = await session.get(Employee, employees[0]["id"])
        employee.daily_token_budget = 9000
        turn = await begin_turn(session, runner.token, employee.id)
        turn_id = turn.id
    async with app.state.db.sessions.begin() as session:
        state = await session.scalar(
            select(EmployeeState).where(EmployeeState.employee_id == employees[0]["id"])
        )
        state.lease_until = now() - 1
    async with app.state.db.sessions.begin() as session:
        with pytest.raises(DomainError, match="预算不足"):
            await begin_turn(session, runner.token, employees[0]["id"])
    async with app.state.db.sessions() as session:
        assert (await session.get(EmployeeTurn, turn_id)).status == "RUNNING"


async def test_persona_private_plan_memory_and_history_do_not_cross_human_dm(api, tmp_path):
    app, client, _ = api
    team, role, employees = await setup_team(client)
    permissions = [*role["permissions"], "memory.write"]
    for collection, obj in [("roles", role), ("employees", employees[0])]:
        response = await client.patch(
            f"/api/v1/{collection}/{obj['id']}",
            json={"revision": obj["revision"], "permissions": permissions},
            headers={"Idempotency-Key": f"memory-permission-{collection}"},
        )
        assert response.status_code == 200, response.text
    await dm_input(client, employees[0])
    native = DecidingRuntime("remember")
    runner = await runner_for(app, team, tmp_path, native)
    assert (await runner.run(employees[0]["id"]))["status"] == "FINISHED"
    from .test_domains import another_human

    _, token = await another_human(app, team["id"])
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "second-dm"}
    dm = (await client.post(f"/api/v1/employees/{employees[0]['id']}/dm", json={}, headers=headers)).json()
    headers["Idempotency-Key"] = "second-message"
    response = await client.post(
        f"/api/v1/channels/{dm['id']}/messages", json={"content": "另一条私聊"}, headers=headers
    )
    assert response.status_code == 200
    native.action = "reply"
    assert (await runner.run(employees[0]["id"]))["status"] == "FINISHED"
    context = native.snapshots[-1]
    assert context["memory"] == {} and context["plan"] == ""
    assert all(item["channel_id"] == dm["id"] for item in context["conversation"])
    snapshot = (await client.get(f"/api/v1/employees/{employees[0]['id']}/dashboard", headers=headers)).json()
    assert snapshot["state"] is None


async def test_persona_dispatch_approval_handoff_share_domain_authority(api, tmp_path):
    from domains.governance.models import Operation
    from domains.runtime.models import Worker
    from domains.work.models import Handoff, Task, TaskExecution

    app, client, admin_id = api
    team, role, employees = await setup_team(client)
    permissions = [*role["permissions"], "task.dispatch", "operation.prepare", "task.pause"]
    response = await client.patch(
        f"/api/v1/roles/{role['id']}",
        json={"revision": role["revision"], "permissions": permissions},
        headers={"Idempotency-Key": "dispatch-role"},
    )
    assert response.status_code == 200
    response = await client.patch(
        f"/api/v1/employees/{employees[0]['id']}",
        json={
            "revision": employees[0]["revision"],
            "permissions": permissions,
            "scope": {"projects": ["project"]},
        },
        headers={"Idempotency-Key": "dispatch-employee"},
    )
    assert response.status_code == 200
    for actor_id in [admin_id, employees[0]["id"]]:
        result = await post(
            client,
            "workspace-grants",
            {
                "team_id": team["id"],
                "actor_id": actor_id,
                "project_id": "project",
                "permissions": ["task.create", "task.dispatch", "task.pause", "task.handoff"],
                "expires_at": now() + 3600,
            },
        )
        assert result.status_code == 200
    worker = (
        await post(
            client,
            "workers",
            {
                "name": "领域测试资源",
                "base_url": "http://native.invalid",
                "capabilities": ["python"],
                "allowed_projects": ["project"],
                "workspace_roots": ["/workspaces"],
            },
        )
    ).json()
    async with app.state.db.sessions.begin() as session:
        obj = await session.get(Worker, worker["id"])
        obj.health, obj.runtime_version, obj.last_seen_at = "HEALTHY", "1.18.35", now()
    await dm_input(client, employees[0])
    native = DecidingRuntime("dispatch")
    native.extra_payload = {
        "worker_id": worker["id"],
        "task": {
            "team_id": team["id"],
            "owner_employee_id": employees[0]["id"],
            "title": "工程委派领域验收",
            "objective": "创建并绑定工程执行",
            "acceptance_criteria": ["独立复验后才能完成"],
            "asset_scope": {"project_id": "project"},
            "required_capabilities": ["python"],
        },
    }
    runner = await runner_for(app, team, tmp_path, native)
    assert (await runner.run(employees[0]["id"]))["status"] == "FINISHED"
    async with app.state.db.sessions() as session:
        task = await session.scalar(select(Task))
        assert task.status == "DISPATCHED" and task.source_event_id
        task_id = task.id
        assert (await session.scalar(select(TaskExecution))).state == "BOUND"
    native.action = "ask_human"
    native.extra_payload = {
        "operation": {"team_id": team["id"], "action": "task.pause", "target_id": task_id}
    }
    await dm_input(client, employees[0])
    assert (await runner.run(employees[0]["id"]))["status"] == "FINISHED"
    async with app.state.db.sessions() as session:
        operation = await session.scalar(select(Operation))
        assert operation.status == "WAIT_HUMAN" and operation.initiator_id == employees[0]["id"]
        operation_id = operation.id
    approved = await post(client, f"operations/{operation_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "EXECUTED"
    native.action = "handoff"
    native.extra_payload = {
        "task_id": task_id,
        "handoff": {"target_employee_id": employees[1]["id"], "reason": "领域测试正式交接"},
    }
    await dm_input(client, employees[0])
    assert (await runner.run(employees[0]["id"]))["status"] == "FINISHED"
    async with app.state.db.sessions() as session:
        assert (await session.get(Task, task_id)).owner_employee_id == employees[0]["id"]
        assert (await session.scalar(select(Handoff))).status == "PROPOSED"

from sqlalchemy import select

from domains.personas.models import InboxAdmission, SourceEvent

from . import test_domains
from .test_domains import post, setup_team, task_for

api = test_domains.api


async def test_clarification_keeps_responsibility_and_blocks_duplicate_or_archive(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    task = await task_for(client, team, employees[0])
    handoff = (
        await post(
            client,
            f"tasks/{task['id']}/handoff",
            {
                "target_employee_id": employees[1]["id"],
                "reason": "需要工程岗位核验",
            },
        )
    ).json()
    clarified = await post(
        client, f"handoffs/{handoff['id']}/request-clarification", {"reason": "请补充验收证据"}
    )
    assert clarified.status_code == 200 and clarified.json()["status"] == "NEEDS_CLARIFICATION"
    assert (await client.get(f"/api/v1/tasks/{task['id']}")).json()["owner_employee_id"] == employees[0]["id"]
    assert (await post(client, f"employees/{employees[1]['id']}/archive")).status_code == 409
    assert (
        await post(client, f"tasks/{task['id']}/handoff", {"target_employee_id": employees[1]["id"]})
    ).status_code == 409
    response = await post(client, f"handoffs/{handoff['id']}/clarify", {"reason": "已补充原始验收要求与来源"})
    assert response.status_code == 200 and response.json()["reason"] == "需要工程岗位核验"
    accepted = await post(client, f"handoffs/{handoff['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    async with app.state.db.sessions() as session:
        events = (await session.scalars(select(SourceEvent).where(SourceEvent.source == "handoff"))).all()
        assert len(events) == 4
        assert {event.payload_ref["action"] for event in events} == {
            "proposed",
            "request-clarification",
            "clarify",
            "accepted",
        }
        admissions = (await session.scalars(select(InboxAdmission))).all()
        assert len(admissions) == 8


async def test_rejection_and_withdrawal_have_durable_receipt_and_do_not_transfer_owner(api):
    _, client, _ = api
    team, _, employees = await setup_team(client)
    task = await task_for(client, team, employees[0])
    handoff = (
        await post(client, f"tasks/{task['id']}/handoff", {"target_employee_id": employees[1]["id"]})
    ).json()
    rejected = await post(
        client, f"handoffs/{handoff['id']}/reject", {"reason": "当前职责范围不适合接手"}, key="reject-once"
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    replay = await post(
        client, f"handoffs/{handoff['id']}/reject", {"reason": "当前职责范围不适合接手"}, key="reject-once"
    )
    assert replay.json() == rejected.json()
    assert (await post(client, f"handoffs/{handoff['id']}/accept")).status_code == 409
    replacement = (
        await post(client, f"tasks/{task['id']}/handoff", {"target_employee_id": employees[1]["id"]})
    ).json()
    withdrawn = await post(client, f"handoffs/{replacement['id']}/withdraw", {"reason": "继续由原岗位处理"})
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "WITHDRAWN"
    assert (await client.get(f"/api/v1/tasks/{task['id']}")).json()["owner_employee_id"] == employees[0]["id"]
    assert (await post(client, f"employees/{employees[1]['id']}/archive")).status_code == 200

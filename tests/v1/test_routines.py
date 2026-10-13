from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from domains.core import DomainError, now
from domains.identity.models import Actor
from domains.identity.service import issue_credential
from domains.organization.models import TeamMember
from domains.personas.models import InboxAdmission, Routine, SourceEvent
from domains.personas.routines import next_due_after, validate_schedule

from . import test_domains
from .test_domains import post, setup_team

api = test_domains.api


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


def test_cron_timezone_dst_and_leap_day_are_real_future_instants():
    assert next_due_after("CRON", "30 2 * * *", "America/New_York", stamp("2026-03-08T06:00")) == stamp(
        "2026-03-09T06:30"
    )
    # 秋季回拨后第二个 01:30 仍是未来时刻，不能跳到下一天。
    assert next_due_after("CRON", "30 1 * * *", "America/New_York", stamp("2026-11-01T05:31")) == stamp(
        "2026-11-01T06:30"
    )
    assert next_due_after("CRON", "0 0 29 2 *", "UTC", stamp("2025-01-01T00:00")) == stamp("2028-02-29T00:00")
    assert validate_schedule("EVENT", "webhook.build", "Asia/Shanghai") is None


@pytest.mark.parametrize(
    "kind,schedule,zone",
    [
        ("INTERVAL", "0", "UTC"),
        ("INTERVAL", "-1", "UTC"),
        ("INTERVAL", "1.5", "UTC"),
        ("CRON", "* * *", "UTC"),
        ("CRON", "60 * * * *", "UTC"),
        ("CRON", "0 0 31 2 *", "UTC"),
        ("EVENT", "*", "UTC"),
        ("INTERVAL", "30", "invalid/zone"),
    ],
)
def test_invalid_routine_schedule_is_rejected(kind, schedule, zone):
    with pytest.raises(DomainError) as caught:
        validate_schedule(kind, schedule, zone)
    assert caught.value.status == 422


async def make_routine(client, employee, **values):
    return await post(
        client,
        "routines",
        {
            "employee_id": employee["id"],
            "title": "持续检查职责",
            "schedule": "60",
            **values,
        },
    )


async def test_server_owns_due_time_and_locked_routine_cannot_be_self_changed(api):
    app, client, _ = api
    _, _, employees = await setup_team(client)
    start = now()
    response = await make_routine(client, employees[0], locked=True)
    assert response.status_code == 200, response.text
    routine = response.json()
    assert start + 60 <= routine["next_due_at"] <= now() + 60
    assert (await make_routine(client, employees[0], next_due_at=1)).status_code == 422
    async with app.state.db.sessions.begin() as session:
        actor = await session.get(Actor, employees[0]["id"])
        token = await issue_credential(session, actor)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as employee:
        response = await employee.patch(
            f"/api/v1/routines/{routine['id']}",
            json={"revision": routine["revision"], "locked": False},
            headers={"Idempotency-Key": "cannot-self-unlock"},
        )
        assert response.status_code == 403
        assert (await post(employee, f"routines/{routine['id']}/run-now")).status_code == 403
        assert (await make_routine(employee, employees[1])).status_code == 403


async def test_due_sweep_coalesces_backlog_and_never_dispatches_task(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    routine = (await make_routine(client, employees[0])).json()
    async with app.state.db.sessions.begin() as session:
        row = await session.get(Routine, routine["id"])
        row.next_due_at = now() - 6000
    first = await post(client, f"teams/{team['id']}/routines/sweep", key="sweep-once")
    assert first.status_code == 200, first.text
    assert len(first.json()["source_event_ids"]) == 1
    replay = await post(client, f"teams/{team['id']}/routines/sweep", key="sweep-once")
    assert replay.json() == first.json()
    second = await post(client, f"teams/{team['id']}/routines/sweep")
    assert second.json()["source_event_ids"] == []
    assert (await client.get("/api/v1/tasks")).json() == []
    async with app.state.db.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SourceEvent)) == 1
        assert await session.scalar(select(func.count()).select_from(InboxAdmission)) == 1
        assert (await session.get(Routine, routine["id"])).next_due_at > now()
    await post(client, f"employees/{employees[0]['id']}/pause")
    async with app.state.db.sessions.begin() as session:
        (await session.get(Routine, routine["id"])).next_due_at = now() - 1
    assert (await post(client, f"teams/{team['id']}/routines/sweep")).json()["source_event_ids"] == []


async def test_event_routines_share_original_event_and_inbox_dedup(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    for _ in range(2):
        response = await make_routine(client, employees[0], kind="EVENT", schedule="webhook.build")
        assert response.status_code == 200
        assert response.json()["next_due_at"] == 0
    payload = {
        "team_id": team["id"],
        "source": "webhook.build",
        "source_id": "build-42",
        "revision": 1,
        "object_ref": "builds/42",
        "payload_ref": {"result": "failed"},
        "causal_root": "build-42",
    }
    one = await post(client, "source-events", payload)
    two = await post(client, "source-events", payload)
    assert one.status_code == 200 and one.json()["id"] == two.json()["id"]
    async with app.state.db.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(InboxAdmission)) == 1
        assert await session.scalar(select(func.count()).select_from(SourceEvent)) == 1


async def test_channel_event_routine_does_not_admit_other_employees_private_dm(api):
    app, client, admin_id = api
    _, _, employees = await setup_team(client)
    for employee in employees:
        assert (await make_routine(client, employee, kind="EVENT", schedule="channel")).status_code == 200
    dm = (await post(client, f"employees/{employees[0]['id']}/dm")).json()
    members = (await client.get(f"/api/v1/channels/{dm['id']}/members")).json()
    assert {row["id"] for row in members} == {admin_id, employees[0]["id"]}
    assert all(set(row) == {"id", "name", "kind"} for row in members)
    assert (
        await post(client, f"channels/{dm['id']}/messages", {"content": "私密工作安排"})
    ).status_code == 200
    async with app.state.db.sessions() as session:
        admissions = (await session.scalars(select(InboxAdmission))).all()
        assert [row.employee_id for row in admissions] == [employees[0]["id"]]


async def test_system_scheduler_requires_team_membership_and_exact_signal_permission(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    routine = (await make_routine(client, employees[0])).json()
    async with app.state.db.sessions.begin() as session:
        (await session.get(Routine, routine["id"])).next_due_at = now() - 1
        system = Actor(kind="SYSTEM", name="可信定时投递", permissions=["routine.signal"])
        session.add(system)
        await session.flush()
        token = await issue_credential(session, system)
        system_id = system.id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as scheduler:
        assert (await post(scheduler, f"teams/{team['id']}/routines/sweep")).status_code == 403
        async with app.state.db.sessions.begin() as session:
            session.add(TeamMember(team_id=team["id"], actor_id=system_id))
        result = await post(scheduler, f"teams/{team['id']}/routines/sweep")
        assert result.status_code == 200, result.text
        assert len(result.json()["source_event_ids"]) == 1
        assert (await make_routine(scheduler, employees[0])).status_code == 403

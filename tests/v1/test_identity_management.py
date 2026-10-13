import asyncio
import json
import secrets

import httpx
import pytest
from sqlalchemy import select

from apps.api.main import INPUTS, PATCHES
from apps.services.routines import sweep_authenticated
from domains.core import DomainError, now
from domains.identity.models import Credential
from domains.identity.service import digest
from domains.personas.models import Routine

from . import test_domains
from .http_server import serve_http
from .test_domains import another_human, post, setup_team

api = test_domains.api


async def test_concrete_write_contracts_publish_strict_request_schemas(api):
    app, _, _ = api
    spec = app.openapi()
    for resources, method in [(INPUTS, "post"), (PATCHES, "patch")]:
        for name, schema in resources.items():
            path = f"/api/v1/{name}" + ("/{object_id}" if method == "patch" else "")
            ref = spec["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/" + schema.__name__)
            assert spec["components"]["schemas"][schema.__name__]["additionalProperties"] is False


async def test_human_permissions_are_versioned_and_credentials_can_be_revoked(api):
    app, client, _ = api
    token = secrets.token_urlsafe(48)
    response = await post(
        client,
        "actors",
        {
            "name": "业务审核者",
            "permissions": [],
            "credential_digest": digest(token),
        },
    )
    assert response.status_code == 200 and "digest" not in response.text and token not in response.text
    actor = response.json()
    update = await client.patch(
        f"/api/v1/actors/{actor['id']}",
        json={
            "revision": actor["revision"],
            "name": "正式审核者",
            "permissions": ["operation.approve"],
        },
        headers={"Idempotency-Key": "update-human"},
    )
    assert update.status_code == 200, update.text
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/me", headers=headers)).json()["permissions"] == ["operation.approve"]
    async with app.state.db.sessions() as session:
        credential = await session.scalar(select(Credential).where(Credential.digest == digest(token)))
        credential_id = credential.id
    assert (await post(client, f"credentials/{credential_id}/revoke")).status_code == 200
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401


async def test_project_grants_can_be_revoked_and_explicitly_renewed_by_version(api):
    _, client, admin_id = api
    team, _, _ = await setup_team(client)
    response = await post(
        client,
        "workspace-grants",
        {
            "team_id": team["id"],
            "actor_id": admin_id,
            "project_id": "project-a",
            "permissions": ["task.create"],
            "expires_at": now() + 3600,
        },
    )
    grant = response.json()
    revoked = await post(client, f"workspace-grants/{grant['id']}/revoke")
    assert revoked.status_code == 200 and revoked.json()["expires_at"] <= now()
    stale = await client.patch(
        f"/api/v1/workspace-grants/{grant['id']}",
        json={
            "revision": grant["revision"],
            "permissions": ["task.create"],
            "expires_at": now() + 7200,
        },
        headers={"Idempotency-Key": "stale-grant"},
    )
    assert stale.status_code == 409
    renewed = await client.patch(
        f"/api/v1/workspace-grants/{grant['id']}",
        json={
            "revision": revoked.json()["revision"],
            "permissions": ["task.create"],
            "expires_at": now() + 7200,
        },
        headers={"Idempotency-Key": "renew-grant"},
    )
    assert renewed.status_code == 200, renewed.text
    assert len((await client.get("/api/v1/workspace-grants")).json()) == 1


async def test_trusted_scheduler_is_provisioned_by_human_and_stops_after_revocation(api, tmp_path):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    token = secrets.token_urlsafe(48)
    scheduler = await post(
        client,
        "system-identities/schedulers",
        {
            "name": "定时投递服务",
            "team_ids": [team["id"]],
            "credential_digest": digest(token),
        },
    )
    assert scheduler.status_code == 200, scheduler.text
    assert scheduler.json()["permissions"] == ["routine.signal"]
    routine = (
        await post(
            client,
            "routines",
            {
                "employee_id": employees[0]["id"],
                "title": "持续巡检",
                "schedule": "60",
            },
        )
    ).json()
    async with app.state.db.sessions.begin() as session:
        (await session.get(Routine, routine["id"])).next_due_at = now() - 60
    token_file = tmp_path / "scheduler.token"
    token_file.write_text(token)
    token_file.chmod(0o600)
    result = await sweep_authenticated(str(app.state.db.engine.url), str(token_file))
    assert result["teams_checked"] == 1 and len(result["source_event_ids"]) == 1
    assert (await post(client, f"actors/{scheduler.json()['id']}/revoke")).status_code == 200
    with pytest.raises(DomainError) as caught:
        await sweep_authenticated(str(app.state.db.engine.url), str(token_file))
    assert caught.value.status == 401


async def test_real_sse_filters_private_dm_and_reauthenticates_open_stream(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    actor_id, token = await another_human(app, team["id"])
    dm = (await post(client, f"employees/{employees[0]['id']}/dm")).json()
    async with serve_http(app) as url:
        async with httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"}) as reader:
            async with reader.stream("GET", "/api/v1/events") as stream:
                assert stream.status_code == 200
                seen = []

                async def consume():
                    async for line in stream.aiter_lines():
                        if line == "event: auth_revoked":
                            return
                        if line.startswith("data: "):
                            seen.append(json.loads(line[6:]))
                    raise AssertionError("SSE 结束前未发出认证撤销事件")

                consuming = asyncio.create_task(consume())
                sent = await post(client, f"channels/{dm['id']}/messages", {"content": "不能泄露给非参与者"})
                assert sent.status_code == 200
                await asyncio.sleep(1.1)
                assert not any(event["type"] == "message.created" for event in seen)
                assert (await post(client, f"actors/{actor_id}/revoke")).status_code == 200
                await asyncio.wait_for(consuming, timeout=5)

import asyncio
import json

import httpx
from sqlalchemy import select

from domains.identity.models import Credential

from . import test_domains
from .http_server import serve_http
from .test_domains import another_human, post, setup_team

api = test_domains.api


async def test_real_sse_filters_private_channel_and_rechecks_revoked_credential(api):
    app, client, _ = api
    team, _, employees = await setup_team(client)
    dm = (await post(client, f"employees/{employees[0]['id']}/dm")).json()
    assert (
        await post(client, f"channels/{dm['id']}/messages", {"content": "不能广播的私聊"})
    ).status_code == 200
    human_id, token = await another_human(app, team["id"])
    async with app.state.db.sessions() as session:
        credential_id = await session.scalar(select(Credential.id).where(Credential.actor_id == human_id))
    async with serve_http(app) as url:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as reader:
            async with reader.stream(
                "GET", f"{url}/api/v1/events?after=0", headers={"Authorization": f"Bearer {token}"}
            ) as response:
                assert response.status_code == 200
                lines = response.aiter_lines()
                visible = []
                async with asyncio.timeout(5):
                    async for line in lines:
                        if line.startswith("data:"):
                            visible.append(json.loads(line[5:]))
                        if line == ": heartbeat":
                            break
                assert visible and all(item["channel_id"] != dm["id"] for item in visible)
                revoked = await post(client, f"credentials/{credential_id}/revoke")
                assert revoked.status_code == 200
                async with asyncio.timeout(5):
                    async for line in lines:
                        if line == "event: auth_revoked":
                            break
                    else:
                        raise AssertionError("SSE 未返回认证撤销事实")

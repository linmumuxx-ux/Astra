"""IM 往返。入站、运行、出站认领和 ACK 都走 HTTP。"""

from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from nexus_api.agentscope import AgentScopeClient
from nexus_api.main import create_app

REPLY = (
    'data: {"type":"REPLY_START","id":"s1","reply_id":"r1"}\n\n'
    'data: {"type":"REPLY_END","id":"e1","reply_id":"r1","finished_reason":"completed"}\n\n'
)


def employee_body(**overrides):
    payload = {
        "name": "星河",
        "domain": "测试自动化工程师",
        "description": "负责自动化脚本",
        "instructions": "直接回答。",
        "avatar": "👩🏻‍💻",
        "enabled": True,
        "knowledge": [],
        "skills": [],
        "tools": [],
    }
    payload.update(overrides)
    return payload


def test_im_http_round_trip_claims_and_acks_the_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    chats: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/" and request.method == "POST":
            return httpx.Response(201, json={"agent_id": "agent-1"})
        if request.url.path == "/sessions/" and request.method == "POST":
            body = json.loads(request.content.decode())
            session_id = "ses-private" if body.get("workspace_id") else f"session-{body['name']}"
            return httpx.Response(201, json={"session_id": session_id})
        if request.url.path == "/chat/":
            body = json.loads(request.content.decode())
            chats.append(body)
            return httpx.Response(200, json={"status": "started", "session_id": body["session_id"]})
        if request.url.path == "/sessions/ses-private/stream":
            return httpx.Response(200, content=REPLY.encode())
        if request.url.path == "/sessions/ses-private/messages":
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {"id": "user-1", "role": "user", "content": [{"type": "text", "text": "你好"}]},
                        {
                            "id": "asst-1",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "已经收到"}],
                        },
                    ],
                    "has_more": False,
                },
            )
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        if request.url.path == "/skill":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})

    with TestClient(create_app()) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        employee = test_client.post("/api/v1/employees", json=employee_body()).json()["employee"]
        saved = test_client.post(
            "/api/v1/im/bots",
            json={"employee_id": employee["id"], "provider": "mock", "bot_id": "bot-1"},
        )
        assert saved.status_code == 200
        accepted = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "evt-1",
                "bot_id": "bot-1",
                "sender_uid": "u9",
                "text": "你好",
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["duplicate"] is False
        assert accepted.json()["session_id"] == "ses-private"
        opened = test_client.get(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers={"X-Verified-UID": "u9"},
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["items"][0]["agentscope_session_id"] == "ses-private"
        assert chats[0]["session_id"] == "ses-private"
        assert chats[0]["input"]["metadata"]["verified_uid"] == "u9"
        claimed = test_client.get("/api/v1/im/outbox")
        assert claimed.status_code == 200, claimed.text
        first = claimed.json()
        assert first["body"] == "已经收到"
        assert first["state"] == "inflight"
        assert first["conversation_key"] == "u9"
        assert first["lease_until"]
        retried = test_client.get("/api/v1/im/outbox")
        assert retried.json()["delivery_id"] == first["delivery_id"]
        assert retried.json()["lease_until"]
        queued = test_client.post(
            "/api/v1/im/contacts",
            json={
                "agent_id": "agent-1",
                "conversation_key": "u9",
                "session_id": "ses-private",
                "body": "工具发出的第二句",
            },
        )
        assert queued.status_code == 200, queued.text
        assert queued.json()["state"] == "queued"
        acked = test_client.post("/api/v1/im/acks", json={"delivery_id": first["delivery_id"]})
        assert acked.json()["state"] == "acked"
        nxt = test_client.get("/api/v1/im/outbox")
        assert nxt.status_code == 200, nxt.text
        assert nxt.json()["body"] == "工具发出的第二句"
        assert nxt.json()["delivery_id"] == queued.json()["delivery_id"]
        again = test_client.get("/api/v1/im/outbox")
        assert again.json()["delivery_id"] == nxt.json()["delivery_id"]
        test_client.post("/api/v1/im/acks", json={"delivery_id": nxt.json()["delivery_id"]})
        empty = test_client.get("/api/v1/im/outbox")
        assert empty.status_code == 404
        duplicate = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "evt-1",
                "bot_id": "bot-1",
                "sender_uid": "u9",
                "text": "你好",
            },
        )
        assert duplicate.json()["duplicate"] is True
        assert [item["input"]["content"][0]["text"] for item in chats].count("你好") == 1
        assert test_client.get("/api/v1/im/outbox").status_code == 404
        followed = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "evt-2",
                "bot_id": "bot-1",
                "sender_uid": "u9",
                "text": "接着说",
                "conversation_key": "u9",
            },
        )
        assert followed.status_code == 200, followed.text
        assert followed.json()["session_id"] == "ses-private"
        assert chats[-1]["session_id"] == "ses-private"
        assert chats[-1]["input"]["content"][0]["text"] == "接着说"
        reply = test_client.get("/api/v1/im/outbox")
        assert reply.json()["body"] == "已经收到"
        assert reply.json()["delivery_id"] != first["delivery_id"]


def test_concurrent_im_event_accepts_once(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    chats: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/" and request.method == "POST":
            return httpx.Response(201, json={"agent_id": "agent-1"})
        if request.url.path == "/sessions/" and request.method == "POST":
            body = json.loads(request.content.decode())
            session_id = "ses-private" if body.get("workspace_id") else f"session-{body['name']}"
            return httpx.Response(201, json={"session_id": session_id})
        if request.url.path == "/chat/":
            body = json.loads(request.content.decode())
            text = body["input"]["content"][0]["text"]
            if text == "并发":
                chats.append(text)
                entered.set()
                await release.wait()
            return httpx.Response(200, json={"status": "started", "session_id": body["session_id"]})
        if request.url.path.endswith("/stream"):
            return httpx.Response(200, content=b"")
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [], "has_more": False})
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    async def scenario():
        application = create_app()
        async with application.router.lifespan_context(application):
            application.state.agentscope = AgentScopeClient(
                "http://agentscope.test",
                "nexus",
                httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
            )
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://nexus.test") as client:
                employee = (await client.post("/api/v1/employees", json=employee_body())).json()["employee"]
                opened = await client.post(
                    f"/api/v1/employees/{employee['id']}/conversations",
                    headers={"X-Verified-UID": "u1"},
                    json={},
                )
                assert opened.status_code == 201, opened.text
                sent = await client.post(
                    f"/api/v1/conversations/{opened.json()['id']}/messages",
                    headers={"X-Verified-UID": "u1"},
                    json={"text": "先有私聊"},
                )
                assert sent.status_code == 200, sent.text
                saved = await client.post(
                    "/api/v1/im/bots",
                    json={"employee_id": employee["id"], "provider": "mock", "bot_id": "bot-1"},
                )
                assert saved.status_code == 200, saved.text
                payload = {
                    "provider": "mock",
                    "event_id": "race-1",
                    "bot_id": "bot-1",
                    "sender_uid": "u1",
                    "text": "并发",
                }

                async def once():
                    response = await client.post("/api/v1/im/events", json=payload)
                    return response.status_code, response.json()

                first = asyncio.create_task(once())
                second = None
                try:
                    await asyncio.wait_for(entered.wait(), timeout=3)
                    second = asyncio.create_task(once())
                    loser = await asyncio.wait_for(second, timeout=3)
                finally:
                    release.set()
                assert second is not None
                winner = await asyncio.wait_for(first, timeout=3)
                return winner, loser

    winner, loser = asyncio.run(scenario())
    assert chats == ["并发"]
    assert winner[0] == 200
    assert winner[1]["duplicate"] is False
    assert loser[0] == 409
    assert loser[1]["detail"] == "这个事件正在处理"


def test_im_http_waits_for_agentscope_and_web_stays_available(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    chats: list[dict] = []
    failed = {"im": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/":
            return httpx.Response(201, json={"agent_id": "agent-1"})
        if request.url.path == "/sessions/" and request.method == "POST":
            return httpx.Response(201, json={"session_id": "ses-private"})
        if request.url.path == "/chat/":
            body = json.loads(request.content.decode())
            text = body["input"]["content"][0]["text"]
            if text == "从 IM 来" and not failed["im"]:
                failed["im"] = True
                return httpx.Response(503, json={"detail": "还没接受"})
            chats.append(body)
            return httpx.Response(200, json={"status": "started", "session_id": body["session_id"]})
        return httpx.Response(200, json={})

    with TestClient(create_app()) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        employee = test_client.post("/api/v1/employees", json=employee_body()).json()["employee"]
        unbound = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "e0",
                "bot_id": "missing",
                "sender_uid": "u1",
                "text": "hi",
            },
        )
        assert unbound.status_code == 409
        assert "IM 不可用" in unbound.json()["detail"]
        web = test_client.post(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers={"X-Verified-UID": "u1"},
            json={},
        )
        assert web.status_code == 201
        opened = test_client.post(
            f"/api/v1/conversations/{web.json()['id']}/messages",
            headers={"X-Verified-UID": "u1"},
            json={"text": "网页上的私聊"},
        )
        assert opened.status_code == 200
        saved = test_client.post(
            "/api/v1/im/bots",
            json={"employee_id": employee["id"], "provider": "mock", "bot_id": "bot-1"},
        )
        assert saved.status_code == 200
        rejected = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "e1",
                "bot_id": "bot-1",
                "sender_uid": "u1",
                "text": "从 IM 来",
            },
        )
        assert rejected.status_code == 503
        assert [item["input"]["content"][0]["text"] for item in chats].count("从 IM 来") == 0
        accepted = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "e1",
                "bot_id": "bot-1",
                "sender_uid": "u1",
                "text": "从 IM 来",
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["session_id"] == "ses-private"
        assert accepted.json()["duplicate"] is False
        duplicate = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "e1",
                "bot_id": "bot-1",
                "sender_uid": "u1",
                "text": "从 IM 来",
            },
        )
        assert duplicate.json()["duplicate"] is True
        assert [item["input"]["content"][0]["text"] for item in chats].count("从 IM 来") == 1
        refused = test_client.post(
            "/api/v1/im/groups",
            json={"employee_id": employee["id"], "external_key": "g1", "session_id": "ses-private"},
        )
        assert refused.status_code == 409
        grouped = test_client.post(
            "/api/v1/im/groups",
            json={"employee_id": employee["id"], "external_key": "g1", "session_id": "ses-group"},
        )
        assert grouped.status_code == 200
        group_event = test_client.post(
            "/api/v1/im/events",
            json={
                "provider": "mock",
                "event_id": "e2",
                "bot_id": "bot-1",
                "sender_uid": "u1",
                "text": "外部群",
                "external_key": "g1",
            },
        )
        assert group_event.json()["session_id"] == "ses-group"
        assert chats[-1]["session_id"] == "ses-group"

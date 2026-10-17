"""IM 契约和模拟 Adapter。不接公司 SDK。"""

from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from nexus_api.agentscope import AgentScopeClient
from nexus_api.db import connect, init_db
from nexus_api.im import accept_inbound, acknowledge, bind_bot, contact_human, open_external, redeliver
from nexus_api.main import create_app


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


class SimulatedAdapter:
    """丢掉 ACK 时只按 delivery_id 再投一次，不再次推理。"""

    def __init__(self, connection) -> None:
        self.connection = connection
        self.inferences = 0
        self.deliveries: list[str] = []

    async def inbound(self, **kwargs):
        async def accept(employee_id: str, session_id: str, text: str) -> None:
            self.inferences += 1

        return await accept_inbound(self.connection, accept=accept, **kwargs)

    def push(self, conversation_key: str) -> dict[str, str]:
        item = redeliver(self.connection, conversation_key)
        self.deliveries.append(item["delivery_id"])
        return item


def test_simulated_adapter_redelivers_without_a_second_inference(tmp_path):
    path = tmp_path / "im.sqlite3"
    init_db(path)
    connection = connect(path)
    connection.execute(
        """
        INSERT INTO employees (
            id, name, domain, description, instructions, avatar, enabled,
            knowledge_json, skills_json, tools_json, agentscope_agent_id,
            mailbox_session_id, created_at, updated_at
        ) VALUES ('emp', '星河', '测试', '', '', '', 1, '[]', '[]', '[]', 'agent', 'mail', 't', 't')
        """
    )
    connection.execute(
        """
        INSERT INTO conversations (
            id, employee_id, owner_id, kind, name, agentscope_session_id, created_at, updated_at
        ) VALUES ('conv', 'emp', 'u1', 'private', '私聊', 'ses-private', 't', 't')
        """
    )
    connection.commit()
    bind_bot(connection, "emp", "mock", "bot-1")
    adapter = SimulatedAdapter(connection)

    first = asyncio.run(
        adapter.inbound(
            provider="mock",
            event_id="evt-1",
            bot_id="bot-1",
            sender_uid="u1",
            text="你好",
        )
    )
    assert first["session_id"] == "ses-private"
    assert first["duplicate"] is False
    again = asyncio.run(
        adapter.inbound(
            provider="mock",
            event_id="evt-1",
            bot_id="bot-1",
            sender_uid="u1",
            text="你好",
        )
    )
    assert again["duplicate"] is True
    assert adapter.inferences == 1
    open_external(connection, "emp", "group-9", "ses-group")
    grouped = asyncio.run(
        adapter.inbound(
            provider="mock",
            event_id="evt-2",
            bot_id="bot-1",
            sender_uid="u1",
            text="群里说",
            external_key="group-9",
        )
    )
    assert grouped["session_id"] == "ses-group"
    assert grouped["session_id"] != "ses-private"
    sent = contact_human(
        connection,
        employee_id="emp",
        conversation_key="dm-1",
        session_id="ses-private",
        body="我先联系你",
    )
    queued = contact_human(
        connection,
        employee_id="emp",
        conversation_key="dm-1",
        session_id="ses-private",
        body="等上一条送达",
    )
    assert sent["state"] == "inflight"
    assert queued["state"] == "queued"
    lost = adapter.push("dm-1")
    retried = adapter.push("dm-1")
    assert lost["delivery_id"] == retried["delivery_id"] == sent["delivery_id"]
    assert adapter.inferences == 2
    acknowledge(connection, sent["delivery_id"])
    nxt = adapter.push("dm-1")
    assert nxt["delivery_id"] == queued["delivery_id"]
    reply = asyncio.run(
        adapter.inbound(
            provider="mock",
            event_id="evt-3",
            bot_id="bot-1",
            sender_uid="u1",
            text="收到",
            conversation_key="dm-1",
        )
    )
    assert reply["session_id"] == "ses-private"
    assert adapter.inferences == 3
    connection.close()


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

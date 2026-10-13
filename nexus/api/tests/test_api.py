"""Nexus API 骨架测试。不启动 AgentScope，也不生成模拟回复。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from nexus_api.agentscope import AgentScopeClient
from nexus_api.main import create_app, load_chat_model_config, stream_cursor

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_AGENTSCOPE_BASE_URL", "")
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client


def employee_body(**overrides):
    payload = {
        "name": "星河",
        "domain": "测试自动化工程师",
        "description": "负责自动化脚本",
        "instructions": "能直接回答的问题直接回答；需要同事时联系对方。",
        "avatar": "👩🏻‍💻",
        "enabled": True,
        "knowledge": [],
        "skills": [],
        "tools": [],
    }
    payload.update(overrides)
    return payload


def test_health_and_runtime_report_pinned_version(client):
    assert client.get("/api/health").json()["product"] == "nexus"
    runtime = client.get("/api/v1/runtime").json()
    assert runtime["agentscope_version"] == "2.0.10"
    assert runtime["configured"] is False
    assert runtime["reachable"] is False


def test_skill_catalog_is_empty_when_service_is_down(client):
    payload = client.get("/api/v1/skills").json()
    assert payload == {"available": False, "items": []}


def test_employee_crud_rejects_duplicates_and_model_is_absent(client):
    created = client.post("/api/v1/employees", json=employee_body())
    assert created.status_code == 201
    employee = created.json()["employee"]
    assert "model" not in employee
    assert created.json()["agentscope"]["ok"] is False

    duplicate = client.post("/api/v1/employees", json=employee_body(name="星河", domain="另一领域"))
    assert duplicate.status_code == 409
    assert "名称" in duplicate.json()["detail"]

    same_domain = client.post("/api/v1/employees", json=employee_body(name="初禾", domain="测试自动化工程师"))
    assert same_domain.status_code == 409

    listed = client.get("/api/v1/employees", params={"q": "自动化"}).json()["items"]
    assert [item["name"] for item in listed] == ["星河"]

    disabled = client.patch(f"/api/v1/employees/{employee['id']}", json=employee_body(enabled=False))
    assert disabled.status_code == 200
    assert disabled.json()["employee"]["enabled"] is False


def test_delete_removes_channel_membership(client):
    first = client.post("/api/v1/employees", json=employee_body()).json()["employee"]
    second = client.post(
        "/api/v1/employees",
        json=employee_body(name="知微", domain="防线运营人员"),
    ).json()["employee"]
    channel = client.post(
        "/api/v1/channels",
        json={"name": "版本交付协同", "description": "跨岗位讨论", "member_ids": [first["id"], second["id"]]},
    )
    assert channel.status_code == 201
    assert client.delete(f"/api/v1/employees/{first['id']}").status_code == 200
    remaining = client.get("/api/v1/channels").json()["items"][0]["members"]
    assert [item["employee_id"] for item in remaining] == [second["id"]]


def test_private_chat_keeps_threads_and_does_not_invent_replies(client):
    employee = client.post("/api/v1/employees", json=employee_body()).json()["employee"]
    headers = {"X-Owner-Id": "browser-a"}
    first = client.post(
        f"/api/v1/employees/{employee['id']}/conversations",
        headers=headers,
        json={"name": "新对话"},
    )
    second = client.post(
        f"/api/v1/employees/{employee['id']}/conversations",
        headers=headers,
        json={"name": "新对话"},
    )
    assert first.json()["id"] != second.json()["id"]
    sent = client.post(
        f"/api/v1/conversations/{first.json()['id']}/messages",
        headers=headers,
        json={"text": "你负责哪些工作？", "attachment_ids": []},
    )
    assert sent.status_code == 200
    body = sent.json()
    assert body["message"]["sender"] == "user"
    assert body["agentscope"]["accepted"] is False
    assert "assistant" not in body
    stored = client.get(f"/api/v1/conversations/{first.json()['id']}", headers=headers).json()["messages"]
    assert [item["sender"] for item in stored] == ["user"]
    other = client.get(f"/api/v1/conversations/{second.json()['id']}", headers=headers).json()["messages"]
    assert other == []


def test_disabled_employee_cannot_receive_private_message(client):
    employee = client.post("/api/v1/employees", json=employee_body(enabled=False)).json()["employee"]
    headers = {"X-Owner-Id": "browser-a"}
    conversation = client.post(
        f"/api/v1/employees/{employee['id']}/conversations",
        headers=headers,
        json={},
    ).json()
    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=headers,
        json={"text": "你好"},
    )
    assert response.status_code == 409


def test_channel_requires_a_member_and_does_not_script_peer_replies(client):
    employee = client.post("/api/v1/employees", json=employee_body()).json()["employee"]
    other = client.post(
        "/api/v1/employees",
        json=employee_body(name="初禾", domain="测试工具工程师"),
    ).json()["employee"]
    empty = client.post(
        "/api/v1/channels",
        json={"name": "空讨论", "description": "没有成员", "member_ids": []},
    )
    assert empty.status_code == 422
    channel = client.post(
        "/api/v1/channels",
        json={
            "name": "防线异常分析",
            "description": "讨论异常归属",
            "member_ids": [employee["id"], other["id"]],
        },
    ).json()
    sent = client.post(
        f"/api/v1/channels/{channel['id']}/messages",
        json={"text": f"@{employee['name']} 请看一下版本差异", "attachment_ids": []},
    )
    assert sent.status_code == 200
    triggered = sent.json()["triggered"]
    assert [item["name"] for item in triggered] == ["星河"]
    assert triggered[0]["accepted"] is False
    messages = client.get(f"/api/v1/channels/{channel['id']}/messages").json()["messages"]
    assert [item["sender"] for item in messages] == ["user"]


def test_new_skills_are_rejected_when_catalog_is_unavailable(client):
    response = client.post("/api/v1/employees", json=employee_body(skills=["not-a-real-skill"]))
    assert response.status_code == 422
    assert "技能" in response.json()["detail"]


def test_new_knowledge_and_tools_are_rejected_when_catalog_is_unavailable(client):
    assert client.get("/api/v1/knowledge").json() == {"available": False, "items": []}
    assert client.get("/api/v1/tools").json() == {"available": False, "items": []}
    knowledge = client.post("/api/v1/employees", json=employee_body(knowledge=["自动化框架 Wiki"]))
    assert knowledge.status_code == 422
    assert "知识库" in knowledge.json()["detail"]
    tools = client.post("/api/v1/employees", json=employee_body(tools=["query_task"]))
    assert tools.status_code == 422
    assert "工具" in tools.json()["detail"]
    known_name = client.post("/api/v1/employees", json=employee_body(tools=["contact_employee"]))
    assert known_name.status_code == 422


def test_connected_catalog_accepts_only_returned_resources(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    application = create_app()
    chat_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"version": "2.0.10"})
        if request.url.path == "/agent/" and request.method == "POST":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"agent_id": f"agent-{body['name']}"})
        if request.method == "PATCH" and request.url.path.startswith("/agent/"):
            return httpx.Response(200, json={})
        if request.method == "DELETE" and request.url.path.startswith("/agent/"):
            return httpx.Response(204)
        if request.url.path == "/sessions/" and request.method == "POST":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"session_id": f"session-{body['name']}"})
        if request.url.path == "/skill":
            return httpx.Response(200, json=[{"id": "failure-analysis", "name": "失败分析"}])
        if request.url.path == "/knowledge_bases/":
            return httpx.Response(
                200,
                json={
                    "knowledge_bases": [{"id": "kb-1", "name": "自动化框架"}],
                    "total": 1,
                    "page": 1,
                    "page_size": 128,
                },
            )
        if request.url.path == "/chat/":
            body = json.loads(request.content.decode())
            chat_calls.append(body["agent_id"])
            return httpx.Response(200, json={"status": "started", "session_id": "session-chat"})
        return httpx.Response(404, json={"detail": "missing"})

    with TestClient(application) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        tools = test_client.get("/api/v1/tools").json()
        assert tools["available"] is True
        tool_ids = {item["id"] for item in tools["items"]}
        assert {"Bash", "contact_employee"} <= tool_ids
        assert "query_task" not in tool_ids
        assert "TeamSay" not in tool_ids
        knowledge = test_client.get("/api/v1/knowledge").json()
        assert knowledge == {"available": True, "items": [{"id": "kb-1", "name": "自动化框架"}]}

        rejected_knowledge = test_client.post(
            "/api/v1/employees",
            json=employee_body(knowledge=["自动化框架 Wiki"]),
        )
        assert rejected_knowledge.status_code == 422
        rejected_tool = test_client.post("/api/v1/employees", json=employee_body(tools=["query_task"]))
        assert rejected_tool.status_code == 422

        created = test_client.post(
            "/api/v1/employees",
            json=employee_body(
                knowledge=["kb-1"],
                skills=["failure-analysis"],
                tools=["contact_employee"],
            ),
        )
        assert created.status_code == 201, created.text
        employee = created.json()["employee"]
        assert employee["knowledge"] == ["kb-1"]
        assert employee["skills"] == ["failure-analysis"]
        assert employee["tools"] == ["contact_employee"]
        assert employee["agentscope_agent_id"] == "agent-星河"
        assert created.json()["agentscope"]["ok"] is True

        headers = {"X-Owner-Id": "browser-a"}
        conversation = test_client.post(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers=headers,
            json={},
        ).json()
        disabled = test_client.patch(
            f"/api/v1/employees/{employee['id']}",
            json=employee_body(
                enabled=False,
                knowledge=["kb-1"],
                skills=["failure-analysis"],
                tools=["contact_employee"],
            ),
        )
        assert disabled.json()["employee"]["enabled"] is False
        refused = test_client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"text": "禁用后不要运行"},
        )
        assert refused.status_code == 409
        assert chat_calls == []
        enabled = test_client.patch(
            f"/api/v1/employees/{employee['id']}",
            json=employee_body(
                enabled=True,
                knowledge=["kb-1"],
                skills=["failure-analysis"],
                tools=["contact_employee"],
            ),
        )
        assert enabled.json()["employee"]["enabled"] is True
        accepted = test_client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"text": "重新启用后再运行"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["agentscope"]["accepted"] is True
        assert chat_calls == ["agent-星河"]


def test_live_client_posts_chat_without_writing_a_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_AGENTSCOPE_BASE_URL", "")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/agent/":
            return httpx.Response(201, json={"agent_id": "agent-1"})
        if request.url.path == "/sessions/":
            return httpx.Response(201, json={"session_id": f"session-{len(seen)}"})
        if request.url.path == "/chat/":
            return httpx.Response(200, json={"status": "started", "session_id": "session-chat"})
        if request.url.path == "/skill":
            return httpx.Response(200, json=[{"id": "failure-analysis", "name": "失败分析"}])
        return httpx.Response(404, json={"detail": "missing"})

    application = create_app()
    with TestClient(application) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        created = test_client.post("/api/v1/employees", json=employee_body(skills=["failure-analysis"]))
        assert created.status_code == 201
        employee = created.json()["employee"]
        assert employee["agentscope_agent_id"] == "agent-1"
        assert employee["mailbox_session_id"]
        assert created.json()["agentscope"]["ok"] is True

        headers = {"X-Owner-Id": "browser-a"}
        conversation = test_client.post(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers=headers,
            json={"name": "新对话"},
        ).json()
        first = test_client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"text": "看一下失败日志"},
        )
        second = test_client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            headers=headers,
            json={"text": "再看一次"},
        )
        assert first.json()["agentscope"]["accepted"] is True
        assert second.json()["agentscope"]["accepted"] is True
        assert first.json()["agentscope"]["session_id"] == second.json()["agentscope"]["session_id"]
        chat_calls = [request for request in seen if request.url.path == "/chat/"]
        assert len(chat_calls) == 2
        payload = json.loads(chat_calls[0].content.decode())
        assert payload["agent_id"] == "agent-1"
        assert payload["input"]["role"] == "user"
        assert payload["input"]["content"] == [{"type": "text", "text": "看一下失败日志"}]
        assert chat_calls[0].headers["x-user-id"] == "nexus"
        session_calls = [request for request in seen if request.url.path == "/sessions/"]
        # 邮箱一次，私聊一次。第二条消息复用私聊 Session。
        assert len(session_calls) == 2
        stored = test_client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers).json()
        assert [item["sender"] for item in stored["messages"]] == ["user", "user"]


def test_mention_triggers_only_the_named_employee(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    application = create_app()
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"agent_id": f"agent-{body['name']}"})
        if request.url.path == "/sessions/":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"session_id": f"session-{body['name']}"})
        if request.url.path == "/chat/":
            calls.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"status": "started", "session_id": "ignored"})
        if request.url.path == "/skill":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    with TestClient(application) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        star = test_client.post("/api/v1/employees", json=employee_body()).json()["employee"]
        zhi = test_client.post(
            "/api/v1/employees",
            json=employee_body(name="知微", domain="防线运营人员"),
        ).json()["employee"]
        channel = test_client.post(
            "/api/v1/channels",
            json={"name": "版本交付协同", "description": "跨岗位", "member_ids": [star["id"], zhi["id"]]},
        ).json()
        response = test_client.post(
            f"/api/v1/channels/{channel['id']}/messages",
            json={"text": "@知微 看一下异常"},
        )
        assert response.status_code == 200
        assert [item["employee_id"] for item in response.json()["triggered"]] == [zhi["id"]]
        assert calls[0]["agent_id"] == zhi["agentscope_agent_id"]
        assert "代替" not in json.dumps(response.json(), ensure_ascii=False)


def test_peer_resolver_returns_mailbox_without_a_scripted_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    application = create_app()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"agent_id": f"agent-{body['name']}"})
        if request.url.path == "/sessions/":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"session_id": f"session-{body['agent_id']}-{body['name']}"})
        if request.url.path == "/skill":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    with TestClient(application) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        star = test_client.post("/api/v1/employees", json=employee_body()).json()["employee"]
        zhi = test_client.post(
            "/api/v1/employees",
            json=employee_body(name="知微", domain="防线运营人员"),
        ).json()["employee"]
        resolved = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": star["mailbox_session_id"], "name": "知微"},
        )
        assert resolved.status_code == 404
        headers = {"X-Owner-Id": "browser-a"}
        conversation = test_client.post(
            f"/api/v1/employees/{star['id']}/conversations",
            headers=headers,
            json={"name": "新对话"},
        ).json()
        test_client.app.state.agentscope.trigger_chat = _accept
        # 直接写入 session 绑定，模拟一次已被接受的私聊。
        from nexus_api.db import connect
        from nexus_api.main import db_path

        connection = connect(db_path())
        connection.execute(
            "UPDATE conversations SET agentscope_session_id = ? WHERE id = ?",
            ("session-private", conversation["id"]),
        )
        connection.commit()
        connection.close()
        resolved = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": "session-private", "name": "知微"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["agent_id"] == zhi["agentscope_agent_id"]
        assert resolved.json()["session_id"] == zhi["mailbox_session_id"]
        assert resolved.json()["sender_name"] == "星河"
        disabled = test_client.patch(
            f"/api/v1/employees/{zhi['id']}",
            json=employee_body(name="知微", domain="防线运营人员", enabled=False),
        )
        assert disabled.status_code == 200
        assert disabled.json()["employee"]["enabled"] is False
        blocked = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": "session-private", "name": "知微"},
        )
        assert blocked.status_code == 404
        assert "禁用" in blocked.json()["detail"]
        headers = {"X-Owner-Id": "browser-a"}
        peer_conversation = test_client.post(
            f"/api/v1/employees/{zhi['id']}/conversations",
            headers=headers,
            json={"name": "新对话"},
        ).json()
        refused = test_client.post(
            f"/api/v1/conversations/{peer_conversation['id']}/messages",
            headers=headers,
            json={"text": "禁用后不应开始运行"},
        )
        assert refused.status_code == 409


async def _accept(*_args, **_kwargs):
    return "session-private"


def test_stream_cursor_is_the_redis_checkpoint_not_an_event_id():
    assert stream_cursor("1710000000000-0") == "1710000000000-0"
    assert stream_cursor("7b674dd0149e4f19b8d5034b8437963b") is None
    assert stream_cursor(None) is None


def test_chat_model_config_is_forwarded_only_when_deploy_sets_it(monkeypatch):
    monkeypatch.delenv("NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG", raising=False)
    assert load_chat_model_config() is None
    monkeypatch.setenv("NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG", "{")
    with pytest.raises(RuntimeError):
        load_chat_model_config()

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"session_id": "session-model"})

    config = {
        "type": "ollama_credential",
        "credential_id": "cred-1",
        "model": "qwen2.5:3b",
        "parameters": {},
    }
    import asyncio

    client = AgentScopeClient(
        "http://agentscope.test",
        "nexus",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        chat_model_config=config,
    )
    assert asyncio.run(client.create_session("agent-1", "邮箱")) == "session-model"
    body = json.loads(seen[0].content.decode())
    assert body["chat_model_config"] == config
    assert "model" not in body


def test_launcher_parses_and_does_not_import_agentscope():
    source = (ROOT / "nexus/deploy/agent_service.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "import agentscope" not in source.split("def main")[0]
    assert "deliver_to_inbox" in source
    assert "IsolationPolicy.PER_SESSION" in source
    assert "TeamSay" not in source
    version = (ROOT / "nexus/deploy/agentscope.version").read_text(encoding="utf-8").strip()
    assert version == "agentscope==2.0.10"

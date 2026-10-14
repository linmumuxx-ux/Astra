"""Nexus API 骨架测试。不启动 AgentScope，也不生成模拟回复。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from nexus_api.agentscope import AgentScopeClient
from nexus_api.main import (
    assistant_replies_after,
    create_app,
    data_dir,
    load_chat_model_config,
    model_input_blocks,
    observe_stream_event,
    package_dir,
    repo_root,
    stream_cursor,
)

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


def test_model_input_includes_text_and_does_not_invent_binary_analysis():
    text = model_input_blocks("看日志", [("run.log", "text/plain", b"LOG-TOKEN-88")])
    assert any("LOG-TOKEN-88" in block.get("text", "") for block in text)
    binary = model_input_blocks("", [("数据.bin", "application/octet-stream", b"\x00\x01secret")])
    assert "不要描述它的内容" in binary[0]["text"]
    assert "secret" not in binary[0]["text"]
    assert "已解析" not in binary[0]["text"]


def test_owners_keep_separate_conversations_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_AGENTSCOPE_BASE_URL", "")
    owner_a = {"X-Owner-Id": "anon-a"}
    owner_b = {"X-Owner-Id": "anon-b"}
    application = create_app()
    with TestClient(application) as test_client:
        employee = test_client.post("/api/v1/employees", json=employee_body()).json()["employee"]
        first = test_client.post(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers=owner_a,
            json={"name": "新对话"},
        ).json()
        second = test_client.post(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers=owner_a,
            json={"name": "新对话"},
        ).json()
        assert first["id"] != second["id"]
        sent = test_client.post(
            f"/api/v1/conversations/{first['id']}/messages",
            headers=owner_a,
            json={"text": "只属于 a"},
        )
        assert sent.status_code == 200
        hidden = test_client.get(f"/api/v1/employees/{employee['id']}/conversations", headers=owner_b)
        assert hidden.json()["items"] == []
        missing = test_client.get(f"/api/v1/conversations/{first['id']}", headers=owner_b)
        assert missing.status_code == 404
    restarted = create_app()
    with TestClient(restarted) as again:
        listed = again.get(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers=owner_a,
        ).json()["items"]
        assert [item["id"] for item in listed] == [first["id"], second["id"]]
        restored = again.get(f"/api/v1/conversations/{first['id']}", headers=owner_a).json()
        assert [item["text"] for item in restored["messages"]] == ["只属于 a"]
        assert restored["messages"][0]["sender"] == "user"


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


def test_channel_peer_contact_creates_session_caps_and_keeps_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    application = create_app()
    calls: list[dict] = []
    replies: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"agent_id": f"agent-{body['name']}"})
        if request.url.path == "/sessions/":
            body = json.loads(request.content.decode())
            return httpx.Response(
                201,
                json={"session_id": f"session-{body['agent_id']}-{body['name']}"},
            )
        if request.url.path == "/chat/":
            calls.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"status": "started", "session_id": "ignored"})
        if request.method == "GET" and request.url.path.endswith("/messages"):
            session_id = request.url.path.split("/")[2]
            text = replies.get(session_id, "")
            messages = []
            if text:
                messages.append(
                    {
                        "id": f"m-{session_id}",
                        "role": "assistant",
                        "created_at": "2099-01-01T00:00:00+00:00",
                        "content": [{"type": "text", "text": text}],
                    }
                )
            return httpx.Response(200, json={"messages": messages, "has_more": False})
        if request.url.path == "/skill":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    with TestClient(application) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        ops = test_client.post(
            "/api/v1/employees",
            json=employee_body(name="运营", domain="运行保障", description="处理故障"),
        ).json()["employee"]
        eng = test_client.post(
            "/api/v1/employees",
            json=employee_body(name="自动化", domain="自动化工程", description="看自动化"),
        ).json()["employee"]
        tools = test_client.post(
            "/api/v1/employees",
            json=employee_body(name="工具", domain="工具工程", description="看工具"),
        ).json()["employee"]
        channel = test_client.post(
            "/api/v1/channels",
            json={
                "name": "故障协同",
                "description": "自动化失败",
                "member_ids": [ops["id"], eng["id"], tools["id"]],
            },
        ).json()
        uploaded = test_client.post(
            "/api/v1/attachments",
            files={"file": ("run.log", b"LOG-TOKEN-88", "text/plain")},
        )
        sent = test_client.post(
            f"/api/v1/channels/{channel['id']}/messages",
            json={"text": "@运营 自动化失败了", "attachment_ids": [uploaded.json()["id"]]},
        )
        assert sent.status_code == 200, sent.text
        assert [item["employee_id"] for item in sent.json()["triggered"]] == [ops["id"]]
        assert len(calls) == 1
        assert calls[0]["agent_id"] == ops["agentscope_agent_id"]
        assert any("LOG-TOKEN-88" in block.get("text", "") for block in calls[0]["input"]["content"])
        ops_session = sent.json()["triggered"][0]["session_id"]
        eng_session = f"session-{eng['agentscope_agent_id']}-故障协同"
        replies[eng_session] = "我是自动化工程师"
        opened = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": ops_session, "name": "自动化", "message": "自动化失败了"},
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["session_id"] == eng_session
        assert opened.json()["session_id"] != eng["mailbox_session_id"]
        assert opened.json()["sender_name"] == "运营"
        assert len(calls) == 1
        again = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": ops_session, "name": "自动化", "message": "自动化失败了"},
        )
        assert again.status_code == 409
        assert "同样的话" in again.json()["detail"]
        second = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": ops_session, "name": "工具", "message": "再看工具"},
        )
        assert second.status_code == 200, second.text
        assert second.json()["agent_id"] == tools["agentscope_agent_id"]
        blocked = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": ops_session, "name": "工具", "message": "第三句"},
        )
        assert blocked.status_code == 409
        assert "不要继续互相调用" in blocked.json()["detail"]
        hopped = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": eng_session, "name": "工具", "message": "需要工具侧看一下"},
        )
        assert hopped.status_code == 200, hopped.text
        assert hopped.json()["sender_name"] == "自动化"
        disabled = test_client.patch(
            f"/api/v1/employees/{tools['id']}",
            json=employee_body(name="工具", domain="工具工程", description="看工具", enabled=False),
        )
        assert disabled.status_code == 200
        refused = test_client.get(
            "/api/v1/peers/resolve",
            params={"session_id": eng_session, "name": "工具", "message": "工具已禁用"},
        )
        assert refused.status_code == 404
        assert "禁用" in refused.json()["detail"]
        transcript = test_client.get(f"/api/v1/channels/{channel['id']}/messages").json()
        senders = [item["sender"] for item in transcript["messages"]]
        assert senders[0] == "user"
        assert eng["id"] in senders
        spoken = next(item for item in transcript["messages"] if item["sender"] == eng["id"])
        assert spoken["text"] == "我是自动化工程师"
        assert ops["id"] != eng["id"]
        assert "已解析" not in json.dumps(transcript, ensure_ascii=False)
        from nexus_api.db import connect
        from nexus_api.main import db_path

        connection = connect(db_path())
        stored = connection.execute(
            "SELECT sender FROM messages WHERE channel_id = ?",
            (channel["id"],),
        ).fetchall()
        connection.close()
        assert [row["sender"] for row in stored] == ["user"]


def test_peer_hint_returns_limit_text_without_delivering():
    import asyncio
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "nexus_agent_service",
        ROOT / "nexus/deploy/agent_service.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen: dict[str, str] = {}

    class Response:
        status_code = 409

        def json(self):
            return {"detail": "已经把同样的话交给对方，不要再联系。"}

        def raise_for_status(self):
            raise AssertionError("不应抛出")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, params):
            seen.update(params)
            return Response()

    class Http:
        def AsyncClient(self, timeout):
            assert timeout == 20
            return Client()

    async def deliver(*_args, **_kwargs):
        raise AssertionError("达到上限时不应投递")

    result = asyncio.run(
        module.deliver_peer_hint(
            Http(),
            deliver,
            None,
            None,
            "http://nexus",
            "nexus",
            "agent-ops",
            "session-ops",
            "自动化",
            "自动化失败了",
        )
    )
    assert result == "已经把同样的话交给对方，不要再联系。"
    assert seen["message"] == "自动化失败了"
    assert seen["name"] == "自动化"


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
            params={"session_id": star["mailbox_session_id"], "name": "知微", "message": "先从邮箱联系"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["session_id"] == zhi["mailbox_session_id"]
        assert resolved.json()["sender_name"] == "星河"
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


def test_private_attachments_are_forwarded_and_session_replies_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    seen: list[dict] = []
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/" and request.method == "POST":
            return httpx.Response(201, json={"agent_id": "agent-1"})
        if request.url.path == "/sessions/" and request.method == "POST":
            return httpx.Response(201, json={"session_id": "session-chat"})
        if request.url.path == "/chat/":
            seen.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"status": "started", "session_id": "session-chat"})
        if request.url.path == "/sessions/session-chat/messages":
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {"id": "u1", "role": "user", "content": [{"type": "text", "text": "看日志"}]},
                        {
                            "id": "a1",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "模型自己的回复"}],
                        },
                    ],
                    "has_more": False,
                    "is_running": False,
                },
            )
        if request.url.path == "/skill":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "missing"})

    application = create_app()
    with TestClient(application) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        employee = test_client.post("/api/v1/employees", json=employee_body()).json()["employee"]
        headers = {"X-Owner-Id": "anon-a"}
        conversation = test_client.post(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers=headers,
            json={"name": "新对话"},
        ).json()
        log_file = test_client.post(
            "/api/v1/attachments",
            files={"file": ("run.log", b"LOG-TOKEN-88", "text/plain")},
        )
        image = test_client.post(
            "/api/v1/attachments",
            files={"file": ("shot.png", png, "image/png")},
        )
        assert log_file.status_code == 201
        assert image.status_code == 201
        downloaded = test_client.get(f"/api/v1/attachments/{log_file.json()['id']}")
        assert downloaded.status_code == 200
        assert downloaded.content == b"LOG-TOKEN-88"
        sent = test_client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            headers=headers,
            json={
                "text": "看日志",
                "attachment_ids": [log_file.json()["id"], image.json()["id"]],
            },
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["agentscope"]["accepted"] is True
        content = seen[0]["input"]["content"]
        logged = [
            block
            for block in content
            if block.get("type") == "text" and "LOG-TOKEN-88" in block.get("text", "")
        ]
        assert logged
        image_block = next(block for block in content if block.get("type") == "data")
        assert image_block["source"]["media_type"] == "image/png"
        assert image_block["source"]["type"] == "base64"
        restored = test_client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers).json()
        assert [item["sender"] for item in restored["messages"]] == ["user", employee["id"]]
        assert restored["messages"][1]["text"] == "模型自己的回复"
        assert restored["messages"][0]["attachments"][0]["name"] == "run.log"
        assert "已解析" not in json.dumps(restored, ensure_ascii=False)


def test_peer_toolkit_drops_team_and_task_tools_but_keeps_contact():
    import asyncio
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "nexus_agent_service_tools",
        ROOT / "nexus/deploy/agent_service.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Toolkit:
        def __init__(self) -> None:
            self.removed: list[str] = []

        async def remove_tool(self, names: list[str]) -> None:
            self.removed = list(names)

    async def original(**_kwargs):
        return Toolkit()

    toolkit = asyncio.run(module.without_team_and_task_tools(original)())
    assert "TeamCreate" in toolkit.removed
    assert "TaskGet" in toolkit.removed
    assert "ToolStop" in toolkit.removed
    assert "ScheduleCreate" in toolkit.removed
    assert "contact_employee" not in toolkit.removed


def test_launcher_parses_and_does_not_import_agentscope():
    source = (ROOT / "nexus/deploy/agent_service.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "import agentscope" not in source.split("def main")[0]
    assert "deliver_to_inbox" in source
    assert "IsolationPolicy.PER_SESSION" in source
    assert "without_team_and_task_tools" in source
    assert "TeamCreate(" not in source
    assert "TaskGet(" not in source
    version = (ROOT / "nexus/deploy/agentscope.version").read_text(encoding="utf-8").strip()
    assert version == "agentscope==2.0.10"


def test_data_dir_does_not_follow_the_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEXUS_DATA_DIR", raising=False)
    assert data_dir() == package_dir() / "data"
    monkeypatch.setenv("NEXUS_DATA_DIR", "nexus/api/data")
    assert data_dir() == (repo_root() / "nexus/api/data").resolve()
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path / "absolute"))
    assert data_dir() == tmp_path / "absolute"


def test_private_stream_skips_the_saved_cursor_and_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    sse = (
        'data: {"type":"REPLY_START","id":"s1","reply_id":"r1"}\n\n'
        'data: {"type":"TEXT_BLOCK_DELTA","id":"d1","delta":"在"}\n\n'
        'data: {"type":"REPLY_END","id":"e1","reply_id":"r1","finished_reason":"completed"}\n\n'
        'data: {"type":"TEXT_BLOCK_DELTA","id":"late","delta":"不应再出现"}\n\n'
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/agent/" and request.method == "POST":
            return httpx.Response(201, json={"agent_id": "agent-1"})
        if request.url.path == "/sessions/" and request.method == "POST":
            return httpx.Response(201, json={"session_id": "session-chat"})
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        if request.url.path == "/sessions/session-chat/messages":
            return httpx.Response(
                200,
                json={"messages": [], "event_cursor": "20-1", "has_more": False},
            )
        if request.url.path == "/sessions/session-chat/stream":
            return httpx.Response(200, content=sse.encode())
        if request.url.path == "/skill":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "missing"})

    application = create_app()
    with TestClient(application) as test_client:
        test_client.app.state.agentscope = AgentScopeClient(
            "http://agentscope.test",
            "nexus",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agentscope.test"),
        )
        employee = test_client.post("/api/v1/employees", json=employee_body()).json()["employee"]
        headers = {"X-Owner-Id": "browser-a"}
        conversation = test_client.post(
            f"/api/v1/employees/{employee['id']}/conversations",
            headers=headers,
            json={"name": "新对话"},
        ).json()
        from nexus_api.db import connect

        connection = connect(tmp_path / "nexus.sqlite3")
        connection.execute(
            "UPDATE conversations SET agentscope_session_id = ? WHERE id = ?",
            ("session-chat", conversation["id"]),
        )
        connection.commit()
        connection.close()
        with test_client.stream(
            "GET",
            f"/api/v1/conversations/{conversation['id']}/stream",
            headers=headers,
        ) as response:
            assert response.status_code == 200
            body = response.read().decode()
    assert "NEXUS_RUN_FINISHED" in body
    assert "不应再出现" not in body
    streamed = [item for item in seen if item.url.path == "/sessions/session-chat/stream"]
    assert streamed[0].url.params["after"] == "20-1"


def test_stream_closes_when_the_started_reply_ends():
    started = 0
    events = [
        {"type": "REPLY_END", "reply_id": "old"},
        {"type": "REPLY_START", "reply_id": "new"},
        {"type": "TEXT_BLOCK_DELTA", "delta": "在"},
        {"type": "REPLY_END", "reply_id": "new", "finished_reason": "completed"},
        {"type": "TEXT_BLOCK_DELTA", "delta": "不应再出现"},
    ]
    closed_at = None
    terminals = []
    for index, event in enumerate(events):
        started, terminal, close = observe_stream_event(started, event)
        if terminal:
            terminals.append(terminal)
        if close:
            closed_at = index
            break
    assert closed_at == 3
    assert terminals == [
        {
            "type": "NEXUS_RUN_FINISHED",
            "reply_id": "new",
            "finished_reason": "completed",
        }
    ]


def test_mailbox_hop_is_scoped_to_the_conversation_and_reply_is_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    patched: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" and request.url.path.startswith("/sessions/"):
            patched.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={})
        if request.url.path == "/agent/" and request.method == "POST":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"agent_id": f"agent-{body['name']}"})
        if request.url.path == "/sessions/" and request.method == "POST":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"session_id": f"session-{body['agent_id']}"})
        if request.url.path == "/sessions/session-agent-知微/messages":
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {"role": "user", "content": [{"type": "text", "text": "方案要点"}]},
                        {"role": "assistant", "content": [{"type": "text", "text": "阈值按账号计算"}]},
                    ],
                    "has_more": False,
                },
            )
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [], "has_more": False})
        if request.url.path == "/skill":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "missing"})

    application = create_app()
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
        wang = test_client.post(
            "/api/v1/employees",
            json=employee_body(name="王五", domain="测试工程师"),
        ).json()["employee"]
        assert patched
        assert patched[0]["permission_mode"] == "dont_ask"
        headers = {"X-Owner-Id": "browser-a"}
        first = test_client.post(
            f"/api/v1/employees/{star['id']}/conversations",
            headers=headers,
            json={"name": "第一条"},
        ).json()
        second = test_client.post(
            f"/api/v1/employees/{star['id']}/conversations",
            headers=headers,
            json={"name": "第二条"},
        ).json()
        from nexus_api.db import connect

        connection = connect(tmp_path / "nexus.sqlite3")
        connection.execute(
            "UPDATE conversations SET agentscope_session_id = ? WHERE id = ?",
            ("session-private", first["id"]),
        )
        connection.execute(
            "UPDATE conversations SET agentscope_session_id = ? WHERE id = ?",
            ("session-other", second["id"]),
        )
        connection.commit()
        connection.close()

        def resolve(session_id: str, name: str, message: str):
            return test_client.get(
                "/api/v1/peers/resolve",
                params={"session_id": session_id, "name": name, "message": message},
            )

        assert resolve("session-private", "知微", "方案要点").status_code == 200
        assert resolve("session-private", "知微", "再补充一点").status_code == 200
        blocked = resolve("session-private", "知微", "第三次不该成功")
        assert blocked.status_code == 409
        forwarded = resolve(zhi["mailbox_session_id"], "王五", "请看测试要点")
        assert forwarded.status_code == 200
        assert forwarded.json()["session_id"] == wang["mailbox_session_id"]
        assert forwarded.json()["sender_name"] == "知微"
        back = resolve(wang["mailbox_session_id"], "星河", "测试要点如下")
        assert back.status_code == 200
        assert back.json()["session_id"] == star["mailbox_session_id"]
        again = resolve(star["mailbox_session_id"], "知微", "邮箱里的第三次")
        assert again.status_code == 409
        other = resolve("session-other", "知微", "另一条对话还可以联系")
        assert other.status_code == 200

        stored = test_client.get(f"/api/v1/conversations/{first['id']}", headers=headers).json()
        peer_lines = [item for item in stored["messages"] if item["sender"] == zhi["id"]]
        assert [item["text"] for item in peer_lines] == ["阈值按账号计算"]
        assert assistant_replies_after(
            [{"role": "user", "content": [{"type": "text", "text": "方案要点"}]}],
            "方案要点",
        ) == []

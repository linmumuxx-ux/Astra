import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agents.tools import CredentialVerifier, build_tools
from domains.core import new_id
from domains.database import Database
from domains.identity.models import Actor
from domains.identity.service import issue_credential

from . import test_domains
from .http_server import serve_http
from .test_domains import setup_team

api = test_domains.api


async def test_mcp_uses_actual_principal_and_revocation(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/tools.db")
    await db.create_for_tests()
    async with db.sessions() as session:
        actor = Actor(id=new_id(), name="独立员工身份", kind="SYSTEM", permissions=["event.ingest"])
        session.add(actor)
        await session.flush()
        token = await issue_credential(session, actor)
        await session.commit()
        verifier = CredentialVerifier(db)
        access = await verifier.verify_token(token)
        assert access.subject == actor.id and access.client_id == actor.id
        assert access.token == token
        assert await verifier.verify_token("forged") is None
        actor.active = False
        await session.commit()
        assert await verifier.verify_token(token) is None
    await db.engine.dispose()


async def test_real_mcp_http_forwards_identity_authorization_and_idempotency(api, tmp_path, monkeypatch):
    app, client, admin_id = api
    team, _, employees = await setup_team(client)
    authorization = client.headers["Authorization"]
    monkeypatch.setenv("ASTRA_V1_MEMORY_ROOT", str(tmp_path / "memory"))
    async with serve_http(app) as api_url:
        server = build_tools(app.state.db, api_url=api_url, resource_url="http://127.0.0.1/mcp")
        mcp_app = server.streamable_http_app(stateless_http=True, json_response=True)
        async with serve_http(mcp_app) as mcp_url:
            async with httpx2.AsyncClient(headers={"Authorization": authorization}) as transport:
                async with streamable_http_client(f"{mcp_url}/mcp", http_client=transport) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        context = await session.call_tool("astra_context_get", {})
                        assert not context.is_error and context.structured_content["id"] == admin_id
                        payload = {
                            "team_id": team["id"],
                            "owner_employee_id": employees[0]["id"],
                            "title": "真实 MCP 业务调用",
                            "objective": "验证认证到 API 的完整链路",
                            "acceptance_criteria": ["重复调用保持同一业务任务"],
                        }
                        one = await session.call_tool(
                            "astra_task_create",
                            {
                                "payload": payload,
                                "operation_key": "mcp-stable-operation",
                            },
                        )
                        assert not one.is_error, one
                        two = await session.call_tool(
                            "astra_task_create",
                            {
                                "payload": payload,
                                "operation_key": "mcp-stable-operation",
                            },
                        )
                        assert one.structured_content["id"] == two.structured_content["id"]
                        assert one.structured_content["created_by_actor"] == admin_id
                        forged = await session.call_tool(
                            "astra_task_create",
                            {
                                "payload": {**payload, "actor_id": employees[1]["id"]},
                                "operation_key": "spoofing-rejected",
                            },
                        )
                        assert forged.is_error
                        memory = await session.call_tool(
                            "astra_memory_write",
                            {
                                "employee_id": employees[0]["id"],
                                "operation_key": "mcp-memory-version",
                                "payload": {
                                    "expected_head": None,
                                    "content": "已确认的工作引用",
                                    "source_refs": [f"tasks/{one.structured_content['id']}"],
                                    "reason": "记录 MCP 验证来源",
                                },
                            },
                        )
                        assert not memory.is_error, memory
                        saved = await session.call_tool(
                            "astra_memory_read", {"employee_id": employees[0]["id"]}
                        )
                        assert (
                            not saved.is_error and saved.structured_content["content"] == "已确认的工作引用"
                        )
            async with httpx2.AsyncClient() as anonymous:
                response = await anonymous.post(f"{mcp_url}/mcp", json={})
                assert response.status_code == 401
    assert len((await client.get("/api/v1/tasks")).json()) == 1


async def test_mcp_registered_tools_never_accept_actor_or_user_id():
    db = Database("sqlite+aiosqlite:///:memory:")
    server = build_tools(db, api_url="http://127.0.0.1:8200", resource_url="http://127.0.0.1:8203/mcp")
    tools = await server.list_tools()
    assert len(tools) == 11
    for tool in tools:
        assert tool.name.startswith("astra_")
        assert not {"actor", "actor_id", "user_id", "employee_identity"} & set(
            tool.input_schema.get("properties", {})
        )
    with pytest.raises(ValueError):
        build_tools(db, api_url="http://admin:secret@host/", resource_url="http://127.0.0.1:8203/mcp")
    await db.engine.dispose()

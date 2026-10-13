"""HTTP/SSE 契约模拟；不冒充真实模型或公司环境验收。"""

import copy
import json
from dataclasses import replace

import httpx
import pytest

from domains.runtime import NativeSessionBinding, OpenCodeClient, OpenCodeConfig, RuntimePurpose
from domains.runtime.errors import (
    NativeSessionNotFound,
    NativeSessionScopeError,
    OpenCodeEventStreamInterrupted,
    OpenCodeIncompatible,
    OpenCodeUnavailable,
)

pytestmark = pytest.mark.asyncio


def native_contract():
    paths = {
        "/global/health": {"get": {}},
        "/event": {"get": {}},
        "/session/status": {"get": {}},
        "/session/{sessionID}": {"get": {}},
        "/session/{sessionID}/message": {"get": {}},
        "/session/{sessionID}/children": {"get": {}},
        "/session/{sessionID}/prompt_async": {"post": {}},
        "/session/{sessionID}/abort": {"post": {}},
        "/question": {"get": {}},
        "/question/{requestID}/reply": {"post": {}},
        "/permission": {"get": {}},
        "/permission/{requestID}/reply": {"post": {}},
    }
    paths["/session"] = {
        "post": {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "properties": {"title": {}, "metadata": {}, "permission": {}},
                        }
                    }
                }
            }
        }
    }
    return {"openapi": "3.1.0", "paths": paths}


class NativeRuntime:
    def __init__(self):
        self.contract = native_contract()
        self.version = "1.19.0"
        self.calls = []
        self.sessions = {}
        self.statuses = {}
        self.questions = []
        self.permissions = []
        self.prompt_disconnect = False
        self.events = ""

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": self.version})
        if path == "/doc":
            return httpx.Response(200, json=self.contract)
        if path == "/session" and request.method == "POST":
            body = json.loads(request.content)
            native = {
                **body,
                "id": "ses_" + str(len(self.sessions) + 1),
                "directory": request.url.params["directory"],
            }
            self.sessions[native["id"]] = native
            return httpx.Response(200, json=native)
        if path == "/session/status":
            return httpx.Response(200, json=self.statuses)
        if path == "/question":
            return httpx.Response(200, json=self.questions)
        if path == "/permission":
            return httpx.Response(200, json=self.permissions)
        if path.startswith(("/question/", "/permission/")):
            return httpx.Response(200, json=True)
        if path == "/event":
            return httpx.Response(200, content=self.events, headers={"content-type": "text/event-stream"})
        session_id = path.split("/")[2]
        native = self.sessions.get(session_id)
        if not native:
            return httpx.Response(404)
        if path.endswith("/children"):
            return httpx.Response(
                200, json=[s for s in self.sessions.values() if s.get("parentID") == session_id]
            )
        if path.endswith("/prompt_async"):
            if self.prompt_disconnect:
                raise httpx.ReadTimeout("sensitive body must not reach errors", request=request)
            return httpx.Response(204)
        if path.endswith("/message"):
            return httpx.Response(
                200,
                json=[{"info": {"id": "msg_native"}, "parts": []}],
                headers={"x-next-cursor": "msg_older"},
            )
        if path.endswith("/abort"):
            return httpx.Response(200, json=True)
        return httpx.Response(200, json=native)


@pytest.fixture
def runtime():
    return NativeRuntime()


def client(runtime, *, purpose=RuntimePurpose.TASK, **kwargs):
    config = OpenCodeConfig(
        "http://runtime.invalid",
        "worker-1",
        purpose,
        ("/workspaces" if purpose is RuntimePurpose.TASK else "/persona",),
        **kwargs,
    )
    return OpenCodeClient(config, transport=httpx.MockTransport(runtime))


async def task_session(runtime, **kwargs):
    api = client(runtime, **kwargs)
    binding = await api.create_session(
        "/workspaces/task/execution",
        owner_ref="execution-1",
        title="真实业务索引",
        permission_rules=[{"permission": "*", "pattern": "*", "action": "ask"}],
    )
    return api, binding


async def test_native_contract_model_auth_and_prompt_identity(runtime):
    api, binding = await task_session(runtime, model="provider/model", password="private-value")
    await api.prompt_async(binding, text="测试指令", message_id="msg_operation1")
    created = next(call for call in runtime.calls if call.url.path == "/session")
    prompt = runtime.calls[-1]
    assert json.loads(created.content)["model"] == {"providerID": "provider", "id": "model"}
    assert json.loads(prompt.content)["model"] == {"providerID": "provider", "modelID": "model"}
    assert json.loads(prompt.content)["messageID"] == "msg_operation1"
    assert created.headers["authorization"].startswith("Basic ")
    assert "private-value" not in repr(api.config)
    assert binding.native_session_id == "ses_1"
    assert await api.abort(binding) is True


@pytest.mark.parametrize("version", ["1.2.27", "1.18.36", "unknown", None])
async def test_unknown_or_unapproved_version_fails_before_session_creation(runtime, version):
    runtime.version = version
    with pytest.raises(OpenCodeIncompatible):
        await task_session(runtime)
    assert not runtime.sessions


async def test_health_alone_does_not_accept_missing_permission_contract(runtime):
    del runtime.contract["paths"]["/session"]["post"]["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ]["permission"]
    with pytest.raises(OpenCodeIncompatible):
        await task_session(runtime)
    assert not runtime.sessions


async def test_persona_has_dedicated_directory_and_deny_all_permission_boundary(runtime):
    api = client(
        runtime, purpose=RuntimePurpose.PERSONA, persona_tools=("astra_context_get", "astra_channel_send")
    )
    binding = await api.create_session("/persona", owner_ref="turn-1", title="员工决策")
    native = runtime.sessions[binding.native_session_id]
    assert native["permission"][0] == {"permission": "*", "pattern": "*", "action": "deny"}
    assert {r["permission"] for r in native["permission"][1:]} == {"astra_context_get", "astra_channel_send"}
    with pytest.raises(ValueError):
        await api.create_session("/persona/project", owner_ref="turn-2", title="越界")
    with pytest.raises(NativeSessionScopeError):
        await client(runtime).session(binding)
    with pytest.raises(NativeSessionScopeError):
        await api.reply_permission(binding, "permission1", approved_once=True)


async def test_task_does_not_inherit_implicit_default_permissions(runtime):
    api = client(runtime)
    with pytest.raises(ValueError):
        await api.create_session("/workspaces/a", owner_ref="execution-1", title="无授权")
    with pytest.raises(ValueError):
        await api.create_session(
            "/workspaces/a", owner_ref="execution-1", title="空授权", permission_rules=[]
        )
    assert not runtime.sessions


async def test_session_binding_checks_owner_directory_and_runtime_before_prompt(runtime):
    api, binding = await task_session(runtime)
    foreign = replace(binding, owner_ref="execution-other")
    with pytest.raises(NativeSessionScopeError):
        await api.prompt_async(foreign, text="不可执行", message_id="msg_foreign")
    runtime.sessions[binding.native_session_id]["directory"] = "/workspaces/other"
    with pytest.raises(NativeSessionScopeError):
        await api.messages(binding)
    assert not any(call.url.path.endswith("/prompt_async") for call in runtime.calls)


async def test_persona_permission_drift_prevents_following_prompt(runtime):
    api = client(runtime, purpose=RuntimePurpose.PERSONA)
    binding = await api.create_session("/persona", owner_ref="turn-1", title="员工决策")
    runtime.sessions[binding.native_session_id]["permission"][0]["action"] = "allow"
    with pytest.raises(NativeSessionScopeError):
        await api.prompt_async(binding, text="不可执行", message_id="msg_drift")


async def test_task_permission_drift_and_unbound_snapshot_prevent_execution(runtime):
    api, binding = await task_session(runtime)
    with pytest.raises(NativeSessionScopeError):
        await api.prompt_async(
            replace(binding, permission_digest=None), text="不可执行", message_id="msg_unbound"
        )
    runtime.sessions[binding.native_session_id]["permission"][0]["action"] = "allow"
    with pytest.raises(NativeSessionScopeError):
        await api.prompt_async(binding, text="不可扩权", message_id="msg_drift")


async def test_mutation_disconnect_is_unknown_outcome_without_retry_or_transcript_copy(runtime):
    api, binding = await task_session(runtime)
    runtime.prompt_disconnect = True
    with pytest.raises(OpenCodeUnavailable) as error:
        await api.prompt_async(binding, text="副作用可能已启动", message_id="msg_stable")
    assert error.value.outcome_uncertain
    assert "sensitive body" not in str(error.value)
    assert len([call for call in runtime.calls if call.url.path.endswith("/prompt_async")]) == 1
    page = await api.messages(binding, limit=5, before="msg_previous")
    assert page == {"messages": [{"info": {"id": "msg_native"}, "parts": []}], "next_before": "msg_older"}
    assert runtime.calls[-1].url.params["before"] == "msg_previous"


async def test_missing_native_session_is_never_converted_to_idle_or_task_success(runtime):
    api, binding = await task_session(runtime)
    runtime.sessions.clear()
    with pytest.raises(NativeSessionNotFound):
        await api.status(binding)
    assert not any(call.url.path == "/session/status" for call in runtime.calls)


async def test_sse_filters_other_tasks_deduplicates_and_admits_native_child(runtime):
    api, binding = await task_session(runtime)
    events = [
        {"id": "evt_other", "type": "session.idle", "properties": {"sessionID": "ses_other"}},
        {
            "id": "evt_child",
            "type": "session.created",
            "properties": {"info": {"id": "ses_child", "parentID": binding.native_session_id}},
        },
        {
            "id": "evt_delta",
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_child", "delta": "输出"},
        },
        {
            "id": "evt_delta",
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_child", "delta": "输出"},
        },
        {"id": "evt_idle", "type": "session.idle", "properties": {"sessionID": binding.native_session_id}},
    ]
    runtime.events = ": heartbeat\n\n" + "".join("data:" + json.dumps(item) + "\n\n" for item in events)
    observed = []
    with pytest.raises(OpenCodeEventStreamInterrupted):
        async for event in api.events(binding):
            observed.append(event)
    assert [item["id"] for item in observed] == ["evt_child", "evt_delta", "evt_idle"]
    assert observed[-1]["type"] == "session.idle"  # 仍然是原生事实，未产生成功判定。


async def test_interventions_are_scoped_and_only_once_grants_are_sent(runtime):
    api, binding = await task_session(runtime)
    runtime.permissions = [
        {"id": "perm_other", "sessionID": "ses_other"},
        {"id": "perm_mine", "sessionID": binding.native_session_id},
    ]
    with pytest.raises(NativeSessionScopeError):
        await api.reply_permission(binding, "perm_other", approved_once=True)
    assert await api.reply_permission(binding, "perm_mine", approved_once=True)
    assert json.loads(runtime.calls[-1].content) == {"reply": "once"}
    before = copy.deepcopy(runtime.sessions[binding.native_session_id])
    assert runtime.sessions[binding.native_session_id] == before


async def test_windows_runtime_paths_are_not_resolved_on_the_api_host():
    config = OpenCodeConfig(
        "http://runtime.invalid", "worker-windows", RuntimePurpose.TASK, ("C:/astra/workspaces",)
    )
    assert config.require_directory("C:\\astra\\workspaces\\task1") == "C:/astra/workspaces/task1"
    with pytest.raises(ValueError):
        config.require_directory("C:/astra/workspaces/../secrets")
    with pytest.raises(ValueError):
        config.require_directory("C:/astra/workspaces-other/task1")


async def test_historical_session_read_does_not_forge_new_employee_identity(runtime):
    runtime.sessions["ses_historical"] = {"id": "ses_historical", "directory": "/workspaces/history"}
    api = client(runtime)
    native = await api.native_session("/workspaces/history", "ses_historical")
    assert "metadata" not in native
    with pytest.raises(NativeSessionScopeError):
        await api.session(
            NativeSessionBinding(
                "ses_historical", "worker-1", RuntimePurpose.TASK, "execution-new", "/workspaces/history"
            )
        )

"""Secret redaction for Workspace SSE, lists, field names, and error bodies."""

import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.api.workspace_routes import (
    load_proxy_secrets,
    native_events,
    redact_secret_fields,
    redact_upstream_body,
)

AUTH = "canary-authorization-value"
XAPI = "canary-x-api-key-value"
APIKEY = "canary-options-api-key-value"
NESTED = "canary-nested-secret-value"
XAUTH = "canary-x-auth-token-value"
XGOOG = "canary-x-goog-api-key-value"
ACCESS = "canary-access-token-value"
REFRESH = "canary-refresh-token-value"
CLIENT = "canary-client-secret-value"
COOKIE = "canary-session-cookie-value"
PASSWORD = "canary-db-password-value"
VALUE = "canary-remote-config-value"
FIELD_CANARIES = (AUTH, XAPI, APIKEY, NESTED, XAUTH, XGOOG, ACCESS, REFRESH, CLIENT, COOKIE, PASSWORD)


def _tool_event() -> dict:
    return {
        "id": "evt_tool",
        "type": "message.part.updated",
        "properties": {
            "sessionID": "ses",
            "part": {
                "id": "prt_tool",
                "sessionID": "ses",
                "messageID": "msg_1",
                "type": "tool",
                "callID": "call_1",
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {
                        "command": "pwd",
                        "request": {
                            "headers": {
                                "authorization": AUTH,
                                "x-api-key": XAPI,
                                "x-auth-token": XAUTH,
                                "x-goog-api-key": XGOOG,
                                "accept": "application/json",
                            },
                            "body": {"options": {"apiKey": APIKEY}, "model": "keep-model"},
                        },
                        "nested": {"one": {"two": {"secret": NESTED, "name": "kept"}}},
                        "access_token": ACCESS,
                        "refresh-token": REFRESH,
                        "client_secret": CLIENT,
                        "session_cookie": COOKIE,
                        "db_password": PASSWORD,
                        "copied": VALUE,
                        "args": ["keep-arg", VALUE, ["inner", VALUE]],
                        "tokens": {
                            "input": 12,
                            "output": 3,
                            "reasoning": 1,
                            "cache": {"read": 2, "write": 4},
                        },
                        "input_tokens": 12,
                        "output_tokens": 3,
                        "total_tokens": 15,
                        "prompt_tokens": 12,
                        "cache_read_tokens": 2,
                        "setCacheKey": True,
                        "authorizationUrl": "https://example.test/oauth",
                    },
                    "output": "ok",
                    "title": "Run pwd",
                    "metadata": {},
                    "time": {"start": 1, "end": 2},
                },
            },
            "time": 3,
        },
    }


def _usage_event() -> dict:
    return {
        "id": "evt_usage",
        "type": "message.updated",
        "properties": {
            "sessionID": "ses",
            "info": {
                "id": "msg_1",
                "sessionID": "ses",
                "role": "assistant",
                "cost": 0.01,
                "tokens": {
                    "input": 12,
                    "output": 3,
                    "reasoning": 1,
                    "cache": {"read": 2, "write": 4},
                },
                "input_tokens": 12,
                "output_tokens": 3,
            },
        },
    }


class _RemoteClient:
    def __init__(self, events):
        self._events = events
        self.config_reads = 0

    async def children(self, *_args, **_kwargs):
        return []

    async def events(self, _directory):
        for event in self._events:
            yield copy.deepcopy(event)

    async def exchange(self, method, path, *, params=None, body=None, session_id=None, task_id=None):
        assert method == "GET"
        assert params["directory"] == "/srv/worker/task"
        self.config_reads += 1
        if path == "/config":
            payload = {"provider": {"astra-gateway": {"options": {"apiKey": VALUE}}}}
            return 200, json.dumps(payload).encode(), {"content-type": "application/json"}
        return 404, b"{}", {}


def _unwrap(chunk: str, global_stream: bool) -> dict:
    assert chunk.startswith("data: ")
    payload = json.loads(chunk.removeprefix("data: ").strip())
    return payload["payload"] if global_stream else payload


@pytest.mark.asyncio
@pytest.mark.parametrize("global_stream", [False, True])
async def test_sse_redacts_tool_part_canaries_on_both_event_modes(monkeypatch, global_stream):
    client = _RemoteClient([_tool_event(), _usage_event()])
    environment = SimpleNamespace(mode="LINUX_REMOTE", id=7, worker_channel="worker")

    @asynccontextmanager
    async def fake_connect(*_args, **_kwargs):
        yield client

    monkeypatch.setattr("app.api.workspace_routes.connect", fake_connect)
    chunks = [
        chunk
        async for chunk in native_events(environment, "/srv/worker/task", "ses", global_stream)
    ]
    assert client.config_reads >= 1
    raw = "".join(chunks)
    for canary in (*FIELD_CANARIES, VALUE):
        assert canary not in raw
    tool = _unwrap(chunks[0], global_stream)
    usage = _unwrap(chunks[1], global_stream)
    assert tool["type"] == "message.part.updated"
    state_input = tool["properties"]["part"]["state"]["input"]
    assert state_input["command"] == "pwd"
    assert state_input["request"]["headers"] == {"accept": "application/json"}
    assert state_input["request"]["body"] == {"options": {}, "model": "keep-model"}
    assert state_input["nested"] == {"one": {"two": {"name": "kept"}}}
    assert state_input["args"] == ["keep-arg", ["inner"]]
    assert state_input["tokens"] == {
        "input": 12,
        "output": 3,
        "reasoning": 1,
        "cache": {"read": 2, "write": 4},
    }
    assert state_input["input_tokens"] == 12
    assert state_input["output_tokens"] == 3
    assert state_input["total_tokens"] == 15
    assert state_input["prompt_tokens"] == 12
    assert state_input["cache_read_tokens"] == 2
    assert state_input["setCacheKey"] is True
    assert state_input["authorizationUrl"] == "https://example.test/oauth"
    assert "copied" not in state_input
    info = usage["properties"]["info"]
    assert info["tokens"]["input"] == 12
    assert info["tokens"]["output"] == 3
    assert info["input_tokens"] == 12
    assert info["output_tokens"] == 3
    assert info["cost"] == 0.01
    if global_stream:
        wrapped = json.loads(chunks[0].removeprefix("data: ").strip())
        assert wrapped["directory"] == "/srv/worker/task"


def test_list_elements_equal_to_a_configured_secret_are_removed():
    secret = "configured-list-canary-value"
    payload = {
        "items": ["keep", secret, ["nested-keep", secret, {"token": "field-token-canary-value"}]],
        "note": "plain",
    }
    redact_secret_fields(payload, {secret})
    assert payload["items"] == ["keep", ["nested-keep", {}]]
    assert payload["note"] == "plain"
    assert secret not in json.dumps(payload)


def test_new_secret_field_names_redact_without_dropping_token_counts():
    payload = {
        "X-Auth-Token": XAUTH,
        "X-Goog-Api-Key": XGOOG,
        "access_token": ACCESS,
        "refresh_token": REFRESH,
        "client_secret": CLIENT,
        "Cookie": COOKIE,
        "dbPassword": PASSWORD,
        "authorization": AUTH,
        "apiKey": APIKEY,
        "tokens": {"input": 4, "output": 5, "reasoning": 0, "cache": {"read": 1, "write": 1}},
        "input_tokens": 4,
        "output_tokens": 5,
        "inputTokens": 9,
        "maxTokens": 100,
        "token_count": 6,
        "setCacheKey": False,
        "authorizationUrl": "https://example.test/oauth",
        "title": "kept",
    }
    redact_secret_fields(payload)
    rendered = json.dumps(payload)
    for canary in (XAUTH, XGOOG, ACCESS, REFRESH, CLIENT, COOKIE, PASSWORD, AUTH, APIKEY):
        assert canary not in rendered
    assert payload["tokens"]["input"] == 4
    assert payload["input_tokens"] == 4
    assert payload["output_tokens"] == 5
    assert payload["inputTokens"] == 9
    assert payload["maxTokens"] == 100
    assert payload["token_count"] == 6
    assert payload["setCacheKey"] is False
    assert payload["authorizationUrl"] == "https://example.test/oauth"
    assert payload["title"] == "kept"


def test_error_json_and_text_bodies_drop_secret_fields_and_values():
    secret = "configured-error-canary-value"
    body = {
        "error": {
            "apiKey": "err-field-api-key-canary",
            "nested": [
                {"token": "err-field-token-canary", "message": "kept"},
                secret,
            ],
            "detail": "failed",
        }
    }
    rendered = redact_upstream_body(json.dumps(body).encode(), {secret})
    parsed = json.loads(rendered)
    assert parsed == {
        "error": {
            "nested": [{"message": "kept"}],
            "detail": "failed",
        }
    }
    text = redact_upstream_body(f"upstream failed {secret} now".encode(), {secret})
    assert secret.encode() not in text
    assert text == b"upstream failed [redacted] now"
    untouched = redact_upstream_body(b'{"error":"missing"}', set())
    assert untouched == b'{"error":"missing"}'


@pytest.mark.asyncio
async def test_remote_workspace_loads_secret_values_through_the_connected_client():
    secret = "platform-config-canary-value"
    environment = SimpleNamespace(mode="LINUX_REMOTE", id=3, worker_channel="worker")

    class Client:
        async def exchange(self, method, path, *, params=None, body=None, session_id=None, task_id=None):
            if path == "/config":
                payload = {
                    "mcp": {"nexus-library": {"headers": {"Authorization": f"Bearer {secret}"}}},
                    "provider": {"astra-gateway": {"options": {"apiKey": secret, "baseURL": "http://127.0.0.1"}}},
                }
                return 200, json.dumps(payload).encode(), {}
            return 404, b"", {}

    found = await load_proxy_secrets("/srv/worker/task", environment, Client())
    assert secret in found
    payload = {"copied": secret, "baseURL": "http://127.0.0.1", "items": [secret, "keep"]}
    redact_secret_fields(payload, found)
    assert secret not in json.dumps(payload)
    assert payload == {"baseURL": "http://127.0.0.1", "items": ["keep"]}

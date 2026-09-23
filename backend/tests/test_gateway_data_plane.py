"""API 中转数据面测试：Mock Proxy 透明转发、鉴权、调度、租约、重试与日志。

用一个进程内 Mock Proxy（httpx.MockTransport）替代真实下游，用
``InMemoryRuntimeStore`` 替代 Redis。运行态实现的语义与 Redis 版本一致：并发
租约、周期用量、熔断与心跳。
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import SessionLocal, init_database
from app.gateway.config import (
    ConfigLoader,
    ConfigReconciler,
    GatewayConfigState,
    PublishedConfig,
)
from app.gateway.errors import (
    CLIENT_DISCONNECTED,
    NO_ELIGIBLE_NODE,
    POOL_SATURATED,
    QUOTA_EXCEEDED,
    RUNTIME_UNAVAILABLE,
)
from app.gateway.models import GatewayConfigVersion, GatewayKey, GatewayRequest, utcnow
from app.gateway.notifier import InMemoryConfigNotifier
from app.gateway.probe import ProbeOutcome
from app.gateway.proxy import GatewayProxy
from app.gateway.runtime import (
    REVOKED_KEYS_KEY,
    SCOPE_KEY,
    SCOPE_NODE,
    InMemoryRuntimeStore,
    RedisRuntimeStore,
    usage_buckets,
)
from app.gateway.scheduler import REASON_SCHEDULING
from app.gateway.security import CredentialCipher, gateway_key_digest
from app.gateway.server import GatewayDataPlane, RequestRecord, create_gateway_app
from app.models import Base

RAW_KEY = "agw_" + uuid4().hex
KEY_DIGEST = gateway_key_digest(RAW_KEY)
MODEL = "gpt-test"
POOL_ID = "gp_test"
NODE_A = "gn_a"
NODE_B = "gn_b"
DOWNSTREAM_KEY = "sk-downstream"

# 真实 Redis 才能验证 Lua 脚本本身；未提供该环境变量时相关用例显式 skip。
REDIS_URL = os.environ.get("ASTRA_TEST_REDIS_URL")


class FakeProbe:
    """进程内探测客户端：按需返回全部成功或全部失败，不发起真实网络。"""

    def __init__(self) -> None:
        self.success = True
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def probe(self, node, probe_types, api_key):
        self.calls.append((node.id, tuple(probe_types)))
        return [ProbeOutcome(probe_type, self.success, 1) for probe_type in probe_types]


@pytest.fixture(scope="module", autouse=True)
def _schema():
    asyncio.run(init_database())
    yield


class MockUpstream:
    """按 host 路由的 Mock Proxy，支持连接失败与 SSE。"""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail_hosts: set[str] = set()
        self.response_status = 200
        self.include_usage = True
        self.usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
        self.stream_chunks = [
            b'data: {"id":"c","choices":[{"delta":{"content":"he"}}]}\n\n',
            b'data: {"id":"c","choices":[{"delta":{"content":"llo"}}]}\n\n',
        ]
        self.stream_usage: dict[str, int] | None = {
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "total_tokens": 7,
        }

    def stream_bytes(self) -> list[bytes]:
        chunks = list(self.stream_chunks)
        if self.stream_usage is not None:
            tail = {"id": "c", "choices": [{"delta": {}}], "usage": self.stream_usage}
            chunks.append(f"data: {json.dumps(tail)}\n\n".encode())
        chunks.append(b"data: [DONE]\n\n")
        return chunks

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host in self.fail_hosts:
            raise httpx.ConnectError("connection refused", request=request)
        payload: dict[str, Any] = {}
        if request.content:
            try:
                payload = json.loads(request.content)
            except ValueError:
                payload = {}
        if payload.get("stream"):
            return httpx.Response(
                self.response_status,
                content=self._sse(),
                headers={"content-type": "text/event-stream"},
            )
        body: dict[str, Any] = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        if self.include_usage:
            body["usage"] = self.usage
        return httpx.Response(self.response_status, json=body)

    async def _sse(self):
        for chunk in self.stream_bytes():
            yield chunk


def _snapshot(
    *,
    nodes: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    keys: list[dict[str, Any]],
    pools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": "2026-09-23T00:00:00+00:00",
        "pools": pools
        if pools is not None
        else [{"id": POOL_ID, "name": "pool", "weight": 1, "enabled": True}],
        "nodes": nodes,
        "routes": routes,
        "keys": keys,
    }


def node_dict(
    node_id: str,
    *,
    host: str,
    cipher: CredentialCipher,
    models: tuple[str, ...] = (MODEL,),
    max_concurrency: int = 0,
    weight: int = 1,
    scheduling_state: str = "ACTIVE",
    health_state: str = "HEALTHY",
    hourly_token_limit: int | None = None,
    quota_policy: str = "STOP",
    auth_type: str = "BEARER",
    auth_header: str = "Authorization",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": node_id,
        "pool_id": POOL_ID,
        "base_url": f"http://{host}",
        "api_key_encrypted": cipher.encrypt(DOWNSTREAM_KEY),
        "auth_type": auth_type,
        "auth_header": auth_header,
        "connect_timeout_seconds": None,
        "request_timeout_seconds": None,
        "models": list(models),
        "weight": weight,
        "max_concurrency": max_concurrency,
        "hourly_token_limit": hourly_token_limit,
        "daily_token_limit": None,
        "quota_policy": quota_policy,
        "config_state": "ENABLED",
        "scheduling_state": scheduling_state,
        "health_state": health_state,
    }


def key_dict(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "gk_test",
        "name": "key",
        "key_prefix": RAW_KEY[:12],
        "key_digest": KEY_DIGEST,
        "owner_id": "owner-1",
        "allowed_models": [MODEL],
        "max_concurrency": 0,
        "hourly_token_limit": None,
        "daily_token_limit": None,
        "enabled": True,
        "expires_at": None,
        "revoked_at": None,
    }
    base.update(overrides)
    return base


def build_config(
    cipher: CredentialCipher,
    *,
    nodes: list[dict[str, Any]] | None = None,
    key: dict[str, Any] | None = None,
    keys: list[dict[str, Any]] | None = None,
    version: int = 1,
) -> PublishedConfig:
    default_nodes = [
        node_dict(NODE_A, host="node-a.test", cipher=cipher),
        node_dict(NODE_B, host="node-b.test", cipher=cipher),
    ]
    if keys is None:
        keys = [key if key is not None else key_dict()]
    return PublishedConfig.from_snapshot(
        version,
        _snapshot(
            nodes=nodes if nodes is not None else default_nodes,
            routes=[{"id": "gr_test", "model": MODEL, "pool_id": POOL_ID, "enabled": True, "weight": 1}],
            keys=keys,
        ),
    )


def build_plane(
    upstream: MockUpstream,
    *,
    config: PublishedConfig,
    cipher: CredentialCipher,
    store: InMemoryRuntimeStore | None = None,
    probe_client: Any | None = None,
    probe_check_interval: float = 3600,
    lease_ttl: int = 900,
    seed_snapshot_health: bool = True,
) -> SimpleNamespace:
    store = store or InMemoryRuntimeStore()
    # 数据面启动不再用发布快照播种健康；测试显式模拟「Redis 已有连接作用域运行态」。
    if seed_snapshot_health:
        for node in config.nodes.values():
            asyncio.run(store.seed_health(node.runtime_scope, node.health_state))
    state = GatewayConfigState(config)
    proxy = GatewayProxy(transport=httpx.MockTransport(upstream.handler))
    plane = GatewayDataPlane(
        config_state=state,
        runtime=store,
        proxy=proxy,
        cipher=cipher,
        session_factory=SessionLocal,
        config_loader=None,
        version_source=None,
        instance_id="test-instance",
        heartbeat_interval=3600,
        heartbeat_ttl=60,
        lease_ttl=lease_ttl,
        config_poll_interval=3600,
        runtime_health_interval=3600,
        timezone="Asia/Shanghai",
        probe_client=probe_client,
        probe_check_interval=probe_check_interval,
    )
    return SimpleNamespace(plane=plane, store=store, state=state, cipher=cipher)


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {RAW_KEY}"}


async def _fetch_logs(limit: int = 20) -> list[GatewayRequest]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(GatewayRequest).order_by(GatewayRequest.started_at.desc()).limit(limit)
        )
        return list(rows)


# 请求体上限与数据面实现保持一致；测试独立声明，避免直接依赖被测常量。
MAX_BODY_BYTES = 20 * 1024 * 1024


def _asgi_chat(
    app: Any,
    *,
    headers: dict[str, str],
    chunks: list[bytes],
) -> SimpleNamespace:
    """直接以 ASGI 协议调用数据面，记录 ``receive`` 调用次数。

    用于验证「鉴权/上限校验是否在读取请求体之前完成」：请求体字节数由
    ``receive`` 事件按需拉取，未被消费时调用次数保持为 0。
    """

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    pending = list(chunks)
    state: dict[str, Any] = {"receive_calls": 0, "status": None, "body": b""}

    async def receive() -> dict[str, Any]:
        state["receive_calls"] += 1
        if pending:
            chunk = pending.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
        elif message["type"] == "http.response.body":
            state["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return SimpleNamespace(**state)


@pytest.fixture
def cipher() -> CredentialCipher:
    return CredentialCipher(Fernet.generate_key().decode())


@pytest.fixture
def upstream() -> MockUpstream:
    return MockUpstream()


@pytest.fixture
def runtime_app(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    app = create_gateway_app(kv.plane)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, upstream=upstream, **vars(kv))


def test_models_lists_allowed_models(runtime_app):
    response = runtime_app.client.get("/v1/models", headers=auth_headers())
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [MODEL]

    denied = runtime_app.client.get("/v1/models", headers={"Authorization": "Bearer agw_nope"})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "UNAUTHORIZED"


def test_invalid_expired_disabled_and_forbidden_keys(cipher, upstream, monkeypatch):
    for key, expected in [
        (key_dict(expires_at="2000-01-01T00:00:00+00:00"), "KEY_EXPIRED"),
        (key_dict(enabled=False), "KEY_DISABLED"),
        (key_dict(revoked_at="2026-01-01T00:00:00+00:00"), "KEY_DISABLED"),
        (key_dict(allowed_models=["other-model"]), "KEY_FORBIDDEN"),
    ]:
        kv = build_plane(upstream, config=build_config(cipher, key=key), cipher=cipher)
        with TestClient(create_gateway_app(kv.plane)) as client:
            response = client.post(
                "/v1/chat/completions",
                json={"model": MODEL, "messages": []},
                headers=auth_headers(),
            )
            assert response.status_code in (401, 403), response.text
            assert response.json()["error"]["code"] == expected
    assert upstream.requests == []


def test_invalid_key_is_rejected_without_reading_request_body(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    result = _asgi_chat(
        create_gateway_app(kv.plane),
        headers={"authorization": "Bearer agw_invalid", "content-type": "application/json"},
        chunks=[json.dumps({"model": MODEL, "messages": []}).encode()],
    )
    assert result.status == 401
    assert json.loads(result.body)["error"]["code"] == "UNAUTHORIZED"
    # 鉴权先于读取：无效 Key 不得消费请求体，也不得转发到下游。
    assert result.receive_calls == 0
    assert upstream.requests == []


def test_revoked_key_is_blocked_immediately_without_republish(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    # 已发布快照仍是启用状态（enabled=True, revoked_at=None）；共享吊销集合追加摘要后，
    # 不重新发布也必须立即拒绝，与前端「立即失效」一致。
    asyncio.run(kv.store.revoke_key_digest(KEY_DIGEST))
    with TestClient(create_gateway_app(kv.plane)) as client:
        chat = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
        models = client.get("/v1/models", headers=auth_headers())
    assert chat.status_code == 401
    assert chat.json()["error"]["code"] == "KEY_DISABLED"
    assert models.status_code == 401
    assert upstream.requests == []


def test_revocation_is_shared_across_data_plane_instances(cipher, upstream):
    store = InMemoryRuntimeStore()
    config = build_config(cipher)
    first = build_plane(upstream, config=config, cipher=cipher, store=store)
    second = build_plane(upstream, config=config, cipher=cipher, store=store)
    asyncio.run(store.revoke_key_digest(KEY_DIGEST))
    with (
        TestClient(create_gateway_app(first.plane)) as client_a,
        TestClient(create_gateway_app(second.plane)) as client_b,
    ):
        response_a = client_a.post(
            "/v1/chat/completions", json={"model": MODEL, "messages": []}, headers=auth_headers()
        )
        response_b = client_b.post(
            "/v1/chat/completions", json={"model": MODEL, "messages": []}, headers=auth_headers()
        )
    assert response_a.status_code == 401
    assert response_b.status_code == 401
    assert response_a.json()["error"]["code"] == "KEY_DISABLED"
    assert response_b.json()["error"]["code"] == "KEY_DISABLED"
    assert upstream.requests == []


def test_rollback_to_old_version_cannot_revive_revoked_key(cipher, upstream):
    # 回滚到吊销前的旧版本：快照里 Key 仍启用且 revoked_at 为空，但共享阻断集合只增
    # 不减，旧版本回滚不能复活它。
    kv = build_plane(
        upstream,
        config=build_config(cipher, key=key_dict(enabled=True, revoked_at=None)),
        cipher=cipher,
    )
    asyncio.run(kv.store.revoke_key_digest(KEY_DIGEST))
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "KEY_DISABLED"
    assert upstream.requests == []


def test_revocation_state_fails_closed_on_runtime_or_marker_loss(cipher, upstream):
    scenarios = {
        "runtime": lambda store: store.set_available(False),
        "marker": lambda store: store.clear_revocation_state(),
    }
    for name, lose in scenarios.items():
        store = InMemoryRuntimeStore()
        kv = build_plane(
            upstream,
            config=build_config(cipher),
            cipher=cipher,
            store=store,
            seed_snapshot_health=False,
        )
        with TestClient(create_gateway_app(kv.plane)) as client:
            lose(store)
            chat = client.post(
                "/v1/chat/completions",
                json={"model": MODEL, "messages": []},
                headers=auth_headers(),
            )
            models = client.get("/v1/models", headers=auth_headers())
        assert chat.status_code == 503, name
        assert chat.json()["error"]["code"] == RUNTIME_UNAVAILABLE, name
        assert models.status_code == 503, name
    assert upstream.requests == []


def test_revocation_state_rebuilds_from_db_after_flush(cipher, upstream):
    revoked_raw = "agw_" + uuid4().hex
    revoked_digest = gateway_key_digest(revoked_raw)
    config = build_config(
        cipher,
        keys=[
            key_dict(),
            key_dict(id="gk_revoked", key_prefix=revoked_raw[:12], key_digest=revoked_digest),
        ],
    )

    async def seed_db():
        async with SessionLocal() as session:
            session.add(
                GatewayKey(
                    id=f"gk_db_{uuid4().hex[:8]}",
                    name="revoked-in-db",
                    key_prefix=revoked_raw[:12],
                    key_digest=revoked_digest,
                    enabled=True,
                    revoked_at=utcnow(),
                )
            )
            await session.commit()

    asyncio.run(seed_db())
    store = InMemoryRuntimeStore()
    kv = build_plane(upstream, config=config, cipher=cipher, store=store)
    with TestClient(create_gateway_app(kv.plane)) as client:
        # 启动已同步过一次；模拟 Redis 清空（集合与标记都丢失）后 fail closed。
        store.clear_revocation_state()
        blocked = client.post(
            "/v1/chat/completions", json={"model": MODEL, "messages": []}, headers=auth_headers()
        )
        assert blocked.status_code == 503
        assert blocked.json()["error"]["code"] == RUNTIME_UNAVAILABLE

        # 从 DB 追加同步所有 revoked_at 非空摘要并重建就绪哨兵。
        assert asyncio.run(kv.plane.sync_revocation_state()) is True
        assert asyncio.run(store.revocation_state_ready()) is True
        assert asyncio.run(store.is_key_revoked(revoked_digest)) is True

        # 未吊销的 Key 不受影响；DB 中已吊销的 Key 被立即阻断。
        allowed = client.post(
            "/v1/chat/completions", json={"model": MODEL, "messages": []}, headers=auth_headers()
        )
        assert allowed.status_code == 200, allowed.text
        revoked = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers={"Authorization": f"Bearer {revoked_raw}"},
        )
        assert revoked.status_code == 401
        assert revoked.json()["error"]["code"] == "KEY_DISABLED"
    assert upstream.requests


def test_declared_content_length_over_limit_is_rejected_before_reading(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    result = _asgi_chat(
        create_gateway_app(kv.plane),
        headers={
            "authorization": f"Bearer {RAW_KEY}",
            "content-type": "application/json",
            "content-length": str(MAX_BODY_BYTES + 1),
        },
        chunks=[b"{}"],
    )
    assert result.status == 413
    error = json.loads(result.body)["error"]
    assert error["code"] == "PAYLOAD_TOO_LARGE"
    assert error["type"] == "invalid_request_error"
    assert result.receive_calls == 0
    assert upstream.requests == []


def test_actual_body_over_limit_is_rejected_while_streaming(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    chunk = b"x" * (1024 * 1024)
    result = _asgi_chat(
        create_gateway_app(kv.plane),
        headers={"authorization": f"Bearer {RAW_KEY}", "content-type": "application/json"},
        chunks=[chunk] * 21,
    )
    assert result.status == 413
    assert json.loads(result.body)["error"]["code"] == "PAYLOAD_TOO_LARGE"
    # 无 Content-Length 时按实际流字节强制上限：读到第 21 MiB 即终止。
    assert result.receive_calls == 21
    assert upstream.requests == []


def test_request_within_limit_is_read_and_forwarded(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    body = json.dumps({"model": MODEL, "messages": []}).encode()
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            content=body,
            headers={**auth_headers(), "content-type": "application/json"},
        )
    assert response.status_code == 200, response.text
    assert json.loads(upstream.requests[-1].content)["model"] == MODEL


def test_non_streaming_is_transparent_and_records_usage(runtime_app):
    response = runtime_app.client.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "hi"

    sent = runtime_app.upstream.requests[-1]
    # 请求体原样转发；认证 Header 被替换为节点凭据，Gateway Key 不再出现。
    assert json.loads(sent.content)["model"] == MODEL
    assert sent.headers["Authorization"] == f"Bearer {DOWNSTREAM_KEY}"

    async def logs():
        return await _fetch_logs()

    rows = asyncio.run(logs())
    latest = next(row for row in rows if row.model == MODEL)
    assert latest.streaming is False
    assert latest.input_tokens == 7
    assert latest.output_tokens == 3
    assert latest.total_tokens == 10
    assert latest.retry_count == 0
    assert latest.node_id == NODE_A

    buckets = usage_buckets(utcnow(), "Asia/Shanghai")
    stored = asyncio.run(
        runtime_app.store.usage(SCOPE_NODE, latest.node_id, "hour", buckets["hour"])
    )
    assert stored.total_tokens == 10
    assert stored.unknown_requests == 0


def test_unknown_usage_is_not_fabricated(cipher, upstream):
    upstream.include_usage = False
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
        assert response.status_code == 200

    rows = asyncio.run(_fetch_logs())
    latest = next(row for row in rows if row.model == MODEL)
    assert latest.input_tokens is None
    assert latest.total_tokens is None
    buckets = usage_buckets(utcnow(), "Asia/Shanghai")
    stored = asyncio.run(kv.store.usage(SCOPE_NODE, NODE_A, "hour", buckets["hour"]))
    assert stored.unknown_requests == 1
    assert stored.total_tokens == 0


def test_streaming_forwards_chunks_and_terminal_usage(runtime_app):
    response = runtime_app.client.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [], "stream": True},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert '"he"' in body and '"llo"' in body and "[DONE]" in body

    rows = asyncio.run(_fetch_logs())
    latest = next(row for row in rows if row.streaming and not row.stream_interrupted)
    assert latest.stream_interrupted is False
    assert latest.input_tokens == 5
    assert latest.total_tokens == 7
    assert latest.ttft_ms is not None
    assert latest.ttfb_ms is not None


def test_retry_only_when_request_not_sent(cipher, upstream):
    upstream.fail_hosts = {"node-a.test"}
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 200, response.text
    hosts = [request.url.host for request in upstream.requests]
    assert hosts == ["node-a.test", "node-b.test"]

    rows = asyncio.run(_fetch_logs())
    latest = next(row for row in rows if row.model == MODEL)
    assert latest.retry_count == 1
    assert latest.node_id == NODE_B


def test_no_retry_after_downstream_responded(cipher, upstream):
    upstream.response_status = 500
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 500
    assert len(upstream.requests) == 1

    rows = asyncio.run(_fetch_logs())
    latest = next(row for row in rows if row.model == MODEL)
    assert latest.retry_count == 0


def test_runtime_unavailable_rejects_new_requests(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    kv.store.set_available(False)
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == RUNTIME_UNAVAILABLE
    assert upstream.requests == []


def test_least_active_prefers_idle_node(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    asyncio.run(kv.store.acquire(SCOPE_NODE, NODE_A, 0, 900))
    asyncio.run(kv.store.acquire(SCOPE_NODE, NODE_A, 0, 900))
    asyncio.run(kv.store.acquire(SCOPE_NODE, NODE_A, 0, 900))
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 200
    assert upstream.requests[-1].url.host == "node-b.test"


def test_draining_and_unknown_nodes_are_not_schedulable(cipher, upstream):
    nodes = [
        node_dict(NODE_A, host="node-a.test", cipher=cipher, scheduling_state="DRAINING"),
        node_dict(NODE_B, host="node-b.test", cipher=cipher, health_state="UNKNOWN"),
    ]
    kv = build_plane(upstream, config=build_config(cipher, nodes=nodes), cipher=cipher)
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == NO_ELIGIBLE_NODE
    assert error["detail"][REASON_SCHEDULING] == 1
    assert upstream.requests == []


def test_full_pool_reports_saturation(cipher, upstream):
    nodes = [node_dict(NODE_A, host="node-a.test", cipher=cipher, max_concurrency=1)]
    kv = build_plane(upstream, config=build_config(cipher, nodes=nodes), cipher=cipher)
    asyncio.run(kv.store.acquire(SCOPE_NODE, NODE_A, 1, 900))
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == POOL_SATURATED


def test_quota_stop_blocks_new_requests(cipher, upstream):
    nodes = [
        node_dict(NODE_A, host="node-a.test", cipher=cipher, hourly_token_limit=10),
    ]
    kv = build_plane(upstream, config=build_config(cipher, nodes=nodes), cipher=cipher)
    buckets = usage_buckets(utcnow(), "Asia/Shanghai")
    asyncio.run(
        kv.store.record_usage(
            SCOPE_NODE, NODE_A, "hour", buckets["hour"], total_tokens=10, known=True
        )
    )
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == QUOTA_EXCEEDED
    assert upstream.requests == []


def test_atomic_lease_single_final_slot():
    async def scenario():
        store = InMemoryRuntimeStore()
        first, second = await asyncio.gather(
            store.acquire(SCOPE_NODE, NODE_A, 1, 900),
            store.acquire(SCOPE_NODE, NODE_A, 1, 900),
        )
        return first, second, await store.active(SCOPE_NODE, NODE_A)

    first, second, active = asyncio.run(scenario())
    granted = [value for value in (first, second) if value is not None]
    # 每请求唯一 lease ID，最后一个槽位只被一个请求拿到。
    assert len(granted) == 1 and isinstance(granted[0], str)
    assert active == 1


def test_unique_lease_ids_release_independently():
    async def scenario():
        store = InMemoryRuntimeStore()
        first = await store.acquire(SCOPE_NODE, NODE_A, 0, 900)
        second = await store.acquire(SCOPE_NODE, NODE_A, 0, 900)
        two = await store.active(SCOPE_NODE, NODE_A)
        await store.release(SCOPE_NODE, NODE_A, first)
        one = await store.active(SCOPE_NODE, NODE_A)
        await store.release(SCOPE_NODE, NODE_A, second)
        return first, second, two, one, await store.active(SCOPE_NODE, NODE_A)

    first, second, two, one, zero = asyncio.run(scenario())
    assert first != second
    assert (two, one, zero) == (2, 1, 0)


def test_expired_lease_is_pruned_and_renew_keeps_it_alive():
    async def scenario():
        store = InMemoryRuntimeStore()
        lease = await store.acquire(SCOPE_NODE, NODE_A, 1, 1)
        assert lease is not None
        # 未续租：TTL 到期后按各租约独立回收，唯一槽位自动腾出。
        await asyncio.sleep(1.1)
        assert await store.active(SCOPE_NODE, NODE_A) == 0
        reclaimed = await store.acquire(SCOPE_NODE, NODE_A, 1, 1)
        assert reclaimed is not None
        assert await store.renew(SCOPE_NODE, NODE_A, reclaimed, 900) is True
        await asyncio.sleep(1.1)
        # 续租后即便超过原 TTL 仍然活跃，槽位不会被误回收。
        assert await store.active(SCOPE_NODE, NODE_A) == 1
        await store.release(SCOPE_NODE, NODE_A, reclaimed)
        assert await store.renew(SCOPE_NODE, NODE_A, reclaimed, 900) is False

    asyncio.run(scenario())


def test_runtime_health_streaks_remove_and_restore():
    async def scenario():
        store = InMemoryRuntimeStore()
        state = None
        for _ in range(3):
            state = await store.record_probe(NODE_A, success=False)
        removed = state
        for _ in range(2):
            state = await store.record_probe(NODE_A, success=True)
        return removed, state, await store.health(NODE_A)

    removed, restored, final = asyncio.run(scenario())
    assert removed == "UNHEALTHY"
    assert restored == "HEALTHY"
    assert final == "HEALTHY"


def test_passive_failure_degrades_healthy_node():
    async def scenario():
        store = InMemoryRuntimeStore()
        await store.seed_health(NODE_A, "HEALTHY")
        await store.mark_degraded(NODE_A)
        return await store.health(NODE_A)

    assert asyncio.run(scenario()) == "DEGRADED"


def test_circuit_open_to_half_open_trial_and_recovery():
    async def scenario():
        store = InMemoryRuntimeStore()
        assert await store.circuit(NODE_A) == "CLOSED"
        # open_seconds=0 立即到期，进入 HALF_OPEN。
        await store.set_circuit_open(NODE_A, 0)
        assert await store.circuit(NODE_A) == "HALF_OPEN"
        assert await store.try_circuit_trial(NODE_A) is True
        assert await store.try_circuit_trial(NODE_A) is False  # 只放行少量试探
        await store.set_circuit_closed(NODE_A)
        assert await store.circuit(NODE_A) == "CLOSED"
        # 再次失败 → 重新打开；OPEN 窗口内不放行任何试探。
        await store.set_circuit_open(NODE_A, 30)
        assert await store.circuit(NODE_A) == "OPEN"
        assert await store.try_circuit_trial(NODE_A) is False

    asyncio.run(scenario())


def test_revoked_key_digests_are_append_only_and_ready():
    async def scenario():
        store = InMemoryRuntimeStore()
        assert await store.revocation_state_ready() is True
        await store.revoke_key_digest("digest-a")
        await store.revoke_key_digest("digest-b")
        # 追加同步绝不整表替换：并发吊销的条目必须保留。
        await store.sync_revoked_key_digests(["digest-c"])
        return (
            await store.is_key_revoked("digest-a"),
            await store.is_key_revoked("digest-b"),
            await store.is_key_revoked("digest-c"),
            await store.is_key_revoked("digest-missing"),
            await store.revocation_state_ready(),
        )

    a, b, c, missing, ready = asyncio.run(scenario())
    assert (a, b, c, missing, ready) == (True, True, True, False, True)


def test_is_key_revoked_fails_closed_when_ready_sentinel_missing():
    async def scenario():
        store = InMemoryRuntimeStore()
        await store.revoke_key_digest("digest-a")
        assert await store.is_key_revoked("digest-a") is True
        # 模拟 Redis 淘汰整个集合键：就绪哨兵与摘要一起丢失。is_key_revoked 本身必须
        # 失败关闭，绝不返回「未吊销」，否则两次调用之间清空会形成放行窗口。
        store.clear_revocation_state()
        ready = await store.revocation_state_ready()
        blocked = False
        try:
            await store.is_key_revoked("digest-a")
        except RuntimeError:
            blocked = True
        # DB 追加同步重建哨兵与摘要后恢复阻断。
        await store.sync_revoked_key_digests(["digest-a"])
        return (
            ready,
            blocked,
            await store.revocation_state_ready(),
            await store.is_key_revoked("digest-a"),
        )

    ready, blocked, restored, revoked = asyncio.run(scenario())
    assert (ready, blocked, restored, revoked) == (False, True, True, True)


def test_key_concurrency_is_enforced(cipher, upstream):
    key = key_dict(max_concurrency=1)
    kv = build_plane(upstream, config=build_config(cipher, key=key), cipher=cipher)
    asyncio.run(kv.store.acquire(SCOPE_KEY, "gk_test", 1, 900))
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "KEY_CONCURRENCY_EXCEEDED"


def test_header_auth_uses_encrypted_credential_only(cipher, upstream):
    nodes = [
        node_dict(
            NODE_A,
            host="node-a.test",
            cipher=cipher,
            auth_type="HEADER",
            auth_header="X-Api-Key",
        )
    ]
    kv = build_plane(upstream, config=build_config(cipher, nodes=nodes), cipher=cipher)
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 200
    sent = upstream.requests[-1]
    assert sent.headers["X-Api-Key"] == DOWNSTREAM_KEY
    # 客户端 Authorization 不转发到下游（除节点认证 Header 外不保留）。
    assert sent.headers.get("Authorization") != f"Bearer {RAW_KEY}"


def test_client_disconnect_releases_leases_and_records(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    plane = kv.plane

    async def scenario():
        await plane.startup()
        try:
            key = plane.authenticate(f"Bearer {RAW_KEY}")
            key_lease = await plane.runtime.acquire(SCOPE_KEY, key.id, 0, 900)
            assert key_lease is not None
            node_id = NODE_A
            node_lease = await plane.runtime.acquire(SCOPE_NODE, node_id, 0, 900)
            assert node_lease is not None
            record = RequestRecord(id=uuid4().hex, started_at=utcnow(), streaming=True, model=MODEL)
            record.key_id = key.id
            record.node_id = node_id
            node = plane.config_state.config.nodes[node_id]
            request = plane.proxy.build_request(
                node,
                "POST",
                "/v1/chat/completions",
                headers={},
                content=json.dumps({"stream": True}).encode(),
            )
            upstream_response = await plane.proxy.send(request, stream=True)
            renewals = plane._start_lease_renewals((SCOPE_NODE, node_id, node_lease))
            generator = plane._stream_body(
                upstream_response,
                record,
                key,
                node_id,
                node.runtime_scope,
                node_lease,
                key_lease,
                renewals,
            )
            await generator.__anext__()
            await generator.aclose()
            return (
                record,
                await plane.runtime.active(SCOPE_NODE, node_id),
                await plane.runtime.active(SCOPE_KEY, key.id),
            )
        finally:
            await plane.shutdown()

    record, node_active, key_active = asyncio.run(scenario())
    assert record.stream_interrupted is True
    assert record.error_code == CLIENT_DISCONNECTED
    assert node_active == 0
    assert key_active == 0
    rows = asyncio.run(_fetch_logs())
    logged = next(row for row in rows if row.id == record.id)
    assert logged.stream_interrupted is True
    assert logged.error_code == CLIENT_DISCONNECTED


def test_heartbeat_registers_and_retires_instance(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)

    async def scenario():
        await kv.plane.startup()
        await kv.plane.heartbeat_now()
        payload = kv.store.instances()
        await kv.plane.shutdown()
        return payload, kv.store.instances()

    registered, after_shutdown = asyncio.run(scenario())
    assert "test-instance" in registered
    assert registered["test-instance"]["config_version"] == 1
    assert "test-instance" not in after_shutdown

def _publish_version(cipher, version: int, snapshot: dict[str, Any]) -> None:
    async def scenario():
        async with SessionLocal() as session:
            session.add(
                GatewayConfigVersion(
                    version=version,
                    status="CURRENT",
                    source_version=None,
                    note="test",
                    snapshot=snapshot,
                    published_by="test",
                    published_at=utcnow(),
                )
            )
            await session.commit()

    asyncio.run(scenario())


def _single_node_snapshot(cipher) -> dict[str, Any]:
    return _snapshot(
        nodes=[node_dict(NODE_A, host="node-a.test", cipher=cipher)],
        routes=[{"id": "gr_test", "model": MODEL, "pool_id": POOL_ID, "enabled": True, "weight": 1}],
        keys=[key_dict()],
    )


def test_config_loader_reads_current_published_version(cipher):
    version = 900001
    _publish_version(cipher, version, _single_node_snapshot(cipher))

    config = asyncio.run(ConfigLoader(SessionLocal).load_current())
    assert config.version == version
    assert NODE_A in config.nodes
    assert config.routes[MODEL].pool_id == POOL_ID


def test_config_loader_ignores_non_current_versions(cipher):
    current = 900010
    _publish_version(cipher, current, _single_node_snapshot(cipher))

    async def add_unpublished(version: int, status: str) -> None:
        async with SessionLocal() as session:
            session.add(
                GatewayConfigVersion(
                    version=version,
                    status=status,
                    source_version=None,
                    note=status,
                    snapshot=_snapshot(
                        nodes=[node_dict(NODE_B, host="node-b.test", cipher=cipher)],
                        routes=[],
                        keys=[],
                    ),
                    published_by="test",
                    published_at=utcnow(),
                )
            )
            await session.commit()

    # 比 CURRENT 更新的 PENDING / FAILED 版本绝不作为“近似当前版本”被加载。
    asyncio.run(add_unpublished(current + 1, "PENDING"))
    asyncio.run(add_unpublished(current + 2, "FAILED"))

    config = asyncio.run(ConfigLoader(SessionLocal).load_current())
    assert config.version == current
    assert NODE_A in config.nodes
    assert NODE_B not in config.nodes


def test_config_loader_returns_empty_without_current_version():
    async def scenario():
        # 隔离内存库：不受其他用例已发布 CURRENT 版本影响。
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with factory() as session:
                for version, status in ((1, "PENDING"), (2, "FAILED")):
                    session.add(
                        GatewayConfigVersion(
                            version=version,
                            status=status,
                            source_version=None,
                            note=status,
                            snapshot={},
                            published_by="test",
                            published_at=utcnow(),
                        )
                    )
                await session.commit()
            return await ConfigLoader(factory).load_current()
        finally:
            await engine.dispose()

    config = asyncio.run(scenario())
    # 只有 PENDING/FAILED 而没有 CURRENT 时必须返回空配置，绝不回退未生效版本。
    assert config.version is None
    assert config.empty_config
    assert config.nodes == {}
    assert config.routes == {}


def test_reconciler_adopts_new_redis_version(cipher):
    version = 900002
    _publish_version(cipher, version, _single_node_snapshot(cipher))
    notifier = InMemoryConfigNotifier()
    notifier.current = version
    state = GatewayConfigState(PublishedConfig.empty())
    reconciler = ConfigReconciler(
        state=state, loader=ConfigLoader(SessionLocal), version_source=notifier, interval=1
    )

    asyncio.run(reconciler.tick())
    assert state.version == version
    assert NODE_A in state.config.nodes

    # 版本未变化时不重复替换当前配置。
    snapshot_before = state.config
    asyncio.run(reconciler.tick())
    assert state.config is snapshot_before


def test_scheduler_reads_live_runtime_health_not_snapshot(cipher, upstream):
    nodes = [node_dict(NODE_A, host="node-a.test", cipher=cipher, health_state="HEALTHY")]
    store = InMemoryRuntimeStore()
    kv = build_plane(
        upstream,
        config=build_config(cipher, nodes=nodes),
        cipher=cipher,
        store=store,
        seed_snapshot_health=False,
    )
    # 发布快照仍是 HEALTHY，但运行态连接作用域健康为 UNHEALTHY。
    node = kv.plane.config_state.config.nodes[NODE_A]
    asyncio.run(store.seed_health(node.runtime_scope, "UNHEALTHY"))
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 503
    assert upstream.requests == []


def test_background_probe_removes_and_restores_node(cipher, upstream):
    probe = FakeProbe()
    nodes = [node_dict(NODE_A, host="node-a.test", cipher=cipher, health_state="HEALTHY")]
    store = InMemoryRuntimeStore()
    kv = build_plane(
        upstream,
        config=build_config(cipher, nodes=nodes),
        cipher=cipher,
        store=store,
        probe_client=probe,
    )
    node = kv.plane.config_state.config.nodes[NODE_A]
    scope = node.runtime_scope

    async def scenario():
        probe.success = False
        for _ in range(3):
            await kv.plane._probe_node(node)
        removed = await store.health(scope)
        opened = await store.circuit(scope)
        probe.success = True
        for _ in range(2):
            await kv.plane._probe_node(node)
        return removed, opened, await store.health(scope), await store.circuit(scope)

    removed, opened, restored, closed = asyncio.run(scenario())
    assert removed == "UNHEALTHY"
    assert opened == "OPEN"
    assert restored == "HEALTHY"
    assert closed == "CLOSED"
    # 探测类型包含网络、服务、真实模型与 SSE 流式。
    assert probe.calls and len(probe.calls[0][1]) == 4


def test_passive_transport_failure_degrades_node(cipher, upstream):
    kv = build_plane(upstream, config=build_config(cipher), cipher=cipher)
    upstream.fail_hosts = {"node-a.test", "node-b.test"}
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code in (502, 504)
    # 被动传输故障降级为 DEGRADED，而不是直接摘除（摘除由连续主动探测负责）。
    node_a = kv.plane.config_state.config.nodes[NODE_A]
    node_b = kv.plane.config_state.config.nodes[NODE_B]
    assert asyncio.run(kv.store.health(node_a.runtime_scope)) == "DEGRADED"
    assert asyncio.run(kv.store.health(node_b.runtime_scope)) == "DEGRADED"


def test_missing_runtime_health_does_not_fall_back_to_snapshot(cipher, upstream):
    # 发布快照健康为 HEALTHY，但运行态缺失（如被 reset 清空、Redis 丢失）：
    # 必须视为 UNKNOWN 而不是回退快照 HEALTHY，否则从未验证的连接仍会被调度。
    nodes = [node_dict(NODE_A, host="node-a.test", cipher=cipher, health_state="HEALTHY")]
    kv = build_plane(
        upstream,
        config=build_config(cipher, nodes=nodes),
        cipher=cipher,
        seed_snapshot_health=False,
    )
    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == NO_ELIGIBLE_NODE
    assert upstream.requests == []


def test_reset_runtime_health_does_not_fall_back_to_snapshot(cipher, upstream):
    # 直接复现回归：运行态健康被 reset 清空后，调度绝不能回退到发布快照 HEALTHY。
    nodes = [node_dict(NODE_A, host="node-a.test", cipher=cipher, health_state="HEALTHY")]
    store = InMemoryRuntimeStore()
    kv = build_plane(upstream, config=build_config(cipher, nodes=nodes), cipher=cipher, store=store)
    node = kv.plane.config_state.config.nodes[NODE_A]
    assert asyncio.run(store.health(node.runtime_scope)) == "HEALTHY"
    asyncio.run(store.reset_health(node.runtime_scope))
    assert asyncio.run(store.health(node.runtime_scope)) is None

    with TestClient(create_gateway_app(kv.plane)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == NO_ELIGIBLE_NODE
    assert upstream.requests == []


def test_new_connection_health_is_isolated_by_scope(cipher, upstream):
    # 旧发布连接的健康作用域已是 HEALTHY；新发布版本换成不同连接后，旧健康不得
    # 授权新配置，旧实例后续探测成功也不能把新连接判为 HEALTHY。
    old_config = build_config(
        cipher,
        nodes=[node_dict(NODE_A, host="node-a.test", cipher=cipher)],
    )
    old_scope = old_config.nodes[NODE_A].runtime_scope

    new_config = build_config(
        cipher,
        nodes=[node_dict(NODE_A, host="node-a-v2.test", cipher=cipher, health_state="UNKNOWN")],
    )
    new_scope = new_config.nodes[NODE_A].runtime_scope
    assert new_scope != old_scope

    store = InMemoryRuntimeStore()
    asyncio.run(store.seed_health(old_scope, "HEALTHY"))
    kv = build_plane(upstream, config=new_config, cipher=cipher, store=store)

    def chat(client: TestClient):
        return client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": []},
            headers=auth_headers(),
        )

    with TestClient(create_gateway_app(kv.plane)) as client:
        blocked = chat(client)
        assert blocked.status_code == 503
        assert blocked.json()["error"]["code"] == NO_ELIGIBLE_NODE
        assert upstream.requests == []

        # 旧连接后续探测成功（旧实例/旧版本）不能把新配置判为 HEALTHY。
        for _ in range(2):
            asyncio.run(store.record_probe(old_scope, success=True))
        still_blocked = chat(client)
        assert still_blocked.status_code == 503
        assert upstream.requests == []

        # 新连接自己的完整探测成功后才重新可调度。
        for _ in range(2):
            asyncio.run(store.record_probe(new_scope, success=True))
        recovered = chat(client)
        assert recovered.status_code == 200, recovered.text
        assert upstream.requests[-1].url.host == "node-a-v2.test"


@pytest.mark.skipif(
    not REDIS_URL,
    reason="未提供 ASTRA_TEST_REDIS_URL：Lua 脚本未在真实 Redis 上联调，默认仅验证进程内等价语义",
)
def test_redis_lua_scripts_against_real_redis():
    async def scenario():
        store = RedisRuntimeStore(REDIS_URL)
        scope_id = f"redis-{uuid4().hex[:8]}"
        try:
            lease = await store.acquire(SCOPE_NODE, scope_id, 1, 5)
            assert lease is not None
            # 限额检查在 Lua 内完成，最后一个槽位不会超卖。
            assert await store.acquire(SCOPE_NODE, scope_id, 1, 5) is None
            assert await store.renew(SCOPE_NODE, scope_id, lease, 5) is True
            await store.release(SCOPE_NODE, scope_id, lease)
            assert await store.active(SCOPE_NODE, scope_id) == 0
        finally:
            await store.close()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not REDIS_URL,
    reason="未提供 ASTRA_TEST_REDIS_URL：吊销集合与就绪哨兵未在真实 Redis 上联调",
)
def test_redis_revocation_set_is_append_only_and_marked_ready():
    async def scenario():
        store = RedisRuntimeStore(REDIS_URL)
        suffix = uuid4().hex[:8]
        first, second, third = (f"rev-{suffix}-{name}" for name in ("a", "b", "c"))
        try:
            await store.sync_revoked_key_digests([first, second])
            assert await store.revocation_state_ready() is True
            await store.revoke_key_digest(third)
            assert await store.is_key_revoked(first) is True
            assert await store.is_key_revoked(third) is True
            assert await store.is_key_revoked(f"rev-{suffix}-missing") is False
            # 追加同步逐条 SADD，既有成员与并发吊销都不会被清空。
            await store.sync_revoked_key_digests([third])
            assert await store.is_key_revoked(second) is True
            # 整集合键被 maxmemory 淘汰/清空：哨兵与摘要一起消失，绝不放行旧 Key。
            await store._connection().delete(REVOKED_KEYS_KEY)
            assert await store.revocation_state_ready() is False
            with pytest.raises(RuntimeError):
                await store.is_key_revoked(first)
            # DB 追加同步用一次 SADD 重建摘要与哨兵，阻断恢复。
            await store.sync_revoked_key_digests([first, second])
            assert await store.revocation_state_ready() is True
            assert await store.is_key_revoked(first) is True
        finally:
            await store.close()

    asyncio.run(scenario())

"""API 中转观测测试：后台探测落库、调用日志分页过滤、范围统计、实例与 Key 自助。

统计来源固定为 ``gateway_requests``；未知 usage 明确标记，不保存 Prompt。普通
Gateway Key 只能读取自身日志与统计，管理凭据与浏览器身份 Header 都不作为 Key 身份。
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.gateway_routes import (
    gateway_cipher,
    gateway_notifier,
    gateway_probe_client,
    gateway_runtime,
)
from app.database import SessionLocal, init_database
from app.gateway.auth import gateway_credential_store
from app.gateway.config import GatewayConfigState, PublishedConfig
from app.gateway.models import (
    GatewayHealthCheck,
    GatewayKey,
    GatewayNode,
    GatewayRequest,
    utcnow,
)
from app.gateway.notifier import InMemoryConfigNotifier
from app.gateway.probe import ProbeOutcome
from app.gateway.proxy import GatewayProxy
from app.gateway.runtime import SCOPE_NODE, InMemoryRuntimeStore
from app.gateway.security import CredentialCipher, gateway_key_digest, parse_credentials
from app.gateway.server import GatewayDataPlane
from app.main import app

ROOT_TOKEN = "obs-root-token"
VIEW_TOKEN = "obs-view-token"


class FakeProbe:
    def __init__(self) -> None:
        self.success = True
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def probe(self, node, probe_types, api_key):
        self.calls.append((node.id, tuple(probe_types)))
        return [ProbeOutcome(probe_type, self.success, 2) for probe_type in probe_types]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    asyncio.run(init_database())
    yield


@pytest.fixture
def observability_env():
    master_key = Fernet.generate_key().decode()
    store = parse_credentials(
        json.dumps(
            [
                {
                    "name": "root",
                    "token": ROOT_TOKEN,
                    "roles": ["view", "node", "route", "key", "publish", "system"],
                },
                {"name": "viewer", "token": VIEW_TOKEN, "roles": ["view"]},
            ]
        )
    )
    runtime = InMemoryRuntimeStore()
    overrides = {
        gateway_credential_store: lambda: store,
        gateway_cipher: lambda: CredentialCipher(master_key),
        gateway_notifier: lambda: InMemoryConfigNotifier(),
        gateway_probe_client: lambda: FakeProbe(),
        gateway_runtime: lambda: runtime,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield SimpleNamespace(runtime=runtime)
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)


def create_key(client: TestClient, *, name: str) -> tuple[str, str]:
    response = client.post("/api/gateway/keys", json={"name": name}, headers=auth(ROOT_TOKEN))
    assert response.status_code == 201, response.text
    return response.json()["id"], response.json()["key"]


def _add_log(
    *,
    key_id: str | None = None,
    model: str | None = None,
    node_id: str | None = None,
    pool_id: str | None = None,
    status_code: int | None = 200,
    error_code: str | None = None,
    input_tokens: int | None = 10,
    output_tokens: int | None = 5,
    total_tokens: int | None = 15,
    output_tps: float | None = 25.5,
    duration_ms: int | None = 100,
    connect_ms: int | None = 8,
    ttfb_ms: int | None = 20,
    ttft_ms: int | None = 30,
    started_at=None,
    finished_at=None,
    streaming: bool = False,
) -> str:
    log_id = uuid4().hex
    start = started_at or utcnow()
    row = GatewayRequest(
        id=log_id,
        key_id=key_id,
        model=model,
        node_id=node_id,
        pool_id=pool_id,
        status_code=status_code,
        error_code=error_code,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        output_tps=output_tps,
        connect_ms=connect_ms,
        ttfb_ms=ttfb_ms,
        ttft_ms=ttft_ms,
        duration_ms=duration_ms,
        streaming=streaming,
        started_at=start,
        finished_at=finished_at or (start + timedelta(seconds=2)),
    )

    async def write():
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()

    asyncio.run(write())
    return log_id


# ── 后台探测落库与健康一致性 ───────────────────────────────────────────


def _build_probe_plane(node_id: str, probe: FakeProbe) -> tuple[GatewayDataPlane, InMemoryRuntimeStore]:
    snapshot = {
        "pools": [],
        "nodes": [
            {
                "id": node_id,
                "name": node_id,
                "pool_id": None,
                "base_url": "https://proxy.example.com",
                "auth_type": "NONE",
                "models": ["gpt-test"],
                "config_state": "ENABLED",
                "scheduling_state": "ACTIVE",
                "health_state": "HEALTHY",
            }
        ],
        "routes": [],
        "keys": [],
    }
    runtime = InMemoryRuntimeStore()
    plane = GatewayDataPlane(
        config_state=GatewayConfigState(PublishedConfig.from_snapshot(1, snapshot)),
        runtime=runtime,
        proxy=GatewayProxy(transport=httpx.MockTransport(lambda _request: httpx.Response(200))),
        cipher=CredentialCipher(None),
        session_factory=SessionLocal,
        config_loader=None,
        version_source=None,
        instance_id="obs-plane",
        heartbeat_interval=3600,
        probe_client=probe,
        config_poll_interval=3600,
    )
    return plane, runtime


def _insert_node(node_id: str) -> None:
    async def write():
        async with SessionLocal() as session:
            session.add(
                GatewayNode(
                    id=node_id,
                    name=node_id,
                    pool_id=None,
                    base_url="https://proxy.example.com",
                    auth_type="NONE",
                    models=["gpt-test"],
                )
            )
            await session.commit()

    asyncio.run(write())


def _health_check_count(node_id: str) -> int:
    async def read():
        async with SessionLocal() as session:
            rows = await session.scalars(
                select(GatewayHealthCheck).where(GatewayHealthCheck.node_id == node_id)
            )
            return len(list(rows))

    return asyncio.run(read())


def test_background_probe_persists_checks_and_matches_runtime_health():
    node_id = unique("gn_obs")
    _insert_node(node_id)
    probe = FakeProbe()
    plane, runtime = _build_probe_plane(node_id, probe)
    node = plane.config_state.config.nodes[node_id]
    scope = node.runtime_scope

    async def db_health() -> str:
        async with SessionLocal() as session:
            row = await session.get(GatewayNode, node_id)
            return row.health_state

    async def run():
        await plane.startup()
        try:
            probe.success = False
            for _ in range(3):
                await plane._probe_node(node)
            removed_runtime = await runtime.health(scope)
            removed_db = await db_health()
            probe.success = True
            for _ in range(2):
                await plane._probe_node(node)
            return removed_runtime, removed_db, await runtime.health(scope), await db_health()
        finally:
            await plane.shutdown()

    removed_runtime, removed_db, restored_runtime, restored_db = asyncio.run(run())
    assert removed_runtime == removed_db == "UNHEALTHY"
    assert restored_runtime == restored_db == "HEALTHY"
    # 每次探测落 4 类健康记录；启动后台探测循环也会先探一次。
    checks = _health_check_count(node_id)
    assert checks >= 20 and checks % 4 == 0


# ── 调用日志分页 / 过滤 ────────────────────────────────────────────────


def test_request_log_pagination_and_filters(observability_env):
    model = unique("model")
    node = unique("node")
    log_ids = [
        _add_log(model=model, node_id=node, status_code=200),
        _add_log(model=model, node_id=node, status_code=500, error_code="UPSTREAM_500"),
        _add_log(model=model, node_id=node, status_code=429, error_code="KEY_CONCURRENCY_EXCEEDED"),
    ]
    with TestClient(app) as client:
        first_page = client.get(
            "/api/gateway/requests",
            params={"model": model, "page": 1, "page_size": 2},
            headers=auth(VIEW_TOKEN),
        )
        assert first_page.status_code == 200, first_page.text
        body = first_page.json()
        assert body["total"] == 3
        assert body["page"] == 1 and body["page_size"] == 2
        assert len(body["items"]) == 2

        second_page = client.get(
            "/api/gateway/requests",
            params={"model": model, "page": 2, "page_size": 2},
            headers=auth(VIEW_TOKEN),
        ).json()
        assert len(second_page["items"]) == 1
        assert {item["id"] for item in body["items"]} | {
            item["id"] for item in second_page["items"]
        } == set(log_ids)

        by_status = client.get(
            "/api/gateway/requests",
            params={"model": model, "status_code": 500},
            headers=auth(VIEW_TOKEN),
        ).json()
        assert by_status["total"] == 1

        by_error = client.get(
            "/api/gateway/requests",
            params={"model": model, "error_code": "UPSTREAM_500"},
            headers=auth(VIEW_TOKEN),
        ).json()
        assert by_error["total"] == 1

        by_id = client.get(
            "/api/gateway/requests",
            params={"request_id": log_ids[0]},
            headers=auth(VIEW_TOKEN),
        ).json()
        assert by_id["total"] == 1
        assert by_id["items"][0]["id"] == log_ids[0]

        by_node = client.get(
            "/api/gateway/requests",
            params={"model": model, "node_id": node},
            headers=auth(VIEW_TOKEN),
        ).json()
        assert by_node["total"] == 3

        # 日志只含元数据，绝不包含 Prompt / 授权头。
        assert "prompt" not in json.dumps(body).lower()
        assert "authorization" not in json.dumps(body).lower()
        assert not hasattr(GatewayRequest, "prompt")


# ── 范围统计与未知 usage ───────────────────────────────────────────────


def test_scope_stats_tokens_latency_peak_and_unknown_usage(observability_env):
    model = unique("model")
    node = unique("node")
    start = utcnow() - timedelta(minutes=30)
    _add_log(
        model=model,
        node_id=node,
        status_code=200,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        started_at=start,
        finished_at=start + timedelta(seconds=5),
    )
    _add_log(
        model=model,
        node_id=node,
        status_code=500,
        error_code="UPSTREAM_500",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        output_tps=None,
        started_at=start + timedelta(seconds=1),
        finished_at=start + timedelta(seconds=3),
    )
    _add_log(
        model=model,
        node_id=node,
        status_code=200,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        started_at=start + timedelta(seconds=10),
        finished_at=start + timedelta(seconds=20),
    )

    # 运行态当前并发直接从 Redis 运行态读取。
    lease = asyncio.run(observability_env.runtime.acquire(SCOPE_NODE, node, 0, 900))
    assert lease is not None

    with TestClient(app) as client:
        response = client.get(
            "/api/gateway/stats",
            params={"scope": "node", "scope_id": node, "window": "7d"},
            headers=auth(VIEW_TOKEN),
        )
        assert response.status_code == 200, response.text
        stats = response.json()

    assert stats["requests"] == 3
    assert stats["success"] == 2
    assert stats["errors"] == 1
    assert stats["input_tokens"] == 10
    assert stats["output_tokens"] == 5
    assert stats["total_tokens"] == 15
    # 未知 usage 只计数，不估算为零。
    assert stats["unknown_usage_requests"] == 1
    assert stats["success_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert stats["qps"] >= 0
    assert stats["active"] == 1
    # 两个请求区间重叠 → 峰值并发至少 2。
    assert stats["peak_concurrency"] >= 2
    assert stats["connect_ms"]["avg"] is not None
    assert stats["ttfb_ms"]["p50"] is not None
    assert stats["ttft_ms"]["p95"] is not None
    assert stats["duration_ms"]["avg"] is not None
    assert len(stats["trend"]) >= 1
    assert sum(bucket["requests"] for bucket in stats["trend"]) == 3
    assert sum(bucket["unknown_usage_requests"] for bucket in stats["trend"]) == 1


def test_stats_overview_and_missing_scope_validation(observability_env):
    with TestClient(app) as client:
        overview = client.get("/api/gateway/stats", headers=auth(VIEW_TOKEN))
        assert overview.status_code == 200
        assert overview.json()["scope"] == "overview"
        assert overview.json()["scope_id"] is None

        missing = client.get(
            "/api/gateway/stats",
            params={"scope": "node"},
            headers=auth(VIEW_TOKEN),
        )
        assert missing.status_code == 422

        invalid_window = client.get(
            "/api/gateway/stats",
            params={"scope": "overview", "window": "year"},
            headers=auth(VIEW_TOKEN),
        )
        assert invalid_window.status_code == 422


# ── 实例心跳与过期 ─────────────────────────────────────────────────────


def test_instances_mark_expired_and_expose_optional_metrics(observability_env):
    live_id = unique("inst-live")
    stale_id = unique("inst-stale")
    asyncio.run(
        observability_env.runtime.heartbeat(
            live_id,
            {
                "instance_id": live_id,
                "app_version": "0.4.0",
                "config_version": 7,
                "pid": 4242,
                "updated_at": utcnow().isoformat(),
                "requests": 11,
                "errors": 1,
                "active": 2,
                "cpu_percent": 12.5,
                "memory_bytes": 1048576,
            },
            60,
        )
    )
    asyncio.run(
        observability_env.runtime.heartbeat(
            stale_id,
            {"instance_id": stale_id, "updated_at": utcnow().isoformat(), "config_version": 3},
            1,
        )
    )
    time.sleep(1.1)

    with TestClient(app) as client:
        response = client.get("/api/gateway/instances", headers=auth(VIEW_TOKEN))
        assert response.status_code == 200, response.text
        by_id = {item["instance_id"]: item for item in response.json()}

    assert by_id[live_id]["status"] == "ACTIVE"
    assert by_id[live_id]["cpu_percent"] == 12.5
    assert by_id[live_id]["memory_bytes"] == 1048576
    assert by_id[stale_id]["status"] == "EXPIRED"
    assert by_id[stale_id]["age_seconds"] >= 1


# ── Key 自助：只能看自己的日志与统计 ───────────────────────────────────


def test_key_self_service_only_sees_own_logs_and_stats(observability_env):
    with TestClient(app) as client:
        key_a_id, key_a_token = create_key(client, name=unique("key-a"))
        key_b_id, key_b_token = create_key(client, name=unique("key-b"))
        model = unique("model")
        log_a = _add_log(key_id=key_a_id, model=model, node_id="gn_shared", status_code=200)
        log_b = _add_log(key_id=key_b_id, model=model, node_id="gn_shared", status_code=500)

        # 不信任浏览器提交的身份 Header。
        forged = client.get(
            "/api/gateway/self/requests",
            headers={"X-Astra-User-Id": key_a_id, "X-Astra-Role": "admin"},
        )
        assert forged.status_code == 401

        # 管理凭据不是 Gateway Key，不能当自助身份。
        assert client.get("/api/gateway/self/requests", headers=auth(ROOT_TOKEN)).status_code == 401

        own = client.get("/api/gateway/self/requests", headers=auth(key_a_token))
        assert own.status_code == 200, own.text
        own_ids = {item["id"] for item in own.json()["items"]}
        assert log_a in own_ids
        assert log_b not in own_ids

        # 过滤条件仍受自身 Key 约束，无法越权查看其他 Key。
        other_attempt = client.get(
            "/api/gateway/self/requests",
            params={"key_id": key_b_id},
            headers=auth(key_a_token),
        )
        assert other_attempt.status_code == 200
        assert {item["id"] for item in other_attempt.json()["items"]} == {log_a}

        stats = client.get("/api/gateway/self/stats", headers=auth(key_a_token))
        assert stats.status_code == 200
        assert stats.json()["scope"] == "key"
        assert stats.json()["scope_id"] == key_a_id
        assert stats.json()["requests"] == 1

        other_stats = client.get("/api/gateway/self/stats", headers=auth(key_b_token))
        assert other_stats.json()["scope_id"] == key_b_id
        assert other_stats.json()["requests"] == 1
        assert other_stats.json()["errors"] == 1


def test_disabled_key_cannot_use_self_service(observability_env):
    with TestClient(app) as client:
        key_id, token = create_key(client, name=unique("key-revoked"))
        revoked = client.delete(f"/api/gateway/keys/{key_id}", headers=auth(ROOT_TOKEN))
        assert revoked.status_code == 200
        denied = client.get("/api/gateway/self/requests", headers=auth(token))
        assert denied.status_code == 403

        async def stored_digest():
            async with SessionLocal() as session:
                key = await session.get(GatewayKey, key_id)
                return key.key_digest

        assert asyncio.run(stored_digest()) == gateway_key_digest(token)


def test_instances_requires_management_role(observability_env):
    with TestClient(app) as client:
        assert client.get("/api/gateway/instances").status_code == 401
        assert client.get("/api/gateway/instances", headers=auth(ROOT_TOKEN)).status_code == 200
"""API 中转控制面测试：鉴权、凭据脱敏、安全下线、探测、发布 / 回滚与审计。"""

import asyncio
import json
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
from app.database import SessionLocal
from app.gateway.auth import gateway_credential_store
from app.gateway.models import (
    GatewayAuditEvent,
    GatewayConfigVersion,
    GatewayHealthCheck,
    GatewayKey,
    GatewayNode,
    utcnow,
)
from app.gateway.notifier import InMemoryConfigNotifier
from app.gateway.probe import HttpGatewayProbeClient, ProbeOutcome
from app.gateway.runtime import SCOPE_NODE, InMemoryRuntimeStore, node_runtime_scope
from app.gateway.security import CredentialCipher, gateway_key_digest, parse_credentials
from app.main import app

ROOT_TOKEN = "it-root-token"
VIEW_TOKEN = "it-view-token"
NODE_TOKEN = "it-node-token"
ROUTE_TOKEN = "it-route-token"
KEY_TOKEN = "it-key-token"
PUBLISH_TOKEN = "it-publish-token"


class FakeProbe:
    def __init__(self) -> None:
        self.success = True
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def probe(self, node, probe_types, api_key):
        self.calls.append((node.id, tuple(probe_types)))
        return [ProbeOutcome(probe_type, self.success, 3) for probe_type in probe_types]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


@pytest.fixture
def gateway_env():
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
                {"name": "node-bot", "token": NODE_TOKEN, "roles": ["node"]},
                {"name": "route-bot", "token": ROUTE_TOKEN, "roles": ["route"]},
                {"name": "key-bot", "token": KEY_TOKEN, "roles": ["key"]},
                {"name": "publisher", "token": PUBLISH_TOKEN, "roles": ["publish"]},
            ]
        )
    )
    notifier = InMemoryConfigNotifier()
    probe = FakeProbe()
    runtime = InMemoryRuntimeStore()
    overrides = {
        gateway_credential_store: lambda: store,
        gateway_cipher: lambda: CredentialCipher(master_key),
        gateway_notifier: lambda: notifier,
        gateway_probe_client: lambda: probe,
        gateway_runtime: lambda: runtime,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield SimpleNamespace(
            master_key=master_key, notifier=notifier, probe=probe, runtime=runtime
        )
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)


def create_pool(client: TestClient, *, enabled: bool = True) -> dict:
    response = client.post(
        "/api/gateway/pools",
        json={"name": unique("pool"), "enabled": enabled},
        headers=auth(ROOT_TOKEN),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_node(
    client: TestClient, pool_id: str, *, api_key: str | None = None, **extra
) -> dict:
    payload = {
        "name": unique("node"),
        "pool_id": pool_id,
        "base_url": "https://proxy.example.com",
        "models": ["gpt-test"],
    }
    if api_key is not None:
        payload["api_key"] = api_key
    payload.update(extra)
    response = client.post("/api/gateway/nodes", json=payload, headers=auth(ROOT_TOKEN))
    assert response.status_code == 201, response.text
    return response.json()


def read_scope(node_id: str) -> str:
    async def run() -> str:
        async with SessionLocal() as session:
            node = await session.get(GatewayNode, node_id)
            return node_runtime_scope(node)

    return asyncio.run(run())


def create_route(client: TestClient, pool_id: str, model: str) -> dict:
    response = client.post(
        "/api/gateway/routes",
        json={"model": model, "pool_id": pool_id},
        headers=auth(ROOT_TOKEN),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_control_plane_requires_server_side_credentials(gateway_env):
    with TestClient(app) as client:
        assert client.get("/api/gateway/pools").status_code == 401
        # 浏览器提交的身份 Header 不是可信登录。
        forged = {"X-Astra-User-Id": "admin", "X-Astra-Role": "admin"}
        assert client.get("/api/gateway/pools", headers=forged).status_code == 401
        assert client.get("/api/gateway/pools", headers=auth("wrong-token")).status_code == 401

        assert client.get("/api/gateway/pools", headers=auth(VIEW_TOKEN)).status_code == 200
        forbidden = client.post(
            "/api/gateway/pools", json={"name": unique("pool")}, headers=auth(VIEW_TOKEN)
        )
        assert forbidden.status_code == 403
        # 只有节点角色也不能改路由。
        assert (
            client.post(
                "/api/gateway/routes",
                json={"model": unique("model"), "pool_id": "gp_missing"},
                headers=auth(NODE_TOKEN),
            ).status_code
            == 403
        )


def test_node_credential_encrypted_and_key_hashed_with_redacted_responses(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"], api_key="sk-node-secret")
        assert node["has_api_key"] is True
        response_text = json.dumps(node)
        assert "sk-node-secret" not in response_text
        assert "api_key_encrypted" not in response_text

        created_key = client.post(
            "/api/gateway/keys",
            json={"name": unique("key"), "allowed_models": ["gpt-test"]},
            headers=auth(ROOT_TOKEN),
        )
        assert created_key.status_code == 201, created_key.text
        raw_key = created_key.json()["key"]
        assert raw_key.startswith("agw_")
        assert created_key.json()["key_prefix"] == raw_key[:12]

        listed = client.get("/api/gateway/keys", headers=auth(VIEW_TOKEN)).json()
        assert all("key_digest" not in item for item in listed)
        assert all("key" not in item for item in listed)

        async def read_secrets():
            async with SessionLocal() as session:
                stored_node = await session.get(GatewayNode, node["id"])
                key = await session.get(GatewayKey, created_key.json()["id"])
                return stored_node.api_key_encrypted, key.key_digest, key.key_prefix

        stored_cipher, stored_digest, stored_prefix = asyncio.run(read_secrets())
        assert stored_cipher and stored_cipher != "sk-node-secret"
        assert CredentialCipher(gateway_env.master_key).decrypt(stored_cipher) == "sk-node-secret"
        assert stored_digest == gateway_key_digest(raw_key)
        assert raw_key not in stored_digest
        assert stored_prefix == raw_key[:12]


def test_revoke_key_blocks_shared_state_before_db_and_fails_closed(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        create_node(client, pool["id"])
        created = client.post(
            "/api/gateway/keys",
            json={"name": unique("key"), "allowed_models": ["gpt-test"]},
            headers=auth(ROOT_TOKEN),
        )
        assert created.status_code == 201, created.text
        key_id = created.json()["id"]
        digest = gateway_key_digest(created.json()["key"])

        async def read_key():
            async with SessionLocal() as session:
                return await session.get(GatewayKey, key_id)

        # Redis 不可用：吊销必须结构化 503，且 DB 吊销不得提交——证明共享阻断先写。
        gateway_env.runtime.set_available(False)
        failed = client.delete(f"/api/gateway/keys/{key_id}", headers=auth(KEY_TOKEN))
        assert failed.status_code == 503
        assert asyncio.run(read_key()).revoked_at is None

        # 恢复后：先追加共享阻断状态，再提交 DB 吊销，返回成功。
        gateway_env.runtime.set_available(True)
        revoked = client.delete(f"/api/gateway/keys/{key_id}", headers=auth(KEY_TOKEN))
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revoked_at"] is not None
        assert asyncio.run(gateway_env.runtime.is_key_revoked(digest)) is True
        assert asyncio.run(read_key()).revoked_at is not None

        audits = client.get(
            "/api/gateway/audits",
            params={"resource_type": "key", "resource_id": key_id},
            headers=auth(VIEW_TOKEN),
        ).json()
        assert any(item["action"] == "key.revoke" for item in audits)


def revoked_key_digests() -> set[str]:
    async def run() -> set[str]:
        async with SessionLocal() as session:
            rows = await session.scalars(
                select(GatewayKey.key_digest).where(GatewayKey.revoked_at.is_not(None))
            )
            return {str(digest) for digest in rows if digest}

    return asyncio.run(run())


def read_key_row(key_id: str) -> GatewayKey | None:
    async def run() -> GatewayKey | None:
        async with SessionLocal() as session:
            return await session.get(GatewayKey, key_id)

    return asyncio.run(run())


def test_node_must_drain_before_delete(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        # 新节点默认安全态 DRAINING/DISABLED 可直接删除；激活后才必须先下线。
        node = create_node(client, pool["id"])
        assert node["scheduling_state"] == "DRAINING"
        for _ in range(2):
            client.post(
                f"/api/gateway/nodes/{node['id']}/probe",
                json={"probe_types": ALL_PROBES},
                headers=auth(NODE_TOKEN),
            )
        activated = client.post(f"/api/gateway/nodes/{node['id']}/activate", headers=auth(NODE_TOKEN))
        assert activated.status_code == 200
        assert activated.json()["scheduling_state"] == "ACTIVE"

        blocked = client.delete(f"/api/gateway/nodes/{node['id']}", headers=auth(NODE_TOKEN))
        assert blocked.status_code == 409
        drained = client.post(f"/api/gateway/nodes/{node['id']}/drain", headers=auth(NODE_TOKEN))
        assert drained.status_code == 200
        assert drained.json()["scheduling_state"] == "DRAINING"
        deleted = client.delete(f"/api/gateway/nodes/{node['id']}", headers=auth(NODE_TOKEN))
        assert deleted.status_code == 204


def test_probe_updates_health_streaks_without_touching_configuration(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])
        assert node["health_state"] == "UNKNOWN"

        first = client.post(
            f"/api/gateway/nodes/{node['id']}/probe", json={}, headers=auth(NODE_TOKEN)
        )
        assert first.status_code == 200
        assert first.json()["node"]["health_state"] == "UNKNOWN"

        second = client.post(
            f"/api/gateway/nodes/{node['id']}/probe", json={}, headers=auth(NODE_TOKEN)
        )
        assert second.json()["node"]["health_state"] == "HEALTHY"

        gateway_env.probe.success = False
        for _ in range(3):
            failed = client.post(
                f"/api/gateway/nodes/{node['id']}/probe", json={}, headers=auth(NODE_TOKEN)
            )
        body = failed.json()["node"]
        assert body["health_state"] == "UNHEALTHY"
        # 健康态变化不修改管理员配置态（新节点默认安全态 DISABLED/DRAINING）。
        assert body["config_state"] == "DISABLED"
        assert body["scheduling_state"] == "DRAINING"


def test_publish_validation_rollback_and_audit(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"], api_key="sk-original")
        model = unique("model")
        create_route(client, pool["id"], model)

        published = client.post(
            "/api/gateway/config/publish", json={"note": "first"}, headers=auth(ROOT_TOKEN)
        )
        assert published.status_code == 200, published.text
        version_one = published.json()["version"]
        assert gateway_env.notifier.current == version_one

        # 路由指向禁用资源池时发布会失败，当前版本保持不变。
        disabled = client.patch(
            f"/api/gateway/pools/{pool['id']}", json={"enabled": False}, headers=auth(ROUTE_TOKEN)
        )
        assert disabled.status_code == 200
        invalid = client.post(
            "/api/gateway/config/publish", json={"note": "bad"}, headers=auth(ROOT_TOKEN)
        )
        assert invalid.status_code == 422
        assert invalid.json()["errors"][0]["code"] == "ROUTE_POOL_DISABLED"
        assert gateway_env.notifier.current == version_one

        client.patch(
            f"/api/gateway/pools/{pool['id']}", json={"enabled": True}, headers=auth(ROUTE_TOKEN)
        )
        updated = client.patch(
            f"/api/gateway/nodes/{node['id']}", json={"name": "node-renamed"}, headers=auth(NODE_TOKEN)
        )
        assert updated.status_code == 200
        second = client.post(
            "/api/gateway/config/publish", json={"note": "second"}, headers=auth(ROOT_TOKEN)
        )
        assert second.status_code == 200
        version_two = second.json()["version"]
        assert version_two > version_one

        rollback = client.post(
            "/api/gateway/config/rollback",
            json={"version": version_one},
            headers=auth(ROOT_TOKEN),
        )
        assert rollback.status_code == 200, rollback.text
        version_three = rollback.json()["version"]
        assert version_three > version_two
        assert rollback.json()["source_version"] == version_one
        assert gateway_env.notifier.current == version_three

        # 回滚同步草稿：节点名恢复为版本 1 的内容。
        draft_nodes = client.get("/api/gateway/nodes", headers=auth(VIEW_TOKEN)).json()
        assert [item["name"] for item in draft_nodes if item["id"] == node["id"]] == [
            node["name"]
        ]

        versions = client.get("/api/gateway/config/versions", headers=auth(VIEW_TOKEN)).json()
        by_version = {item["version"]: item["status"] for item in versions}
        assert by_version[version_three] == "CURRENT"
        assert by_version[version_two] == "SUPERSEDED"

        detail = client.get(
            f"/api/gateway/config/versions/{version_two}", headers=auth(VIEW_TOKEN)
        ).json()
        assert "api_key_encrypted" not in json.dumps(detail["snapshot"])
        snapshot_node = next(
            item for item in detail["snapshot"]["nodes"] if item["id"] == node["id"]
        )
        assert snapshot_node["has_api_key"] is True

        audits = client.get(
            "/api/gateway/audits", params={"resource_type": "config"}, headers=auth(VIEW_TOKEN)
        ).json()
        actions = {item["action"] for item in audits}
        assert {"config.publish", "config.rollback"} <= actions

        async def count_versions():
            async with SessionLocal() as session:
                return len(list(await session.scalars(select(GatewayConfigVersion))))

        async def audit_secrets():
            async with SessionLocal() as session:
                events = list(await session.scalars(select(GatewayAuditEvent)))
                return json.dumps([event.before for event in events] + [event.after for event in events])

        assert asyncio.run(count_versions()) == 3
        audit_text = asyncio.run(audit_secrets())
        assert "sk-original" not in audit_text


def test_credential_replacements_are_audited_without_secrets(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"], api_key="sk-before")
        replaced = client.patch(
            f"/api/gateway/nodes/{node['id']}", json={"api_key": "sk-after"}, headers=auth(NODE_TOKEN)
        )
        assert replaced.status_code == 200
        audits = client.get(
            "/api/gateway/audits",
            params={"resource_type": "node", "resource_id": node["id"]},
            headers=auth(VIEW_TOKEN),
        ).json()
        update_events = [item for item in audits if item["action"] == "node.update"]
        assert update_events
        text = json.dumps(update_events)
        assert "sk-before" not in text
        assert "sk-after" not in text
        assert "has_api_key" in text


def test_credential_operations_require_master_key(gateway_env):
    with TestClient(app) as client:
        app.dependency_overrides[gateway_cipher] = lambda: CredentialCipher(None)
        pool = create_pool(client)
        rejected = client.post(
            "/api/gateway/nodes",
            json={
                "name": unique("node"),
                "pool_id": pool["id"],
                "base_url": "https://proxy.example.com",
                "models": ["gpt-test"],
                "api_key": "sk-secret",
            },
            headers=auth(ROOT_TOKEN),
        )
        assert rejected.status_code == 503
        without_secret = client.post(
            "/api/gateway/nodes",
            json={
                "name": unique("node"),
                "pool_id": pool["id"],
                "base_url": "https://proxy.example.com",
                "models": ["gpt-test"],
            },
            headers=auth(ROOT_TOKEN),
        )
        assert without_secret.status_code == 201


def test_probe_network_performs_real_dns_and_tcp():
    async def scenario():
        server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = HttpGatewayProbeClient(2.0)
        reachable = (
            await client.probe(SimpleNamespace(base_url=f"http://127.0.0.1:{port}"), ["NETWORK"], None)
        )[0]
        server.close()
        await server.wait_closed()
        refused = (
            await client.probe(SimpleNamespace(base_url=f"http://127.0.0.1:{port}"), ["NETWORK"], None)
        )[0]
        unresolved = (
            await client.probe(
                SimpleNamespace(base_url="http://astra-no-such-host.invalid:80"), ["NETWORK"], None
            )
        )[0]
        return reachable, refused, unresolved

    reachable, refused, unresolved = asyncio.run(scenario())
    assert reachable.success is True
    assert reachable.detail["port"] > 0
    assert refused.success is False
    assert unresolved.success is False


def test_probe_service_model_and_stream_use_node_configuration():
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured[request.url.path] = request
        if request.url.path == "/readyz":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            if body.get("stream"):
                sse = 'data: {"choices":[{"delta":{"content":"p"}}]}\n\ndata: [DONE]\n\n'
                return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "p"}}]})
        return httpx.Response(404)

    node = SimpleNamespace(
        base_url="https://proxy.example.com",
        models=["gpt-test"],
        auth_type="HEADER",
        auth_header="X-Api-Key",
        health_path="/readyz",
        connect_timeout_seconds=None,
        request_timeout_seconds=None,
    )
    client = HttpGatewayProbeClient(
        1.0, default_health_path="/health", transport=httpx.MockTransport(handler)
    )
    outcomes = asyncio.run(client.probe(node, ["SERVICE", "MODEL", "STREAM"], "sk-secret"))
    by_type = {outcome.probe_type: outcome for outcome in outcomes}

    assert captured["/readyz"].headers["X-Api-Key"] == "sk-secret"
    assert "Bearer" not in captured["/readyz"].headers["X-Api-Key"]
    assert captured["/v1/chat/completions"].headers["X-Api-Key"] == "sk-secret"
    assert by_type["SERVICE"].success is True
    assert by_type["MODEL"].success is True
    assert by_type["MODEL"].detail["model"] == "gpt-test"
    assert by_type["STREAM"].success is True
    assert by_type["STREAM"].detail["done"] is True


def test_probe_service_falls_back_to_configured_default_health_path():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    node = SimpleNamespace(
        base_url="https://proxy.example.com",
        models=[],
        auth_type="NONE",
        auth_header="Authorization",
        health_path="",
        connect_timeout_seconds=None,
        request_timeout_seconds=None,
    )
    client = HttpGatewayProbeClient(
        1.0, default_health_path="/internal/health", transport=httpx.MockTransport(handler)
    )
    outcome = asyncio.run(client.probe(node, ["SERVICE"], None))[0]
    assert outcome.success is True
    assert seen == ["/internal/health"]


def test_delete_node_requires_zero_active_concurrency(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])
        drained = client.post(f"/api/gateway/nodes/{node['id']}/drain", headers=auth(NODE_TOKEN))
        assert drained.status_code == 200

        # 活跃并发来自与数据面同一事实来源（按 lease 的 ZSET），而非旧计数键。
        lease = asyncio.run(
            gateway_env.runtime.acquire(SCOPE_NODE, node["id"], 0, 900)
        )
        assert lease is not None
        blocked = client.delete(f"/api/gateway/nodes/{node['id']}", headers=auth(NODE_TOKEN))
        assert blocked.status_code == 409

        asyncio.run(gateway_env.runtime.release(SCOPE_NODE, node["id"], lease))
        deleted = client.delete(f"/api/gateway/nodes/{node['id']}", headers=auth(NODE_TOKEN))
        assert deleted.status_code == 204


def test_rollback_preserves_node_health_history(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])
        for _ in range(2):
            probed = client.post(
                f"/api/gateway/nodes/{node['id']}/probe", json={}, headers=auth(NODE_TOKEN)
            )
        assert probed.json()["node"]["health_state"] == "HEALTHY"
        create_route(client, pool["id"], unique("model"))
        version_one = client.post(
            "/api/gateway/config/publish", json={"note": "v1"}, headers=auth(ROOT_TOKEN)
        ).json()["version"]
        client.patch(
            f"/api/gateway/nodes/{node['id']}", json={"name": "renamed"}, headers=auth(NODE_TOKEN)
        )
        client.post("/api/gateway/config/publish", json={"note": "v2"}, headers=auth(ROOT_TOKEN))

        async def count_health():
            async with SessionLocal() as session:
                rows = await session.scalars(
                    select(GatewayHealthCheck).where(GatewayHealthCheck.node_id == node["id"])
                )
                return len(list(rows))

        before = asyncio.run(count_health())
        assert before == 8

        rollback = client.post(
            "/api/gateway/config/rollback",
            json={"version": version_one},
            headers=auth(ROOT_TOKEN),
        )
        assert rollback.status_code == 200, rollback.text

        assert asyncio.run(count_health()) == before
        refreshed = client.get(f"/api/gateway/nodes/{node['id']}", headers=auth(VIEW_TOKEN)).json()
        assert refreshed["id"] == node["id"]
        assert refreshed["name"] == node["name"]
        # 健康态是运行观测，回滚配置不覆盖它。
        assert refreshed["health_state"] == "HEALTHY"


def test_publish_failure_keeps_immutable_version_and_previous_current(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        create_node(client, pool["id"])
        create_route(client, pool["id"], unique("model"))
        first = client.post(
            "/api/gateway/config/publish", json={"note": "v1"}, headers=auth(ROOT_TOKEN)
        )
        version_one = first.json()["version"]

        async def explode(_version, _snapshot):
            raise RuntimeError("redis unavailable")

        gateway_env.notifier.publish = explode
        failed = client.post(
            "/api/gateway/config/publish", json={"note": "v2"}, headers=auth(ROOT_TOKEN)
        )
        assert failed.status_code == 503
        # 不谎称旧配置已恢复：响应说明结果未知、待对账，当前版本以运行态为准。
        assert "对账" in failed.json()["detail"]

        versions = client.get("/api/gateway/config/versions", headers=auth(VIEW_TOKEN)).json()
        currents = [item for item in versions if item["status"] == "CURRENT"]
        assert [item["version"] for item in currents] == [version_one]
        # 结果未知的发布版本作为不可变历史保留，不被删除，并保持待对账（PENDING）。
        pending_versions = [item["version"] for item in versions if item["status"] == "PENDING"]
        assert pending_versions == [version_one + 1]


def test_concurrent_publishes_keep_unique_versions_and_single_current(gateway_env):
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(app) as client:
        pool = create_pool(client)
        create_node(client, pool["id"])
        create_route(client, pool["id"], unique("model"))

        def publish(index: int):
            return client.post(
                "/api/gateway/config/publish",
                json={"note": f"concurrent-{index}"},
                headers=auth(ROOT_TOKEN),
            )

        with ThreadPoolExecutor(max_workers=4) as pool_executor:
            responses = list(pool_executor.map(publish, range(4)))
        assert all(response.status_code == 200 for response in responses), [
            response.text for response in responses
        ]

        versions = client.get("/api/gateway/config/versions", headers=auth(VIEW_TOKEN)).json()
        numbers = [item["version"] for item in versions]
        assert len(numbers) == len(set(numbers))
        currents = [item["version"] for item in versions if item["status"] == "CURRENT"]
        assert len(currents) == 1
        assert currents[0] == max(numbers)


def test_reconcile_resolves_unknown_publish_outcome(gateway_env):
    def latest_version() -> int:
        async def read():
            async with SessionLocal() as session:
                row = await session.scalar(
                    select(GatewayConfigVersion)
                    .order_by(GatewayConfigVersion.version.desc())
                    .limit(1)
                )
                return row.version if row is not None else 0

        return asyncio.run(read())

    def add_pending(version: int) -> None:
        async def write():
            async with SessionLocal() as session:
                session.add(
                    GatewayConfigVersion(
                        version=version,
                        status="PENDING",
                        source_version=None,
                        note="pending",
                        snapshot={},
                        published_by="test",
                        published_at=utcnow(),
                    )
                )
                await session.commit()

        asyncio.run(write())

    with TestClient(app) as client:
        pool = create_pool(client)
        create_node(client, pool["id"])
        create_route(client, pool["id"], unique("model"))
        client.post("/api/gateway/config/publish", json={"note": "base"}, headers=auth(ROOT_TOKEN))

        # 运行态（Redis）已写入该版本，只是提升 CURRENT 前中断 → 对账应提升为 CURRENT。
        promoted = latest_version() + 1
        add_pending(promoted)
        gateway_env.notifier.current = promoted
        response = client.post("/api/gateway/config/reconcile", headers=auth(ROOT_TOKEN))
        assert response.status_code == 200
        # 历史用例可能遗留其他 PENDING 版本，对账会一并收敛。
        assert response.json()["changed"] >= 1

        versions = client.get("/api/gateway/config/versions", headers=auth(VIEW_TOKEN)).json()
        by_version = {item["version"]: item["status"] for item in versions}
        assert by_version[promoted] == "CURRENT"

        # 运行态指向别的版本（通知实际未生效）→ 对账标记 FAILED，不谎称生效。
        unknown = latest_version() + 1
        add_pending(unknown)
        gateway_env.notifier.current = promoted
        response = client.post("/api/gateway/config/reconcile", headers=auth(ROOT_TOKEN))
        assert response.status_code == 200
        versions = client.get("/api/gateway/config/versions", headers=auth(VIEW_TOKEN)).json()
        by_version = {item["version"]: item["status"] for item in versions}
        assert by_version[unknown] == "FAILED"
        currents = [item["version"] for item in versions if item["status"] == "CURRENT"]
        assert currents == [promoted]


def test_node_auth_configuration_validated_and_redacted_in_audit(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"], api_key="sk-node")
        updated = client.patch(
            f"/api/gateway/nodes/{node['id']}",
            json={"auth_type": "HEADER", "auth_header": "X-Api-Key"},
            headers=auth(NODE_TOKEN),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["auth_type"] == "HEADER"
        assert updated.json()["auth_header"] == "X-Api-Key"
        # 节点凭据只保留加密字段与 has_api_key，响应不含明文或密文。
        assert "custom_headers" not in updated.json()
        assert "api_key_encrypted" not in json.dumps(updated.json())

        audits = client.get(
            "/api/gateway/audits",
            params={"resource_type": "node", "resource_id": node["id"]},
            headers=auth(VIEW_TOKEN),
        ).json()
        assert "sk-node" not in json.dumps(audits)

        unknown_auth = client.patch(
            f"/api/gateway/nodes/{node['id']}",
            json={"auth_type": "TOKEN"},
            headers=auth(NODE_TOKEN),
        )
        assert unknown_auth.status_code == 409

        none_auth = client.patch(
            f"/api/gateway/nodes/{node['id']}",
            json={"auth_type": "NONE"},
            headers=auth(NODE_TOKEN),
        )
        assert none_auth.status_code == 200, none_auth.text
        assert none_auth.json()["auth_type"] == "NONE"


ALL_PROBES = ["NETWORK", "SERVICE", "MODEL", "STREAM"]


def test_node_base_url_must_be_root_without_v1_suffix(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        for bad in ("https://proxy.example.com/v1", "https://proxy.example.com/v1/"):
            rejected = client.post(
                "/api/gateway/nodes",
                json={
                    "name": unique("node"),
                    "pool_id": pool["id"],
                    "base_url": bad,
                    "models": ["gpt-test"],
                },
                headers=auth(ROOT_TOKEN),
            )
            assert rejected.status_code == 409, rejected.text

        node = create_node(client, pool["id"])
        patched = client.patch(
            f"/api/gateway/nodes/{node['id']}",
            json={"base_url": "https://proxy.example.com/v1"},
            headers=auth(NODE_TOKEN),
        )
        assert patched.status_code == 409
        refreshed = client.get(f"/api/gateway/nodes/{node['id']}", headers=auth(VIEW_TOKEN)).json()
        assert refreshed["base_url"] == "https://proxy.example.com"


def test_partial_probe_cannot_promote_unknown_health(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])
        for _ in range(3):
            partial = client.post(
                f"/api/gateway/nodes/{node['id']}/probe",
                json={"probe_types": ["NETWORK"]},
                headers=auth(NODE_TOKEN),
            ).json()["node"]
        # 仅局部探测即使连续成功也不能让 UNKNOWN 晋升为 HEALTHY。
        assert partial["health_state"] == "UNKNOWN"
        assert partial["success_streak"] == 0

        # 完整探测连续成功两次才晋升为 HEALTHY。
        for _ in range(2):
            full = client.post(
                f"/api/gateway/nodes/{node['id']}/probe",
                json={"probe_types": ALL_PROBES},
                headers=auth(NODE_TOKEN),
            ).json()["node"]
        assert full["health_state"] == "HEALTHY"


def test_activating_unhealthy_node_is_rejected(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])
        assert node["health_state"] == "UNKNOWN"
        drained = client.post(f"/api/gateway/nodes/{node['id']}/drain", headers=auth(NODE_TOKEN))
        assert drained.status_code == 200

        assert (
            client.post(
                f"/api/gateway/nodes/{node['id']}/activate", headers=auth(NODE_TOKEN)
            ).status_code
            == 409
        )
        assert (
            client.patch(
                f"/api/gateway/nodes/{node['id']}",
                json={"scheduling_state": "ACTIVE"},
                headers=auth(NODE_TOKEN),
            ).status_code
            == 409
        )
        # 未经探测的新节点不能显式以 ACTIVE 创建。
        explicit = client.post(
            "/api/gateway/nodes",
            json={
                "name": unique("node"),
                "pool_id": pool["id"],
                "base_url": "https://proxy.example.com",
                "models": ["gpt-test"],
                "scheduling_state": "ACTIVE",
            },
            headers=auth(ROOT_TOKEN),
        )
        assert explicit.status_code == 409


def test_editing_connection_fields_resets_draft_health_scope(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])

        def become_healthy() -> dict:
            for _ in range(2):
                client.post(
                    f"/api/gateway/nodes/{node['id']}/probe",
                    json={"probe_types": ALL_PROBES},
                    headers=auth(NODE_TOKEN),
                )
            return client.get(f"/api/gateway/nodes/{node['id']}", headers=auth(VIEW_TOKEN)).json()

        assert become_healthy()["health_state"] == "HEALTHY"
        assert asyncio.run(gateway_env.runtime.health(read_scope(node["id"]))) == "HEALTHY"

        # 与连接无关的字段变化不重置健康。
        client.patch(
            f"/api/gateway/nodes/{node['id']}", json={"weight": 5}, headers=auth(NODE_TOKEN)
        )
        assert (
            client.get(f"/api/gateway/nodes/{node['id']}", headers=auth(VIEW_TOKEN)).json()[
                "health_state"
            ]
            == "HEALTHY"
        )

        changes = [
            {"base_url": "https://proxy2.example.com"},
            {"auth_type": "HEADER", "auth_header": "X-Api-Key"},
            {"models": ["gpt-other"]},
            {"health_path": "/healthz"},
            {"api_key": "sk-new"},
        ]
        for payload in changes:
            assert become_healthy()["health_state"] == "HEALTHY", payload
            previous_scope = read_scope(node["id"])
            assert asyncio.run(gateway_env.runtime.health(previous_scope)) == "HEALTHY", payload
            changed = client.patch(
                f"/api/gateway/nodes/{node['id']}", json=payload, headers=auth(NODE_TOKEN)
            ).json()
            # 草稿投影重置；连接指纹变化产生新作用域（必须重新探测）。
            assert changed["health_state"] == "UNKNOWN", payload
            assert changed["success_streak"] == 0, payload
            new_scope = read_scope(node["id"])
            assert new_scope != previous_scope, payload
            assert asyncio.run(gateway_env.runtime.health(new_scope)) is None, payload
            # 旧作用域运行态不被草稿编辑抹除：它可能仍代表当前已发布连接。
            assert asyncio.run(gateway_env.runtime.health(previous_scope)) == "HEALTHY", payload


def test_new_node_defaults_to_safe_draining_disabled(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])
        # 缺省创建绝不能隐式 ACTIVE/ENABLED：新节点默认安全态且健康 UNKNOWN。
        assert node["scheduling_state"] == "DRAINING"
        assert node["config_state"] == "DISABLED"
        assert node["health_state"] == "UNKNOWN"
        # 显式以 ACTIVE 创建仍被拒绝（尚未通过完整探测）。
        explicit = client.post(
            "/api/gateway/nodes",
            json={
                "name": unique("node"),
                "pool_id": pool["id"],
                "base_url": "https://proxy.example.com",
                "models": ["gpt-test"],
                "scheduling_state": "ACTIVE",
            },
            headers=auth(ROOT_TOKEN),
        )
        assert explicit.status_code == 409


def test_draft_edit_and_probe_do_not_rewrite_published_runtime(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        node = create_node(client, pool["id"])
        create_route(client, pool["id"], unique("model"))
        for _ in range(2):
            client.post(
                f"/api/gateway/nodes/{node['id']}/probe",
                json={"probe_types": ALL_PROBES},
                headers=auth(NODE_TOKEN),
            )
        published_scope = read_scope(node["id"])
        assert asyncio.run(gateway_env.runtime.health(published_scope)) == "HEALTHY"
        published = client.post(
            "/api/gateway/config/publish", json={"note": "v1"}, headers=auth(ROOT_TOKEN)
        )
        assert published.status_code == 200, published.text

        # 编辑未发布草稿的连接：只影响草稿，已发布连接的健康/熔断保持不变。
        changed = client.patch(
            f"/api/gateway/nodes/{node['id']}",
            json={"base_url": "https://proxy2.example.com"},
            headers=auth(NODE_TOKEN),
        ).json()
        assert changed["health_state"] == "UNKNOWN"
        draft_scope = read_scope(node["id"])
        assert draft_scope != published_scope
        assert asyncio.run(gateway_env.runtime.health(published_scope)) == "HEALTHY"
        assert asyncio.run(gateway_env.runtime.circuit(published_scope)) == "CLOSED"

        # 手动探测草稿连接成功也不能以草稿结果改写已发布运行态。
        for _ in range(2):
            client.post(
                f"/api/gateway/nodes/{node['id']}/probe",
                json={"probe_types": ALL_PROBES},
                headers=auth(NODE_TOKEN),
            )
        assert asyncio.run(gateway_env.runtime.health(draft_scope)) == "HEALTHY"
        assert asyncio.run(gateway_env.runtime.health(published_scope)) == "HEALTHY"


def test_production_requires_gateway_control_credentials():
    from pydantic import ValidationError

    from app.config.settings import Settings

    master_key = Fernet.generate_key().decode()
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            gateway_enabled=True,
            gateway_master_key=master_key,
            gateway_control_credentials="",
        )
    configured = Settings(
        _env_file=None,
        environment="production",
        gateway_enabled=True,
        gateway_master_key=master_key,
        gateway_control_credentials="admin-token",
    )
    assert configured.gateway_master_key == master_key


def test_rollback_to_version_with_revoked_key_keeps_tombstone(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        create_node(client, pool["id"])
        create_route(client, pool["id"], unique("model"))
        created = client.post(
            "/api/gateway/keys",
            json={"name": unique("key"), "allowed_models": ["gpt-test"]},
            headers=auth(KEY_TOKEN),
        )
        assert created.status_code == 201, created.text
        key_id = created.json()["id"]
        digest = gateway_key_digest(created.json()["key"])

        # v1 包含启用中的 Key（enabled=True, revoked_at=None）。
        version_one = client.post(
            "/api/gateway/config/publish", json={"note": "v1"}, headers=auth(ROOT_TOKEN)
        ).json()["version"]

        revoked = client.delete(f"/api/gateway/keys/{key_id}", headers=auth(KEY_TOKEN))
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["enabled"] is False
        assert revoked.json()["revoked_at"] is not None

        # 回滚到吊销前的 v1：新快照不得再声明该 Key 可用，DB 行保持吊销 tombstone。
        rollback = client.post(
            "/api/gateway/config/rollback",
            json={"version": version_one},
            headers=auth(ROOT_TOKEN),
        )
        assert rollback.status_code == 200, rollback.text
        new_version = rollback.json()["version"]

        detail = client.get(
            f"/api/gateway/config/versions/{new_version}", headers=auth(VIEW_TOKEN)
        ).json()
        snapshot_key = next(
            item for item in detail["snapshot"]["keys"] if item["id"] == key_id
        )
        assert snapshot_key["enabled"] is False
        assert snapshot_key["revoked_at"] is not None

        stored = read_key_row(key_id)
        assert stored is not None
        assert stored.enabled is False
        assert stored.revoked_at is not None

        # 模拟 Redis 清空后从 DB 重建永久吊销：摘要仍可被重新同步并生效。
        assert digest in revoked_key_digests()
        gateway_env.runtime.clear_revocation_state()
        assert asyncio.run(gateway_env.runtime.revocation_state_ready()) is False
        asyncio.run(gateway_env.runtime.sync_revoked_key_digests(revoked_key_digests()))
        assert asyncio.run(gateway_env.runtime.is_key_revoked(digest)) is True


def test_rollback_to_version_without_revoked_key_keeps_db_tombstone(gateway_env):
    with TestClient(app) as client:
        pool = create_pool(client)
        create_node(client, pool["id"])
        create_route(client, pool["id"], unique("model"))
        # v1：该 Key 尚未创建。
        version_one = client.post(
            "/api/gateway/config/publish", json={"note": "v1"}, headers=auth(ROOT_TOKEN)
        ).json()["version"]

        created = client.post(
            "/api/gateway/keys",
            json={"name": unique("key"), "allowed_models": ["gpt-test"]},
            headers=auth(KEY_TOKEN),
        )
        assert created.status_code == 201, created.text
        key_id = created.json()["id"]
        client.post("/api/gateway/config/publish", json={"note": "v2"}, headers=auth(ROOT_TOKEN))
        client.delete(f"/api/gateway/keys/{key_id}", headers=auth(KEY_TOKEN))

        rollback = client.post(
            "/api/gateway/config/rollback",
            json={"version": version_one},
            headers=auth(ROOT_TOKEN),
        )
        assert rollback.status_code == 200, rollback.text

        # 回滚到不含该 Key 的版本也不得删除其行，否则 Redis 清空后无法重建永久吊销。
        stored = read_key_row(key_id)
        assert stored is not None
        assert stored.enabled is False
        assert stored.revoked_at is not None
        draft_keys = client.get("/api/gateway/keys", headers=auth(VIEW_TOKEN)).json()
        assert any(item["id"] == key_id for item in draft_keys)
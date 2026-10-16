"""运行总览健康判断：按服务影响，不按 QPS，P95 不使用均值。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.gateway_routes import gateway_runtime
from app.database import SessionLocal, init_database
from app.gateway.health import record_health_transition
from app.gateway.health_summary import (
    HealthFacts,
    NodeFact,
    RequestSample,
    RouteFact,
    build_trends,
    judge_health,
    window_metrics,
)
from app.gateway.models import (
    HEALTH_HEALTHY,
    HEALTH_UNHEALTHY,
    GatewayNode,
    GatewayPool,
    GatewayRequest,
    GatewayRoute,
)
from app.gateway.observability import percentile
from app.gateway.runtime import InMemoryRuntimeStore
from app.main import app

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    asyncio.run(init_database())
    yield


def _node(**overrides) -> NodeFact:
    payload = dict(
        id="node-a",
        name="node-a",
        pool_id="pool-chat",
        pool_name="chat-main",
        models=("chat",),
        enabled=True,
        scheduling="ACTIVE",
        health="HEALTHY",
        circuit_open=False,
        max_concurrency=4,
        active=1,
        last_checked_at=NOW - timedelta(seconds=30),
        probe_interval_seconds=60,
    )
    payload.update(overrides)
    return NodeFact(**payload)


def _route(**overrides) -> RouteFact:
    payload = dict(
        model="chat",
        pool_id="pool-chat",
        pool_name="chat-main",
        route_enabled=True,
        pool_enabled=True,
    )
    payload.update(overrides)
    return RouteFact(**payload)


def _sample(**overrides) -> RequestSample:
    payload = dict(
        started_at=NOW - timedelta(seconds=20),
        finished_at=NOW - timedelta(seconds=10),
        status_code=200,
        stream_interrupted=False,
        retry_count=0,
        streaming=False,
        ttft_ms=None,
        output_tps=None,
        connect_ms=None,
        ttfb_ms=None,
        duration_ms=None,
        usage_known=True,
        total_tokens=15,
        node_id="node-a",
        model="chat",
        pool_id="pool-chat",
    )
    payload.update(overrides)
    return RequestSample(**payload)


def _facts(**overrides) -> HealthFacts:
    payload = dict(
        now=NOW,
        nodes=[_node()],
        routes=[_route()],
        samples=[],
        collection_ok=True,
        instances_stale=False,
    )
    payload.update(overrides)
    return HealthFacts(**payload)


def test_redundant_node_failure_is_not_down():
    summary = judge_health(
        _facts(
            nodes=[
                _node(id="node-a", name="node-a"),
                _node(id="node-b", name="node-b", health="UNHEALTHY"),
            ]
        )
    )
    assert summary.status in {"normal", "degraded"}
    assert summary.status != "down"
    assert summary.status == "degraded"
    assert "chat-main 降级" in summary.impact_summary


def test_no_traffic_with_fresh_probes_is_normal_and_error_rate_is_absent():
    summary = judge_health(_facts())
    assert summary.status == "normal"
    assert summary.stale is False
    assert summary.metrics.error_rate is None
    assert summary.metrics.ttft_p95_ms is None
    assert any("无完成请求" in reason for reason in summary.reasons)


def test_no_traffic_with_stale_probes_is_unknown():
    summary = judge_health(
        _facts(nodes=[_node(last_checked_at=NOW - timedelta(hours=2))])
    )
    assert summary.status == "unknown"
    assert summary.stale is True
    assert summary.status != "down"


def test_collection_failure_is_unknown():
    summary = judge_health(_facts(collection_ok=False))
    assert summary.status == "unknown"
    assert summary.stale is True
    assert any("采集失败" in reason for reason in summary.reasons)


def test_fallback_exhausted_is_down():
    summary = judge_health(
        _facts(
            nodes=[
                _node(id="node-a", health="UNHEALTHY"),
                _node(id="node-b", health="UNHEALTHY"),
            ]
        )
    )
    assert summary.status == "down"
    assert "chat-main 不可用" in summary.impact_summary


def test_partial_route_outage_is_degraded_with_impact_scope():
    summary = judge_health(
        _facts(
            nodes=[
                _node(health="UNHEALTHY"),
                _node(
                    id="node-e",
                    name="node-e",
                    pool_id="pool-embed",
                    pool_name="embed",
                    models=("embed",),
                ),
            ],
            routes=[
                _route(),
                _route(model="embed", pool_id="pool-embed", pool_name="embed"),
            ],
        )
    )
    assert summary.status == "degraded"
    assert summary.status != "down"
    assert "chat-main 不可用" in summary.impact_summary
    assert "embed 正常" in summary.impact_summary


def test_retry_then_success_is_not_a_failure():
    samples = [
        _sample(retry_count=2, status_code=200, started_at=NOW - timedelta(seconds=15 + index))
        for index in range(24)
    ]
    summary = judge_health(_facts(samples=samples))
    assert summary.metrics.error_rate == 0
    assert summary.metrics.retry_rate == 1
    assert summary.metrics.error_failures == 0
    assert summary.status == "normal"


def test_stream_interrupt_counts_as_final_failure_when_sustained():
    samples = []
    for index in range(12):
        samples.append(
            _sample(
                status_code=200,
                stream_interrupted=True,
                streaming=True,
                finished_at=NOW - timedelta(seconds=10 + index),
            )
        )
    for index in range(12):
        samples.append(
            _sample(
                status_code=200,
                stream_interrupted=True,
                streaming=True,
                finished_at=NOW - timedelta(seconds=70 + index),
            )
        )
    summary = judge_health(_facts(samples=samples))
    assert summary.metrics.error_rate == 1
    assert summary.metrics.stream_interrupt_rate == 1
    assert summary.status == "degraded"
    assert summary.status != "down"


def test_small_sample_does_not_flip_health():
    samples = [_sample(status_code=500, finished_at=NOW - timedelta(seconds=5 + index)) for index in range(8)]
    summary = judge_health(_facts(samples=samples))
    assert summary.metrics.error_rate == 1
    assert summary.metrics.error_rate_applies is False
    assert summary.status == "normal"


def test_disabled_and_idle_pools_are_ignored():
    summary = judge_health(
        _facts(
            nodes=[
                _node(),
                _node(
                    id="node-off",
                    pool_id="pool-off",
                    pool_name="legacy",
                    health="UNHEALTHY",
                    models=("old",),
                ),
                _node(
                    id="node-idle",
                    pool_id="pool-idle",
                    pool_name="spare",
                    health="UNHEALTHY",
                    models=("spare",),
                ),
            ],
            routes=[
                _route(),
                _route(
                    model="old",
                    pool_id="pool-off",
                    pool_name="legacy",
                    pool_enabled=False,
                ),
                _route(
                    model="spare",
                    pool_id="pool-idle",
                    pool_name="spare",
                    route_enabled=False,
                ),
            ],
        )
    )
    assert summary.status == "normal"
    reasons = {item.pool_id: item.reason for item in summary.ignored_pools}
    assert reasons["pool-off"] == "disabled"
    assert reasons["pool-idle"] == "idle"
    assert "legacy" not in summary.impact_summary
    assert "spare" not in summary.impact_summary


def test_high_qps_does_not_change_health():
    samples = [
        _sample(started_at=NOW - timedelta(seconds=index % 50), finished_at=NOW - timedelta(seconds=1))
        for index in range(600)
    ]
    summary = judge_health(_facts(samples=samples))
    assert summary.metrics.qps > 5
    assert summary.status == "normal"


def test_ttft_p95_is_interpolated_not_the_mean():
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 0.95) == 48
    assert percentile(values, 0.95) != round(sum(values) / len(values), 3)
    samples = [
        _sample(ttft_ms=value, finished_at=NOW - timedelta(seconds=10 + index))
        for index, value in enumerate(values)
    ]
    metrics = window_metrics(samples, NOW)
    assert metrics.ttft_p95_ms == 48


def test_window_p95_is_not_the_average_of_bucket_p95s():
    samples = []
    early = NOW - timedelta(minutes=50)
    late = NOW - timedelta(minutes=5)
    for value in (1, 1, 1, 1, 1):
        samples.append(_sample(ttft_ms=value, started_at=early, finished_at=early))
    for value in (100, 100, 100, 100, 100):
        samples.append(_sample(ttft_ms=value, started_at=late, finished_at=late))
    trend = build_trends(samples, now=NOW, window="1h", group_by="none", labels={})
    bucket_p95 = [point.ttft_p95_ms for point in trend.series[0].points if point.ttft_p95_ms is not None]
    assert bucket_p95
    averaged = round(sum(bucket_p95) / len(bucket_p95), 3)
    assert trend.ttft_p95_ms == 100
    assert trend.ttft_p95_ms != averaged


def test_upstream_429_is_final_status_only():
    samples = [_sample(status_code=429) for _ in range(4)]
    samples.append(_sample(status_code=200, retry_count=1))
    metrics = window_metrics(samples, NOW)
    assert metrics.upstream_429_rate == pytest.approx(4 / 5)
    assert metrics.error_rate == pytest.approx(4 / 5)
    assert metrics.retry_rate == pytest.approx(1 / 5)


def test_in_flight_requests_are_outside_the_error_denominator():
    samples = [_sample(finished_at=None, status_code=None) for _ in range(10)]
    samples.append(_sample(status_code=500))
    metrics = window_metrics(samples, NOW)
    assert metrics.error_samples == 1
    assert metrics.error_rate == 1
    assert metrics.qps_requests == 11


class BoomRuntime(InMemoryRuntimeStore):
    async def active(self, scope: str, scope_id: str) -> int:
        raise RuntimeError("redis down")


def test_health_summary_endpoint_and_runtime_event():
    pool_id = f"pool-{uuid4().hex[:8]}"
    node_id = f"node-{uuid4().hex[:8]}"
    route_id = f"route-{uuid4().hex[:8]}"

    async def seed():
        async with SessionLocal() as session:
            session.add(GatewayPool(id=pool_id, name="chat-main", enabled=True))
            node = GatewayNode(
                id=node_id,
                name="node-a",
                pool_id=pool_id,
                base_url="https://upstream.example",
                auth_type="NONE",
                models=["chat"],
                max_concurrency=4,
                health_state=HEALTH_HEALTHY,
                last_checked_at=datetime.now(UTC),
                probe_interval_seconds=60,
            )
            session.add(node)
            session.add(
                GatewayRoute(id=route_id, model=f"chat-{route_id}", pool_id=pool_id, enabled=True)
            )
            await session.flush()
            node.health_state = HEALTH_UNHEALTHY
            record_health_transition(session, node, HEALTH_HEALTHY)
            node.health_state = HEALTH_HEALTHY
            for value in (10, 20, 30, 40, 50):
                session.add(
                    GatewayRequest(
                        id=uuid4().hex,
                        model=f"chat-{route_id}",
                        pool_id=pool_id,
                        node_id=node_id,
                        status_code=200,
                        ttft_ms=value,
                        total_tokens=10,
                        started_at=datetime.now(UTC) - timedelta(seconds=30),
                        finished_at=datetime.now(UTC) - timedelta(seconds=20),
                    )
                )
            await session.commit()

    asyncio.run(seed())
    runtime = InMemoryRuntimeStore()
    app.dependency_overrides[gateway_runtime] = lambda: runtime
    try:
        client = TestClient(app)
        response = client.get("/api/gateway/health-summary")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] in {"normal", "degraded", "down", "unknown"}
        assert "metrics" in body and "generated_at" in body
        assert body["metrics"]["queue"] is None
        assert "ttft_p95_ms" in body["metrics"]
        nodes = client.get("/api/gateway/node-metrics")
        assert nodes.status_code == 200
        assert any(item["node_id"] == node_id and item["ttft_p95_ms"] == 48 for item in nodes.json())
        trends = client.get("/api/gateway/trends", params={"window": "1h", "group_by": "node"})
        assert trends.status_code == 200
        assert trends.json()["window"] == "1h"
        events = client.get("/api/gateway/ops-events")
        assert events.status_code == 200
        matched = [
            item
            for item in events.json()
            if item["node_id"] == node_id and item["source"] == "runtime"
        ]
        assert matched
        assert matched[0]["kind"] == "health"
    finally:
        app.dependency_overrides.pop(gateway_runtime, None)


def test_collection_failure_endpoint_is_unknown():
    app.dependency_overrides[gateway_runtime] = lambda: BoomRuntime()
    try:
        response = TestClient(app).get("/api/gateway/health-summary")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "unknown"
        assert body["stale"] is True
    finally:
        app.dependency_overrides.pop(gateway_runtime, None)


def test_request_time_range_filter():
    old_id = uuid4().hex
    new_id = uuid4().hex
    model = f"range-{uuid4().hex[:8]}"
    now = datetime.now(UTC)

    async def seed():
        async with SessionLocal() as session:
            session.add(
                GatewayRequest(
                    id=old_id,
                    model=model,
                    status_code=200,
                    started_at=now - timedelta(hours=3),
                    finished_at=now - timedelta(hours=3),
                )
            )
            session.add(
                GatewayRequest(
                    id=new_id,
                    model=model,
                    status_code=200,
                    started_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=5),
                )
            )
            await session.commit()

    asyncio.run(seed())
    app.dependency_overrides[gateway_runtime] = lambda: InMemoryRuntimeStore()
    try:
        client = TestClient(app)
        response = client.get(
            "/api/gateway/requests",
            params={
                "model": model,
                "from": (now - timedelta(hours=1)).isoformat(),
                "to": now.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        ids = {item["id"] for item in response.json()["items"]}
        assert new_id in ids
        assert old_id not in ids
    finally:
        app.dependency_overrides.pop(gateway_runtime, None)

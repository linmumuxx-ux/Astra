"""API 中转运行总览的健康判断与窗口指标。

口径只来自调用日志与节点运行态，前端不得重算。P95 使用
``observability.percentile`` 的线性插值，不用均值，也不把各节点 P95 再平均。

健康判断看服务影响，不看 QPS 上限：

- 生效路由：路由启用且所属资源池启用。禁用池、以及启用但没有生效路由的空闲池不参与。
- 路由可服务：至少有一个可调度节点支持该模型。可调度 = 配置启用、调度 ACTIVE、
  健康 HEALTHY/DEGRADED、熔断未打开、并发未满。
- 最终失败：已完成请求里，流中断、缺少状态码，或状态码不在 200–399。
  重试后最终成功不算失败。``retry_count > 0`` 单独计入重试率（日志没有逐次尝试行）。
- 错误率影响健康需要近 5 分钟已完成样本 ≥ 20，且至少两个连续的 1 分钟桶各自样本 ≥ 5
  且失败率 > 2%。最近 1 分钟样本 ≥ 5 且失败率 ≤ 2% 则恢复，不再因错误率降级。
- 探测超过 ``max(180s, 3 × 探测间隔)`` 未更新，或运行态采集失败，状态为 unknown。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.models import (
    CONFIG_ENABLED,
    HEALTH_DEGRADED,
    HEALTH_HEALTHY,
    SCHEDULING_ACTIVE,
    GatewayAuditEvent,
    GatewayHealthCheck,
    GatewayNode,
    GatewayPool,
    GatewayRequest,
    GatewayRoute,
    GatewayRuntimeEvent,
)
from app.gateway.observability import percentile
from app.gateway.runtime import CIRCUIT_OPEN, RuntimeStore
from app.gateway.schemas import (
    HealthImpact,
    HealthSummary,
    HealthWindow,
    IgnoredPool,
    NodeWindowMetric,
    OpsEventRead,
    OverviewMetrics,
    TrendPoint,
    TrendRead,
    TrendSeries,
)
from app.models import utcnow

QPS_WINDOW = timedelta(seconds=60)
ERROR_WINDOW = timedelta(minutes=5)
TREND_1H = timedelta(hours=1)
TREND_15M = timedelta(minutes=15)
FAILURE_RATE_THRESHOLD = 0.02
MIN_ERROR_SAMPLE = 20
BUCKET_MIN_SAMPLE = 5
SUSTAINED_BUCKETS = 2
STALE_FLOOR_SECONDS = 180
PROBE_INTERVAL_MULTIPLIER = 3
DEFAULT_PROBE_INTERVAL_SECONDS = 60
OPS_EVENT_LIMIT = 80

STATUS_NORMAL = "normal"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"

SCHEDULABLE_HEALTH = (HEALTH_HEALTHY, HEALTH_DEGRADED)


@dataclass(frozen=True)
class RequestSample:
    started_at: datetime
    finished_at: datetime | None
    status_code: int | None
    stream_interrupted: bool
    retry_count: int
    streaming: bool
    ttft_ms: float | None
    output_tps: float | None
    connect_ms: float | None
    ttfb_ms: float | None
    duration_ms: float | None
    usage_known: bool
    total_tokens: int
    node_id: str | None
    model: str | None
    pool_id: str | None


@dataclass(frozen=True)
class NodeFact:
    id: str
    name: str
    pool_id: str | None
    pool_name: str | None
    models: tuple[str, ...]
    enabled: bool
    scheduling: str
    health: str
    circuit_open: bool
    max_concurrency: int
    active: int
    last_checked_at: datetime | None
    probe_interval_seconds: int | None


@dataclass(frozen=True)
class RouteFact:
    model: str
    pool_id: str
    pool_name: str
    route_enabled: bool
    pool_enabled: bool


@dataclass
class HealthFacts:
    now: datetime
    nodes: list[NodeFact]
    routes: list[RouteFact]
    samples: list[RequestSample]
    collection_ok: bool
    instances_stale: bool = False


def is_final_failure(sample: RequestSample) -> bool:
    """已完成请求的最终失败。进行中的请求不进入分母。"""

    if sample.finished_at is None:
        return False
    if sample.stream_interrupted:
        return True
    if sample.status_code is None:
        return True
    return not (200 <= int(sample.status_code) < 400)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def probe_stale(node: NodeFact, now: datetime) -> bool:
    interval = node.probe_interval_seconds or DEFAULT_PROBE_INTERVAL_SECONDS
    threshold = max(STALE_FLOOR_SECONDS, PROBE_INTERVAL_MULTIPLIER * interval)
    checked = _aware(node.last_checked_at)
    if checked is None:
        return True
    return (now - checked).total_seconds() > threshold


def _supports(node: NodeFact, model: str) -> bool:
    return model in node.models


def _schedulable(node: NodeFact, model: str) -> bool:
    if not node.enabled or node.scheduling != SCHEDULING_ACTIVE:
        return False
    if node.health not in SCHEDULABLE_HEALTH:
        return False
    if node.circuit_open:
        return False
    if not _supports(node, model):
        return False
    if node.max_concurrency > 0 and node.active >= node.max_concurrency:
        return False
    return True


def _effective_routes(facts: HealthFacts) -> list[RouteFact]:
    return [route for route in facts.routes if route.route_enabled and route.pool_enabled]


def _ignored_pools(facts: HealthFacts) -> list[IgnoredPool]:
    effective_pool_ids = {route.pool_id for route in _effective_routes(facts)}
    seen: dict[str, IgnoredPool] = {}
    for route in facts.routes:
        if route.pool_id in effective_pool_ids or route.pool_id in seen:
            continue
        if not route.pool_enabled:
            seen[route.pool_id] = IgnoredPool(
                pool_id=route.pool_id, pool_name=route.pool_name, reason="disabled"
            )
    enabled_pools = {route.pool_id: route.pool_name for route in facts.routes if route.pool_enabled}
    for node in facts.nodes:
        if node.pool_id and node.pool_name and node.pool_id not in enabled_pools:
            enabled_pools.setdefault(node.pool_id, node.pool_name)
    # 启用但没有任何生效路由的池。路由列表里禁用路由仍能标出池名。
    named = {route.pool_id: route.pool_name for route in facts.routes}
    for pool_id, pool_name in named.items():
        if pool_id in effective_pool_ids or pool_id in seen:
            continue
        pool_enabled = any(route.pool_id == pool_id and route.pool_enabled for route in facts.routes)
        if pool_enabled:
            seen[pool_id] = IgnoredPool(pool_id=pool_id, pool_name=pool_name, reason="idle")
        else:
            seen[pool_id] = IgnoredPool(pool_id=pool_id, pool_name=pool_name, reason="disabled")
    return list(seen.values())


def _finished_in(samples: list[RequestSample], start: datetime, end: datetime) -> list[RequestSample]:
    chosen: list[RequestSample] = []
    for sample in samples:
        finished = _aware(sample.finished_at)
        if finished is None:
            continue
        if start <= finished <= end:
            chosen.append(sample)
    return chosen


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _percentile_of(samples: list[RequestSample], attr: str) -> float | None:
    values = [value for sample in samples if (value := getattr(sample, attr)) is not None]
    return percentile(values, 0.95)


def window_metrics(samples: list[RequestSample], now: datetime) -> OverviewMetrics:
    """卡片、健康判断、节点表共用的窗口指标。没有样本的比率和 P95 为 null。"""

    error_start = now - ERROR_WINDOW
    qps_start = now - QPS_WINDOW
    finished = _finished_in(samples, error_start, now)
    started_1m = [
        sample
        for sample in samples
        if _aware(sample.started_at) is not None and qps_start <= _aware(sample.started_at) <= now
    ]
    failures = sum(1 for sample in finished if is_final_failure(sample))
    retries = sum(1 for sample in finished if sample.retry_count > 0)
    limited = sum(1 for sample in finished if sample.status_code == 429)
    streaming = [sample for sample in finished if sample.streaming]
    interrupted = sum(1 for sample in streaming if sample.stream_interrupted)
    unknown = sum(1 for sample in finished if not sample.usage_known)
    known_tokens = sum(sample.total_tokens for sample in finished if sample.usage_known)
    known_any = any(sample.usage_known for sample in finished)
    return OverviewMetrics(
        qps=round(len(started_1m) / QPS_WINDOW.total_seconds(), 6),
        qps_requests=len(started_1m),
        error_rate=_rate(failures, len(finished)),
        error_samples=len(finished),
        error_failures=failures,
        error_rate_applies=len(finished) >= MIN_ERROR_SAMPLE,
        retry_rate=_rate(retries, len(finished)),
        upstream_429_rate=_rate(limited, len(finished)),
        stream_interrupt_rate=_rate(interrupted, len(streaming)),
        ttft_p95_ms=_percentile_of(finished, "ttft_ms"),
        output_tps_p95=_percentile_of(finished, "output_tps"),
        connect_p95_ms=_percentile_of(finished, "connect_ms"),
        ttfb_p95_ms=_percentile_of(finished, "ttfb_ms"),
        duration_p95_ms=_percentile_of(finished, "duration_ms"),
        unknown_usage_share=_rate(unknown, len(finished)),
        token_throughput=(
            round(known_tokens / ERROR_WINDOW.total_seconds(), 6) if known_any else None
        ),
        known_total_tokens=known_tokens if known_any else None,
        peak_concurrency=_peak(samples, error_start, now),
        queue=None,
    )


def _peak(samples: list[RequestSample], start: datetime, end: datetime) -> int:
    events: list[tuple[datetime, int]] = []
    for sample in samples:
        started = _aware(sample.started_at)
        if started is None or started > end:
            continue
        finished = _aware(sample.finished_at) or end
        if finished < start:
            continue
        event_start = max(started, start)
        event_end = min(finished, end)
        if event_end < event_start:
            event_end = event_start
        events.append((event_start, 1))
        events.append((event_end, -1))
    events.sort(key=lambda item: (item[0], item[1]))
    current = 0
    peak = 0
    for _moment, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def _error_penalty(samples: list[RequestSample], now: datetime) -> str | None:
    """返回 'down_candidate' / 'degraded' / None。down 还要看剩余容量。"""

    finished = _finished_in(samples, now - ERROR_WINDOW, now)
    if len(finished) < MIN_ERROR_SAMPLE:
        return None
    buckets: list[list[RequestSample]] = [[] for _ in range(5)]
    for sample in finished:
        finished_at = _aware(sample.finished_at)
        if finished_at is None:
            continue
        age = (now - finished_at).total_seconds()
        if age < 0 or age >= ERROR_WINDOW.total_seconds():
            continue
        buckets[int(age // 60)].append(sample)

    def bad(bucket: list[RequestSample]) -> bool:
        if len(bucket) < BUCKET_MIN_SAMPLE:
            return False
        failures = sum(1 for sample in bucket if is_final_failure(sample))
        return failures / len(bucket) > FAILURE_RATE_THRESHOLD

    latest = buckets[0]
    if len(latest) >= BUCKET_MIN_SAMPLE:
        latest_failures = sum(1 for sample in latest if is_final_failure(sample))
        if latest_failures / len(latest) <= FAILURE_RATE_THRESHOLD:
            return None
    sustained = any(
        all(bad(buckets[index + offset]) for offset in range(SUSTAINED_BUCKETS))
        for index in range(len(buckets) - SUSTAINED_BUCKETS + 1)
    )
    if not sustained:
        return None
    return "degraded"


def _remaining_capacity(nodes: list[NodeFact], model_nodes: list[NodeFact]) -> int | None:
    """None 表示存在不限并发的可调度节点。0 表示没有剩余槽位。"""

    if any(node.max_concurrency <= 0 for node in model_nodes):
        return None
    remaining = 0
    for node in model_nodes:
        remaining += max(0, node.max_concurrency - node.active)
    if not model_nodes and not nodes:
        return 0
    return remaining


def _route_nodes(facts: HealthFacts, route: RouteFact) -> list[NodeFact]:
    return [
        node
        for node in facts.nodes
        if node.pool_id == route.pool_id and node.enabled and _supports(node, route.model)
    ]


def judge_health(facts: HealthFacts) -> HealthSummary:
    metrics = window_metrics(facts.samples, facts.now)
    ignored = _ignored_pools(facts)
    window = HealthWindow(
        qps_seconds=int(QPS_WINDOW.total_seconds()),
        error_seconds=int(ERROR_WINDOW.total_seconds()),
        start=facts.now - ERROR_WINDOW,
        end=facts.now,
    )
    base = dict(
        metrics=metrics,
        window=window,
        generated_at=facts.now,
        ignored_pools=ignored,
        impact=[],
        impact_summary="",
    )
    if not facts.collection_ok:
        return HealthSummary(
            status=STATUS_UNKNOWN,
            stale=True,
            reasons=["运行态或统计采集失败"],
            **base,
        )

    effective = _effective_routes(facts)
    impacts: list[HealthImpact] = []
    required_nodes: list[NodeFact] = []
    any_unservable = False
    any_redundant = False
    servable_nodes: list[NodeFact] = []
    for route in effective:
        supporting = _route_nodes(facts, route)
        required_nodes.extend(
            node for node in supporting if node.scheduling == SCHEDULING_ACTIVE
        )
        schedulable = [node for node in supporting if _schedulable(node, route.model)]
        servable_nodes.extend(schedulable)
        weakened = [
            node
            for node in supporting
            if node.health not in SCHEDULABLE_HEALTH or node.circuit_open
        ]
        if schedulable and weakened:
            state = "degraded"
            any_redundant = True
            text = f"{route.pool_name} 降级"
        elif schedulable:
            state = "normal"
            text = f"{route.pool_name} 正常"
        else:
            state = "down"
            any_unservable = True
            text = f"{route.pool_name} 不可用"
        impacts.append(
            HealthImpact(
                pool_id=route.pool_id,
                pool_name=route.pool_name,
                model=route.model,
                state=state,
                text=text,
            )
        )

    summary = _impact_summary(impacts)
    stale_probes = any(probe_stale(node, facts.now) for node in required_nodes)
    stale = stale_probes or facts.instances_stale
    penalty = _error_penalty(facts.samples, facts.now)
    capacity_left = _remaining_capacity(facts.nodes, servable_nodes)
    reasons: list[str] = []

    if not effective:
        return HealthSummary(
            status=STATUS_UNKNOWN,
            stale=stale,
            reasons=["没有生效路由"],
            impact=impacts,
            impact_summary=summary or "没有生效路由",
            metrics=metrics,
            window=window,
            generated_at=facts.now,
            ignored_pools=ignored,
        )

    if any_unservable and all(item.state == "down" for item in impacts):
        status = STATUS_DOWN
        reasons.append("生效路由都没有可调度节点")
    elif any_unservable or any_redundant:
        status = STATUS_DEGRADED
        if any_unservable:
            reasons.append("部分生效路由没有可调度节点")
        if any_redundant:
            reasons.append("有节点不健康或熔断，路由仍有其它节点可承接")
    else:
        status = STATUS_NORMAL
        reasons.append("生效路由均可服务")

    if penalty == "degraded":
        if capacity_left == 0:
            status = STATUS_DOWN
            reasons.append("近 5 分钟最终失败率持续超过 2%，且没有剩余并发")
        else:
            if status == STATUS_NORMAL:
                status = STATUS_DEGRADED
            reasons.append("近 5 分钟最终失败率持续超过 2%")
    elif metrics.error_samples == 0 and status == STATUS_NORMAL:
        reasons.append("近 5 分钟无完成请求")

    if stale and penalty is None:
        # 探测过期时不拿健康投影判正常、降级或不可用。新鲜日志里的持续失败仍保留。
        status = STATUS_UNKNOWN
        reasons.append("探测或实例心跳超过新鲜度阈值")
    elif stale:
        reasons.append("探测或实例心跳超过新鲜度阈值")

    return HealthSummary(
        status=status,
        stale=stale or status == STATUS_UNKNOWN,
        reasons=reasons,
        impact=impacts,
        impact_summary=summary,
        metrics=metrics,
        window=window,
        generated_at=facts.now,
        ignored_pools=ignored,
    )


def _impact_summary(impacts: list[HealthImpact]) -> str:
    by_pool: dict[str, list[HealthImpact]] = {}
    for item in impacts:
        by_pool.setdefault(item.pool_id, []).append(item)
    phrases: list[str] = []
    rank = {"down": 2, "degraded": 1, "normal": 0}
    for group in by_pool.values():
        worst = max(group, key=lambda item: rank.get(item.state, 0))
        states = {item.state for item in group}
        if len(states) == 1:
            phrases.append(worst.text)
            continue
        for item in group:
            label = {"down": "不可用", "degraded": "降级", "normal": "正常"}[item.state]
            phrases.append(f"{item.pool_name}/{item.model} {label}")
    return ", ".join(phrases)


def health_label(state: str) -> tuple[str, str]:
    if state == HEALTH_HEALTHY:
        return "healthy", "健康"
    if state in ("UNHEALTHY", HEALTH_DEGRADED):
        return "unhealthy", "不健康"
    return "unknown", "未知"


def scheduling_label(node: NodeFact, *, runtime_ok: bool) -> tuple[str, str]:
    if not node.enabled or node.scheduling != SCHEDULING_ACTIVE:
        return "disabled", "手动停用"
    if not runtime_ok:
        return "available", "可用"
    if node.circuit_open:
        return "circuit", "熔断"
    if node.max_concurrency > 0 and node.active >= node.max_concurrency:
        return "limited", "限流"
    return "available", "可用"


def node_window_metrics(facts: HealthFacts) -> list[NodeWindowMetric]:
    metrics_by_node: list[NodeWindowMetric] = []
    for node in facts.nodes:
        own = [sample for sample in facts.samples if sample.node_id == node.id]
        metrics = window_metrics(own, facts.now)
        health, health_text = health_label(node.health)
        scheduling, scheduling_text = scheduling_label(node, runtime_ok=facts.collection_ok)
        limit = node.max_concurrency if node.max_concurrency > 0 else None
        occupancy = None
        active: int | None = node.active if facts.collection_ok else None
        if facts.collection_ok and limit:
            occupancy = round(node.active / limit, 6)
        abnormal = health != "healthy" or scheduling != "available"
        if (
            facts.collection_ok
            and metrics.error_rate is not None
            and metrics.error_samples >= BUCKET_MIN_SAMPLE
            and metrics.error_rate > FAILURE_RATE_THRESHOLD
        ):
            abnormal = True
        metrics_by_node.append(
            NodeWindowMetric(
                node_id=node.id,
                name=node.name,
                pool_id=node.pool_id,
                pool_name=node.pool_name,
                health=health,
                health_label=health_text,
                scheduling=scheduling,
                scheduling_label=scheduling_text,
                active=active,
                capacity_limit=limit,
                occupancy=occupancy,
                queue=None,
                qps=metrics.qps,
                error_rate=metrics.error_rate,
                error_samples=metrics.error_samples,
                ttft_p95_ms=metrics.ttft_p95_ms,
                retry_rate=metrics.retry_rate,
                abnormal=abnormal,
            )
        )
    rank = {"disabled": 0, "circuit": 1, "limited": 2, "available": 3}
    metrics_by_node.sort(
        key=lambda item: (
            0 if item.abnormal else 1,
            rank.get(item.scheduling, 9),
            -(item.error_rate or 0),
            item.name,
        )
    )
    return metrics_by_node


def build_trends(
    samples: list[RequestSample],
    *,
    now: datetime,
    window: str,
    group_by: str,
    labels: dict[str, str],
) -> TrendRead:
    span = TREND_1H if window == "1h" else TREND_15M
    bucket_seconds = 300 if window == "1h" else 60
    start = now - span
    count = int(span.total_seconds() // bucket_seconds)
    starts = [start + timedelta(seconds=index * bucket_seconds) for index in range(count)]
    chosen = [
        sample
        for sample in samples
        if _aware(sample.started_at) is not None and start <= _aware(sample.started_at) <= now
    ]
    groups: dict[str, list[RequestSample]] = {"all": chosen}
    if group_by == "model":
        for sample in chosen:
            if sample.model:
                groups.setdefault(sample.model, []).append(sample)
    elif group_by == "node":
        for sample in chosen:
            if sample.node_id:
                groups.setdefault(sample.node_id, []).append(sample)

    def points_for(rows: list[RequestSample]) -> list[TrendPoint]:
        buckets: list[list[RequestSample]] = [[] for _ in starts]
        for sample in rows:
            started = _aware(sample.started_at)
            if started is None:
                continue
            index = int((started - start).total_seconds() // bucket_seconds)
            if 0 <= index < len(buckets):
                buckets[index].append(sample)
        points: list[TrendPoint] = []
        for index, bucket_start in enumerate(starts):
            bucket = buckets[index]
            finished = [sample for sample in bucket if sample.finished_at is not None]
            failures = sum(1 for sample in finished if is_final_failure(sample))
            points.append(
                TrendPoint(
                    bucket_start=bucket_start,
                    requests=len(bucket),
                    errors=failures,
                    error_rate=_rate(failures, len(finished)),
                    ttft_p95_ms=_percentile_of(finished, "ttft_ms"),
                    output_tps_p95=_percentile_of(finished, "output_tps"),
                    total_tokens=sum(sample.total_tokens for sample in finished if sample.usage_known),
                )
            )
        return points

    ordered_keys = ["all"] + sorted(
        (key for key in groups if key != "all"),
        key=lambda key: len(groups[key]),
        reverse=True,
    )[:8]
    series = [
        TrendSeries(
            key=key,
            label="全部" if key == "all" else labels.get(key, key),
            points=points_for(groups[key]),
        )
        for key in ordered_keys
        if key in groups
    ]
    finished = [sample for sample in chosen if sample.finished_at is not None]
    return TrendRead(
        window=window,
        group_by=group_by,
        window_start=start,
        window_end=now,
        bucket_seconds=bucket_seconds,
        series=series,
        ttft_p95_ms=_percentile_of(finished, "ttft_ms"),
        output_tps_p95=_percentile_of(finished, "output_tps"),
    )


def _sample_from_row(row: Any) -> RequestSample:
    known = row.input_tokens is not None or row.output_tokens is not None or row.total_tokens is not None
    total = int(row.total_tokens or 0) if known else 0
    return RequestSample(
        started_at=row.started_at,
        finished_at=row.finished_at,
        status_code=row.status_code,
        stream_interrupted=bool(row.stream_interrupted),
        retry_count=int(row.retry_count or 0),
        streaming=bool(row.streaming),
        ttft_ms=_number(row.ttft_ms),
        output_tps=_number(row.output_tps),
        connect_ms=_number(row.connect_ms),
        ttfb_ms=_number(row.ttfb_ms),
        duration_ms=_number(row.duration_ms),
        usage_known=known,
        total_tokens=total,
        node_id=row.node_id,
        model=row.model,
        pool_id=row.pool_id,
    )


class GatewayOpsService:
    def __init__(self, session: AsyncSession, *, runtime: RuntimeStore | None = None) -> None:
        self._session = session
        self._runtime = runtime

    async def _load_samples(self, since: datetime) -> list[RequestSample]:
        rows = (
            await self._session.scalars(
                select(GatewayRequest).where(
                    or_(
                        GatewayRequest.started_at >= since,
                        GatewayRequest.finished_at >= since,
                    )
                )
            )
        ).all()
        return [_sample_from_row(row) for row in rows]

    async def _facts(self, *, horizon: timedelta) -> HealthFacts:
        now = utcnow()
        nodes = list(await self._session.scalars(select(GatewayNode)))
        pools = list(await self._session.scalars(select(GatewayPool)))
        routes = list(await self._session.scalars(select(GatewayRoute)))
        pool_names = {pool.id: pool.name for pool in pools}
        pool_enabled = {pool.id: pool.enabled for pool in pools}
        collection_ok = True
        instances_stale = False
        active: dict[str, int] = {}
        circuit_open: dict[str, bool] = {}
        if self._runtime is None:
            collection_ok = False
        else:
            try:
                for node in nodes:
                    active[node.id] = int(await self._runtime.active("node", node.id))
                    circuit_open[node.id] = await self._runtime.circuit(node.id) == CIRCUIT_OPEN
                instances = await self._runtime.list_instances()
                if instances and all(item.get("status") != "ACTIVE" for item in instances):
                    instances_stale = True
            except Exception:  # noqa: BLE001 - 采集失败必须变成 unknown，不能当成 0
                collection_ok = False
        node_facts = [
            NodeFact(
                id=node.id,
                name=node.name,
                pool_id=node.pool_id,
                pool_name=pool_names.get(node.pool_id or ""),
                models=tuple(node.models or []),
                enabled=node.config_state == CONFIG_ENABLED,
                scheduling=node.scheduling_state,
                health=node.health_state,
                circuit_open=circuit_open.get(node.id, False),
                max_concurrency=int(node.max_concurrency or 0),
                active=active.get(node.id, 0),
                last_checked_at=node.last_checked_at,
                probe_interval_seconds=node.probe_interval_seconds,
            )
            for node in nodes
        ]
        route_facts = []
        for route in routes:
            enabled = pool_enabled.get(route.pool_id, False)
            route_facts.append(
                RouteFact(
                    model=route.model,
                    pool_id=route.pool_id,
                    pool_name=pool_names.get(route.pool_id, route.pool_id),
                    route_enabled=bool(route.enabled),
                    pool_enabled=enabled,
                )
            )
        samples = await self._load_samples(now - horizon)
        return HealthFacts(
            now=now,
            nodes=node_facts,
            routes=route_facts,
            samples=samples,
            collection_ok=collection_ok,
            instances_stale=instances_stale,
        )

    async def health_summary(self) -> HealthSummary:
        facts = await self._facts(horizon=ERROR_WINDOW)
        summary = judge_health(facts)
        if facts.collection_ok:
            active_sum = sum(node.active for node in facts.nodes)
            limited = [node for node in facts.nodes if node.enabled and node.max_concurrency > 0]
            limit_sum = sum(node.max_concurrency for node in limited)
            occupancy = round(active_sum / limit_sum, 6) if limit_sum else None
            summary.metrics.active = active_sum
            summary.metrics.capacity_limit = limit_sum or None
            summary.metrics.capacity_occupancy = occupancy
        return summary

    async def node_metrics(self) -> list[NodeWindowMetric]:
        facts = await self._facts(horizon=ERROR_WINDOW)
        return node_window_metrics(facts)

    async def trends(self, *, window: str = "1h", group_by: str = "none") -> TrendRead:
        if window not in ("1h", "15m"):
            window = "1h"
        if group_by not in ("none", "model", "node"):
            group_by = "none"
        span = TREND_1H if window == "1h" else TREND_15M
        facts = await self._facts(horizon=span)
        labels = {node.id: node.name for node in facts.nodes}
        return build_trends(
            facts.samples, now=facts.now, window=window, group_by=group_by, labels=labels
        )

    async def ops_events(self, *, limit: int = 50) -> list[OpsEventRead]:
        cap = max(1, min(limit, 200))
        audits = list(
            await self._session.scalars(
                select(GatewayAuditEvent)
                .order_by(GatewayAuditEvent.created_at.desc(), GatewayAuditEvent.id.desc())
                .limit(OPS_EVENT_LIMIT)
            )
        )
        runtime_events = list(
            await self._session.scalars(
                select(GatewayRuntimeEvent)
                .order_by(GatewayRuntimeEvent.created_at.desc(), GatewayRuntimeEvent.id.desc())
                .limit(OPS_EVENT_LIMIT)
            )
        )
        probes = list(
            await self._session.scalars(
                select(GatewayHealthCheck)
                .where(GatewayHealthCheck.success.is_(False))
                .order_by(GatewayHealthCheck.created_at.desc(), GatewayHealthCheck.id.desc())
                .limit(OPS_EVENT_LIMIT)
            )
        )
        events: list[OpsEventRead] = []
        for row in audits:
            node_id = row.resource_id if row.resource_type == "node" else None
            model = None
            if row.resource_type == "route":
                model = (row.after or {}).get("model") or (row.before or {}).get("model")
            events.append(
                OpsEventRead(
                    id=f"audit-{row.id}",
                    source="config",
                    kind=row.action,
                    summary=f"{row.action} · {row.resource_type} {row.resource_id or ''}".strip(),
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    node_id=node_id,
                    model=model if isinstance(model, str) else None,
                    pool_id=row.resource_id if row.resource_type == "pool" else None,
                    created_at=row.created_at,
                )
            )
        for row in runtime_events:
            events.append(
                OpsEventRead(
                    id=f"runtime-{row.id}",
                    source=row.source or "runtime",
                    kind=row.kind,
                    summary=row.summary,
                    resource_type="node" if row.node_id else None,
                    resource_id=row.node_id,
                    node_id=row.node_id,
                    model=row.model,
                    pool_id=row.pool_id,
                    created_at=row.created_at,
                )
            )
        for row in probes:
            events.append(
                OpsEventRead(
                    id=f"probe-{row.id}",
                    source="runtime",
                    kind="probe_failed",
                    summary=f"探测失败 {row.probe_type}" + (f"：{row.error}" if row.error else ""),
                    resource_type="node",
                    resource_id=row.node_id,
                    node_id=row.node_id,
                    created_at=row.created_at,
                )
            )
        events.sort(key=lambda item: item.created_at, reverse=True)
        return events[:cap]

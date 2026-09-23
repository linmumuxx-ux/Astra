"""API 中转控制面服务：CRUD、探测、草稿校验、发布 / 回滚与审计。"""

from __future__ import annotations

import asyncio
import copy
import weakref
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.health import (
    apply_probe_outcome,
    build_health_checks,
    probe_complete,
    probe_detail,
    probe_success,
)
from app.gateway.models import (
    AUTH_NONE,
    AUTH_TYPES,
    CONFIG_DISABLED,
    CONFIG_ENABLED,
    HEALTH_DEGRADED,
    HEALTH_HEALTHY,
    HEALTH_UNKNOWN,
    PROBE_TYPES,
    SCHEDULING_ACTIVE,
    SCHEDULING_BLOCKED,
    SCHEDULING_DRAINING,
    VERSION_CURRENT,
    VERSION_FAILED,
    VERSION_PENDING,
    VERSION_SUPERSEDED,
    GatewayAuditEvent,
    GatewayConfigVersion,
    GatewayHealthCheck,
    GatewayKey,
    GatewayNode,
    GatewayPool,
    GatewayRoute,
)
from app.gateway.notifier import ConfigNotifier, GatewayNotificationError
from app.gateway.probe import GatewayProbeClient
from app.gateway.runtime import SCOPE_NODE, RuntimeStore, node_runtime_scope
from app.gateway.schemas import (
    AuditEventRead,
    ConfigVersionDetail,
    ConfigVersionRead,
    DraftValidationRead,
    GatewayKeyCreate,
    GatewayKeyPatch,
    HealthCheckRead,
    NodeCreate,
    NodePatch,
    PoolCreate,
    PoolPatch,
    RouteCreate,
    RoutePatch,
    ValidationErrorRead,
)
from app.gateway.security import (
    CredentialCipher,
    gateway_key_digest,
    gateway_key_prefix,
    generate_gateway_key,
)
from app.models import utcnow

# 探测失败时熔断打开窗口：与数据面保持一致（OPEN 30 秒后进入 HALF_OPEN）。
RUNTIME_CIRCUIT_OPEN_SECONDS = 30
# 同一进程内的发布串行化：DB 行锁负责跨进程，进程锁负责跨协程，保证版本号单调。
# 锁按事件循环创建，避免同一进程内多个事件循环（如测试）复用同一 asyncio.Lock。
_PUBLISH_LOCKS: weakref.WeakKeyDictionary[Any, asyncio.Lock] = weakref.WeakKeyDictionary()


def _publish_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _PUBLISH_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _PUBLISH_LOCKS[loop] = lock
    return lock
VALID_CONFIG_STATES = {CONFIG_ENABLED, CONFIG_DISABLED}
VALID_SCHEDULING_STATES = {SCHEDULING_ACTIVE, SCHEDULING_DRAINING, SCHEDULING_BLOCKED}
VALID_QUOTA_POLICIES = {"STOP", "ALERT", "RECORD"}

# 回滚同步草稿时保留的节点运行态字段：健康态属于运行观测，不由配置版本覆盖。
NODE_RUNTIME_FIELDS = frozenset(
    {"health_state", "success_streak", "failure_streak", "health_detail", "last_checked_at"}
)

# 改变节点可达性或认证的配置字段：任一变化都让旧健康态失效，必须重新完整探测后
# 才允许被调度，避免旧健康状态继续授权新配置。凭据（api_key）单独判断。
NODE_CONNECTION_FIELDS = ("base_url", "auth_type", "auth_header", "models", "health_path")


class GatewayError(Exception):
    """控制面领域错误基类。"""


class GatewayNotFound(GatewayError):
    pass


class GatewayConflict(GatewayError):
    pass


class GatewayForbidden(GatewayError):
    pass


class GatewayValidationFailed(GatewayError):
    def __init__(self, errors: list[ValidationErrorRead]) -> None:
        self.errors = errors
        super().__init__("草稿校验失败")


class GatewayRuntimeUnavailable(GatewayError):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class GatewayControlService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        cipher: CredentialCipher,
        notifier: ConfigNotifier,
        probe_client: GatewayProbeClient,
        runtime: RuntimeStore | None = None,
        circuit_open_seconds: int = RUNTIME_CIRCUIT_OPEN_SECONDS,
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._notifier = notifier
        self._probe_client = probe_client
        self._runtime = runtime
        self._circuit_open_seconds = circuit_open_seconds

    # ── 审计 ───────────────────────────────────────────────────────────

    def _audit(
        self,
        *,
        actor: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        result: str = "SUCCESS",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            GatewayAuditEvent(
                actor=actor,
                actor_role=actor_role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                before=before or {},
                after=after or {},
            )
        )

    async def list_audits(
        self,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        limit: int = 100,
    ) -> list[GatewayAuditEvent]:
        stmt = select(GatewayAuditEvent).order_by(GatewayAuditEvent.created_at.desc()).limit(limit)
        if resource_type:
            stmt = stmt.where(GatewayAuditEvent.resource_type == resource_type)
        if resource_id:
            stmt = stmt.where(GatewayAuditEvent.resource_id == resource_id)
        return list(await self._session.scalars(stmt))

    # ── 落库 / 回滚 ────────────────────────────────────────────────────

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise GatewayConflict("唯一约束冲突，请检查名称或模型是否重复") from exc

    # ── Pool ───────────────────────────────────────────────────────────

    async def list_pools(self) -> list[GatewayPool]:
        return list(
            await self._session.scalars(
                select(GatewayPool).order_by(GatewayPool.sort_order, GatewayPool.name)
            )
        )

    async def get_pool(self, pool_id: str) -> GatewayPool:
        pool = await self._session.get(GatewayPool, pool_id)
        if not pool:
            raise GatewayNotFound("资源池不存在")
        return pool

    async def create_pool(self, payload: PoolCreate, *, actor: str, actor_role: str) -> GatewayPool:
        pool = GatewayPool(id=f"gp_{uuid4().hex[:12]}", **payload.model_dump())
        self._session.add(pool)
        await self._session.flush()
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="pool.create",
            resource_type="pool",
            resource_id=pool.id,
            after=self._pool_dict(pool),
        )
        await self._commit()
        return pool

    async def update_pool(
        self, pool_id: str, payload: PoolPatch, *, actor: str, actor_role: str
    ) -> GatewayPool:
        pool = await self.get_pool(pool_id)
        before = self._pool_dict(pool)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(pool, field, value)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="pool.update",
            resource_type="pool",
            resource_id=pool.id,
            before=before,
            after=self._pool_dict(pool),
        )
        await self._commit()
        return pool

    async def delete_pool(self, pool_id: str, *, actor: str, actor_role: str) -> None:
        pool = await self.get_pool(pool_id)
        node_count = await self._session.scalar(
            select(func.count()).select_from(GatewayNode).where(GatewayNode.pool_id == pool_id)
        )
        route_count = await self._session.scalar(
            select(func.count()).select_from(GatewayRoute).where(GatewayRoute.pool_id == pool_id)
        )
        if node_count or route_count:
            raise GatewayConflict("资源池仍被节点或路由引用，无法删除")
        before = self._pool_dict(pool)
        await self._session.delete(pool)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="pool.delete",
            resource_type="pool",
            resource_id=pool_id,
            before=before,
        )
        await self._commit()

    # ── Node ───────────────────────────────────────────────────────────

    async def list_nodes(self) -> list[GatewayNode]:
        return list(
            await self._session.scalars(
                select(GatewayNode).order_by(GatewayNode.sort_order, GatewayNode.name)
            )
        )

    async def get_node(self, node_id: str) -> GatewayNode:
        node = await self._session.get(GatewayNode, node_id)
        if not node:
            raise GatewayNotFound("节点不存在")
        return node

    async def create_node(self, payload: NodeCreate, *, actor: str, actor_role: str) -> GatewayNode:
        self._validate_node_states(payload.config_state, payload.scheduling_state, payload.quota_policy)
        self._validate_node_auth(payload.auth_type, payload.auth_header)
        self._validate_node_base_url(payload.base_url)
        if "scheduling_state" in payload.model_fields_set:
            # 显式要求以 ACTIVE 创建的新节点尚未通过任何探测，直接拒绝。
            self._validate_scheduling_activation(
                current_scheduling=SCHEDULING_DRAINING,
                target_scheduling=payload.scheduling_state,
                health_state=HEALTH_UNKNOWN,
            )
        await self._ensure_pool(payload.pool_id)
        data = payload.model_dump(exclude={"api_key"})
        api_key_encrypted = self._cipher.encrypt(payload.api_key) if payload.api_key else None
        node = GatewayNode(id=f"gn_{uuid4().hex[:12]}", api_key_encrypted=api_key_encrypted, **data)
        self._session.add(node)
        await self._session.flush()
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="node.create",
            resource_type="node",
            resource_id=node.id,
            after=self._redact_node(node),
        )
        await self._commit()
        return node

    async def update_node(
        self, node_id: str, payload: NodePatch, *, actor: str, actor_role: str
    ) -> GatewayNode:
        node = await self.get_node(node_id)
        before = self._redact_node(node)
        critical_change = self._node_connection_changed(node, payload)
        if "api_key" in payload.model_fields_set:
            if payload.api_key:
                node.api_key_encrypted = self._cipher.encrypt(payload.api_key)
            else:
                node.api_key_encrypted = None
        data = payload.model_dump(exclude={"api_key"}, exclude_unset=True)
        if data.get("pool_id"):
            await self._ensure_pool(data["pool_id"])
        if "base_url" in data:
            self._validate_node_base_url(data["base_url"])
        self._validate_node_states(
            data.get("config_state", node.config_state),
            data.get("scheduling_state", node.scheduling_state),
            data.get("quota_policy", node.quota_policy),
        )
        self._validate_node_auth(
            data.get("auth_type", node.auth_type),
            data.get("auth_header", node.auth_header),
        )
        # 连接配置一旦变化，旧健康态立即失效，不允许它继续授权新配置进入调度。
        self._validate_scheduling_activation(
            current_scheduling=node.scheduling_state,
            target_scheduling=data.get("scheduling_state", node.scheduling_state),
            health_state=HEALTH_UNKNOWN if critical_change else node.health_state,
        )
        for field, value in data.items():
            setattr(node, field, value)
        if critical_change:
            # 只重置草稿自身的健康投影。草稿编辑不得触碰已发布连接的 Redis
            # 健康/熔断：已发布连接仍由数据面服务，健康/熔断按连接指纹作用域隔离。
            self._reset_node_health(node)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="node.update",
            resource_type="node",
            resource_id=node.id,
            before=before,
            after=self._redact_node(node),
        )
        await self._commit()
        return node

    async def delete_node(self, node_id: str, *, actor: str, actor_role: str) -> None:
        node = await self.get_node(node_id)
        if node.scheduling_state != SCHEDULING_DRAINING:
            raise GatewayConflict("节点仍在调度中，请先安全下线（DRAINING）后再删除")
        # 与数据面同一事实来源：RuntimeStore.active 读取按 lease 的 ZSET。
        # 绝不能再读已废弃的计数键，否则永远得到 0 而误删活跃节点。
        if self._runtime is None:
            raise GatewayRuntimeUnavailable("运行态未配置，无法确认节点活跃并发，已拒绝删除")
        try:
            active = await self._runtime.active(SCOPE_NODE, node.id)
        except Exception as exc:  # noqa: BLE001 - Redis 不可达时拒绝删除
            raise GatewayRuntimeUnavailable(
                "无法确认节点活跃并发（Redis 不可用），已拒绝删除"
            ) from exc
        if active > 0:
            raise GatewayConflict(f"节点仍有 {active} 个活跃请求，无法删除")
        before = self._redact_node(node)
        await self._session.delete(node)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="node.delete",
            resource_type="node",
            resource_id=node_id,
            before=before,
        )
        await self._commit()

    async def set_node_scheduling(
        self, node_id: str, scheduling_state: str, *, actor: str, actor_role: str
    ) -> GatewayNode:
        node = await self.get_node(node_id)
        if scheduling_state not in VALID_SCHEDULING_STATES:
            raise GatewayConflict("非法调度状态")
        self._validate_scheduling_activation(
            current_scheduling=node.scheduling_state,
            target_scheduling=scheduling_state,
            health_state=node.health_state,
        )
        before = self._redact_node(node)
        node.scheduling_state = scheduling_state
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="node.drain" if scheduling_state == SCHEDULING_DRAINING else "node.activate",
            resource_type="node",
            resource_id=node.id,
            before=before,
            after=self._redact_node(node),
        )
        await self._commit()
        return node

    async def probe_node(
        self,
        node_id: str,
        probe_types: list[str],
        *,
        actor: str,
        actor_role: str,
    ) -> tuple[GatewayNode, list[GatewayHealthCheck]]:
        node = await self.get_node(node_id)
        selected = probe_types or list(PROBE_TYPES)
        unknown = [item for item in selected if item not in PROBE_TYPES]
        if unknown:
            raise GatewayConflict(f"未知探测类型: {', '.join(unknown)}")
        api_key = self._cipher.decrypt(node.api_key_encrypted) if node.api_key_encrypted else None
        outcomes = await self._probe_client.probe(node, selected, api_key)
        checks = build_health_checks(node.id, outcomes)
        for check in checks:
            self._session.add(check)
        success = probe_success(outcomes)
        if probe_complete(outcomes):
            apply_probe_outcome(node, success=success)
            node.health_detail = probe_detail(node, outcomes)
            await self._record_runtime_probe(node, success, node.health_detail)
        else:
            # 局部探测不推进健康也不写运行态：只有完整 NETWORK/SERVICE/MODEL/STREAM
            # 结果才能让节点脱离 UNKNOWN，避免局部成功被误判为可调度。
            node.last_checked_at = utcnow()
            node.health_detail = probe_detail(node, outcomes)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="node.probe",
            resource_type="node",
            resource_id=node.id,
            after={
                "health_state": node.health_state,
                "success_streak": node.success_streak,
                "failure_streak": node.failure_streak,
            },
        )
        await self._commit()
        return node, checks

    # ── Route ──────────────────────────────────────────────────────────

    async def list_routes(self) -> list[GatewayRoute]:
        return list(
            await self._session.scalars(
                select(GatewayRoute).order_by(GatewayRoute.model)
            )
        )

    async def get_route(self, route_id: str) -> GatewayRoute:
        route = await self._session.get(GatewayRoute, route_id)
        if not route:
            raise GatewayNotFound("路由不存在")
        return route

    async def create_route(
        self, payload: RouteCreate, *, actor: str, actor_role: str
    ) -> GatewayRoute:
        await self._ensure_pool(payload.pool_id)
        route = GatewayRoute(id=f"gr_{uuid4().hex[:12]}", **payload.model_dump())
        self._session.add(route)
        await self._session.flush()
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="route.create",
            resource_type="route",
            resource_id=route.id,
            after=self._route_dict(route),
        )
        await self._commit()
        return route

    async def update_route(
        self, route_id: str, payload: RoutePatch, *, actor: str, actor_role: str
    ) -> GatewayRoute:
        route = await self.get_route(route_id)
        before = self._route_dict(route)
        data = payload.model_dump(exclude_unset=True)
        if data.get("pool_id"):
            await self._ensure_pool(data["pool_id"])
        for field, value in data.items():
            setattr(route, field, value)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="route.update",
            resource_type="route",
            resource_id=route.id,
            before=before,
            after=self._route_dict(route),
        )
        await self._commit()
        return route

    async def delete_route(self, route_id: str, *, actor: str, actor_role: str) -> None:
        route = await self.get_route(route_id)
        before = self._route_dict(route)
        await self._session.delete(route)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="route.delete",
            resource_type="route",
            resource_id=route_id,
            before=before,
        )
        await self._commit()

    # ── Gateway Key ────────────────────────────────────────────────────

    async def list_keys(self) -> list[GatewayKey]:
        return list(
            await self._session.scalars(select(GatewayKey).order_by(GatewayKey.created_at.desc()))
        )

    async def get_key(self, key_id: str) -> GatewayKey:
        key = await self._session.get(GatewayKey, key_id)
        if not key:
            raise GatewayNotFound("Gateway Key 不存在")
        return key

    async def _lock_key(self, key_id: str) -> GatewayKey:
        """以行锁读取 Key，串行化并发 revoke 与 rollback。

        多进程下 ``FOR UPDATE`` 让吊销与回滚互斥：任一操作读到并写入的都是提交后的
        最新吊销状态，避免并发回滚覆写刚写入的吊销。SQLite 忽略 ``FOR UPDATE``，仅
        MySQL 生效。
        """

        key = await self._session.scalar(
            select(GatewayKey).where(GatewayKey.id == key_id).with_for_update()
        )
        if not key:
            raise GatewayNotFound("Gateway Key 不存在")
        return key

    async def create_key(
        self, payload: GatewayKeyCreate, *, actor: str, actor_role: str
    ) -> tuple[GatewayKey, str]:
        raw = generate_gateway_key()
        key = GatewayKey(
            id=f"gk_{uuid4().hex[:12]}",
            key_prefix=gateway_key_prefix(raw),
            key_digest=gateway_key_digest(raw),
            **payload.model_dump(),
        )
        self._session.add(key)
        await self._session.flush()
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="key.create",
            resource_type="key",
            resource_id=key.id,
            after=self._redact_key(key),
        )
        await self._commit()
        return key, raw

    async def update_key(
        self, key_id: str, payload: GatewayKeyPatch, *, actor: str, actor_role: str
    ) -> GatewayKey:
        key = await self.get_key(key_id)
        before = self._redact_key(key)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(key, field, value)
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="key.update",
            resource_type="key",
            resource_id=key.id,
            before=before,
            after=self._redact_key(key),
        )
        await self._commit()
        return key

    async def revoke_key(self, key_id: str, *, actor: str, actor_role: str) -> GatewayKey:
        # 行锁读取，避免与并发回滚交错：回滚提交前吊销不会读到并覆盖旧版本内容。
        key = await self._lock_key(key_id)
        before = self._redact_key(key)
        # 先写共享阻断状态再提交 DB 吊销：数据面按已发布快照鉴权，只改草稿不会
        # 让旧 Key 立即失效。Redis 失败时返回结构化 503，绝不谎称吊销成功。
        if self._runtime is None:
            raise GatewayRuntimeUnavailable("运行态未配置，无法写入吊销阻断状态，已拒绝吊销")
        try:
            await self._runtime.revoke_key_digest(key.key_digest)
        except Exception as exc:  # noqa: BLE001 - Redis 不可达时拒绝吊销
            raise GatewayRuntimeUnavailable(
                "吊销阻断状态未能写入运行态（Redis 不可用），已拒绝吊销，请稍后重试"
            ) from exc
        key.enabled = False
        key.revoked_at = utcnow()
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action="key.revoke",
            resource_type="key",
            resource_id=key.id,
            before=before,
            after=self._redact_key(key),
        )
        await self._commit()
        return key

    # ── 草稿校验 / 发布 / 回滚 ─────────────────────────────────────────

    async def validate_draft(self) -> DraftValidationRead:
        pools = await self.list_pools()
        nodes = await self.list_nodes()
        routes = await self.list_routes()
        errors: list[ValidationErrorRead] = []
        warnings: list[str] = []
        pool_map = {pool.id: pool for pool in pools}
        for node in nodes:
            if not node.base_url.strip():
                errors.append(self._error("NODE_BASE_URL", "节点缺少下游地址", "node", node.id))
            elif urlparse(node.base_url).path.rstrip("/").endswith("/v1"):
                errors.append(
                    self._error(
                        "NODE_BASE_URL_V1",
                        "节点地址应填写根地址，不要包含 /v1（否则会请求到 /v1/v1/...）",
                        "node",
                        node.id,
                    )
                )
            if node.health_path and not node.health_path.strip().startswith("/"):
                errors.append(
                    self._error("NODE_HEALTH_PATH", "节点健康路径必须以 / 开头", "node", node.id)
                )
            if node.pool_id and node.pool_id not in pool_map:
                errors.append(self._error("NODE_POOL_MISSING", "节点引用了不存在的资源池", "node", node.id))
            if not node.models:
                warnings.append(f"节点 {node.name} 未配置支持模型，将无法被任何路由选中")
            if node.api_key_encrypted and not self._cipher.available:
                warnings.append(f"节点 {node.name} 含有加密凭据，但当前未配置主密钥")
        for route in routes:
            if not route.model.strip():
                errors.append(self._error("ROUTE_MODEL_EMPTY", "路由缺少模型名", "route", route.id))
            pool = pool_map.get(route.pool_id)
            if not pool:
                errors.append(
                    self._error("ROUTE_POOL_MISSING", "路由指向不存在的资源池", "route", route.id)
                )
            elif not pool.enabled:
                errors.append(
                    self._error("ROUTE_POOL_DISABLED", "路由指向已禁用的资源池", "route", route.id)
                )
        active_routes = sum(1 for route in routes if route.enabled)
        counts = {
            "pools": len(pools),
            "nodes": len(nodes),
            "routes": len(routes),
            "active_routes": active_routes,
            "keys": len(await self.list_keys()),
        }
        return DraftValidationRead(
            valid=not errors, errors=errors, warnings=warnings, counts=counts
        )

    async def list_versions(self) -> list[GatewayConfigVersion]:
        return list(
            await self._session.scalars(
                select(GatewayConfigVersion).order_by(GatewayConfigVersion.version.desc())
            )
        )

    async def get_version(self, version: int) -> GatewayConfigVersion:
        row = await self._session.scalar(
            select(GatewayConfigVersion).where(GatewayConfigVersion.version == version)
        )
        if not row:
            raise GatewayNotFound("配置版本不存在")
        return row

    def version_detail(self, row: GatewayConfigVersion) -> ConfigVersionDetail:
        return ConfigVersionDetail(
            **ConfigVersionRead.model_validate(row).model_dump(),
            snapshot=redact_snapshot(row.snapshot),
        )

    async def publish(
        self, *, note: str, actor: str, actor_role: str
    ) -> GatewayConfigVersion:
        # 进程内发布串行化，避免并发发布抢占同一版本号或同时提升为 CURRENT。
        async with _publish_lock():
            validation = await self.validate_draft()
            if not validation.valid:
                self._audit(
                    actor=actor,
                    actor_role=actor_role,
                    action="config.publish",
                    resource_type="config",
                    resource_id=None,
                    result="FAILURE",
                    after={"errors": [error.model_dump() for error in validation.errors]},
                )
                await self._commit()
                raise GatewayValidationFailed(validation.errors)
            return await self._commit_version(
                snapshot=await self._build_snapshot(),
                note=note,
                actor=actor,
                actor_role=actor_role,
                source_version=None,
                action="config.publish",
            )

    async def rollback(
        self, version: int, *, actor: str, actor_role: str
    ) -> GatewayConfigVersion:
        async with _publish_lock():
            source = await self.get_version(version)
            snapshot = copy.deepcopy(source.snapshot)
            snapshot["generated_at"] = utcnow().isoformat()
            await self._apply_snapshot(snapshot)
            return await self._commit_version(
                snapshot=snapshot,
                note=f"回滚自版本 {version}",
                actor=actor,
                actor_role=actor_role,
                source_version=version,
                action="config.rollback",
            )

    async def _commit_version(
        self,
        *,
        snapshot: dict[str, Any],
        note: str,
        actor: str,
        actor_role: str,
        source_version: int | None,
        action: str,
    ) -> GatewayConfigVersion:
        """两阶段发布：先落不可变 PENDING 版本，通知成功后再提升为 CURRENT。

        通知失败或结果未知时保留该不可变版本并标记 FAILED / 待对账，绝不删除版本，
        也不谎称旧配置仍然生效——当前生效版本以 Redis 运行态与对账结果为准。
        """

        # 锁住当前版本行，跨进程串行化并保证版本号递增唯一。
        await self._session.scalar(
            select(GatewayConfigVersion)
            .where(GatewayConfigVersion.status == VERSION_CURRENT)
            .order_by(GatewayConfigVersion.version.desc())
            .with_for_update()
        )
        next_version = (
            await self._session.scalar(select(func.max(GatewayConfigVersion.version))) or 0
        ) + 1
        row = GatewayConfigVersion(
            version=next_version,
            status=VERSION_PENDING,
            source_version=source_version,
            note=note,
            snapshot=snapshot,
            published_by=actor,
            published_at=utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action=action,
            resource_type="config",
            resource_id=str(next_version),
            result="SUCCESS",
            after={
                "version": next_version,
                "status": VERSION_PENDING,
                "source_version": source_version,
                "note": note,
            },
        )
        await self._commit()
        try:
            await self._notifier.publish(next_version, snapshot)
        except Exception as exc:  # noqa: BLE001 - Redis 运行态失败以结构化 503 返回
            await self._mark_publish_uncertain(
                next_version, action=action, actor=actor, actor_role=actor_role
            )
            raise GatewayRuntimeUnavailable(
                "配置发布通知失败或结果未知：新版本已保留为待对账，"
                "当前生效版本以运行态对账为准，请检查 Redis 后重试"
            ) from exc
        await self._promote_version(
            next_version, action=action, actor=actor, actor_role=actor_role
        )
        return await self.get_version(next_version)

    async def _promote_version(
        self,
        version: int,
        *,
        action: str,
        actor: str,
        actor_role: str,
    ) -> None:
        """把已成功通知的 PENDING 版本提升为 CURRENT，并让更新的版本保持权威。"""

        target = await self._session.scalar(
            select(GatewayConfigVersion)
            .where(GatewayConfigVersion.version == version)
            .with_for_update()
        )
        current = await self._session.scalar(
            select(GatewayConfigVersion)
            .where(GatewayConfigVersion.status == VERSION_CURRENT)
            .order_by(GatewayConfigVersion.version.desc())
            .with_for_update()
        )
        if current is not None and current.version > version:
            # 更晚的版本已生效：本版本只作为历史保留，不能反向覆盖。
            if target is not None and target.status == VERSION_PENDING:
                target.status = VERSION_SUPERSEDED
        else:
            if current is not None and current.version != version:
                current.status = VERSION_SUPERSEDED
            if target is not None:
                target.status = VERSION_CURRENT
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action=action,
            resource_type="config",
            resource_id=str(version),
            result="SUCCESS",
            after={"version": version, "status": target.status if target is not None else None},
        )
        await self._commit()

    async def _mark_publish_uncertain(
        self, version: int, *, action: str, actor: str, actor_role: str
    ) -> None:
        """通知结果未知：保留不可变版本为 PENDING（待对账），不动当前生效版本。

        不标记 FAILED 是因为异常可能发生在 Redis SET 成功之后；由对账以运行态为
        权威将其收敛为 CURRENT 或 FAILED，避免误判或谎称旧配置生效。
        """

        target = await self._session.scalar(
            select(GatewayConfigVersion).where(GatewayConfigVersion.version == version)
        )
        if target is not None:
            target.status = VERSION_PENDING
        self._audit(
            actor=actor,
            actor_role=actor_role,
            action=action,
            resource_type="config",
            resource_id=str(version),
            result="FAILURE",
            after={"version": version, "status": VERSION_PENDING, "reason": "notification_unknown"},
        )
        await self._commit()

    async def reconcile_publications(self) -> int:
        """对账：把 PENDING 版本按 Redis 运行态收敛为 CURRENT 或 FAILED。

        发布通知结果未知时（例如 SET 成功但 PUBLISH 失败、连接中断），以 Redis
        当前版本为权威；无法确认（Redis 无当前版本或不可达）时保持 PENDING。
        """

        pending = list(
            await self._session.scalars(
                select(GatewayConfigVersion)
                .where(GatewayConfigVersion.status == VERSION_PENDING)
                .order_by(GatewayConfigVersion.version)
            )
        )
        if not pending:
            return 0
        try:
            remote = await self._notifier.current_version()
        except GatewayNotificationError:
            return 0
        if remote is None:
            return 0
        changed = 0
        for row in pending:
            if int(remote) == row.version:
                await self._promote_version(
                    row.version, action="config.publish.reconcile", actor="system", actor_role="system"
                )
            else:
                row.status = VERSION_FAILED
            changed += 1
        if changed:
            await self._commit()
        return changed

    async def _record_runtime_probe(
        self, node: GatewayNode, success: bool, detail: dict[str, Any]
    ) -> None:
        """把探测结果写入「草稿连接指纹」作用域，使数据面调度立即读到最新健康态。

        作用域只取决于连接参数：草稿改成不同连接后，结果落在新作用域，绝不改写
        已发布连接的运行态健康/熔断；草稿与已发布连接完全一致时才自然共享。
        """

        if self._runtime is None:
            return
        scope = node_runtime_scope(node)
        try:
            await self._runtime.record_probe(scope, success=success, detail=detail)
            if success:
                await self._runtime.set_circuit_closed(scope)
            else:
                await self._runtime.set_circuit_open(scope, self._circuit_open_seconds)
        except Exception:  # noqa: BLE001 - 运行态写入失败不阻断控制面响应
            pass

    # ── 快照 ───────────────────────────────────────────────────────────

    async def _build_snapshot(self) -> dict[str, Any]:
        pools = await self.list_pools()
        nodes = await self.list_nodes()
        routes = await self.list_routes()
        keys = await self.list_keys()
        return {
            "generated_at": utcnow().isoformat(),
            "pools": [self._pool_dict(pool) for pool in pools],
            "nodes": [self._node_snapshot(node) for node in nodes],
            "routes": [self._route_dict(route) for route in routes],
            "keys": [self._key_snapshot(key) for key in keys],
        }

    async def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        """用历史快照同步草稿。

        节点采用就地 upsert 而非删除重建，避免 CASCADE 删除健康记录；运行态
        健康字段（健康态、连击、最近检查时间）保持当前值，不被配置回滚覆盖。

        已吊销 Gateway Key 是永久 tombstone：回滚旧快照既不删除其行、也不清除
        ``revoked_at`` 或重新启用；若旧快照包含该 Key，回滚生成的新快照也会被改为
        disabled+revoked 并保留当前吊销时间，避免新版本再次声明该 Key 可用。
        """

        pools = {pool.id: pool for pool in await self.list_pools()}
        nodes = {node.id: node for node in await self.list_nodes()}
        routes = {route.id: route for route in await self.list_routes()}
        # 行锁串行化并发 revoke 与 rollback：回滚在提交前持有全部 Key 行锁，并发吊销
        # 会阻塞到提交后，因此不会出现「回滚读取到未吊销视图、随后覆写吊销」的竞态。
        keys = {
            key.id: key
            for key in await self._session.scalars(
                select(GatewayKey).order_by(GatewayKey.created_at.desc()).with_for_update()
            )
        }
        revoked_at_by_key = {
            key_id: key.revoked_at for key_id, key in keys.items() if key.revoked_at is not None
        }

        pool_ids = {item["id"] for item in snapshot.get("pools", [])}
        node_ids = {item["id"] for item in snapshot.get("nodes", [])}
        route_ids = {item["id"] for item in snapshot.get("routes", [])}
        key_ids = {item["id"] for item in snapshot.get("keys", [])}

        for route_id, route in routes.items():
            if route_id not in route_ids:
                await self._session.delete(route)
        for key_id, key in keys.items():
            # 已吊销 Key 即使不在旧快照中也不得删除：DB 行是 Redis 清空后重建永久
            # 吊销的唯一来源，删掉就等于复活。
            if key_id not in key_ids and key_id not in revoked_at_by_key:
                await self._session.delete(key)
        for node_id, node in nodes.items():
            if node_id not in node_ids:
                await self._session.delete(node)
        for pool_id, pool in pools.items():
            if pool_id not in pool_ids:
                await self._session.delete(pool)
        await self._session.flush()

        for item in snapshot.get("pools", []):
            row = pools.get(item["id"])
            if row is None:
                self._session.add(GatewayPool(**item))
            else:
                self._assign(row, item)
        for item in snapshot.get("nodes", []):
            row = nodes.get(item["id"])
            if row is None:
                self._session.add(GatewayNode(**item))
            else:
                self._assign(row, item, skip=NODE_RUNTIME_FIELDS)
        for item in snapshot.get("routes", []):
            row = routes.get(item["id"])
            if row is None:
                self._session.add(GatewayRoute(**item))
            else:
                self._assign(row, item)
        for item in snapshot.get("keys", []):
            data = dict(item)
            revoked_at = revoked_at_by_key.get(data["id"])
            if revoked_at is not None:
                # tombstone：否决旧快照声明的 enabled/revoked_at，并同步改写回滚生成的
                # 新快照条目，使其也声明 disabled+revoked。
                revoked_iso = _iso(revoked_at)
                data["enabled"] = False
                data["revoked_at"] = revoked_iso
                item["enabled"] = False
                item["revoked_at"] = revoked_iso
            data["expires_at"] = _parse_dt(data.get("expires_at"))
            data["revoked_at"] = _parse_dt(data.get("revoked_at"))
            row = keys.get(data["id"])
            if row is None:
                self._session.add(GatewayKey(**data))
            else:
                self._assign(row, data)
        await self._session.flush()

    @staticmethod
    def _assign(row: Any, data: dict[str, Any], *, skip: frozenset[str] = frozenset()) -> None:
        for field, value in data.items():
            if field in skip:
                continue
            if hasattr(row, field):
                setattr(row, field, value)

    # ── 脱敏 / 序列化 ──────────────────────────────────────────────────

    def _redact_node(self, node: GatewayNode) -> dict[str, Any]:
        return NodeReadDict.from_node(node)

    def _redact_key(self, key: GatewayKey) -> dict[str, Any]:
        return {
            "id": key.id,
            "name": key.name,
            "key_prefix": key.key_prefix,
            "owner_id": key.owner_id,
            "allowed_models": list(key.allowed_models or []),
            "max_concurrency": key.max_concurrency,
            "hourly_token_limit": key.hourly_token_limit,
            "daily_token_limit": key.daily_token_limit,
            "enabled": key.enabled,
            "expires_at": _iso(key.expires_at),
            "revoked_at": _iso(key.revoked_at),
        }

    @staticmethod
    def _pool_dict(pool: GatewayPool) -> dict[str, Any]:
        return {
            "id": pool.id,
            "name": pool.name,
            "description": pool.description,
            "weight": pool.weight,
            "enabled": pool.enabled,
            "sort_order": pool.sort_order,
        }

    @staticmethod
    def _node_snapshot(node: GatewayNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "name": node.name,
            "pool_id": node.pool_id,
            "base_url": node.base_url,
            "api_key_encrypted": node.api_key_encrypted,
            "auth_type": node.auth_type,
            "auth_header": node.auth_header,
            "connect_timeout_seconds": node.connect_timeout_seconds,
            "request_timeout_seconds": node.request_timeout_seconds,
            "health_path": node.health_path,
            "probe_interval_seconds": node.probe_interval_seconds,
            "models": list(node.models or []),
            "weight": node.weight,
            "max_concurrency": node.max_concurrency,
            "hourly_token_limit": node.hourly_token_limit,
            "daily_token_limit": node.daily_token_limit,
            "quota_policy": node.quota_policy,
            "config_state": node.config_state,
            "scheduling_state": node.scheduling_state,
            "health_state": node.health_state,
            "success_streak": node.success_streak,
            "failure_streak": node.failure_streak,
            "health_detail": dict(node.health_detail or {}),
            "sort_order": node.sort_order,
        }

    @staticmethod
    def _route_dict(route: GatewayRoute) -> dict[str, Any]:
        return {
            "id": route.id,
            "model": route.model,
            "pool_id": route.pool_id,
            "description": route.description,
            "enabled": route.enabled,
            "weight": route.weight,
        }

    @staticmethod
    def _key_snapshot(key: GatewayKey) -> dict[str, Any]:
        return {
            "id": key.id,
            "name": key.name,
            "key_prefix": key.key_prefix,
            "key_digest": key.key_digest,
            "owner_id": key.owner_id,
            "allowed_models": list(key.allowed_models or []),
            "max_concurrency": key.max_concurrency,
            "hourly_token_limit": key.hourly_token_limit,
            "daily_token_limit": key.daily_token_limit,
            "enabled": key.enabled,
            "expires_at": _iso(key.expires_at),
            "revoked_at": _iso(key.revoked_at),
        }

    # ── 校验辅助 ───────────────────────────────────────────────────────

    async def _ensure_pool(self, pool_id: str | None) -> None:
        if pool_id and not await self._session.get(GatewayPool, pool_id):
            raise GatewayConflict("资源池不存在")

    @staticmethod
    def _validate_node_states(config_state: str, scheduling_state: str, quota_policy: str) -> None:
        if config_state not in VALID_CONFIG_STATES:
            raise GatewayConflict("非法配置状态")
        if scheduling_state not in VALID_SCHEDULING_STATES:
            raise GatewayConflict("非法调度状态")
        if quota_policy not in VALID_QUOTA_POLICIES:
            raise GatewayConflict("非法额度策略")

    @staticmethod
    def _validate_node_auth(auth_type: str, auth_header: str) -> None:
        normalized = str(auth_type or "").strip().upper()
        if normalized not in AUTH_TYPES:
            raise GatewayConflict("非法认证方式")
        if normalized == AUTH_NONE:
            return
        if not (auth_header or "").strip():
            raise GatewayConflict("认证 Header 不能为空")

    @staticmethod
    def _validate_node_base_url(base_url: str) -> None:
        """节点地址必须是根地址：数据面/探测会自动追加 /v1/... 路径。"""

        path = urlparse(str(base_url or "").strip()).path.rstrip("/")
        if path.endswith("/v1"):
            raise GatewayConflict(
                "Base URL 应填写节点根地址，不要包含 /v1；"
                "Gateway 会自动追加 /v1/chat/completions，否则会请求到 /v1/v1/..."
            )

    @staticmethod
    def _validate_scheduling_activation(
        *, current_scheduling: str, target_scheduling: str, health_state: str
    ) -> None:
        """只有健康态 HEALTHY/DEGRADED 的节点才允许新进入 ACTIVE 调度。"""

        if (
            target_scheduling == SCHEDULING_ACTIVE
            and current_scheduling != SCHEDULING_ACTIVE
            and health_state not in (HEALTH_HEALTHY, HEALTH_DEGRADED)
        ):
            raise GatewayConflict(
                "节点尚未通过完整探测（健康态非 HEALTHY/DEGRADED），不能进入 ACTIVE 调度"
            )

    @staticmethod
    def _node_connection_changed(node: GatewayNode, payload: NodePatch) -> bool:
        if "api_key" in payload.model_fields_set:
            return True
        data = payload.model_dump(exclude={"api_key"}, exclude_unset=True)
        return any(
            field in data and data[field] != getattr(node, field)
            for field in NODE_CONNECTION_FIELDS
        )

    @staticmethod
    def _reset_node_health(node: GatewayNode) -> None:
        node.health_state = HEALTH_UNKNOWN
        node.success_streak = 0
        node.failure_streak = 0
        node.health_detail = {}
        node.last_checked_at = None

    @staticmethod
    def _error(code: str, message: str, resource_type: str, resource_id: str) -> ValidationErrorRead:
        return ValidationErrorRead(
            code=code, message=message, resource_type=resource_type, resource_id=resource_id
        )


class NodeReadDict:
    """节点审计用脱敏字典：绝不包含加密凭据。"""

    @staticmethod
    def from_node(node: GatewayNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "name": node.name,
            "pool_id": node.pool_id,
            "base_url": node.base_url,
            "auth_type": node.auth_type,
            "auth_header": node.auth_header,
            "connect_timeout_seconds": node.connect_timeout_seconds,
            "request_timeout_seconds": node.request_timeout_seconds,
            "health_path": node.health_path,
            "probe_interval_seconds": node.probe_interval_seconds,
            "models": list(node.models or []),
            "weight": node.weight,
            "max_concurrency": node.max_concurrency,
            "hourly_token_limit": node.hourly_token_limit,
            "daily_token_limit": node.daily_token_limit,
            "quota_policy": node.quota_policy,
            "config_state": node.config_state,
            "scheduling_state": node.scheduling_state,
            "health_state": node.health_state,
            "has_api_key": node.has_api_key,
            "sort_order": node.sort_order,
        }


def redact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """版本详情返回的脱敏快照：剔除节点密文与 Key 摘要。"""

    redacted = copy.deepcopy(snapshot or {})
    for node in redacted.get("nodes", []):
        node["has_api_key"] = bool(node.pop("api_key_encrypted", None))
    for key in redacted.get("keys", []):
        key.pop("key_digest", None)
    return redacted


def health_check_read(check: GatewayHealthCheck) -> HealthCheckRead:
    return HealthCheckRead.model_validate(check)


def audit_read(event: GatewayAuditEvent) -> AuditEventRead:
    return AuditEventRead.model_validate(event)
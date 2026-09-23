"""API 中转持久化模型。

草稿配置（节点 / Pool / 路由 / Key）保存在可编辑表；发布时生成不可变版本
快照。调用日志与健康记录只保存元数据，不保存 Prompt、Authorization 或原始
响应体。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime, utcnow

# 三维节点状态：配置态、健康态、调度态相互独立。
CONFIG_ENABLED = "ENABLED"
CONFIG_DISABLED = "DISABLED"
# 健康态：UNKNOWN 表示尚未通过完整探测，CHECKING 表示探测进行中，DEGRADED 表示
# 被动故障降级但未达到摘除阈值。只有 HEALTHY / DEGRADED 允许被数据面调度。
HEALTH_UNKNOWN = "UNKNOWN"
HEALTH_CHECKING = "CHECKING"
HEALTH_HEALTHY = "HEALTHY"
HEALTH_DEGRADED = "DEGRADED"
HEALTH_UNHEALTHY = "UNHEALTHY"
HEALTH_STATES = (
    HEALTH_UNKNOWN,
    HEALTH_CHECKING,
    HEALTH_HEALTHY,
    HEALTH_DEGRADED,
    HEALTH_UNHEALTHY,
)
# 调度态：ACTIVE 允许新请求，DRAINING 仅阻止新请求，BLOCKED 由额度或管理员显式阻止。
SCHEDULING_ACTIVE = "ACTIVE"
SCHEDULING_DRAINING = "DRAINING"
SCHEDULING_BLOCKED = "BLOCKED"
SCHEDULING_STATES = (SCHEDULING_ACTIVE, SCHEDULING_DRAINING, SCHEDULING_BLOCKED)

PROBE_NETWORK = "NETWORK"
PROBE_SERVICE = "SERVICE"
PROBE_MODEL = "MODEL"
PROBE_STREAM = "STREAM"
PROBE_TYPES = (PROBE_NETWORK, PROBE_SERVICE, PROBE_MODEL, PROBE_STREAM)

# 节点下游认证方式：Bearer Token、自定义 Header（值取自加密的 api_key_encrypted）、
# 无认证。自定义 Header 名称由 auth_header 指定，凭据值绝不单独明文落库。
AUTH_BEARER = "BEARER"
AUTH_HEADER = "HEADER"
AUTH_NONE = "NONE"
AUTH_TYPES = (AUTH_BEARER, AUTH_HEADER, AUTH_NONE)
DEFAULT_HEALTH_PATH = "/health"

# 配置版本状态机：草稿发布先生成不可变 PENDING 版本，运行态通知成功后才提升为
# CURRENT；通知失败/结果未知保留为 FAILED 或 PENDING，由对账收敛，绝不删除版本。
VERSION_CURRENT = "CURRENT"
VERSION_SUPERSEDED = "SUPERSEDED"
VERSION_PENDING = "PENDING"
VERSION_FAILED = "FAILED"


class GatewayPool(Base):
    __tablename__ = "gateway_pools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class GatewayNode(Base):
    __tablename__ = "gateway_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    pool_id: Mapped[str | None] = mapped_column(
        ForeignKey("gateway_pools.id", ondelete="SET NULL"), nullable=True, index=True
    )
    base_url: Mapped[str] = mapped_column(String(512))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str] = mapped_column(String(16), default=AUTH_BEARER)
    auth_header: Mapped[str] = mapped_column(String(64), default="Authorization")
    connect_timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    request_timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_path: Mapped[str] = mapped_column(String(256), default="")
    probe_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=0)
    hourly_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_policy: Mapped[str] = mapped_column(String(16), default="STOP")
    config_state: Mapped[str] = mapped_column(String(16), default=CONFIG_ENABLED, index=True)
    scheduling_state: Mapped[str] = mapped_column(String(16), default=SCHEDULING_ACTIVE, index=True)
    health_state: Mapped[str] = mapped_column(String(16), default=HEALTH_UNKNOWN, index=True)
    success_streak: Mapped[int] = mapped_column(Integer, default=0)
    failure_streak: Mapped[int] = mapped_column(Integer, default=0)
    health_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_encrypted)


class GatewayRoute(Base):
    __tablename__ = "gateway_routes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    pool_id: Mapped[str] = mapped_column(ForeignKey("gateway_pools.id", ondelete="RESTRICT"), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class GatewayKey(Base):
    __tablename__ = "gateway_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    key_prefix: Mapped[str] = mapped_column(String(24), index=True)
    key_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    allowed_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=0)
    hourly_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class GatewayConfigVersion(Base):
    __tablename__ = "gateway_config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default=VERSION_CURRENT, index=True)
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    published_by: Mapped[str] = mapped_column(String(120), default="system")
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class GatewayHealthCheck(Base):
    __tablename__ = "gateway_health_checks"
    __table_args__ = (Index("ix_gateway_health_node_time", "node_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("gateway_nodes.id", ondelete="CASCADE"), index=True)
    probe_type: Mapped[str] = mapped_column(String(16), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class GatewayRequest(Base):
    """调用日志：只保留元数据与测量值，不保存 Prompt / Authorization / 响应体。"""

    __tablename__ = "gateway_requests"
    __table_args__ = (
        Index("ix_gateway_requests_time", "started_at"),
        Index("ix_gateway_requests_key_time", "key_id", "started_at"),
        Index("ix_gateway_requests_node_time", "node_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pool_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stream_interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    connect_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttfb_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class GatewayAuditEvent(Base):
    __tablename__ = "gateway_audit_events"
    __table_args__ = (Index("ix_gateway_audit_resource", "resource_type", "resource_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(120), index=True)
    actor_role: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result: Mapped[str] = mapped_column(String(16), default="SUCCESS", index=True)
    before: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
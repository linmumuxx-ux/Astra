"""已发布配置的内存视图与版本收敛。

数据面每次请求只读 :class:`GatewayConfigState` 里的内存快照，绝不查询 MySQL。
启动时从数据库加载最近一个 ``CURRENT`` 版本；随后由 :class:`ConfigReconciler`
按 Redis 当前版本号轮询收敛，Redis 通知丢失时也能追平。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.models import VERSION_CURRENT, GatewayConfigVersion
from app.gateway.runtime import node_runtime_scope


def _text(value: Any, default: str = "") -> str:
    return str(value) if value is not None else default


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(frozen=True)
class PoolConfig:
    id: str
    name: str
    weight: int
    enabled: bool


@dataclass(frozen=True)
class NodeConfig:
    id: str
    name: str
    pool_id: str | None
    base_url: str
    api_key_encrypted: str | None
    auth_type: str
    auth_header: str
    connect_timeout_seconds: float | None
    request_timeout_seconds: float | None
    health_path: str
    probe_interval_seconds: int | None
    models: tuple[str, ...]
    weight: int
    max_concurrency: int
    hourly_token_limit: int | None
    daily_token_limit: int | None
    quota_policy: str
    config_state: str
    scheduling_state: str
    health_state: str

    @property
    def runtime_scope(self) -> str:
        """健康/熔断运行态作用域：只对完全相同的下游连接参数有效。"""

        return node_runtime_scope(self)

    @classmethod
    def from_snapshot(cls, item: Mapping[str, Any]) -> NodeConfig:
        return cls(
            id=_text(item.get("id")),
            name=_text(item.get("name")),
            pool_id=item.get("pool_id") or None,
            base_url=_text(item.get("base_url")),
            api_key_encrypted=item.get("api_key_encrypted") or None,
            auth_type=_text(item.get("auth_type"), "BEARER"),
            auth_header=_text(item.get("auth_header"), "Authorization"),
            connect_timeout_seconds=_optional_float(item.get("connect_timeout_seconds")),
            request_timeout_seconds=_optional_float(item.get("request_timeout_seconds")),
            health_path=_text(item.get("health_path")),
            probe_interval_seconds=_optional_int(item.get("probe_interval_seconds")),
            models=tuple(str(model) for model in (item.get("models") or [])),
            weight=int(item.get("weight") or 0),
            max_concurrency=int(item.get("max_concurrency") or 0),
            hourly_token_limit=_optional_int(item.get("hourly_token_limit")),
            daily_token_limit=_optional_int(item.get("daily_token_limit")),
            quota_policy=_text(item.get("quota_policy"), "STOP"),
            config_state=_text(item.get("config_state"), "ENABLED"),
            scheduling_state=_text(item.get("scheduling_state"), "ACTIVE"),
            health_state=_text(item.get("health_state"), "UNKNOWN"),
        )


@dataclass(frozen=True)
class RouteConfig:
    id: str
    model: str
    pool_id: str
    enabled: bool
    weight: int

    @classmethod
    def from_snapshot(cls, item: Mapping[str, Any]) -> RouteConfig:
        return cls(
            id=_text(item.get("id")),
            model=_text(item.get("model")),
            pool_id=_text(item.get("pool_id")),
            enabled=bool(item.get("enabled", True)),
            weight=int(item.get("weight") or 0),
        )


@dataclass(frozen=True)
class KeyConfig:
    id: str
    name: str
    key_prefix: str
    key_digest: str
    owner_id: str | None
    allowed_models: tuple[str, ...]
    max_concurrency: int
    hourly_token_limit: int | None
    daily_token_limit: int | None
    enabled: bool
    expires_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_snapshot(cls, item: Mapping[str, Any]) -> KeyConfig:
        return cls(
            id=_text(item.get("id")),
            name=_text(item.get("name")),
            key_prefix=_text(item.get("key_prefix")),
            key_digest=_text(item.get("key_digest")),
            owner_id=item.get("owner_id") or None,
            allowed_models=tuple(str(model) for model in (item.get("allowed_models") or [])),
            max_concurrency=int(item.get("max_concurrency") or 0),
            hourly_token_limit=_optional_int(item.get("hourly_token_limit")),
            daily_token_limit=_optional_int(item.get("daily_token_limit")),
            enabled=bool(item.get("enabled", True)),
            expires_at=_optional_dt(item.get("expires_at")),
            revoked_at=_optional_dt(item.get("revoked_at")),
        )


@dataclass(frozen=True)
class PublishedConfig:
    version: int | None
    pools: Mapping[str, PoolConfig]
    nodes: Mapping[str, NodeConfig]
    routes: Mapping[str, RouteConfig]
    keys: Mapping[str, KeyConfig]

    @classmethod
    def empty(cls) -> PublishedConfig:
        return cls(version=None, pools={}, nodes={}, routes={}, keys={})

    @classmethod
    def from_snapshot(cls, version: int | None, snapshot: Mapping[str, Any] | None) -> PublishedConfig:
        data = snapshot or {}
        pools = {
            item["id"]: PoolConfig(
                id=_text(item.get("id")),
                name=_text(item.get("name")),
                weight=int(item.get("weight") or 0),
                enabled=bool(item.get("enabled", True)),
            )
            for item in data.get("pools", [])
            if item.get("id")
        }
        nodes = {
            item["id"]: NodeConfig.from_snapshot(item)
            for item in data.get("nodes", [])
            if item.get("id")
        }
        routes = {
            item["model"]: RouteConfig.from_snapshot(item)
            for item in data.get("routes", [])
            if item.get("model")
        }
        keys = {
            item["key_digest"]: KeyConfig.from_snapshot(item)
            for item in data.get("keys", [])
            if item.get("key_digest")
        }
        return cls(version=version, pools=pools, nodes=nodes, routes=routes, keys=keys)

    @property
    def empty_config(self) -> bool:
        return not self.nodes and not self.routes


class GatewayConfigState:
    """进程内原子替换的已发布配置。"""

    def __init__(self, config: PublishedConfig | None = None) -> None:
        self._config = config or PublishedConfig.empty()
        self._lock = asyncio.Lock()

    @property
    def config(self) -> PublishedConfig:
        return self._config

    @property
    def version(self) -> int | None:
        return self._config.version

    async def replace(self, config: PublishedConfig) -> None:
        async with self._lock:
            self._config = config


class ConfigLoader:
    """从 MySQL 读取已发布版本快照。只在启动与版本收敛时调用。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_current(self) -> PublishedConfig:
        """只加载最新的 ``CURRENT`` 版本；没有则返回空配置。

        绝不回退到最新 ``PENDING`` / ``FAILED`` / ``SUPERSEDED`` 版本：未生效的
        发布不存在“近似当前版本”，回退会让数据面采用从未被确认生效的配置。
        """

        async with self._session_factory() as session:
            row = await session.scalar(
                select(GatewayConfigVersion)
                .where(GatewayConfigVersion.status == VERSION_CURRENT)
                .order_by(GatewayConfigVersion.version.desc())
            )
        if row is None:
            return PublishedConfig.empty()
        return PublishedConfig.from_snapshot(row.version, row.snapshot)

    async def load_version(self, version: int) -> PublishedConfig | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(GatewayConfigVersion).where(GatewayConfigVersion.version == version)
            )
        if row is None:
            return None
        return PublishedConfig.from_snapshot(row.version, row.snapshot)


class ConfigReconciler:
    """定期校验 Redis 当前版本并原子替换内存配置。"""

    def __init__(
        self,
        *,
        state: GatewayConfigState,
        loader: ConfigLoader,
        version_source: Any,
        interval: float,
    ) -> None:
        self._state = state
        self._loader = loader
        self._version_source = version_source
        self._interval = interval
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue

    async def tick(self) -> None:
        try:
            remote = await self._version_source.current_version()
        except Exception:  # noqa: BLE001 - Redis 不可达时保持当前配置并等待恢复
            return
        if remote is None or remote == self._state.version:
            return
        config = await self._loader.load_version(int(remote))
        if config is not None and config.version is not None:
            await self._state.replace(config)

    def stop(self) -> None:
        self._stop.set()
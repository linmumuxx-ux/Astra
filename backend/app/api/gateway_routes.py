"""API 中转控制面 REST 路由。

只提供管理接口，不承载模型数据面转发。所有写操作都要求服务端校验的管理
角色并写入审计。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database import get_session
from app.gateway.auth import (
    GatewayKeyPrincipal,
    GatewayPrincipal,
    require_gateway_key,
    require_gateway_role,
)
from app.gateway.models import SCHEDULING_ACTIVE, SCHEDULING_DRAINING
from app.gateway.notifier import ConfigNotifier, RedisConfigNotifier
from app.gateway.observability import GatewayObservabilityService
from app.gateway.probe import GatewayProbeClient, HttpGatewayProbeClient
from app.gateway.runtime import RedisRuntimeStore, RuntimeStore
from app.gateway.schemas import (
    AuditEventRead,
    ConfigVersionDetail,
    ConfigVersionRead,
    DraftValidationRead,
    GatewayInstanceRead,
    GatewayKeyCreate,
    GatewayKeyCreated,
    GatewayKeyPatch,
    GatewayKeyRead,
    GatewayPermissions,
    HealthCheckRead,
    NodeCreate,
    NodePatch,
    NodeProbeResult,
    NodeRead,
    PoolCreate,
    PoolPatch,
    PoolRead,
    ProbeRequest,
    PublishRequest,
    RequestLogPage,
    RollbackRequest,
    RouteCreate,
    RoutePatch,
    RouteRead,
    ScopeStats,
)
from app.gateway.security import (
    CredentialCipher,
    CredentialError,
    CredentialUnavailable,
)
from app.gateway.service import (
    GatewayConflict,
    GatewayControlService,
    GatewayForbidden,
    GatewayNotFound,
    GatewayRuntimeUnavailable,
    GatewayValidationFailed,
)

router = APIRouter(prefix="/api/gateway", tags=["api-gateway-control"])


def gateway_cipher() -> CredentialCipher:
    return CredentialCipher(get_settings().gateway_master_key)


def gateway_notifier() -> ConfigNotifier:
    settings = get_settings()
    return RedisConfigNotifier(settings.redis_url, settings.gateway_config_channel)


def gateway_probe_client() -> GatewayProbeClient:
    settings = get_settings()
    return HttpGatewayProbeClient(
        settings.gateway_probe_timeout_seconds,
        default_health_path=settings.gateway_health_path,
    )


async def gateway_runtime() -> AsyncIterator[RuntimeStore]:
    """控制面读取节点活跃并发与健康时，必须复用数据面的运行态事实来源。"""

    runtime = RedisRuntimeStore(get_settings().redis_url)
    try:
        yield runtime
    finally:
        await runtime.close()


def gateway_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    cipher: Annotated[CredentialCipher, Depends(gateway_cipher)],
    notifier: Annotated[ConfigNotifier, Depends(gateway_notifier)],
    probe_client: Annotated[GatewayProbeClient, Depends(gateway_probe_client)],
    runtime: Annotated[RuntimeStore, Depends(gateway_runtime)],
) -> GatewayControlService:
    return GatewayControlService(
        session, cipher=cipher, notifier=notifier, probe_client=probe_client, runtime=runtime
    )


def gateway_observability(
    session: Annotated[AsyncSession, Depends(get_session)],
    runtime: Annotated[RuntimeStore, Depends(gateway_runtime)],
) -> GatewayObservabilityService:
    return GatewayObservabilityService(
        session, runtime=runtime, timezone=get_settings().timezone
    )


async def gateway_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, GatewayNotFound):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})
    if isinstance(exc, GatewayValidationFailed):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc), "errors": [error.model_dump() for error in exc.errors]},
        )
    if isinstance(exc, GatewayConflict):
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})
    if isinstance(exc, GatewayForbidden):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})
    if isinstance(exc, (GatewayRuntimeUnavailable, CredentialUnavailable, CredentialError)):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )
    raise exc


def _actor_role(principal: GatewayPrincipal) -> str:
    return ",".join(sorted(principal.roles))


@router.get("/permissions", response_model=GatewayPermissions)
async def permissions(principal: GatewayPrincipal = Depends(require_gateway_role("view"))):
    return GatewayPermissions(actor=principal.name, roles=sorted(principal.roles))


# ── Pool ──────────────────────────────────────────────────────────────


@router.get("/pools", response_model=list[PoolRead])
async def list_pools(
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_pools()


@router.post("/pools", response_model=PoolRead, status_code=status.HTTP_201_CREATED)
async def create_pool(
    payload: PoolCreate,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("route")),
):
    return await service.create_pool(payload, actor=principal.name, actor_role=_actor_role(principal))


@router.patch("/pools/{pool_id}", response_model=PoolRead)
async def update_pool(
    pool_id: str,
    payload: PoolPatch,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("route")),
):
    return await service.update_pool(
        pool_id, payload, actor=principal.name, actor_role=_actor_role(principal)
    )


@router.delete("/pools/{pool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pool(
    pool_id: str,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("route")),
):
    await service.delete_pool(pool_id, actor=principal.name, actor_role=_actor_role(principal))


# ── Node ──────────────────────────────────────────────────────────────


@router.get("/nodes", response_model=list[NodeRead])
async def list_nodes(
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_nodes()


@router.get("/nodes/{node_id}", response_model=NodeRead)
async def get_node(
    node_id: str,
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.get_node(node_id)


@router.post("/nodes", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
async def create_node(
    payload: NodeCreate,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("node")),
):
    return await service.create_node(payload, actor=principal.name, actor_role=_actor_role(principal))


@router.patch("/nodes/{node_id}", response_model=NodeRead)
async def update_node(
    node_id: str,
    payload: NodePatch,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("node")),
):
    return await service.update_node(
        node_id, payload, actor=principal.name, actor_role=_actor_role(principal)
    )


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: str,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("node")),
):
    await service.delete_node(node_id, actor=principal.name, actor_role=_actor_role(principal))


@router.post("/nodes/{node_id}/drain", response_model=NodeRead)
async def drain_node(
    node_id: str,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("node")),
):
    return await service.set_node_scheduling(
        node_id, SCHEDULING_DRAINING, actor=principal.name, actor_role=_actor_role(principal)
    )


@router.post("/nodes/{node_id}/activate", response_model=NodeRead)
async def activate_node(
    node_id: str,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("node")),
):
    return await service.set_node_scheduling(
        node_id, SCHEDULING_ACTIVE, actor=principal.name, actor_role=_actor_role(principal)
    )


@router.post("/nodes/{node_id}/probe", response_model=NodeProbeResult)
async def probe_node(
    node_id: str,
    payload: ProbeRequest,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("node")),
):
    node, checks = await service.probe_node(
        node_id, payload.probe_types, actor=principal.name, actor_role=_actor_role(principal)
    )
    return NodeProbeResult(node=NodeRead.model_validate(node), checks=checks)


# ── Route ─────────────────────────────────────────────────────────────


@router.get("/routes", response_model=list[RouteRead])
async def list_routes(
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_routes()


@router.post("/routes", response_model=RouteRead, status_code=status.HTTP_201_CREATED)
async def create_route(
    payload: RouteCreate,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("route")),
):
    return await service.create_route(payload, actor=principal.name, actor_role=_actor_role(principal))


@router.patch("/routes/{route_id}", response_model=RouteRead)
async def update_route(
    route_id: str,
    payload: RoutePatch,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("route")),
):
    return await service.update_route(
        route_id, payload, actor=principal.name, actor_role=_actor_role(principal)
    )


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("route")),
):
    await service.delete_route(route_id, actor=principal.name, actor_role=_actor_role(principal))


# ── Gateway Key ───────────────────────────────────────────────────────


@router.get("/keys", response_model=list[GatewayKeyRead])
async def list_keys(
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_keys()


@router.post("/keys", response_model=GatewayKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: GatewayKeyCreate,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("key")),
):
    key, raw = await service.create_key(
        payload, actor=principal.name, actor_role=_actor_role(principal)
    )
    return GatewayKeyCreated(
        **GatewayKeyRead.model_validate(key).model_dump(), key=raw
    )


@router.patch("/keys/{key_id}", response_model=GatewayKeyRead)
async def update_key(
    key_id: str,
    payload: GatewayKeyPatch,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("key")),
):
    return await service.update_key(
        key_id, payload, actor=principal.name, actor_role=_actor_role(principal)
    )


@router.delete("/keys/{key_id}", response_model=GatewayKeyRead)
async def revoke_key(
    key_id: str,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("key")),
):
    return await service.revoke_key(key_id, actor=principal.name, actor_role=_actor_role(principal))


# ── 草稿 / 版本 / 审计 ────────────────────────────────────────────────


@router.get("/config/draft", response_model=DraftValidationRead)
async def draft_validation(
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.validate_draft()


@router.get("/config/versions", response_model=list[ConfigVersionRead])
async def list_versions(
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_versions()


@router.get("/config/versions/{version}", response_model=ConfigVersionDetail)
async def get_version(
    version: int,
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    row = await service.get_version(version)
    return service.version_detail(row)


@router.post("/config/publish", response_model=ConfigVersionRead)
async def publish(
    payload: PublishRequest,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("publish")),
):
    return await service.publish(note=payload.note, actor=principal.name, actor_role=_actor_role(principal))


@router.post("/config/rollback", response_model=ConfigVersionRead)
async def rollback(
    payload: RollbackRequest,
    service: GatewayControlService = Depends(gateway_service),
    principal: GatewayPrincipal = Depends(require_gateway_role("publish")),
):
    return await service.rollback(
        payload.version, actor=principal.name, actor_role=_actor_role(principal)
    )


@router.post("/config/reconcile")
async def reconcile_publications(
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("publish")),
):
    """对账未决发布：以 Redis 运行态为权威，把 PENDING 版本收敛为 CURRENT 或 FAILED。"""

    changed = await service.reconcile_publications()
    return {"changed": changed}


@router.get("/audits", response_model=list[AuditEventRead])
async def list_audits(
    resource_type: str | None = None,
    resource_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    service: GatewayControlService = Depends(gateway_service),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_audits(
        resource_type=resource_type, resource_id=resource_id, limit=limit
    )


# ── 观测：调用日志 / 统计 / 实例 ───────────────────────────────────────

StatsScope = Literal["overview", "node", "pool", "model", "key"]
StatsWindow = Literal["hour", "today", "7d", "30d"]


def _require_scope_id(scope: str, scope_id: str | None) -> str | None:
    if scope != "overview" and not scope_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{scope} 统计需要 scope_id",
        )
    return scope_id


@router.get("/requests", response_model=RequestLogPage)
async def list_gateway_requests(
    request_id: str | None = None,
    node_id: str | None = None,
    model: str | None = None,
    key_id: str | None = None,
    status_code: int | None = None,
    error_code: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    service: GatewayObservabilityService = Depends(gateway_observability),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_requests(
        page=page,
        page_size=page_size,
        request_id=request_id,
        node_id=node_id,
        model=model,
        key_id=key_id,
        status_code=status_code,
        error_code=error_code,
    )


@router.get("/stats", response_model=ScopeStats)
async def get_gateway_stats(
    scope: StatsScope = "overview",
    scope_id: str | None = None,
    window: StatsWindow = "today",
    service: GatewayObservabilityService = Depends(gateway_observability),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.scope_stats(
        scope=scope, scope_id=_require_scope_id(scope, scope_id), window=window
    )


@router.get("/instances", response_model=list[GatewayInstanceRead])
async def list_gateway_instances(
    service: GatewayObservabilityService = Depends(gateway_observability),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_instances()


@router.get("/nodes/{node_id}/health-checks", response_model=list[HealthCheckRead])
async def list_node_health_checks(
    node_id: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    service: GatewayObservabilityService = Depends(gateway_observability),
    _principal: GatewayPrincipal = Depends(require_gateway_role("view")),
):
    return await service.list_health_checks(node_id, limit=limit)


# ── Key 自助：用 Key 自身鉴权，只能看自己的日志与统计 ──────────────────


@router.get("/self/requests", response_model=RequestLogPage)
async def self_requests(
    model: str | None = None,
    node_id: str | None = None,
    status_code: int | None = None,
    error_code: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    principal: GatewayKeyPrincipal = Depends(require_gateway_key),
    service: GatewayObservabilityService = Depends(gateway_observability),
):
    return await service.list_requests(
        page=page,
        page_size=page_size,
        key_id=principal.key_id,
        model=model,
        node_id=node_id,
        status_code=status_code,
        error_code=error_code,
    )


@router.get("/self/stats", response_model=ScopeStats)
async def self_stats(
    window: StatsWindow = "today",
    principal: GatewayKeyPrincipal = Depends(require_gateway_key),
    service: GatewayObservabilityService = Depends(gateway_observability),
):
    return await service.scope_stats(scope="key", scope_id=principal.key_id, window=window)
"""控制面管理鉴权。

身份只来自部署环境提供的管理凭据（``Authorization: Bearer``），由服务端校验；
浏览器提交的身份 Header 一律不参与鉴权。每个写操作按角色（view/node/route/
key/publish/system）判定，system 等价于全部权限。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database import get_session
from app.gateway.models import GatewayKey
from app.gateway.security import (
    CredentialError,
    GatewayCredential,
    gateway_key_digest,
    hash_credential_token,
    parse_credentials,
)
from app.models import utcnow


@dataclass(frozen=True)
class GatewayPrincipal:
    name: str
    roles: frozenset[str]

    def grants(self, role: str) -> bool:
        return role in self.roles or "system" in self.roles


def gateway_credential_store() -> dict[str, GatewayCredential]:
    try:
        return parse_credentials(get_settings().gateway_control_credentials)
    except CredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def authenticate_gateway(
    authorization: str | None, store: dict[str, GatewayCredential]
) -> GatewayPrincipal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 API 中转管理凭据"
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理凭据为空")
    credential = store.get(hash_credential_token(token))
    if credential is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理凭据无效")
    return GatewayPrincipal(name=credential.name, roles=credential.roles)


def require_gateway_role(*required: str):
    def dependency(
        authorization: Annotated[str | None, Header()] = None,
        store: dict[str, GatewayCredential] = Depends(gateway_credential_store),
    ) -> GatewayPrincipal:
        principal = authenticate_gateway(authorization, store)
        if required and not any(principal.grants(role) for role in required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少所需管理角色")
        return principal

    return dependency


@dataclass(frozen=True)
class GatewayKeyPrincipal:
    """普通 Gateway Key 自助身份：只代表该 Key 自身。"""

    key_id: str
    name: str
    owner_id: str | None


async def require_gateway_key(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,
) -> GatewayKeyPrincipal:
    """用 Gateway Key 自身鉴权，只允许访问该 Key 的日志与统计。

    身份完全来自 ``Authorization: Bearer agw_...`` 对应的库中摘要，服务端校验
    状态 / 有效期 / 吊销；绝不读取浏览器提交的身份 Header。
    """

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 Gateway Key")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gateway Key 为空")
    key = await session.scalar(
        select(GatewayKey).where(GatewayKey.key_digest == gateway_key_digest(token))
    )
    if key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gateway Key 无效")
    if not key.enabled or key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gateway Key 已停用")
    if key.expires_at is not None and key.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gateway Key 已过期")
    return GatewayKeyPrincipal(key_id=key.id, name=key.name, owner_id=key.owner_id)
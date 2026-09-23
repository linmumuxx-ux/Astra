"""API 中转凭据安全：主密钥加密、Gateway Key 摘要与管理凭据解析。

本模块刻意不导入 settings，避免配置校验时形成循环依赖；所有函数都接收
原始字符串，由调用方（settings / 依赖注入）决定取值来源。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

GATEWAY_KEY_ALGO_PREFIX = "agw_"
GATEWAY_KEY_RANDOM_BYTES = 32
GATEWAY_KEY_PREFIX_LENGTH = 12

# 控制面角色：读、节点、路由/Pool、Key、发布、系统。system 等价于全部权限。
ALL_ROLES = frozenset({"view", "node", "route", "key", "publish", "system"})


class CredentialError(Exception):
    """主密钥或管理凭据不可用。"""


class CredentialUnavailable(CredentialError):
    """未配置主密钥，禁止涉及节点凭据的写操作。"""


@dataclass(frozen=True)
class GatewayCredential:
    name: str
    token_digest: str
    roles: frozenset[str]

    def grants(self, role: str) -> bool:
        return role in self.roles or "system" in self.roles


def hash_credential_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_credentials(raw: str) -> dict[str, GatewayCredential]:
    """解析部署环境提供的管理凭据。

    支持两种形式：JSON 数组 ``[{"name","token","roles"}]``，或单个 token
    （授予全部角色）。返回以 token 摘要为键的映射，便于 O(1) 校验。
    """

    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("["):
        try:
            items = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CredentialError("ASTRA_GATEWAY_CONTROL_CREDENTIALS 不是合法 JSON") from exc
        if not isinstance(items, list):
            raise CredentialError("ASTRA_GATEWAY_CONTROL_CREDENTIALS 必须是 JSON 数组")
        store: dict[str, GatewayCredential] = {}
        for item in items:
            if not isinstance(item, dict):
                raise CredentialError("每条管理凭据必须是对象")
            token = str(item.get("token") or "").strip()
            name = str(item.get("name") or "").strip()
            roles = item.get("roles") or []
            if not token or not name:
                raise CredentialError("管理凭据必须包含 name 与非空 token")
            if not isinstance(roles, list) or not roles:
                raise CredentialError(f"管理凭据 {name} 必须声明至少一个角色")
            normalized = frozenset(str(role).strip().lower() for role in roles)
            unknown = normalized - ALL_ROLES
            if unknown:
                raise CredentialError(f"管理凭据 {name} 含未知角色: {', '.join(sorted(unknown))}")
            digest = hash_credential_token(token)
            if digest in store:
                raise CredentialError("管理凭据 token 重复")
            store[digest] = GatewayCredential(name=name, token_digest=digest, roles=normalized)
        return store

    return {
        hash_credential_token(text): GatewayCredential(
            name="admin", token_digest=hash_credential_token(text), roles=ALL_ROLES
        )
    }


def generate_gateway_key() -> str:
    return GATEWAY_KEY_ALGO_PREFIX + secrets.token_urlsafe(GATEWAY_KEY_RANDOM_BYTES)


def gateway_key_prefix(raw_key: str) -> str:
    return raw_key[:GATEWAY_KEY_PREFIX_LENGTH]


def gateway_key_digest(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_gateway_key(raw_key: str, digest: str) -> bool:
    return hmac.compare_digest(gateway_key_digest(raw_key), digest)


class CredentialCipher:
    """使用 Fernet 主密钥加密节点下游凭据，库中只保存密文。"""

    def __init__(self, master_key: str | None) -> None:
        normalized = (master_key or "").strip()
        self._fernet: Fernet | None = None
        if normalized:
            try:
                self._fernet = Fernet(normalized.encode("ascii"))
            except Exception as exc:  # noqa: BLE001 - Fernet 对非法 key 抛 ValueError
                raise CredentialError("ASTRA_GATEWAY_MASTER_KEY 不是合法的 Fernet 主密钥") from exc

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def require(self) -> None:
        if self._fernet is None:
            raise CredentialUnavailable("未配置 ASTRA_GATEWAY_MASTER_KEY，无法加密或解密节点凭据")

    def encrypt(self, plaintext: str) -> str:
        self.require()
        assert self._fernet is not None
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        self.require()
        assert self._fernet is not None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise CredentialError("节点凭据无法用当前主密钥解密") from exc
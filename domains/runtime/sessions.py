"""只保存原生 Session 绑定，业务终态与长期消息由各自领域负责。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from domains.runtime.config import RuntimePurpose


@dataclass(frozen=True, slots=True)
class NativeSessionBinding:
    native_session_id: str
    runtime_id: str
    purpose: RuntimePurpose
    owner_ref: str
    directory: str
    permission_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.native_session_id.startswith("ses") or not self.owner_ref:
            raise ValueError("Session 绑定必须含原生 Session ID 和业务索引")


def permission_digest(rules: list[dict[str, str]]) -> str:
    """规则顺序决定 OpenCode 匹配优先级，哈希保留顺序。"""
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def event_session_id(event: dict[str, Any]) -> str | None:
    # 复制自旧 OpenCode 通信层；保留原生 envelope，不另造执行日志。
    properties = event.get("properties")
    if not isinstance(properties, dict):
        return None
    part = properties.get("part") if isinstance(properties.get("part"), dict) else {}
    info = properties.get("info") if isinstance(properties.get("info"), dict) else {}
    value = properties.get("sessionID") or part.get("sessionID") or info.get("sessionID")
    # session.created/updated 的 info.id 是 Session ID，不是 Message ID。
    if not value and str(event.get("type", "")).startswith("session."):
        value = info.get("id")
    return str(value) if value else None

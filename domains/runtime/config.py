"""独立 OpenCode 配置，不引用旧应用 Settings 或执行员工。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

SUPPORTED_OPENCODE_VERSION = "1.19.0"


class RuntimePurpose(StrEnum):
    PERSONA = "persona"
    TASK = "task"


def normalized_directory(value: str) -> str:
    """目录属于 Runtime 主机；不得用 API 主机的 resolve 改写远端路径。"""
    if "\x00" in value or not value:
        raise ValueError("Runtime 目录不能为空或包含 NUL")
    windows = PureWindowsPath(value)
    if windows.drive:
        if not windows.is_absolute() or ".." in windows.parts:
            raise ValueError("Runtime 目录必须是没有上级引用的绝对路径")
        return windows.as_posix().rstrip("/") or windows.anchor
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Runtime 目录必须是没有上级引用的绝对路径")
    return str(path)


def split_model(value: str | None) -> tuple[str, str] | None:
    # 复制自 backend/app/executors/opencode_server.py 的已使用模型协议。
    if value is None:
        return None
    provider, separator, model = value.partition("/")
    if not separator or not provider or not model:
        raise ValueError("OpenCode 模型必须使用 provider/model 格式")
    return provider, model


@dataclass(frozen=True, slots=True)
class OpenCodeConfig:
    base_url: str
    runtime_id: str
    purpose: RuntimePurpose
    workspace_roots: tuple[str, ...]
    model: str | None = None
    agent: str | None = None
    username: str = "opencode"
    password: str | None = field(default=None, repr=False)
    control_timeout_seconds: float = 30
    stream_read_timeout_seconds: float = 90
    verify_tls: bool = True
    # Persona 只可使用显式的 Astra MCP 业务工具，后端仍检查完整业务权限。
    persona_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenCode base_url 必须是 HTTP(S) 服务地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OpenCode URL 不得携带凭据、查询参数或 fragment")
        if not self.runtime_id or not self.workspace_roots:
            raise ValueError("Runtime 标识、工作区根目录和兼容版本必须显式配置")
        if self.control_timeout_seconds <= 0 or self.stream_read_timeout_seconds <= 0:
            raise ValueError("Runtime 超时必须大于 0")
        if not isinstance(self.purpose, RuntimePurpose):
            object.__setattr__(self, "purpose", RuntimePurpose(self.purpose))
        roots = tuple(normalized_directory(root) for root in self.workspace_roots)
        object.__setattr__(self, "workspace_roots", roots)
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        if self.purpose is RuntimePurpose.PERSONA and len(roots) != 1:
            raise ValueError("Persona Runtime 必须绑定单独的决策目录")
        if any(not re.fullmatch(r"astra_[a-z0-9_]+", name) for name in self.persona_tools):
            raise ValueError("Persona 仅允许显式命名的 Astra 业务工具")
        split_model(self.model)

    def require_directory(self, directory: str) -> str:
        normalized = normalized_directory(directory)
        for root in self.workspace_roots:
            if normalized == root:
                return normalized
            # Persona 目录不允许任何工程子目录，也不隐式获得 Task 工作区。
            if self.purpose is RuntimePurpose.TASK and normalized.startswith(root.rstrip("/") + "/"):
                return normalized
        raise ValueError("目录不在此 Runtime 的工作区边界内")

    def persona_permissions(self) -> list[dict[str, str]]:
        if self.purpose is not RuntimePurpose.PERSONA:
            raise ValueError("工程 Runtime 不使用 Persona 权限模板")
        return [
            {"permission": "*", "pattern": "*", "action": "deny"},
            *({"permission": name, "pattern": "*", "action": "allow"} for name in self.persona_tools),
        ]

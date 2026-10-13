"""受控部署配置定义工程位置/工具上限；任务正文不能选择主机路径或凭据。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domains.core import DomainError
from domains.runtime import OpenCodeClient, OpenCodeConfig, RuntimePurpose


class ProjectExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    transport: Literal["local"]
    repository: str
    workspace_root: str
    base_ref: str = Field(min_length=1)
    model: str
    permission_rules: list[dict[str, str]] = Field(min_length=1)

    @model_validator(mode="after")
    def deny_by_default(self):
        if self.permission_rules[0] != {"permission": "*", "pattern": "*", "action": "deny"}:
            raise ValueError("工程执行规则须以 deny-all 开始")
        OpenCodeClient._validate_permissions(self.permission_rules)
        for rule in self.permission_rules[1:]:
            if rule["permission"] == "*" and rule["action"] != "deny":
                raise ValueError("不能给工程 Runtime 无限制通配权限")
        for value in [self.repository, self.workspace_root]:
            path = Path(value)
            if not path.is_absolute() or path != path.resolve(strict=True) or not path.is_dir():
                raise ValueError("本地工程配置必须为存在且无符号链接的绝对目录")
        return self

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    projects: dict[str, dict[str, ProjectExecutionConfig]]  # worker_id -> project_id -> config

    def project(self, worker_id, project_id):
        config = self.projects.get(worker_id, {}).get(project_id)
        if config is None:
            raise DomainError(409, "Worker 工程执行配置尚未建立，不能猜测主机路径或权限")
        return config


def protected_json(path: str) -> dict:
    """配置与凭据只读 0600 常规文件；不把内容放入错误或模型上下文。"""
    target = Path(path)
    if not target.is_absolute() or target != target.resolve(strict=True):
        raise DomainError(503, "受控配置路径必须为无符号链接的绝对路径")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077 or metadata.st_size > 262144:
            raise DomainError(503, "受控配置必须是最大 256KB 的 0600 常规文件")
        if metadata.st_uid != os.getuid():
            raise DomainError(503, "受控配置必须属于当前服务用户")
        with os.fdopen(fd, "r", closefd=False) as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise DomainError(503, "受控配置必须为 JSON 对象")
        return value
    finally:
        os.close(fd)


def configured_settings():
    path = os.getenv("ASTRA_V1_EXECUTION_CONFIG")
    if not path:
        raise DomainError(503, "工程执行配置尚未部署")
    try:
        return ExecutionSettings.model_validate(protected_json(path))
    except (OSError, ValueError, RuntimeError):
        raise DomainError(503, "工程执行配置无效，请由部署管理员核验") from None


def runtime_client(worker, execution, config):
    if urlsplit(execution["grant_snapshot"]["runtime_base_url"]).hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise DomainError(409, "local 工程配置只能连接本机 Runtime；远程须使用已验证 SSH 适配")
    if config.workspace_root not in worker["workspace_roots"]:
        raise DomainError(403, "执行目录不在 Worker 注册的授权根目录内")
    password = worker_password(worker.get("credential_ref"))
    return OpenCodeClient(
        OpenCodeConfig(
            base_url=execution["grant_snapshot"]["runtime_base_url"],
            runtime_id=worker["id"],
            purpose=RuntimePurpose.TASK,
            workspace_roots=(config.workspace_root,),
            model=config.model,
            password=password,
        )
    )


def worker_password(credential_ref):
    password = None
    if credential_ref:
        if not credential_ref.startswith("file:"):
            raise DomainError(503, "Worker 凭据引用须使用受控 file: 路径")
        secret = protected_json(credential_ref[5:])
        if set(secret) != {"password"} or not isinstance(secret["password"], str) or not secret["password"]:
            raise DomainError(503, "Worker 凭据文件格式无效")
        password = secret["password"]
    return password

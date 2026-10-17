"""Worker Gateway 管理接口的内部服务密钥。

任务平台的 HTTP 路由没有统一登录。图书馆身份来自受信任的上游头，MCP 密钥只保护 MCP。
管理接口因此单独使用一把内部密钥：已配置就用配置，没有就在启动时生成并写入 ops/env/.env。
WebSocket 仍用 Worker token，健康检查不带这把密钥。
"""

from __future__ import annotations

import os
from pathlib import Path
from secrets import token_urlsafe

from app.config.settings import Settings

ENV_NAME = "ASTRA_WORKER_GATEWAY_ADMIN_KEY"


def ensure_worker_gateway_admin_key(settings: Settings, env_path: Path | None = None) -> str:
    configured = (settings.worker_gateway_admin_key or "").strip()
    if configured:
        return configured
    if env_path is None:
        env_path = Path(settings.model_config["env_file"])
    generated = f"wgk_{token_urlsafe(32)}"
    _upsert_env(env_path, ENV_NAME, generated)
    os.environ[ENV_NAME] = generated
    settings.worker_gateway_admin_key = generated
    return generated


def _upsert_env(path: Path, name: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{name}="
    replaced = False
    updated: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            updated.append(f"{name}={value}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(f"{name}={value}")
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")

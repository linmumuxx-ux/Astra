"""Runtime-owned OpenCode configuration for the digital-library MCP.

The task git worktree is user code and must never carry runtime configuration.
Astra writes this file into its own runtime directory and points the employee
OpenCode server at it through ``OPENCODE_CONFIG`` (verified on OpenCode 1.18.31).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.config.settings import BACKEND_ROOT, Settings


def _library_stdio_server() -> dict:
    return {
        "type": "local",
        "command": [sys.executable, "-m", "app.mcp_server"],
        "cwd": str(BACKEND_ROOT),
        "environment": {"ASTRA_MCP_TRANSPORT": "stdio"},
        "enabled": True,
        "timeout": 10000,
    }


def _library_http_server(url: str, api_key: str | None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return {
        "type": "remote",
        "url": url,
        "headers": headers,
        "enabled": True,
        "timeout": 10000,
    }


def _config(server: dict) -> dict:
    return {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"astra_library": server},
        "permission": {"astra_library_*": "allow"},
    }


def local_runtime_config_path(settings: Settings, employee_id: str) -> Path:
    return settings.resolved_runtime_dir / "opencode" / f"{employee_id}.json"


def write_local_runtime_config(settings: Settings, employee_id: str) -> Path:
    path = local_runtime_config_path(settings, employee_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_config(_library_stdio_server()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def remote_runtime_config_content(settings: Settings, mcp_url: str) -> str:
    return json.dumps(
        _config(_library_http_server(mcp_url, settings.mcp_api_key)),
        ensure_ascii=False,
        indent=2,
    )
"""Explicit ssh/worker mark. Snapshots never carry it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models import OpenCodeExecutionEnvironment, WorkerInstance
from app.runtime.occupancy import blocking_session_exists, occupying_exists

Switch = Callable[[], Awaitable[dict[str, Any]]]


async def read_worker_channel(session: AsyncSession, environment_id: int | None) -> str:
    if environment_id is None:
        return "ssh"
    environment = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if environment is None:
        return "ssh"
    return environment.worker_channel if environment.worker_channel in {"ssh", "worker"} else "ssh"


async def mark_worker_channel(
    session: AsyncSession,
    environment_id: int,
    *,
    switch: Switch | None = None,
) -> OpenCodeExecutionEnvironment:
    """Maintenance switch. A failed step keeps ssh and reports the reason.

    Reload happens inside the Worker command, never because a socket dropped.
    """

    environment = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if environment is None:
        raise HTTPException(404, "环境不存在")
    occupied = await session.scalar(select(occupying_exists(environment.employee_id)))
    blocked = await session.scalar(select(blocking_session_exists(environment.employee_id)))
    if occupied or blocked:
        await session.rollback()
        raise HTTPException(409, "员工被占用，不能切换通道")
    workspace = environment.workspace_root
    port = environment.opencode_server_port
    if switch is None:
        instance = await session.scalar(
            select(WorkerInstance).where(WorkerInstance.environment_id == environment.id)
        )
        online = instance is not None and instance.status == "online"
        await session.rollback()
        if not online:
            await _keep_ssh(session, environment_id, "Worker 不在线，通道保持 ssh")
        operation = _worker_switch(environment_id, workspace, port)
    else:
        await session.rollback()
        operation = switch
    try:
        result = await operation()
    except Exception as exc:
        await _keep_ssh(session, environment_id, f"切换失败，通道保持 ssh：{exc}")
    mismatch = _mismatch(result)
    if mismatch:
        await _keep_ssh(session, environment_id, mismatch)
    stored = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if stored is None:
        raise HTTPException(404, "环境不存在")
    stored.worker_channel = "worker"
    await session.commit()
    return stored


def _worker_switch(environment_id: int, workspace: str, port: int) -> Switch:
    async def switch() -> dict[str, Any]:
        from app.runtime.worker_client import WorkerOpenCodeClient

        client = WorkerOpenCodeClient(get_settings(), environment_id=environment_id)
        return await client.run_command("switch_channel", {"workspace": workspace, "port": port})

    return switch


def _mismatch(result: object) -> str | None:
    if not isinstance(result, dict) or result.get("reloaded") is not True:
        return "受控重载没有完成，通道保持 ssh"
    settings = get_settings()
    if not _same_direct_url(result.get("gateway_url"), settings.remote_gateway_local_url):
        return "生效的 Gateway 地址与内网配置不一致，通道保持 ssh"
    if not _same_direct_url(result.get("mcp_url"), settings.mcp_resource_server_url):
        return "生效的 MCP 地址与内网配置不一致，通道保持 ssh"
    return None


def _same_direct_url(actual: object, expected: str) -> bool:
    return isinstance(actual, str) and actual.rstrip("/") == expected.rstrip("/")


async def _keep_ssh(session: AsyncSession, environment_id: int, reason: str) -> None:
    environment = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if environment is not None:
        environment.worker_channel = "ssh"
        await session.commit()
    raise HTTPException(409, reason)

"""Explicit ssh/worker mark. Snapshots never carry it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models import OpenCodeExecutionEnvironment
from app.runtime.occupancy import blocking_session_exists, occupying_exists

Probe = Callable[[str], Awaitable[bool]]


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
    probe: Probe,
) -> OpenCodeExecutionEnvironment:
    """Probe only the configured Gateway and MCP addresses, then set the mark."""

    environment = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if environment is None:
        raise HTTPException(404, "环境不存在")
    occupied = await session.scalar(select(occupying_exists(environment.employee_id)))
    blocked = await session.scalar(select(blocking_session_exists(environment.employee_id)))
    if occupied or blocked:
        raise HTTPException(409, "员工被占用，不能切换通道")
    settings = get_settings()
    targets = (settings.remote_gateway_local_url, settings.mcp_resource_server_url)
    for url in targets:
        if not await probe(url):
            environment.worker_channel = "ssh"
            await session.commit()
            raise HTTPException(409, "内网 Gateway 或 MCP 探测失败，通道保持 ssh")
    environment.worker_channel = "worker"
    await session.commit()
    return environment

"""Explicit ssh/worker mark. Snapshots never carry it."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database import SessionLocal
from app.domain import EnvironmentStatus
from app.models import OpenCodeExecutionEnvironment, WorkerInstance
from app.runtime.occupancy import blocking_session_exists, occupying_exists
from app.runtime.remote_provisioning import no_active_operation, require_no_operation

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
    """Maintenance switch. The occupancy reservation is held until the mark is written.

    Reload happens inside the Worker command, never because a socket dropped.
    """

    environment = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if environment is None:
        raise HTTPException(404, "环境不存在")
    await session.refresh(environment)
    try:
        require_no_operation(environment)
    except HTTPException:
        await session.rollback()
        raise
    employee_id = environment.employee_id
    previous_status = environment.status
    workspace = environment.workspace_root
    port = environment.opencode_server_port
    operation_id = uuid4().hex
    now = datetime.now(UTC)
    settings = get_settings()
    operation = {
        "id": operation_id,
        "action": "switch_channel",
        "state": "RUNNING",
        "previous_status": previous_status,
        "started_at": now.isoformat(),
        "expires_at": (
            now + timedelta(seconds=settings.opencode_control_timeout_seconds + 30)
        ).isoformat(),
    }
    reserved = await session.execute(
        update(OpenCodeExecutionEnvironment)
        .where(
            OpenCodeExecutionEnvironment.id == environment_id,
            OpenCodeExecutionEnvironment.status_detail == environment.status_detail,
            no_active_operation(now),
            ~occupying_exists(employee_id),
            ~blocking_session_exists(employee_id),
        )
        .values(status=EnvironmentStatus.CHECKING, status_detail={"operation": operation})
        .execution_options(synchronize_session=False)
    )
    if reserved.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "员工被占用或环境正在维护，不能切换通道")
    await session.commit()
    if switch is None:
        online = await _worker_online(environment_id)
        if not online:
            await _release(
                session, environment_id, operation_id, previous_status, "Worker 不在线，通道保持 ssh"
            )
        operation_fn: Switch = _worker_switch(environment_id, workspace, port)
    else:
        operation_fn = switch
    try:
        result = await operation_fn()
    except Exception as exc:
        await _release(
            session, environment_id, operation_id, previous_status, f"切换失败，通道保持 ssh：{exc}"
        )
    mismatch = _mismatch(result)
    if mismatch:
        await _release(session, environment_id, operation_id, previous_status, mismatch)
    written = await session.execute(
        update(OpenCodeExecutionEnvironment)
        .where(
            OpenCodeExecutionEnvironment.id == environment_id,
            OpenCodeExecutionEnvironment.status_detail["operation"]["id"].as_string() == operation_id,
            ~occupying_exists(employee_id),
            ~blocking_session_exists(employee_id),
        )
        .values(worker_channel="worker", status=previous_status, status_detail={})
        .execution_options(synchronize_session=False)
    )
    if written.rowcount != 1:
        await session.rollback()
        await _release(
            session,
            environment_id,
            operation_id,
            previous_status,
            "切换期间员工被占用或维护锁已失效，通道保持 ssh",
        )
    await session.commit()
    stored = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if stored is None:
        raise HTTPException(404, "环境不存在")
    await session.refresh(stored)
    return stored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把执行环境切换到 Worker 通道")
    parser.add_argument("--environment-id", type=int, required=True)
    args = parser.parse_args(argv)

    async def run() -> int:
        async with SessionLocal() as session:
            try:
                environment = await mark_worker_channel(session, args.environment_id)
            except HTTPException as exc:
                print(exc.detail)
                return 1
        print(environment.worker_channel)
        return 0

    return asyncio.run(run())


def _worker_switch(environment_id: int, workspace: str, port: int) -> Switch:
    async def switch() -> dict[str, Any]:
        from app.runtime.worker_client import WorkerOpenCodeClient

        client = WorkerOpenCodeClient(get_settings(), environment_id=environment_id)
        return await client.run_command("switch_channel", {"workspace": workspace, "port": port})

    return switch


async def _worker_online(environment_id: int) -> bool:
    async with SessionLocal() as session:
        instance = await session.scalar(
            select(WorkerInstance).where(WorkerInstance.environment_id == environment_id)
        )
        return instance is not None and instance.status == "online"


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


async def _release(
    session: AsyncSession,
    environment_id: int,
    operation_id: str,
    previous_status: str,
    reason: str,
) -> None:
    await session.execute(
        update(OpenCodeExecutionEnvironment)
        .where(
            OpenCodeExecutionEnvironment.id == environment_id,
            OpenCodeExecutionEnvironment.status_detail["operation"]["id"].as_string() == operation_id,
        )
        .values(worker_channel="ssh", status=previous_status, status_detail={})
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    raise HTTPException(409, reason)


if __name__ == "__main__":
    raise SystemExit(main())

"""投递待发送的任务唤醒。重复投递只标记 outbox，不改任务状态。"""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models import TaskWakeOutbox

MAX_ATTEMPTS = 30


class WakeRetry(Exception):
    pass


class HttpWakeSender:
    async def send(self, row: TaskWakeOutbox) -> None:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=10) as client:
            target = await client.get(
                f"{settings.nexus_api_base.rstrip('/')}/api/v1/internal/wake-target",
                params={
                    "employee_id": row.responsible_employee_id,
                    "session_id": row.source_session_id or "",
                },
            )
            if target.status_code == 404:
                raise WakeRetry(target.text.strip() or "没有可唤醒的会话")
            target.raise_for_status()
            body = target.json()
            response = await client.post(
                f"{settings.agentscope_base_url.rstrip('/')}/nexus/task-hint",
                json={
                    "session_id": body["session_id"],
                    "agent_id": body["agent_id"],
                    "hint": row.hint,
                    "user_id": settings.agentscope_user_id,
                },
            )
            response.raise_for_status()


async def deliver_pending(
    session: AsyncSession,
    sender,
    *,
    now: datetime | None = None,
    limit: int = 20,
) -> int:
    moment = now or datetime.now(UTC)
    rows = (
        await session.scalars(
            select(TaskWakeOutbox)
            .where(TaskWakeOutbox.status == "pending", TaskWakeOutbox.next_retry_at <= moment)
            .order_by(TaskWakeOutbox.id)
            .limit(limit)
        )
    ).all()
    delivered = 0
    settings = get_settings()
    for row in rows:
        try:
            await sender.send(row)
        except Exception as exc:
            row.attempts += 1
            row.last_error = str(exc)[:500]
            row.updated_at = moment
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
            else:
                row.next_retry_at = moment + timedelta(seconds=settings.outbox_retry_seconds)
            continue
        row.status = "delivered"
        row.updated_at = moment
        row.last_error = None
        delivered += 1
    await session.commit()
    return delivered

"""Reconnect to native Sessions. Never manufacture a new execution on transport loss."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select

from app.database import SessionLocal
from app.executors.errors import OpenCodeSessionNotFound
from app.executors.opencode_server import server_event_session_id
from app.models import Task
from app.runtime.lifecycle import RuntimeService
from app.runtime.session_connection import connect, resolve_environment
from app.runtime.session_state import SessionState

logger = logging.getLogger(__name__)


async def refresh_sessions():
    async with SessionLocal() as session:
        ids = (
            await session.scalars(
                select(Task.id).where(
                    Task.current_session_id.is_not(None),
                    or_(Task.status.in_(["RUNNING", "WAITING"]), Task.pending_prompt.is_not(None)),
                )
            )
        ).all()
    for task_id in ids:
        async with SessionLocal() as session:
            try:
                await RuntimeService(session).refresh(task_id)
            except OpenCodeSessionNotFound:
                # refresh() already persisted SESSION_MISSING.
                pass
            except Exception as exc:
                await session.rollback()
                await RuntimeService(session).disconnected(task_id, exc)
    return list(ids)


async def watch_session(task_id):
    delay = 1
    while True:
        try:
            async with SessionLocal() as session:
                task = await session.get(Task, task_id)
                if (
                    not task
                    or not task.current_session_id
                    or (task.status not in {"RUNNING", "WAITING"} and not task.pending_prompt)
                ):
                    return
                environment = await resolve_environment(session, task)
                session_id, workspace = task.current_session_id, task.workspace
            async with connect(environment, start=True) as client:
                async with SessionLocal() as session:
                    await RuntimeService(session).refresh(task_id, client=client)
                async for event in client.events(Path(workspace)):
                    if server_event_session_id(event) != session_id:
                        continue
                    if event.get("type") not in {
                        "session.status",
                        "session.idle",
                        "session.error",
                        "question.asked",
                        "question.replied",
                        "permission.asked",
                        "permission.replied",
                    }:
                        continue
                    async with SessionLocal() as session:
                        current = await session.get(Task, task_id)
                        if current.current_session_id != session_id or current.status == "CANCELED":
                            return
                        runtime = RuntimeService(session)
                        if event["type"] == "session.error":
                            current.failure_reason = str(
                                event.get("properties", {}).get("error", "Session error")
                            )
                            await runtime.apply_session_state(
                                current,
                                SessionState(
                                    status="FAILED",
                                    terminal_reason="assistant_error",
                                    finished_at=datetime.now(UTC),
                                ),
                            )
                        else:
                            await runtime.refresh(task_id, client=client)
                        if current.status in {"SUCCEEDED", "FAILED", "CANCELED"}:
                            return
                    delay = 1
                raise ConnectionError("OpenCode Event SSE 已断开")
        except asyncio.CancelledError:
            raise
        except OpenCodeSessionNotFound as exc:
            logger.warning("Session missing for %s: %s", task_id, exc)
            return
        except Exception as exc:
            logger.warning("Session connection lost for %s: %s", task_id, exc)
            async with SessionLocal() as session:
                await RuntimeService(session).disconnected(task_id, exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def supervise_sessions():
    """Reconcile once at startup, then let native SSE/reconnect drive Session state."""
    listeners = {}
    # Startup-only reconciliation covers process restarts without introducing a
    # second periodic state owner beside the native OpenCode event stream.
    await refresh_sessions()
    try:
        while True:
            async with SessionLocal() as session:
                ids = set(
                    (
                        await session.scalars(
                            select(Task.id).where(
                                Task.current_session_id.is_not(None),
                                or_(
                                    Task.status.in_(["RUNNING", "WAITING"]), Task.pending_prompt.is_not(None)
                                ),
                            )
                        )
                    ).all()
                )
            for task_id in ids:
                if task_id not in listeners or listeners[task_id].done():
                    listeners[task_id] = asyncio.create_task(watch_session(task_id))
            for task_id in list(listeners):
                if task_id not in ids:
                    listener = listeners.pop(task_id)
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)
            await asyncio.sleep(2)
    finally:
        for listener in listeners.values():
            listener.cancel()
        await asyncio.gather(*listeners.values(), return_exceptions=True)

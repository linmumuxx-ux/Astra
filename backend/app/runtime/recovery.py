"""Reconnect and reconcile native Sessions without inventing a second execution model."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_, or_, select

from app.config.settings import get_settings
from app.database import SessionLocal
from app.executors.errors import OpenCodeSessionNotFound
from app.executors.opencode_server import server_event_session_id
from app.models import Task, TaskSummary
from app.runtime.lifecycle import RuntimeService
from app.runtime.session_connection import connect, resolve_environment, session_tree
from app.runtime.session_state import SessionState
from app.runtime.summary import (
    TaskSummaryService,
    extract_final_assistant_text,
    summary_is_complete,
)

logger = logging.getLogger(__name__)

SUPERVISOR_INTERVAL_SECONDS = 2
SUPERVISOR_RETRY_MAX_SECONDS = 30


def _active_task_filter():
    # WAITING after MANUAL_CONFIRM submission is a business review state, not
    # an executing Session that needs an SSE watcher.
    return or_(
        Task.status == "RUNNING",
        and_(Task.status == "WAITING", Task.submitted_at.is_(None)),
        Task.pending_prompt.is_not(None),
    )


def _terminal_task_filter():
    return or_(
        Task.status.in_(["SUCCEEDED", "FAILED", "CANCELED"]),
        and_(Task.status == "WAITING", Task.submitted_at.is_not(None)),
    )


def _summary_needs_repair_filter():
    return or_(
        TaskSummary.id.is_(None),
        TaskSummary.stale.is_(True),
        TaskSummary.source_status != Task.status,
        and_(
            Task.status.in_(["SUCCEEDED", "FAILED"]),
            TaskSummary.artifacts_processed_generation < TaskSummary.generation,
        ),
    )


async def refresh_sessions():
    async with SessionLocal() as session:
        ids = (
            await session.scalars(
                select(Task.id).where(
                    Task.current_session_id.is_not(None),
                    _active_task_filter(),
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


async def _refresh_with_client(task_id: str, client) -> Task | None:
    async with SessionLocal() as session:
        task = await RuntimeService(session).refresh(task_id, client=client)
        return task


async def watch_session(task_id):
    """Use native SSE for immediacy and bounded refresh for eventual convergence."""

    delay = 1
    settings = get_settings()
    loop = asyncio.get_running_loop()
    while True:
        next_event: asyncio.Task | None = None
        try:
            async with SessionLocal() as session:
                task = await session.get(Task, task_id)
                if (
                    not task
                    or not task.current_session_id
                    or not (
                        task.status == "RUNNING"
                        or (task.status == "WAITING" and task.submitted_at is None)
                        or task.pending_prompt
                    )
                ):
                    return
                environment = await resolve_environment(session, task)
                session_id, workspace = task.current_session_id, task.workspace
                await session.commit()

            async with connect(environment, start=True) as client:
                directory = Path(workspace)
                events = client.events(directory).__aiter__()
                # Start the subscription first, then reconcile. A bounded refresh
                # below closes any remaining read-before-subscribe race.
                next_event = asyncio.create_task(anext(events))
                current = await _refresh_with_client(task_id, client)
                if not current or current.status in {"SUCCEEDED", "FAILED", "CANCELED"}:
                    return
                if current.status == "WAITING" and current.submitted_at is not None:
                    return
                allowed = await session_tree(client, directory, session_id)
                deadline = loop.time() + settings.opencode_reconcile_interval_seconds

                while True:
                    # The reconcile deadline is absolute: unrelated SSE events must
                    # never push convergence past it.
                    if loop.time() >= deadline:
                        current = await _refresh_with_client(task_id, client)
                        if not current or current.status in {"SUCCEEDED", "FAILED", "CANCELED"}:
                            return
                        if current.status == "WAITING" and current.submitted_at is not None:
                            return
                        allowed = await session_tree(client, directory, session_id)
                        delay = 1
                        deadline = (
                            loop.time() + settings.opencode_reconcile_interval_seconds
                        )
                        continue

                    done, _ = await asyncio.wait(
                        {next_event},
                        timeout=max(0, deadline - loop.time()),
                    )
                    if not done:
                        continue

                    try:
                        event = next_event.result()
                    except StopAsyncIteration as exc:
                        raise ConnectionError("OpenCode Event SSE 已断开") from exc
                    next_event = asyncio.create_task(anext(events))

                    props = event.get("properties", {})
                    info = props.get("info", {}) if isinstance(props.get("info"), dict) else {}
                    if event.get("type") == "session.created" and info.get("parentID") in allowed:
                        child_id = info.get("id")
                        if child_id:
                            allowed.add(child_id)
                    event_session_id = server_event_session_id(event)
                    if event_session_id and event_session_id not in allowed:
                        continue
                    if event.get("type") not in {
                        "session.created",
                        "session.status",
                        "session.idle",
                        "session.error",
                        "question.asked",
                        "question.replied",
                        "permission.asked",
                        "permission.replied",
                    }:
                        continue

                    if event["type"] == "session.error" and event_session_id == session_id:
                        async with SessionLocal() as session:
                            current = await session.get(Task, task_id)
                            if not current or current.current_session_id != session_id:
                                return
                            current.failure_reason = str(props.get("error", "Session error"))
                            await RuntimeService(session).apply_session_state(
                                current,
                                SessionState(
                                    status="FAILED",
                                    terminal_reason="assistant_error",
                                    finished_at=datetime.now(UTC),
                                ),
                            )
                    else:
                        current = await _refresh_with_client(task_id, client)

                    if not current or current.status in {"SUCCEEDED", "FAILED", "CANCELED"}:
                        return
                    if current.status == "WAITING" and current.submitted_at is not None:
                        return
                    allowed = await session_tree(client, directory, session_id)
                    delay = 1
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
        finally:
            if next_event and not next_event.done():
                next_event.cancel()
                await asyncio.gather(next_event, return_exceptions=True)


async def _read_final_text(session, task: Task) -> str:
    """Read the current turn's real final assistant reply from the bound Session."""

    environment = await resolve_environment(session, task)
    anchor_id = task.last_message_id
    session_id = task.current_session_id
    workspace = task.workspace
    await session.commit()
    async with connect(environment, start=True) as client:
        messages = await client.messages(Path(workspace), session_id)
    final_text, _ = extract_final_assistant_text(messages, turn_anchor_id=anchor_id)
    return final_text


async def reconcile_terminal_artifacts(limit: int = 100) -> list[str]:
    """Repair summaries/experience after a crash between Task terminal commit and artifact commit."""

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Task.id)
                .outerjoin(TaskSummary, TaskSummary.task_id == Task.id)
                .where(_terminal_task_filter(), _summary_needs_repair_filter())
                .order_by(Task.updated_at.desc())
                .limit(limit)
            )
        ).all()
    task_ids = [row[0] for row in rows]

    repaired: list[str] = []
    for task_id in task_ids:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                continue
            summary = await session.scalar(
                select(TaskSummary).where(TaskSummary.task_id == task.id)
            )
            needs_summary = not summary_is_complete(summary, task)
            needs_artifacts = bool(
                summary
                and task.status in {"SUCCEEDED", "FAILED"}
                and summary.artifacts_processed_generation < summary.generation
            )
            if not needs_summary and not needs_artifacts:
                continue

            final_text = summary.summary if summary and not summary.stale else ""
            if needs_summary and task.current_session_id and task.workspace:
                try:
                    final_text = await _read_final_text(session, task)
                except OpenCodeSessionNotFound:
                    # The Session is proven absent; recorded Task facts are definitive.
                    final_text = ""
                except Exception as exc:
                    # Temporary transport failure: keep the Task pending so the next
                    # reconcile round can still read the real result.
                    logger.warning(
                        "Unable to reload terminal Session for artifact repair %s: %s",
                        task_id,
                        exc,
                    )
                    await session.rollback()
                    continue
                task = await session.get(Task, task_id)

            summary = await TaskSummaryService(session).upsert(
                task,
                source_status=task.status,
                primary_session_id=task.current_session_id,
                summary_text=final_text,
            )
            if task.status in {"SUCCEEDED", "FAILED"}:
                await RuntimeService(session).process_terminal_artifacts(task, summary)
            repaired.append(task_id)
    return repaired


async def supervise_sessions():
    """Own native Session watching and idempotent terminal artifact repair."""

    listeners: dict[str, asyncio.Task] = {}
    try:
        await refresh_sessions()
    except Exception:
        logger.exception("Session Supervisor 初始 refresh 失败，继续运行")
    try:
        await reconcile_terminal_artifacts()
    except Exception:
        logger.exception("Session Supervisor 初始终态产物对账失败，继续运行")
    settings = get_settings()
    loop = asyncio.get_running_loop()
    next_artifact_reconcile = loop.time() + settings.terminal_artifact_reconcile_interval_seconds
    delay = SUPERVISOR_INTERVAL_SECONDS
    try:
        while True:
            try:
                async with SessionLocal() as session:
                    ids = set(
                        (
                            await session.scalars(
                                select(Task.id).where(
                                    Task.current_session_id.is_not(None),
                                    _active_task_filter(),
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

                if loop.time() >= next_artifact_reconcile:
                    await reconcile_terminal_artifacts()
                    next_artifact_reconcile = (
                        loop.time() + settings.terminal_artifact_reconcile_interval_seconds
                    )
                delay = SUPERVISOR_INTERVAL_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session Supervisor 周期失败，退避后重试")
                delay = min(delay * 2, SUPERVISOR_RETRY_MAX_SECONDS)
            await asyncio.sleep(delay)
    finally:
        for listener in listeners.values():
            listener.cancel()
        await asyncio.gather(*listeners.values(), return_exceptions=True)

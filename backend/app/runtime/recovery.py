"""Reconnect and reconcile native Sessions without inventing a second execution model."""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import and_, or_, select

from app.assistant.review import reconcile_task_reviews
from app.config.settings import get_settings
from app.database import SessionLocal
from app.executors.errors import OpenCodeSessionNotFound
from app.executors.opencode_server import server_event_session_id
from app.models import Task
from app.runtime.lifecycle import RuntimeService
from app.runtime.session_connection import connect, resolve_environment, session_tree

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
    # Each bound Session is refreshed concurrently behind a bound so one slow or
    # unreachable Session cannot serialize the others.
    semaphore = asyncio.Semaphore(get_settings().supervisor_max_concurrency)

    async def refresh_one(task_id: str) -> None:
        async with semaphore:
            async with SessionLocal() as session:
                try:
                    await RuntimeService(session).refresh(task_id)
                except OpenCodeSessionNotFound:
                    # refresh() already persisted SESSION_MISSING.
                    pass
                except Exception as exc:
                    await session.rollback()
                    await RuntimeService(session).disconnected(task_id, exc)

    await asyncio.gather(*(refresh_one(task_id) for task_id in ids), return_exceptions=True)
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
                        # An error event only proves the Session had an error at some
                        # point; it does not prove the current round failed. Record the
                        # native reason, then let a live re-read decide the round.
                        async with SessionLocal() as session:
                            current = await session.get(Task, task_id)
                            if not current or current.current_session_id != session_id:
                                return
                            if current.status not in {"SUCCEEDED", "FAILED", "CANCELED"}:
                                current.failure_reason = str(
                                    props.get("error", "Session error")
                                )
                            await session.commit()

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


class _BackgroundWork:
    """Bounded, single-flight background jobs owned by the Supervisor.

    Jobs run off the supervision loop so a slow assistant dispatch or history
    recovery can never delay Session discovery or listener management.
    """

    def __init__(self, limit: int):
        self._semaphore = asyncio.Semaphore(limit)
        self._tasks: dict[str, asyncio.Task] = {}

    def running(self, name: str) -> bool:
        task = self._tasks.get(name)
        return bool(task and not task.done())

    def spawn(self, name: str, factory) -> None:
        if self.running(name):
            return

        async def runner() -> None:
            async with self._semaphore:
                await factory()

        task = asyncio.create_task(runner())
        self._tasks[name] = task

        def _discard(done: asyncio.Task, key: str = name) -> None:
            if self._tasks.get(key) is done:
                self._tasks.pop(key, None)
            if not done.cancelled() and done.exception() is not None:
                logger.error("后台任务 %s 失败", key, exc_info=done.exception())

        task.add_done_callback(_discard)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


async def supervise_sessions():
    """Own native Session watching and independent assistant review dispatch."""

    listeners: dict[str, asyncio.Task] = {}
    settings = get_settings()
    loop = asyncio.get_running_loop()
    work = _BackgroundWork(settings.supervisor_max_concurrency)
    next_review_reconcile = loop.time() + settings.task_review_reconcile_interval_seconds
    delay = SUPERVISOR_INTERVAL_SECONDS
    try:
        # Startup recovery/repair is scheduled off-loop: discovery and listener
        # creation must never wait on a slow OpenCode request.
        work.spawn("startup_refresh", refresh_sessions)
        work.spawn("startup_reviews", reconcile_task_reviews)
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

                if loop.time() >= next_review_reconcile:
                    # Never await repair inline; keep supervising while it runs.
                    work.spawn("reviews", reconcile_task_reviews)
                    next_review_reconcile = (
                        loop.time() + settings.task_review_reconcile_interval_seconds
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
        await work.shutdown()

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import get_settings
from app.models import Base, Task
from app.runtime import recovery


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _fake_resolve_environment(session, task):
    return SimpleNamespace(mode="LOCAL", opencode_server_port=1, workspace_root="/tmp")


async def _fake_session_tree(client, directory, session_id):
    return {session_id}


async def test_watch_session_reconciles_on_absolute_deadline(
    monkeypatch, session_factory, tmp_path
):
    async with session_factory() as session:
        session.add(
            Task(
                id="T1",
                task_type="ISSUE",
                title="t",
                status="RUNNING",
                current_session_id="ses_current",
                workspace=str(tmp_path),
            )
        )
        await session.commit()

    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "resolve_environment", _fake_resolve_environment)
    monkeypatch.setattr(recovery, "session_tree", _fake_session_tree)

    class FakeClient:
        async def _events(self):
            while True:
                yield {"type": "message.part.updated", "properties": {}}
                await asyncio.sleep(0)

        def events(self, directory):
            return self._events()

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        yield FakeClient()

    monkeypatch.setattr(recovery, "connect", fake_connect)
    monkeypatch.setattr(
        get_settings(), "opencode_reconcile_interval_seconds", 0.05
    )

    refreshes = {"count": 0}

    async def fake_refresh(task_id, client):
        refreshes["count"] += 1
        return SimpleNamespace(
            status="RUNNING", current_session_id="ses_current", submitted_at=None
        )

    monkeypatch.setattr(recovery, "_refresh_with_client", fake_refresh)

    watcher = asyncio.create_task(recovery.watch_session("T1"))
    await asyncio.sleep(0.4)
    watcher.cancel()
    await asyncio.gather(watcher, return_exceptions=True)

    assert refreshes["count"] > 1


async def test_old_session_error_event_does_not_fail_new_running_round(
    monkeypatch, session_factory, tmp_path
):
    async with session_factory() as session:
        session.add(
            Task(
                id="T1",
                task_type="ISSUE",
                title="t",
                status="RUNNING",
                current_session_id="ses_current",
                workspace=str(tmp_path),
                last_message_id="msg_new_round",
            )
        )
        await session.commit()

    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "resolve_environment", _fake_resolve_environment)
    monkeypatch.setattr(recovery, "session_tree", _fake_session_tree)

    class FakeClient:
        def __init__(self):
            self._sent = False

        async def _events(self):
            while True:
                if not self._sent:
                    self._sent = True
                    yield {
                        "type": "session.error",
                        "properties": {
                            "sessionID": "ses_current",
                            "error": "old round failed",
                        },
                    }
                await asyncio.sleep(0.01)

        def events(self, directory):
            return self._events()

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        yield FakeClient()

    monkeypatch.setattr(recovery, "connect", fake_connect)

    # The live re-read proves the new round is still running.
    async def fake_refresh(task_id, client):
        return SimpleNamespace(
            status="RUNNING", current_session_id="ses_current", submitted_at=None
        )

    monkeypatch.setattr(recovery, "_refresh_with_client", fake_refresh)

    watcher = asyncio.create_task(recovery.watch_session("T1"))
    await asyncio.sleep(0.15)
    watcher.cancel()
    await asyncio.gather(watcher, return_exceptions=True)

    async with session_factory() as session:
        task = await session.get(Task, "T1")
    assert task.status == "RUNNING"
    assert task.failure_reason == "old round failed"


async def test_slow_artifact_repair_does_not_block_session_discovery(
    monkeypatch, session_factory
):
    async with session_factory() as session:
        session.add(
            Task(
                id="T1",
                task_type="ISSUE",
                title="t",
                status="RUNNING",
                current_session_id="ses_1",
                workspace="/tmp/ws",
            )
        )
        await session.commit()

    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "SUPERVISOR_INTERVAL_SECONDS", 0.05)

    async def noop_refresh(*args, **kwargs):
        return []

    monkeypatch.setattr(recovery, "refresh_sessions", noop_refresh)

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_reconcile(*args, **kwargs):
        started.set()
        await release.wait()
        return []

    monkeypatch.setattr(recovery, "reconcile_terminal_artifacts", slow_reconcile)

    discovered: list[str] = []
    watcher_started = asyncio.Event()

    async def fake_watch(task_id):
        discovered.append(task_id)
        if task_id == "T2":
            watcher_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(recovery, "watch_session", fake_watch)

    supervisor = asyncio.create_task(recovery.supervise_sessions())
    await asyncio.wait_for(started.wait(), timeout=2)

    # A new Task must still be discovered while the repair stays blocked.
    async with session_factory() as session:
        session.add(
            Task(
                id="T2",
                task_type="ISSUE",
                title="t2",
                status="RUNNING",
                current_session_id="ses_2",
                workspace="/tmp/ws",
            )
        )
        await session.commit()

    await asyncio.wait_for(watcher_started.wait(), timeout=2)
    assert "T1" in discovered
    assert "T2" in discovered
    assert not release.is_set()

    release.set()
    supervisor.cancel()
    with pytest.raises(asyncio.CancelledError):
        await supervisor


async def test_supervisor_survives_transient_db_failure(monkeypatch, session_factory):
    async def noop(*args, **kwargs):
        return []

    monkeypatch.setattr(recovery, "refresh_sessions", noop)
    monkeypatch.setattr(recovery, "reconcile_terminal_artifacts", noop)

    real_asyncio = asyncio
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)
        await real_asyncio.sleep(0)

    monkeypatch.setattr(
        recovery,
        "asyncio",
        SimpleNamespace(
            sleep=fake_sleep,
            get_running_loop=real_asyncio.get_running_loop,
            create_task=real_asyncio.create_task,
            gather=real_asyncio.gather,
            CancelledError=real_asyncio.CancelledError,
            wait=real_asyncio.wait,
            Semaphore=real_asyncio.Semaphore,
        ),
    )

    calls = {"count": 0}

    class UnavailableSession:
        async def __aenter__(self):
            raise RuntimeError("database temporarily unavailable")

        async def __aexit__(self, *exc):
            return False

    class FlakyFactory:
        def __call__(self):
            index = calls["count"]
            calls["count"] += 1
            if index < 2:
                return UnavailableSession()
            return session_factory()

    monkeypatch.setattr(recovery, "SessionLocal", FlakyFactory())

    supervisor = asyncio.create_task(recovery.supervise_sessions())
    for _ in range(500):
        await real_asyncio.sleep(0)
        if calls["count"] >= 5:
            break

    assert not supervisor.done()
    supervisor.cancel()
    with pytest.raises(real_asyncio.CancelledError):
        await supervisor

    assert calls["count"] >= 5
    assert len(delays) >= 3
    assert delays[0] < delays[1]
    assert delays[2] == recovery.SUPERVISOR_INTERVAL_SECONDS
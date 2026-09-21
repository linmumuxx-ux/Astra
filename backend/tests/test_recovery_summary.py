from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.executors.errors import OpenCodeSessionNotFound
from app.models import Base, DigitalEmployee, RuntimeSession, Task, TaskSummary
from app.runtime import recovery
from app.runtime.lifecycle import RuntimeService, RuntimeStateError


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


class _FakeClient:
    def __init__(self, state):
        self._state = state

    async def messages(self, directory, sid):
        error = self._state.get("error")
        if error is not None:
            raise error
        return self._state["messages"]


def _install_connect(monkeypatch, state):
    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        yield _FakeClient(state)

    monkeypatch.setattr(recovery, "connect", fake_connect)


def _noop_artifacts(monkeypatch):
    async def noop(self, task):
        return None

    monkeypatch.setattr(RuntimeService, "_reconcile_experience", noop)
    monkeypatch.setattr(RuntimeService, "_extract_experience", noop)


async def _seed_terminal_task(session_factory, *, task_id="T1", status="SUCCEEDED", **kwargs):
    async with session_factory() as session:
        session.add(
            Task(
                id=task_id,
                task_type="ISSUE",
                title="t",
                status=status,
                current_session_id="ses_1",
                workspace="/tmp/ws",
                last_message_id="msg_anchor",
                current_progress="中间进度",
                **kwargs,
            )
        )
        await session.commit()


def _reply_messages(text):
    return [
        {"info": {"id": "msg_anchor", "role": "user"}, "parts": [{"type": "text", "text": "go"}]},
        {"info": {"id": "msg_reply", "role": "assistant"}, "parts": [{"type": "text", "text": text}]},
    ]


async def test_transient_network_failure_keeps_summary_pending(monkeypatch, session_factory):
    await _seed_terminal_task(session_factory)
    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "resolve_environment", _fake_resolve_environment)
    _install_connect(
        monkeypatch, {"messages": [], "error": ConnectionError("network down")}
    )

    repaired = await recovery.reconcile_terminal_artifacts()

    async with session_factory() as session:
        summary = await session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == "T1")
        )
    assert repaired == []
    assert summary is None


async def test_recovery_reads_real_final_reply(monkeypatch, session_factory):
    await _seed_terminal_task(session_factory)
    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "resolve_environment", _fake_resolve_environment)
    _noop_artifacts(monkeypatch)
    state = {"messages": [], "error": ConnectionError("network down")}
    _install_connect(monkeypatch, state)

    assert await recovery.reconcile_terminal_artifacts() == []

    state["error"] = None
    state["messages"] = _reply_messages("真实最终回复")
    repaired = await recovery.reconcile_terminal_artifacts()

    async with session_factory() as session:
        summary = await session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == "T1")
        )
    assert repaired == ["T1"]
    assert summary.summary == "真实最终回复"
    assert summary.stale is False
    assert summary.source_status == "SUCCEEDED"
    assert summary.artifacts_processed_generation == summary.generation


async def test_missing_session_uses_recorded_facts(monkeypatch, session_factory):
    await _seed_terminal_task(
        session_factory,
        status="FAILED",
        failure_reason="Session 已不存在，保留失败事实",
    )
    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "resolve_environment", _fake_resolve_environment)
    _noop_artifacts(monkeypatch)
    _install_connect(
        monkeypatch, {"messages": [], "error": OpenCodeSessionNotFound("ses_1")}
    )

    repaired = await recovery.reconcile_terminal_artifacts()

    async with session_factory() as session:
        summary = await session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == "T1")
        )
    assert repaired == ["T1"]
    assert summary.summary == "Session 已不存在，保留失败事实"
    assert summary.stale is False
    assert summary.source_status == "FAILED"


async def test_artifacts_only_repair_does_not_reread_messages(monkeypatch, session_factory):
    await _seed_terminal_task(session_factory)
    async with session_factory() as session:
        session.add(
            TaskSummary(
                id="TS-1",
                task_id="T1",
                primary_session_id="ses_1",
                summary="已完成结果",
                source_status="SUCCEEDED",
                generation=1,
                stale=False,
                artifacts_processed_generation=0,
            )
        )
        await session.commit()

    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "resolve_environment", _fake_resolve_environment)
    calls = {"read": 0}

    @asynccontextmanager
    async def failing_connect(*args, **kwargs):
        calls["read"] += 1
        raise AssertionError("messages must not be re-read for artifacts-only repair")
        yield  # pragma: no cover

    monkeypatch.setattr(recovery, "connect", failing_connect)
    processed = {"count": 0}

    async def noop(self, task):
        processed["count"] += 1

    monkeypatch.setattr(RuntimeService, "_reconcile_experience", noop)
    monkeypatch.setattr(RuntimeService, "_extract_experience", noop)

    repaired = await recovery.reconcile_terminal_artifacts()

    async with session_factory() as session:
        summary = await session.get(TaskSummary, "TS-1")
    assert repaired == ["T1"]
    assert calls["read"] == 0
    assert processed["count"] == 2
    assert summary.artifacts_processed_generation == summary.generation


async def test_limit_filters_pending_before_scan_window(monkeypatch, session_factory):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        session.add(
            Task(
                id="T-OLD",
                task_type="ISSUE",
                title="old",
                status="SUCCEEDED",
                current_session_id="ses_old",
                workspace="/tmp/ws",
                last_message_id="msg_anchor",
                current_progress="旧任务进度",
                updated_at=base,
            )
        )
        for index in range(100):
            session.add(
                Task(
                    id=f"T-NEW-{index}",
                    task_type="ISSUE",
                    title=f"new{index}",
                    status="SUCCEEDED",
                    current_session_id=f"ses_{index}",
                    workspace="/tmp/ws",
                    updated_at=base + timedelta(seconds=index + 1),
                )
            )
        await session.commit()
        for index in range(100):
            session.add(
                TaskSummary(
                    id=f"TS-NEW-{index}",
                    task_id=f"T-NEW-{index}",
                    summary="done",
                    source_status="SUCCEEDED",
                    generation=1,
                    stale=False,
                    artifacts_processed_generation=1,
                )
            )
        await session.commit()

    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(recovery, "resolve_environment", _fake_resolve_environment)
    _noop_artifacts(monkeypatch)
    _install_connect(
        monkeypatch, {"messages": _reply_messages("旧任务真实回复"), "error": None}
    )

    repaired = await recovery.reconcile_terminal_artifacts(limit=100)

    assert repaired == ["T-OLD"]
    async with session_factory() as session:
        summary = await session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == "T-OLD")
        )
    assert summary is not None
    assert summary.summary == "旧任务真实回复"


async def _seed_manual_confirm(session_factory, *, summary=None, stale=False):
    async with session_factory() as session:
        session.add(DigitalEmployee(id="E1", name="Eng", role="build", status="IDLE"))
        session.add(
            Task(
                id="T1",
                task_type="ISSUE",
                title="t",
                status="WAITING",
                completion_policy="MANUAL_CONFIRM",
                employee_id="E1",
                current_session_id="ses_1",
                workspace="/tmp/ws",
                last_message_id="msg_anchor",
                current_progress="等待人工确认",
                submitted_at=datetime.now(UTC),
            )
        )
        session.add(
            RuntimeSession(
                id="ses_1",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="SUCCEEDED",
            )
        )
        if summary is not None:
            session.add(
                TaskSummary(
                    id="TS-1",
                    task_id="T1",
                    primary_session_id="ses_1",
                    summary=summary,
                    source_status="WAITING",
                    generation=1,
                    stale=stale,
                    artifacts_processed_generation=1,
                )
            )
        await session.commit()


async def test_confirm_rejects_missing_summary(monkeypatch, session_factory):
    await _seed_manual_confirm(session_factory, summary=None)
    _noop_artifacts(monkeypatch)

    async with session_factory() as session:
        with pytest.raises(RuntimeStateError, match="摘要尚未补齐"):
            await RuntimeService(session).confirm_completion("T1")
        await session.rollback()

    async with session_factory() as session:
        task = await session.get(Task, "T1")
        summary = await session.get(TaskSummary, "TS-1")
    assert task.status == "WAITING"
    assert task.confirmed_at is None
    assert task.submitted_at is not None
    assert summary is None


async def test_confirm_rejects_stale_summary(monkeypatch, session_factory):
    await _seed_manual_confirm(session_factory, summary="旧结果", stale=True)
    _noop_artifacts(monkeypatch)

    async with session_factory() as session:
        with pytest.raises(RuntimeStateError, match="摘要尚未补齐"):
            await RuntimeService(session).confirm_completion("T1")
        await session.rollback()

    async with session_factory() as session:
        task = await session.get(Task, "T1")
        summary = await session.get(TaskSummary, "TS-1")
    assert task.status == "WAITING"
    assert task.confirmed_at is None
    assert summary.stale is True
    assert summary.summary == "旧结果"


async def test_confirm_succeeds_with_complete_summary(monkeypatch, session_factory):
    await _seed_manual_confirm(session_factory, summary="真实已完成结果", stale=False)
    _noop_artifacts(monkeypatch)

    async with session_factory() as session:
        task = await RuntimeService(session).confirm_completion("T1")
        assert task.status == "SUCCEEDED"

    async with session_factory() as session:
        summary = await session.get(TaskSummary, "TS-1")
    assert summary.summary == "真实已完成结果"
    assert summary.source_status == "SUCCEEDED"
    assert summary.artifacts_processed_generation == summary.generation
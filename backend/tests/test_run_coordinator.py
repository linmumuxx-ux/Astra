from types import SimpleNamespace

import pytest

import app.runtime.run_coordinator as run_coordinator_module
from app.domain import ExecutionMode
from app.runtime.run_coordinator import RunCoordinator


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSessionFactory:
    def __call__(self):
        return _FakeSession()


@pytest.mark.asyncio
async def test_run_coordinator_rejects_identifier_without_run_lease(monkeypatch):
    monkeypatch.setattr(run_coordinator_module, "SessionLocal", _FakeSessionFactory())
    received = None

    class FakeRuntime:
        def __init__(self, session):
            pass

        async def claim_run(self, run_id, *, worker_id):
            nonlocal received
            received = (run_id, worker_id)
            return None

    monkeypatch.setattr(run_coordinator_module, "RuntimeService", FakeRuntime)

    await RunCoordinator().process("TASK-001", worker_id="worker-1")

    assert received == ("TASK-001", "worker-1")


@pytest.mark.asyncio
async def test_run_coordinator_enters_execution_only_after_run_claim(monkeypatch):
    monkeypatch.setattr(run_coordinator_module, "SessionLocal", _FakeSessionFactory())
    calls: list[str] = []
    task = SimpleNamespace(
        id="TASK-001",
        opencode_session_id=None,
        execution_environment_snapshot={},
    )
    employee = SimpleNamespace(id="EMP-001")
    run = SimpleNamespace(
        id="RUN-001",
        started_at=None,
        opencode_session_id=None,
    )

    class FakeRuntime:
        def __init__(self, session):
            pass

        async def claim_run(self, run_id, *, worker_id):
            calls.append(f"claim:{run_id}:{worker_id}")
            return task, employee, run, "token-1"

        async def mark_running(self, claimed_task, claimed_run, execution_token):
            calls.append(f"mark:{claimed_run.id}:{execution_token}")
            return False

    monkeypatch.setattr(run_coordinator_module, "RuntimeService", FakeRuntime)
    monkeypatch.setattr(
        RunCoordinator,
        "_resolve_environment",
        staticmethod(
            lambda task, employee: SimpleNamespace(
                workspace_root="/tmp/astra-runtime-test",
                mode=ExecutionMode.LINUX_REMOTE,
                name="test-env",
            )
        ),
    )

    await RunCoordinator().process("RUN-001", worker_id="worker-1")

    assert calls == ["claim:RUN-001:worker-1", "mark:RUN-001:token-1"]

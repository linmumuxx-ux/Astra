import pytest

import app.runtime.run_coordinator as run_coordinator_module
from app.runtime.coordinator import TaskCoordinator
from app.runtime.run_coordinator import RunCoordinator


class _FakeSession:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, key):
        return self.value


class _FakeSessionFactory:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return _FakeSession(self.value)


@pytest.mark.asyncio
async def test_run_coordinator_rejects_non_run_identifier(monkeypatch):
    monkeypatch.setattr(run_coordinator_module, "SessionLocal", _FakeSessionFactory(None))
    called = False

    async def parent_process(self, run_id, *, worker_id=None):
        nonlocal called
        called = True

    monkeypatch.setattr(TaskCoordinator, "process", parent_process)

    await RunCoordinator().process("TASK-001", worker_id="worker-1")

    assert called is False


@pytest.mark.asyncio
async def test_run_coordinator_delegates_persisted_run(monkeypatch):
    monkeypatch.setattr(run_coordinator_module, "SessionLocal", _FakeSessionFactory(object()))
    received = None

    async def parent_process(self, run_id, *, worker_id=None):
        nonlocal received
        received = (run_id, worker_id)

    monkeypatch.setattr(TaskCoordinator, "process", parent_process)

    await RunCoordinator().process("RUN-001", worker_id="worker-1")

    assert received == ("RUN-001", "worker-1")

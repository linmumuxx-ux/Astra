import asyncio
from pathlib import Path

from app.config.settings import Settings
from app.executors.opencode_server import (
    OpenCodeServerExecutor,
    OpenCodeSessionNotFound,
)
from app.models import Run, Task


class MissingSessionClient:
    async def health(self):
        return {"healthy": True, "version": "test"}

    async def events(self, _directory):
        yield {"type": "server.connected", "properties": {}}
        await asyncio.Event().wait()

    async def session(self, _directory, session_id):
        raise OpenCodeSessionNotFound(session_id)


def settings() -> Settings:
    return Settings(
        executor_type="opencode_server",
        opencode_model="opencode/glm-5.1",
        opencode_timeout_seconds=2,
        seed_demo=False,
    )


async def test_missing_opencode_session_returns_structured_failure(tmp_path: Path):
    task = Task(
        id="T-SESSION-MISSING",
        source="manual",
        task_type="ISSUE",
        title="Session recovery",
        opencode_session_id="ses-missing",
    )
    run = Run(
        id="RUN-SESSION-MISSING",
        task_id=task.id,
        employee_id="employee",
        run_number=1,
        opencode_session_id="ses-missing",
    )
    executor = OpenCodeServerExecutor(settings(), client=MissingSessionClient())

    result = await executor.resume(task, run, tmp_path)

    assert result.status == "FAILED"
    assert result.exit_code == 1
    assert result.session_id == "ses-missing"
    assert result.failure_code == "SESSION_NOT_FOUND"

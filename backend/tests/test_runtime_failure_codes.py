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


def test_every_failure_has_one_shared_policy():
    from app.runtime.failure import FailureCode, failure_for

    for code in FailureCode:
        failure = failure_for(code, "raw detail")
        assert failure.failure_code == code
        assert failure.failure_scope
        assert failure.recovery_action
        assert failure.raw_error == "raw detail"
    assert failure_for(FailureCode.SESSION_NOT_FOUND).recovery_action == "CREATE_SESSION"
    assert not failure_for(FailureCode.USER_CANCELLED).retryable


def test_recovery_cannot_complete_from_previous_turn_or_failed_message():
    from datetime import UTC, datetime

    run = Run(
        id="RUN-result",
        task_id="T-result",
        employee_id="E-result",
        run_number=1,
        started_at=datetime(2026, 9, 8, tzinfo=UTC),
    )
    old_message = {
        "info": {"role": "assistant", "time": {"created": 1}},
        "parts": [{"type": "text", "text": "old success"}],
    }
    collect = OpenCodeServerExecutor.recovered_message_result
    assert collect(run, [old_message], {}) == {}
    failed = {
        "info": {"role": "assistant", "error": {"name": "ProviderError"}},
        "parts": [{"type": "text", "text": "partial output"}],
    }
    result = collect(run, [failed], {})
    assert result["failure_code"] == "SESSION_ERROR"
    assert "raw_text" not in result


async def test_http_failures_are_typed_without_message_matching(monkeypatch):
    import httpx
    import pytest

    from app.executors.errors import OpenCodeExecutionError, OpenCodeServerUnavailable
    from app.executors.opencode_server import OpenCodeServerClient

    original = httpx.AsyncClient
    for status_code, expected in [
        (404, OpenCodeSessionNotFound),
        (503, OpenCodeServerUnavailable),
        (400, OpenCodeExecutionError),
    ]:
        transport = httpx.MockTransport(
            lambda request, status_code=status_code: httpx.Response(status_code, text="opaque error")
        )
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda transport=transport, **kwargs: original(transport=transport, **kwargs),
        )
        with pytest.raises(expected):
            await OpenCodeServerClient(settings()).session(Path("/tmp"), "ses-typed")

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_session
from app.executors.errors import OpenCodeSessionNotFound
from app.main import app
from app.models import (
    Base,
    DigitalEmployee,
    OpenCodeExecutionEnvironment,
    RuntimeSession,
    Task,
    TaskSummary,
)
from app.runtime.environment import environment_snapshot
from app.runtime.lifecycle import RuntimeService, RuntimeStateError
from app.runtime.workspace_files import materialize_task_attachments, same_workspace_path, upload, validate_path


class NativeServer:
    def __init__(self):
        self.sessions = {"ses_current": []}
        self.state = "idle"
        self.pending = []
        self.sent = []
        self.fail_after_accept = False
        self.auth = None
        self.base_url = "http://native"

    def _timeout(self):
        return 5

    async def session(self, directory, sid):
        if sid not in self.sessions:
            raise OpenCodeSessionNotFound(sid)
        return {"id": sid, "directory": str(directory)}

    async def status(self, directory, sid):
        await self.session(directory, sid)
        return self.state

    async def questions(self, directory):
        return self.pending

    async def permissions(self, directory):
        return []

    async def children(self, directory, sid):
        return []

    async def messages(self, directory, sid):
        await self.session(directory, sid)
        return self.sessions[sid]

    async def request(self, method, path, *, directory=None, body=None):
        if method == "POST" and path.endswith("/prompt_async"):
            sid = path.split("/")[2]
            self.sent.append((sid, body))
            self.sessions[sid].append(
                {"info": {"id": body["messageID"], "role": "user"}, "parts": body["parts"]}
            )
            # Real OpenCode persists the assistant placeholder synchronously before
            # prompt_async returns 204; mirror that so an in-flight turn always has an
            # assistant message. A turn that errors before execution (unknown model or
            # provider) persists no assistant message at all.
            self.sessions[sid].append(
                {"info": {"id": f"asst_{body['messageID']}", "role": "assistant"}, "parts": []}
            )
            self.state = "busy"
            if self.fail_after_accept:
                raise ConnectionError("ACK lost")
        if path == "/question":
            return self.pending
        if path == "/permission":
            return []

    async def abort(self, directory, sid):
        self.state = "idle"
        self.pending = []
        return True

    async def create_session(self, directory, **kwargs):
        sid = f"ses_{len(self.sessions)}"
        self.sessions[sid] = []
        return {"id": sid}


@pytest.fixture
async def runtime(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    native = NativeServer()

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield native

    monkeypatch.setattr("app.runtime.lifecycle.connect", connect)
    monkeypatch.setattr("app.api.workspace_routes.connect", connect)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    async with factory() as session:
        employee = DigitalEmployee(id="E1", name="Engineer", role="build", status="IDLE")
        environment = OpenCodeExecutionEnvironment(
            employee_id="E1", mode="LOCAL", name="test", workspace_root=str(workspace), status="AVAILABLE"
        )
        session.add_all([employee, environment])
        await session.flush()
        task = Task(
            id="T1",
            title="Task",
            task_type="ISSUE",
            status="FAILED",
            employee_id="E1",
            current_session_id="ses_current",
            workspace=str(workspace),
            execution_environment_snapshot=environment_snapshot(environment),
        )
        session.add(task)
        session.add(
            RuntimeSession(
                id="ses_current",
                task_id="T1",
                employee_id="E1",
                workspace=str(workspace),
                environment=environment_snapshot(environment),
            )
        )
        await session.commit()

        async def dependency():
            yield session

        app.dependency_overrides[get_session] = dependency
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://astra") as api:
            yield SimpleNamespace(
                session=session,
                native=native,
                task=task,
                environment=environment,
                service=RuntimeService(session),
                api=api,
                workspace=workspace,
            )
        app.dependency_overrides.clear()
    await engine.dispose()


async def test_continue_keeps_session_and_does_not_create_execution_copies(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "continue"}]})
    assert r.task.status == "RUNNING"
    assert r.task.current_session_id == "ses_current"
    assert await r.session.scalar(select(func.count()).select_from(RuntimeSession)) == 1
    assert r.task.pending_prompt is None


async def test_waiting_takes_priority_over_native_busy_and_resumes(runtime):
    r = runtime
    r.native.state = "busy"
    r.native.pending = [{"id": "q1", "sessionID": "ses_current"}]
    await r.service.refresh("T1")
    assert r.task.status == "WAITING"
    with pytest.raises(RuntimeStateError, match="回答"):
        await r.service.send("T1", {"parts": []})
    r.native.pending = []
    await r.service.refresh("T1")
    assert r.task.status == "RUNNING"


async def test_lost_ack_is_reconciled_without_duplicate_prompt(runtime):
    r = runtime
    r.native.fail_after_accept = True
    with pytest.raises(ConnectionError):
        await r.service.send("T1", {"parts": [{"type": "text", "text": "continue"}]})
    assert r.task.status == "FAILED"  # Transport loss does not assert an execution outcome.
    assert r.task.pending_message_id
    r.native.fail_after_accept = False
    await r.service.retry_submission("T1")
    assert len(r.native.sent) == 1
    assert r.task.pending_prompt is None
    assert r.task.status == "RUNNING"


async def test_previous_completed_turn_cannot_complete_new_submission(runtime):
    r = runtime
    r.native.sessions["ses_current"] = [
        {"info": {"id": "old", "role": "assistant", "time": {"completed": 1}, "finish": "stop"}}
    ]
    await r.service.send("T1", {"parts": [{"type": "text", "text": "next turn"}]})
    r.native.state = "idle"
    await r.service.refresh("T1")
    assert r.task.status == "RUNNING"
    r.native.sessions["ses_current"].append(
        {
            "info": {"role": "assistant", "time": {"completed": 2}, "finish": "stop"},
            "parts": [{"type": "text", "text": "new turn completed"}],
        }
    )
    await r.service.refresh("T1")
    assert r.task.status == "SUCCEEDED"


async def test_turn_without_assistant_reply_projects_failed(runtime):
    r = runtime
    await r.service.send("T1", {"messageID": "msg_client0001", "parts": [{"type": "text", "text": "go"}]})
    assert r.task.status == "RUNNING"
    # OpenCode errored before persisting any assistant reply (e.g. unknown model or
    # provider): only the user message exists and the session is idle. This must not
    # stay RUNNING forever.
    r.native.state = "idle"
    r.native.sessions["ses_current"] = [
        {"info": {"id": "msg_client0001", "role": "user"}, "parts": []}
    ]
    # Only an aged turn without any assistant reply is a real failure; a freshly
    # submitted prompt stays RUNNING until the no-reply window elapses.
    r.task.turn_started_at = datetime.now(UTC) - timedelta(minutes=5)
    await r.session.commit()
    await r.service.refresh("T1")
    assert r.task.status == "FAILED"
    assert r.task.failure_reason


async def test_missing_session_never_creates_replacement(runtime):
    r = runtime
    r.native.sessions.clear()
    response = await r.api.post("/api/tasks/T1/reconnect")
    assert response.status_code == 404
    assert r.task.current_session_id == "ses_current"
    assert not r.native.sessions
    assert r.task.status == "FAILED"


async def test_disconnect_preserves_running_and_cancel_is_explicit(runtime):
    r = runtime
    await r.service.project(r.task, "RUNNING")
    await r.service.disconnected("T1", ConnectionError("network down"))
    assert r.task.status == "RUNNING"
    assert r.task.runtime_connection == "UNAVAILABLE"
    await r.service.stop("T1")
    assert r.task.status == "CANCELED"
    r.native.state = "idle"
    await r.service.refresh("T1")
    assert r.task.status == "CANCELED"


async def test_explicit_restart_supersedes_each_running_session(runtime):
    r = runtime
    await r.service.start("T1", restart=True)
    first_new = r.task.current_session_id
    assert first_new != "ses_current"
    assert await r.session.scalar(select(func.count()).select_from(RuntimeSession)) == 2
    old = await r.session.get(RuntimeSession, "ses_current")
    assert old.status == "INTERRUPTED"
    assert old.terminal_reason == "aborted"
    assert old.superseded_by == first_new and old.superseded_at is not None

    await r.service.start("T1", restart=True)
    second_new = r.task.current_session_id
    assert second_new != first_new
    assert await r.session.scalar(select(func.count()).select_from(RuntimeSession)) == 3
    first = await r.session.get(RuntimeSession, first_new)
    assert first.status == "INTERRUPTED"
    assert first.superseded_by == second_new


def test_windows_workspace_path_comparison_accepts_slash_and_case_variants(runtime):
    assert same_workspace_path(
        runtime.environment,
        r"D:\Code\Astra\.astra-tasks\E1\T1",
        "d:/Code/Astra/.astra-tasks/E1/T1",
    )


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", ".git/config", "..\\secret"])
async def test_file_path_cannot_escape_workspace(runtime, path):
    with pytest.raises(PermissionError):
        await validate_path(runtime.environment, str(runtime.workspace), path)


async def test_symlink_escape_and_upload_symlink_are_rejected(runtime, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (runtime.workspace / "escape").symlink_to(outside)
    (runtime.workspace / "uploads").symlink_to(outside)
    with pytest.raises(PermissionError):
        await validate_path(runtime.environment, str(runtime.workspace), "escape/private")
    with pytest.raises(PermissionError):
        await upload(runtime.environment, str(runtime.workspace), "test.txt", b"content")
    assert not list(outside.iterdir())


async def test_upload_lands_in_workspace_and_returns_actual_path(runtime):
    response = await runtime.api.post("/api/tasks/T1/files/input.txt", content=b"hello")
    assert response.status_code == 200
    path = Path(response.json()["path"])
    assert path.parent == runtime.workspace / "uploads"
    assert path.read_bytes() == b"hello"

async def test_task_creation_attachment_materializes_once(runtime):
    attachments = [
        {
            "name": "requirements.md",
            "size": 5,
            "content_type": "text/markdown",
            "content": "data:text/markdown;base64,aGVsbG8=",
        }
    ]
    first = await materialize_task_attachments(
        runtime.environment, str(runtime.workspace), attachments
    )
    assert "content" not in first[0]
    path = Path(first[0]["workspace_path"])
    assert path.read_bytes() == b"hello"

    second = await materialize_task_attachments(
        runtime.environment, str(runtime.workspace), first
    )
    assert second[0]["workspace_path"] == first[0]["workspace_path"]
    assert len(list((runtime.workspace / "uploads").iterdir())) == 1



@pytest.mark.parametrize("path", ["session/ses_other/message", "global/dispose", "config", "pty"])
async def test_gateway_rejects_cross_session_and_global_mutations(runtime, path):
    response = await runtime.api.post(f"/api/tasks/T1/opencode/ses_current/{path}", json={})
    assert response.status_code == 403
    assert not runtime.native.sent


async def test_shells_read_is_allowed_but_pty_lifecycle_is_denied(runtime, monkeypatch):
    """Native Settings only needs the read-only shell list; PTY lifecycle stays denied."""
    original = httpx.AsyncClient

    def upstream(request):
        assert request.url.path == "/pty/shells"
        assert request.url.params["directory"] == str(runtime.workspace)
        return httpx.Response(200, json=[{"path": "/bin/bash", "name": "bash", "acceptable": True}])

    monkeypatch.setattr(
        "app.api.workspace_routes.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs),
    )
    shells = await runtime.api.get("/api/tasks/T1/opencode/ses_current/pty/shells")
    assert shells.status_code == 200
    assert shells.json() == [{"path": "/bin/bash", "name": "bash", "acceptable": True}]
    assert (
        await runtime.api.post("/api/tasks/T1/opencode/ses_current/pty", json={})
    ).status_code == 403
    assert (
        await runtime.api.get("/api/tasks/T1/opencode/ses_current/pty/pty_1/connect")
    ).status_code == 403
    assert not runtime.native.sent


async def test_gateway_rejects_forged_binding_and_directory(runtime):
    response = await runtime.api.get("/api/tasks/T1/opencode/ses_other/session")
    assert response.status_code == 404
    response = await runtime.api.get(
        "/api/tasks/T1/opencode/ses_current/session", params={"directory": "/other"}
    )
    assert response.status_code == 403


async def test_native_composer_submission_uses_existing_session(runtime):
    response = await runtime.api.post(
        "/api/tasks/T1/opencode/ses_current/session/ses_current/prompt_async",
        json={"messageID": "msg_client1234", "parts": [{"type": "text", "text": "hello"}]},
    )
    assert response.status_code == 204
    assert runtime.native.sent[0][0] == "ses_current"
    assert runtime.native.sent[0][1]["messageID"] == "msg_client1234"


async def test_history_session_is_read_only(runtime):
    runtime.task.current_session_id = "ses_new"
    await runtime.session.commit()
    response = await runtime.api.post(
        "/api/tasks/T1/opencode/ses_current/session/ses_current/prompt_async", json={"parts": []}
    )
    assert response.status_code == 403


async def test_task_list_and_detail_have_identical_status(runtime):
    detail = (await runtime.api.get("/api/tasks/T1")).json()
    listing = (await runtime.api.get("/api/tasks", params={"status": "FAILED"})).json()
    assert detail["runtime_state"] == listing[0]["runtime_state"] == "FAILED"
    assert detail["runtime_status_label"] == listing[0]["runtime_status_label"] == "执行失败"


async def test_global_session_status_read_is_allowed_and_scoped(runtime, monkeypatch):
    # "/session/status" textually matches the per-session read pattern. It is a global
    # read and must be forwarded + scoped to the task's sessions, never rejected as a
    # foreign session id literally named "status".
    class FakeResponse:
        is_error = False
        status_code = 200
        headers = {}
        content = b'{"ses_current": "idle", "ses_foreign": "busy"}'

        def json(self):
            return {"ses_current": "idle", "ses_foreign": "busy"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, *, params=None, json=None):
            assert url.endswith("/session/status")
            assert params["directory"] == str(runtime.workspace)
            return FakeResponse()

    monkeypatch.setattr("app.api.workspace_routes.httpx.AsyncClient", FakeClient)
    response = await runtime.api.get("/api/tasks/T1/opencode/ses_current/session/status")
    assert response.status_code == 200
    assert response.json() == {"ses_current": "idle"}


async def test_native_config_uses_bound_employee_model_and_status_is_filtered(runtime, monkeypatch):
    """Regression: global status is not a Session ID, and composer defaults use the employee model."""
    binding = await runtime.session.get(RuntimeSession, "ses_current")
    binding.environment = {**binding.environment, "model_name": "deepseek/deepseek-flash"}
    await runtime.session.commit()
    original = httpx.AsyncClient

    def upstream(request):
        if request.url.path == "/config":
            return httpx.Response(200, json={"model": "other/image-model", "provider": {"secret": "private"}})
        return httpx.Response(200, json={"ses_current": {"type": "busy"}, "ses_other": {"type": "busy"}})

    monkeypatch.setattr(
        "app.api.workspace_routes.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs),
    )
    config = await runtime.api.get("/api/tasks/T1/opencode/ses_current/config")
    assert config.status_code == 200
    assert config.json() == {"model": "deepseek/deepseek-flash"}
    status = await runtime.api.get("/api/tasks/T1/opencode/ses_current/session/status")
    assert status.status_code == 200
    assert status.json() == {"ses_current": {"type": "busy"}}


async def test_native_abort_accepts_empty_body(runtime):
    await runtime.service.project(runtime.task, "RUNNING")
    response = await runtime.api.post("/api/tasks/T1/opencode/ses_current/session/ses_current/abort")
    assert response.status_code == 200
    assert runtime.task.status == "CANCELED"


async def test_gateway_rejects_workspace_override_and_foreign_question(runtime):
    response = await runtime.api.get(
        "/api/tasks/T1/opencode/ses_current/session", params={"workspace": "foreign"}
    )
    assert response.status_code == 403
    runtime.native.pending = [{"id": "q_foreign", "sessionID": "ses_other"}]
    response = await runtime.api.post(
        "/api/tasks/T1/opencode/ses_current/question/q_foreign/reply", json={"answers": [["yes"]]}
    )
    assert response.status_code == 403


async def test_timeout_aborts_native_busy_but_waiting_does_not_timeout(runtime):
    from datetime import UTC, datetime, timedelta

    await runtime.service.project(runtime.task, "RUNNING")
    runtime.task.turn_started_at = datetime.now(UTC) - timedelta(days=1)
    await runtime.session.commit()
    runtime.native.state = "busy"
    runtime.native.pending = [{"id": "q", "sessionID": "ses_current"}]
    await runtime.service.refresh("T1")
    assert runtime.task.status == "WAITING"
    assert runtime.native.state == "busy"
    runtime.native.pending = []
    await runtime.service.refresh("T1")
    assert runtime.task.status == "RUNNING"
    runtime.task.turn_started_at = datetime.now(UTC) - timedelta(days=1)
    await runtime.session.commit()
    await runtime.service.refresh("T1")
    assert runtime.native.state == "idle"
    assert runtime.task.status == "FAILED"
    assert "时间上限" in runtime.task.failure_reason


async def _complete_current_turn(r):
    r.native.state = "idle"
    assistant = r.native.sessions["ses_current"][-1]
    assistant["parts"] = [
        {"type": "text", "text": "DONE"},
        {"type": "tool", "tool": "bash", "callID": "call_1", "state": {"status": "completed"}},
    ]
    assistant["info"].update(
        {
            "time": {"completed": 1},
            "finish": "stop",
            "tokens": {"input": 100, "output": 20, "cache": {"read": 5}},
        }
    )
    await r.service.refresh("T1")


async def test_succeeded_persists_runtime_session_terminal(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "go"}]})
    await _complete_current_turn(r)
    session = await r.session.get(RuntimeSession, "ses_current")
    assert r.task.status == "SUCCEEDED"
    assert session.status == "SUCCEEDED"
    assert session.finish_reason == "stop"
    assert session.finished_at is not None
    assert session.terminal_reason == "completed"


async def test_terminal_session_stores_aggregate_usage(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "go"}]})
    await _complete_current_turn(r)
    session = await r.session.get(RuntimeSession, "ses_current")
    assert session.total_tokens == 125
    assert session.input_tokens == 100 and session.output_tokens == 20
    assert session.cache_read_tokens == 5
    assert session.llm_call_count == 1
    assert session.tool_call_count == 1
    assert session.tool_usage == [
        {
            "tool_name": "bash",
            "call_count": 1,
            "success_count": 1,
            "failure_count": 0,
            "duration_ms": 0,
        }
    ]


async def test_continue_after_success_clears_finished_at(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "go"}]})
    await _complete_current_turn(r)
    session = await r.session.get(RuntimeSession, "ses_current")
    assert session.finished_at is not None

    await r.service.send("T1", {"parts": [{"type": "text", "text": "again"}]})
    session = await r.session.get(RuntimeSession, "ses_current")
    assert r.task.status == "RUNNING"
    assert session.status == "RUNNING"
    assert session.finished_at is None

    await _complete_current_turn(r)
    session = await r.session.get(RuntimeSession, "ses_current")
    assert session.status == "SUCCEEDED" and session.finished_at is not None


async def test_restart_preserves_succeeded_old_status(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "go"}]})
    await _complete_current_turn(r)
    await r.service.start("T1", restart=True)
    new_id = r.task.current_session_id
    old = await r.session.get(RuntimeSession, "ses_current")
    assert old.status == "SUCCEEDED"
    assert old.superseded_by == new_id
    new = await r.session.get(RuntimeSession, new_id)
    assert new.status == "RUNNING" and new.runtime_context_hash is not None


async def test_task_summary_is_one_row_with_generation_and_stale(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "go"}]})
    await _complete_current_turn(r)

    summary = await r.session.scalar(select(TaskSummary).where(TaskSummary.task_id == "T1"))
    assert summary is not None
    assert summary.generation == 1 and summary.stale is False
    assert summary.primary_session_id == "ses_current"
    assert summary.summary == "DONE"
    assert summary.source_status == "SUCCEEDED"
    assert [item["status"] for item in summary.acceptance_results] == []

    await r.service.send("T1", {"parts": [{"type": "text", "text": "again"}]})
    await r.session.refresh(summary)
    assert summary.stale is True

    await _complete_current_turn(r)
    await r.session.refresh(summary)
    assert summary.generation == 2 and summary.stale is False

    count = await r.session.scalar(select(func.count()).select_from(TaskSummary))
    assert count == 1


async def test_repeated_terminal_refresh_does_not_regenerate_summary(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "go"}]})
    await _complete_current_turn(r)

    summary = await r.session.scalar(select(TaskSummary).where(TaskSummary.task_id == "T1"))
    assert summary.generation == 1

    await r.service.refresh("T1")
    await r.session.refresh(summary)
    assert summary.generation == 1


async def test_task_summary_survives_restart_with_new_primary_session(runtime):
    r = runtime
    await r.service.send("T1", {"parts": [{"type": "text", "text": "go"}]})
    await _complete_current_turn(r)
    await r.service.start("T1", restart=True)
    new_id = r.task.current_session_id
    r.native.sessions[new_id] = [
        {"info": {"id": "u2", "role": "user"}, "parts": []},
        {
            "info": {"id": "a2", "role": "assistant", "time": {"completed": 2}, "finish": "stop"},
            "parts": [{"type": "text", "text": "RESTART_DONE"}],
        },
    ]
    r.task.last_message_id = "u2"
    await r.session.commit()
    r.native.state = "idle"
    await r.service.refresh("T1")

    summary = await r.session.scalar(select(TaskSummary).where(TaskSummary.task_id == "T1"))
    await r.session.refresh(summary)
    assert summary.primary_session_id == new_id
    assert summary.summary == "RESTART_DONE"
    assert set(summary.referenced_session_ids) == {"ses_current", new_id}
    assert await r.session.scalar(select(func.count()).select_from(TaskSummary)) == 1


async def test_restart_refuses_when_old_session_does_not_stop(runtime, monkeypatch):
    r = runtime
    await r.service.project(r.task, "RUNNING")

    class StuckClient:
        async def abort(self, *_args, **_kwargs):
            return True

        async def status(self, *_args, **_kwargs):
            return "busy"

    @asynccontextmanager
    async def stuck_connect(*_args, **_kwargs):
        yield StuckClient()

    monkeypatch.setattr("app.runtime.lifecycle.connect", stuck_connect)
    monkeypatch.setattr(
        "app.runtime.lifecycle.get_settings",
        lambda: SimpleNamespace(opencode_restart_abort_timeout_seconds=0),
    )
    with pytest.raises(RuntimeStateError, match="超时"):
        await r.service.start("T1", restart=True)
    # No second binding may be created while the old Session can still write.
    assert await r.session.scalar(select(func.count()).select_from(RuntimeSession)) == 1


async def test_disconnect_marks_session_unknown_without_failing_task(runtime):
    r = runtime
    await r.service.project(r.task, "RUNNING")
    await r.service.disconnected("T1", ConnectionError("network down"))
    session = await r.session.get(RuntimeSession, "ses_current")
    assert session.status == "UNKNOWN"
    assert session.terminal_reason == "transport_unknown"
    assert r.task.status == "RUNNING"


async def test_refresh_recovers_unknown_session_to_terminal(runtime):
    r = runtime
    session = await r.session.get(RuntimeSession, "ses_current")
    session.status = "UNKNOWN"
    await r.session.commit()
    r.native.sessions["ses_current"] = [
        {"info": {"id": "u1", "role": "user"}, "parts": []},
        {
            "info": {"id": "a1", "role": "assistant", "time": {"completed": 1}, "finish": "stop"},
            "parts": [{"type": "text", "text": "恢复后确认执行完成"}],
        },
    ]
    r.task.last_message_id = "u1"
    await r.session.commit()
    r.native.state = "idle"
    await r.service.refresh("T1")
    session = await r.session.get(RuntimeSession, "ses_current")
    assert session.status == "SUCCEEDED"
    assert r.task.status == "SUCCEEDED"


@pytest.mark.parametrize("params", [
    {"location[directory]": "/other"},
    {"location[workspace]": "foreign"},
    {"location": "foreign"},
])
async def test_gateway_rejects_current_protocol_location_override(runtime, params):
    response = await runtime.api.get("/api/tasks/T1/opencode/ses_current/api/reference", params=params)
    assert response.status_code == 403


async def test_native_vcs_diff_is_forwarded_with_workspace_containment(runtime, monkeypatch):
    nested = runtime.workspace / "src"
    nested.mkdir()
    original = httpx.AsyncClient
    patch = '--- a/src/hello.ts\n+++ b/src/hello.ts\n@@ -1 +1 @@\n-before\n+after\n'

    def upstream(request):
        assert request.url.params["directory"] == str(nested)
        if request.url.path.endswith("/raw"):
            return httpx.Response(200, text=patch, headers={"content-type": "text/x-diff"})
        return httpx.Response(200, json=[{"file": "src/hello.ts", "patch": patch}])

    monkeypatch.setattr(
        "app.api.workspace_routes.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs),
    )
    base = "/api/tasks/T1/opencode/ses_current/vcs/diff"
    response = await runtime.api.get(base, params={"directory": str(nested), "mode": "git"})
    assert response.status_code == 200
    assert response.json()[0]["patch"] == patch
    raw = await runtime.api.get(base + "/raw", params={"directory": str(nested), "mode": "git"})
    assert raw.status_code == 200
    assert raw.text == patch
    outside = await runtime.api.get(base, params={"directory": str(runtime.workspace.parent)})
    assert outside.status_code == 403


async def test_idle_employee_heartbeat_does_not_require_on_demand_server(runtime, monkeypatch):
    @asynccontextmanager
    async def unavailable_connect(*args, **kwargs):
        raise AssertionError("idle employee heartbeat must not start OpenCode Serve")
        yield

    monkeypatch.setattr("app.runtime.lifecycle.connect", unavailable_connect)
    employee = await runtime.session.get(DigitalEmployee, "E1")
    employee.status = "OFFLINE"
    runtime.task.status = "FAILED"
    await runtime.session.commit()

    healthy = await runtime.service.refresh_employee_heartbeats()

    await runtime.session.refresh(employee)
    assert "E1" in healthy
    assert employee.status == "IDLE"
    assert employee.current_task_count == 0


async def test_active_employee_heartbeat_releases_db_transaction_before_runtime_io(runtime, monkeypatch):
    observations = []

    @asynccontextmanager
    async def observed_connect(*args, **kwargs):
        observations.append((kwargs.get("start"), runtime.session.in_transaction()))
        yield runtime.native

    monkeypatch.setattr("app.runtime.lifecycle.connect", observed_connect)
    runtime.task.status = "RUNNING"
    await runtime.session.commit()

    await runtime.service.refresh_employee_heartbeats()

    assert observations == [(True, False)]


async def test_stop_can_force_cancel_local_session_when_no_runtime_listener(runtime, monkeypatch):
    @asynccontextmanager
    async def unavailable_connect(*args, **kwargs):
        raise ConnectionError("runtime process is gone")
        yield

    monkeypatch.setattr("app.runtime.lifecycle.connect", unavailable_connect)
    await runtime.service.project(runtime.task, "WAITING")

    stopped = await runtime.service.stop("T1")

    assert stopped.status == "CANCELED"
    session = await runtime.session.get(RuntimeSession, "ses_current")
    assert session.status == "INTERRUPTED"
    assert session.terminal_reason == "aborted"

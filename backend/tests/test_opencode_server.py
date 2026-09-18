import asyncio
from pathlib import Path, PurePosixPath
from typing import Any

from app.config.settings import Settings
from app.executors.opencode_remote_server import (
    RemoteOpenCodeServerConnection,
    RemoteOpenCodeServerExecutor,
)
from app.executors.opencode_server import OpenCodeServerExecutor, OpenCodeServerUnavailable
from app.models import OpenCodeExecutionEnvironment, Run, Task


class FakeServerClient:
    def __init__(
        self,
        events: list[dict[str, Any]],
        *,
        session_id: str = "ses_main",
        final_messages: list[dict[str, Any]] | None = None,
    ):
        self.event_items = events
        self.session_id = session_id
        self.final_messages = final_messages or []
        self.message_calls = 0
        self.prompts: list[tuple[str, str]] = []
        self.question_replies: list[tuple[str, list[list[str]]]] = []
        self.aborted: list[str] = []
        self.directories: list[Path | PurePosixPath] = []

    async def health(self):
        return {"healthy": True, "version": "test"}

    async def events(self, directory):
        self.directories.append(directory)
        for event in self.event_items:
            yield event
            await asyncio.sleep(0)
        await asyncio.Event().wait()

    async def create_session(self, directory, **_kwargs):
        self.directories.append(directory)
        return {"id": self.session_id}

    async def session(self, _directory, session_id):
        assert session_id == self.session_id
        return {"id": session_id}

    async def prompt(self, directory, session_id, *, text, **_kwargs):
        self.directories.append(directory)
        self.prompts.append((session_id, text))

    async def messages(self, _directory, _session_id):
        self.message_calls += 1
        return [] if self.message_calls == 1 else self.final_messages

    async def permissions(self, _directory):
        return []

    async def reply_question(self, _directory, request_id, answers):
        self.question_replies.append((request_id, answers))
        return True

    async def reply_permission(self, _directory, _request_id, _reply):
        return True

    async def abort(self, _directory, session_id):
        self.aborted.append(session_id)
        return True

    async def status(self, _directory, _session_id):
        return "idle"


def settings(**values) -> Settings:
    defaults = {
        "executor_type": "opencode_server",
        "opencode_model": "opencode/glm-5.1",
        "opencode_timeout_seconds": 2,
        "seed_demo": False,
    }
    defaults.update(values)
    return Settings(
        **defaults,
    )


def task(**values) -> Task:
    defaults = {
        "id": "ASTRA-SERVER-TEST",
        "source": "manual",
        "task_type": "ISSUE",
        "title": "Server runtime test",
        "description": "Use real structured events",
        "acceptance_criteria": [{"id": "AC-01", "content": "done"}],
        "review_history": [],
    }
    defaults.update(values)
    return Task(**defaults)


def raw_event(event_type: str, **properties) -> dict[str, Any]:
    return {"type": event_type, "properties": properties}


async def test_server_executor_streams_tools_messages_and_usage(tmp_path: Path):
    client = FakeServerClient(
        [
            raw_event("server.connected"),
            raw_event(
                "message.part.updated",
                part={
                    "id": "prt_tool",
                    "sessionID": "ses_main",
                    "type": "tool",
                    "tool": "bash",
                    "callID": "call_1",
                    "state": {
                        "status": "completed",
                        "title": "Run pwd",
                        "input": {"command": "pwd"},
                        "output": str(tmp_path),
                    },
                },
            ),
            raw_event(
                "message.updated",
                info={
                    "id": "msg_assistant",
                    "sessionID": "ses_main",
                    "role": "assistant",
                    "providerID": "opencode",
                    "modelID": "glm-5.1",
                    "tokens": {"input": 12, "output": 3, "cache": {"read": 2, "write": 1}},
                },
            ),
            raw_event(
                "message.part.updated",
                part={"id": "prt_text", "sessionID": "ses_main", "type": "text", "text": "DONE"},
            ),
            raw_event("session.idle", sessionID="ses_main"),
        ],
        final_messages=[
            {
                "info": {"id": "msg_assistant", "role": "assistant"},
                "parts": [{"type": "text", "text": "DONE"}],
            }
        ],
    )
    observed: list[dict[str, Any]] = []
    sessions: list[str] = []
    executor = OpenCodeServerExecutor(
        settings(),
        client=client,
        event_callback=lambda event: _append(observed, event),
        session_callback=lambda session_id: _append(sessions, session_id),
    )

    result = await executor.start(task(), tmp_path)

    assert result.status == "SUCCEEDED"
    assert result.session_id == "ses_main"
    assert sessions == ["ses_main"]
    assert any(item.get("part", {}).get("tool") == "bash" for item in observed)
    assert result.token_usage.total_tokens == 18
    assert result.tool_usage[0].name == "bash"
    assert client.prompts and "ASTRA_RESULT_JSON" in client.prompts[0][1]


async def test_server_executor_blocks_on_native_question_and_replies_in_same_session(
    tmp_path: Path,
):
    first_client = FakeServerClient(
        [
            raw_event("server.connected"),
            raw_event(
                "question.asked",
                id="que_1",
                sessionID="ses_main",
                questions=[
                    {
                        "question": "Which marker?",
                        "options": [
                            {"label": "BLUE", "description": "Print blue"},
                            {"label": "GREEN", "description": "Print green"},
                        ],
                    }
                ],
            ),
        ]
    )
    current_task = task()
    first = await OpenCodeServerExecutor(settings(), client=first_client).start(
        current_task,
        tmp_path,
    )

    assert first.status == "WAITING_INPUT"
    assert first.inquiry and first.inquiry["runtime_request_id"] == "que_1"
    current_task.human_intervention = {**first.inquiry, "response": "BLUE"}
    current_task.opencode_session_id = "ses_main"
    run = Run(
        id="RUN-SERVER-QUESTION",
        task_id=current_task.id,
        employee_id="employee",
        run_number=1,
        opencode_session_id="ses_main",
    )
    second_client = FakeServerClient(
        [
            raw_event("server.connected"),
            raw_event("question.replied", id="que_1", sessionID="ses_main"),
            raw_event(
                "message.part.updated",
                part={
                    "id": "prt_answer",
                    "sessionID": "ses_main",
                    "type": "text",
                    "text": "QUESTION_RESUMED:BLUE",
                },
            ),
            raw_event("session.idle", sessionID="ses_main"),
        ],
        final_messages=[
            {
                "info": {"id": "msg_answer", "role": "assistant"},
                "parts": [{"type": "text", "text": "QUESTION_RESUMED:BLUE"}],
            }
        ],
    )

    resumed = await OpenCodeServerExecutor(settings(), client=second_client).resume(
        current_task,
        run,
        tmp_path,
    )

    assert resumed.status == "SUCCEEDED"
    assert second_client.question_replies == [("que_1", [["BLUE"]])]
    assert second_client.prompts == []


async def test_server_executor_observes_child_session_internal_tools(tmp_path: Path):
    client = FakeServerClient(
        [
            raw_event("server.connected"),
            raw_event(
                "session.created",
                info={
                    "id": "ses_child",
                    "sessionID": "ses_child",
                    "parentID": "ses_main",
                    "agent": "explore",
                },
            ),
            raw_event(
                "message.part.updated",
                part={
                    "id": "prt_child_tool",
                    "sessionID": "ses_child",
                    "type": "tool",
                    "tool": "grep",
                    "callID": "call_child",
                    "state": {"status": "completed", "title": "Search files"},
                },
            ),
            raw_event(
                "message.part.updated",
                part={"id": "prt_done", "sessionID": "ses_main", "type": "text", "text": "DONE"},
            ),
            raw_event("session.idle", sessionID="ses_main"),
        ]
    )
    observed: list[dict[str, Any]] = []
    executor = OpenCodeServerExecutor(
        settings(),
        client=client,
        event_callback=lambda event: _append(observed, event),
    )

    result = await executor.start(task(), tmp_path)

    assert result.status == "SUCCEEDED"
    child_tool = next(item for item in observed if item.get("part", {}).get("callID") == "call_child")
    assert child_tool["agent"] == "explore"
    assert child_tool["part"]["agent"] == "explore"


async def test_server_timeout_aborts_and_fails_instead_of_requesting_human(tmp_path: Path):
    client = FakeServerClient([raw_event("server.connected")])
    executor = OpenCodeServerExecutor(
        settings(opencode_timeout_seconds=0),
        client=client,
    )

    result = await executor.start(task(), tmp_path)

    assert result.status == "FAILED"
    assert result.exit_code == 124
    assert result.inquiry is None
    assert client.aborted == ["ses_main"]


class FakeTunnel:
    base_url = "http://127.0.0.1:45123"

    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeReverseTunnel:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeSSHSession:
    def __init__(self):
        self.tunnel = FakeTunnel()
        self.tunnel_target: tuple[str, int] | None = None
        self.reverse = None
        self.reverse_tunnel = FakeReverseTunnel()
        self.commands: list[str] = []
        self.closed = False

    async def open_tunnel(self, *, remote_host: str, remote_port: int):
        self.tunnel_target = (remote_host, remote_port)
        return self.tunnel

    async def open_reverse_tunnel(self, *, remote_port: int, local_host: str = "127.0.0.1", local_port: int):
        self.reverse = (remote_port, local_host, local_port)
        return self.reverse_tunnel

    async def run_command(self, command: str):
        self.commands.append(command)
        return 0, "", ""

    async def close(self):
        self.closed = True


class FakeRemoteRuntime:
    def __init__(self, session: FakeSSHSession):
        self.session = session

    async def open_session(self, _environment):
        return self.session


def remote_environment() -> OpenCodeExecutionEnvironment:
    return OpenCodeExecutionEnvironment(
        employee_id="remote-agent",
        mode="LINUX_REMOTE",
        name="Remote Linux",
        host="linux.internal",
        port=22,
        username="astra",
        ssh_password="secret",
        opencode_server_port=4196,
        opencode_path="/opt/OpenCode/opencode",
        model_name="opencode/glm-5.1",
        workspace_root="/srv/projects/NEXUS 工作区",
    )


async def test_remote_server_connection_starts_private_loopback_server():
    ssh = FakeSSHSession()

    class StartingClient:
        def __init__(self):
            self.health_calls = 0

        async def health(self):
            self.health_calls += 1
            if self.health_calls == 1:
                raise OpenCodeServerUnavailable("connection refused")
            return {"healthy": True, "version": "1.18.25"}

    client = StartingClient()
    connection = RemoteOpenCodeServerConnection(
        remote_environment(),
        settings(),
        FakeRemoteRuntime(ssh),
        client_factory=lambda base_url: client,
    )

    async with connection as opened:
        assert opened is client

    assert ssh.tunnel_target == ("127.0.0.1", 4196)
    assert len(ssh.commands) == 2
    assert "opencode.json" in ssh.commands[0]
    assert "serve --hostname 127.0.0.1 --port 4196" in ssh.commands[1]
    assert "OPENCODE_CONFIG=" in ssh.commands[1]
    assert "cd '/srv/projects/NEXUS 工作区'" in ssh.commands[1]
    assert ssh.reverse is not None
    assert ssh.reverse_tunnel.closed is True
    assert ssh.tunnel.closed is True
    assert ssh.closed is True


async def test_remote_executor_uses_remote_posix_workspace_and_structured_events(tmp_path: Path):
    client = FakeServerClient(
        [
            raw_event("server.connected"),
            raw_event(
                "message.part.updated",
                part={
                    "id": "prt_remote",
                    "sessionID": "ses_remote",
                    "type": "text",
                    "text": "REMOTE_DONE",
                },
            ),
            raw_event("session.idle", sessionID="ses_remote"),
        ],
        session_id="ses_remote",
    )
    ssh = FakeSSHSession()
    executor = RemoteOpenCodeServerExecutor(
        remote_environment(),
        settings(),
        FakeRemoteRuntime(ssh),
        client_factory=lambda base_url: client,
    )

    result = await executor.start(task(id="ASTRA-REMOTE-SERVER"), tmp_path)

    assert result.status == "SUCCEEDED"
    assert result.session_id == "ses_remote"
    assert client.directories
    assert all(directory == PurePosixPath("/srv/projects/NEXUS 工作区") for directory in client.directories)
    assert ssh.commands == []
    assert ssh.tunnel_target == ("127.0.0.1", 4196)
    assert ssh.tunnel.closed is True
    assert ssh.closed is True


async def _append(items: list[Any], value: Any) -> None:
    items.append(value)


async def test_remote_environment_probe_does_not_start_absent_server(monkeypatch):
    from app.executors import opencode_remote_server as remote

    ssh = FakeSSHSession()

    class UnavailableClient:
        def __init__(self, *args, **kwargs):
            pass

        async def health(self):
            raise OpenCodeServerUnavailable("connection refused")

    monkeypatch.setattr(remote, "OpenCodeServerClient", UnavailableClient)
    passed, detail = await remote.test_remote_server(
        remote_environment(),
        settings(),
        FakeRemoteRuntime(ssh),
    )
    assert passed and "未启动" in detail
    assert ssh.commands == []
    assert ssh.closed and ssh.tunnel.closed

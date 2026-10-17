"""Worker-marked environments use the Gateway and leave SSH forwarding in place."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.domain import ExecutionMode
from app.executors.opencode_remote_server import RemoteOpenCodeServerConnection
from app.models import DigitalEmployee, OpenCodeExecutionEnvironment
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.session_connection import connect
from app.runtime.worker_client import WorkerOpenCodeClient
from app.worker_agent.connection import handle_command
from app.worker_agent.local_opencode import gateway_http_base
from app.worker_agent.supervisor import RuntimeSupervisor
from app.worker_gateway.data_channel import DataChannel
from app.worker_gateway.protocol import envelope, parse_message
from tests.test_worker_gateway import bring_online, gateway_for


@pytest.fixture
async def environment_id() -> int:
    await init_database()
    async with SessionLocal() as session:
        employee = DigitalEmployee(id=f"emp-{uuid4().hex[:8]}", name="远程员工", role="执行")
        session.add(employee)
        await session.flush()
        environment = OpenCodeExecutionEnvironment(
            employee_id=employee.id, mode="LINUX_REMOTE", name="云执行机", worker_channel="ssh"
        )
        session.add(environment)
        await session.commit()
        return environment.id


@pytest.mark.asyncio
async def test_worker_connect_does_not_open_ssh(environment_id, monkeypatch):
    await _mark(environment_id, "worker")
    called = False

    async def opened(self, environment):
        nonlocal called
        called = True
        raise AssertionError(environment.host)

    monkeypatch.setattr(ExecutionEnvironmentRuntime, "open_session", opened)
    environment = await _load(environment_id)
    async with connect(environment, start=False) as client:
        assert isinstance(client, WorkerOpenCodeClient)
    assert called is False


@pytest.mark.asyncio
async def test_ssh_connect_still_opens_a_session(environment_id, monkeypatch):
    await _mark(environment_id, "ssh")
    seen = {}

    class Tunnel:
        base_url = "http://127.0.0.1:9"

        async def close(self):
            return None

    class SSH:
        async def open_tunnel(self, **kwargs):
            seen["tunnel"] = kwargs
            return Tunnel()

        async def close(self):
            return None

    async def opened(self, environment):
        seen["host"] = environment.host
        return SSH()

    monkeypatch.setattr(ExecutionEnvironmentRuntime, "open_session", opened)
    environment = await _load(environment_id)
    environment.host = "worker.example"
    environment.username = "dev"
    environment.ssh_password = "secret"
    async with connect(environment, start=False) as client:
        assert client.base_url == "http://127.0.0.1:9"
    assert seen["tunnel"]["remote_port"] == environment.opencode_server_port


@pytest.mark.asyncio
async def test_worker_http_exchange_returns_cursor_headers(environment_id):
    gateway = gateway_for()
    enrolled, auth = await bring_online(gateway, environment_id)
    await _mark(environment_id, "worker")
    queues = gateway.bus.bound[enrolled.worker_instance_id]

    async def answer():
        frame = await queues.wait_frame()
        async with SessionLocal() as session:
            fetched = await DataChannel(gateway).fetch_request(
                session,
                request_id=frame["request_id"],
                worker_instance_id=enrolled.worker_instance_id,
                epoch=auth.epoch,
            )
        assert fetched["query"]["directory"] == "/work"
        async with SessionLocal() as session:
            await DataChannel(gateway).commit_upload(
                session,
                request_id=frame["request_id"],
                worker_instance_id=enrolled.worker_instance_id,
                epoch=auth.epoch,
                upload_id="up-call",
                http_status=200,
                headers={"x-next-cursor": "cursor-9", "link": "<next>"},
                content_type="application/json",
                chunk=json.dumps([{"id": "ses"}]),
                complete=True,
            )

    running = asyncio.create_task(answer())
    client = WorkerOpenCodeClient(
        environment_id=environment_id, gateway=gateway, timeout_seconds=5
    )
    payload, headers = await client.request(
        "GET", "/session", directory=Path("/work"), include_headers=True
    )
    await running
    assert payload == [{"id": "ses"}]
    assert headers["x-next-cursor"] == "cursor-9"
    assert headers["link"] == "<next>"


@pytest.mark.asyncio
async def test_prepare_workspace_command_copies_config(environment_id, tmp_path):
    gateway = gateway_for()
    enrolled, auth = await bring_online(gateway, environment_id)
    root = tmp_path / "root"
    root.mkdir()
    (root / "opencode.json").write_text('{"model":"deepseek-flash"}\n')
    target = tmp_path / "task"
    queues = gateway.bus.bound[enrolled.worker_instance_id]

    async def answer():
        frame = await queues.wait_frame()
        message = parse_message(json.dumps(frame), max_bytes=10**6)
        result, error = handle_command(message, RuntimeSupervisor())
        reply = envelope(
            request_id=message.request_id,
            worker_instance_id=message.worker_instance_id,
            environment_id=message.environment_id,
            session_id=message.session_id,
            message_type="response",
            payload={"stage": "result", "ok": error is None, "result": result, "error_code": error},
        )
        reply.epoch = auth.epoch
        async with SessionLocal() as session:
            assert await gateway.apply_response(
                session,
                worker_instance_id=enrolled.worker_instance_id,
                epoch=auth.epoch,
                message=reply,
            )
        await gateway.bus.publish_response(message.request_id, reply.to_dict())

    running = asyncio.create_task(answer())
    client = WorkerOpenCodeClient(
        environment_id=environment_id, gateway=gateway, timeout_seconds=5
    )
    result = await client.run_command(
        "prepare_workspace",
        {"root": str(root), "target": str(target), "reuse_existing": False},
    )
    await running
    assert result["created"] == "true"
    assert json.loads((target / "opencode.json").read_text())["model"] == "deepseek-flash"


@pytest.mark.asyncio
async def test_remote_connection_on_worker_does_not_start_ssh(environment_id, monkeypatch):
    await _mark(environment_id, "worker")

    async def opened(self, environment):
        raise AssertionError("ssh opened")

    monkeypatch.setattr(ExecutionEnvironmentRuntime, "open_session", opened)
    environment = await _load(environment_id)
    connection = RemoteOpenCodeServerConnection(
        environment, get_settings(), ExecutionEnvironmentRuntime()
    )
    with pytest.raises(RuntimeError, match="启动方式=Worker"):
        async with connection:
            pass


async def _mark(environment_id: int, channel: str) -> None:
    await init_database()
    async with SessionLocal() as session:
        environment = await session.get(OpenCodeExecutionEnvironment, environment_id)
        environment.worker_channel = channel
        environment.mode = ExecutionMode.LINUX_REMOTE
        await session.commit()


async def _load(environment_id: int) -> OpenCodeExecutionEnvironment:
    async with SessionLocal() as session:
        stored = await session.get(OpenCodeExecutionEnvironment, environment_id)
        return OpenCodeExecutionEnvironment(
            id=stored.id,
            employee_id=stored.employee_id,
            mode=stored.mode,
            name=stored.name,
            host=stored.host,
            port=stored.port,
            username=stored.username,
            opencode_server_port=stored.opencode_server_port,
            opencode_path=stored.opencode_path,
            model_name=stored.model_name,
            workspace_root=stored.workspace_root,
            worker_channel=stored.worker_channel,
            status=stored.status,
        )


def test_gateway_http_base_is_the_origin():
    assert (
        gateway_http_base("ws://127.0.0.1:8877/api/worker-gateway/connect")
        == "http://127.0.0.1:8877"
    )
    assert gateway_http_base("wss://worker.example/connect") == "https://worker.example"

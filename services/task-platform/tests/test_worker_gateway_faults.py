import asyncio
import json
import os
import time
from collections import deque
from datetime import timedelta
from uuid import uuid4

import pytest
import websockets
from sqlalchemy import select, update
from websockets.exceptions import ConnectionClosed

from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.models import (
    DigitalEmployee,
    OpenCodeExecutionEnvironment,
    WorkerCommand,
    utcnow,
)
from app.worker_agent.connection import AgentConfig, WorkerConnectionManager
from app.worker_agent.supervisor import RuntimeSupervisor
from app.worker_agent.transport import WebSocketTransport, translate_transport_error
from app.worker_gateway.admin_key import ENV_NAME, ensure_worker_gateway_admin_key
from app.worker_gateway.bus import MemoryRouteBus, RedisRouteBus
from app.worker_gateway.protocol import WorkerGatewayError, dump_message, envelope
from app.worker_gateway.service import WorkerGateway, _SocketLease
from tests.test_worker_gateway import (
    ADMIN_HEADERS,
    ScriptedTransport,
    gateway_for,
    live_frame,
)

REDIS_URL = os.environ.get("ASTRA_TEST_REDIS_URL")


class Adapter:
    def __init__(self, socket) -> None:
        self.socket = socket

    async def accept(self) -> None:
        return None

    async def send_text(self, data: str) -> None:
        await self.socket.send(data)

    async def receive_text(self) -> str:
        message = await self.socket.recv()
        if isinstance(message, bytes):
            return message.decode()
        return message

    async def close(self, code: int = 1000) -> None:
        await self.socket.close(code)


class HoldingTransport:
    def __init__(self, inbound: list[dict]) -> None:
        self.inbound = list(inbound)
        self.sent: list[dict] = []
        self.hold = asyncio.Event()

    async def send(self, message: dict) -> None:
        self.sent.append(message)

    async def recv(self) -> dict:
        if self.inbound:
            return self.inbound.pop(0)
        await self.hold.wait()
        raise ConnectionError("closed")

    async def close(self) -> None:
        self.hold.set()


@pytest.fixture
async def environment_id() -> int:
    await init_database()
    async with SessionLocal() as session:
        employee = DigitalEmployee(id=f"emp-{uuid4().hex[:8]}", name="故障员工", role="执行")
        session.add(employee)
        await session.flush()
        environment = OpenCodeExecutionEnvironment(
            employee_id=employee.id, mode="LINUX_REMOTE", name="故障执行机"
        )
        session.add(environment)
        await session.commit()
        return environment.id


def auth_frame(worker_id: str, environment_id: int, token: str, request_id: str = "auth-1") -> dict:
    return envelope(
        request_id=request_id,
        worker_instance_id=worker_id,
        environment_id=environment_id,
        session_id=None,
        message_type="command",
        payload={"name": "authenticate", "token": token, "agent_version": "0.1.0"},
    ).to_dict()


async def enroll(gateway: WorkerGateway, environment_id: int):
    async with SessionLocal() as session:
        return await gateway.enroll(session, environment_id)


async def test_agent_reconnects_after_close_refusal_and_auth_timeout():
    modes: asyncio.Queue[str] = asyncio.Queue()
    for mode in ("close", "timeout", "ok"):
        await modes.put(mode)

    async def handler(socket) -> None:
        mode = await modes.get()
        await socket.recv()
        if mode == "timeout":
            await asyncio.sleep(2)
            return
        reply = envelope(
            request_id="auth-wrk_agent",
            worker_instance_id="wrk_agent",
            environment_id=7,
            session_id=None,
            message_type="response",
            payload={"ok": True, "epoch": 1 if mode == "close" else 2, "ping_seconds": 30},
        )
        await socket.send(dump_message(reply))
        await socket.close()

    server = await websockets.serve(handler, "127.0.0.1", 0, ping_interval=None)
    port = server.sockets[0].getsockname()[1]
    steps = ["close", "refuse", "timeout", "ok"]

    async def connect():
        step = steps.pop(0)
        target = "ws://127.0.0.1:9" if step == "refuse" else f"ws://127.0.0.1:{port}"
        try:
            socket = await websockets.connect(target, open_timeout=0.5, ping_interval=None)
        except Exception as exc:
            raise translate_transport_error(exc) from exc
        return WebSocketTransport(socket)

    config = AgentConfig(
        gateway_url=f"ws://127.0.0.1:{port}",
        worker_instance_id="wrk_agent",
        environment_id=7,
        token="wtk_test",
        auth_timeout_seconds=0.3,
        ping_seconds=30,
    )
    manager = WorkerConnectionManager(
        config, supervisor=RuntimeSupervisor(), sleep=lambda _seconds: asyncio.sleep(0)
    )
    try:
        await manager.run(connect, asyncio.Event(), max_sessions=4)
    finally:
        server.close()
        await server.wait_closed()

    assert manager.epochs == [1, 2]
    assert manager.supervisor.restart_count == 0
    assert len(manager.delays) == 3


async def test_protocol_violation_closes_real_socket(environment_id: int):
    gateway = gateway_for(
        MemoryRouteBus(),
        worker_gateway_max_frame_bytes=480,
        worker_gateway_ping_seconds=30,
    )
    enrolled = await enroll(gateway, environment_id)

    async def handler(socket) -> None:
        await gateway.serve_socket(Adapter(socket))

    server = await websockets.serve(handler, "127.0.0.1", 0, ping_interval=None, max_size=2**20)
    port = server.sockets[0].getsockname()[1]
    url = f"ws://127.0.0.1:{port}"
    oversized = {
        "request_id": "too-big",
        "worker_instance_id": enrolled.worker_instance_id,
        "environment_id": environment_id,
        "session_id": None,
        "type": "command",
        "payload": {"name": "authenticate", "token": enrolled.token, "blob": "x" * 400},
    }
    try:
        async with websockets.connect(url, ping_interval=None, max_size=2**20) as socket:
            await socket.send(json.dumps(oversized))
            code = await _close_code(socket)
        assert code == 1009

        async with websockets.connect(url, ping_interval=None, max_size=2**20) as socket:
            await socket.send(json.dumps(auth_frame(
                enrolled.worker_instance_id, environment_id, enrolled.token, "auth-ok"
            )))
            ack = json.loads(await asyncio.wait_for(socket.recv(), 2))
            assert ack["payload"]["ok"] is True, ack
            await socket.send(json.dumps({**oversized, "request_id": "too-big-2"}))
            code = await _close_code(socket)
        assert code == 1009

        async with websockets.connect(url, ping_interval=None, max_size=2**20) as socket:
            await socket.send(json.dumps(auth_frame(
                enrolled.worker_instance_id, environment_id, enrolled.token, "auth-bad-frame"
            )))
            await asyncio.wait_for(socket.recv(), 2)
            await socket.send("not-json")
            code = await _close_code(socket)
        assert code == 1008
    finally:
        server.close()
        await server.wait_closed()


async def _close_code(socket) -> int | None:
    while True:
        try:
            await asyncio.wait_for(socket.recv(), 2)
        except ConnectionClosed as exc:
            return None if exc.rcvd is None else exc.rcvd.code


async def test_older_registration_cannot_replace_owner_or_socket():
    bus = MemoryRouteBus()
    gateway = gateway_for(bus)
    assert await bus.set_owner("wrk_order", "gw-new", 4) is True
    assert await bus.set_owner("wrk_order", "gw-old", 3) is False
    assert await bus.set_owner("wrk_order", "gw-other", 4) is False
    assert await bus.get_owner("wrk_order") == ("gw-new", 4)
    current = _SocketLease(4, object(), deque(), 1)
    stale = _SocketLease(3, object(), deque(), 1)
    assert gateway._remember_socket("wrk_order", current) is True
    assert gateway._remember_socket("wrk_order", stale) is False
    assert gateway.sockets["wrk_order"] is current


async def test_concurrent_request_id_replays_match_and_rejects_conflict(environment_id: int):
    gateway = gateway_for()
    async with SessionLocal() as session:
        first = await gateway.enroll(session, environment_id)
        employee = DigitalEmployee(id=f"emp-{uuid4().hex[:8]}", name="另一员工", role="执行")
        session.add(employee)
        await session.flush()
        other_env = OpenCodeExecutionEnvironment(
            employee_id=employee.id, mode="LINUX_REMOTE", name="另一执行机"
        )
        session.add(other_env)
        await session.commit()
        other_env_id = other_env.id
    async with SessionLocal() as session:
        second = await gateway.enroll(session, other_env_id)

    async def submit(worker_id: str, payload: dict):
        async with SessionLocal() as session:
            return await gateway.dispatch(
                session,
                worker_instance_id=worker_id,
                request_id="req-shared",
                name="echo",
                payload=payload,
            )

    results = await asyncio.gather(
        submit(first.worker_instance_id, {"n": 1}),
        submit(first.worker_instance_id, {"n": 1}),
    )
    assert {item.command.id for item in results} == {results[0].command.id}
    assert sum(item.replayed for item in results) == 1

    with pytest.raises(WorkerGatewayError) as mismatched:
        await submit(first.worker_instance_id, {"n": 2})
    assert mismatched.value.code == "duplicate_request"
    with pytest.raises(WorkerGatewayError) as other_worker:
        await submit(second.worker_instance_id, {"n": 1})
    assert other_worker.value.code == "duplicate_request"


async def test_sweep_and_result_keep_a_single_terminal_state(environment_id: int):
    gateway = gateway_for()
    async with SessionLocal() as session:
        enrolled = await gateway.enroll(session, environment_id)
        auth = await gateway.authenticate(
            session,
            envelope(
                request_id="auth-sweep",
                worker_instance_id=enrolled.worker_instance_id,
                environment_id=environment_id,
                session_id=None,
                message_type="command",
                payload={"name": "authenticate", "token": enrolled.token},
            ),
            enrolled.token,
        )
        succeeded = WorkerCommand(
            request_id="req-succeeded",
            worker_instance_id=enrolled.worker_instance_id,
            environment_id=environment_id,
            name="ping",
            payload={},
            status="succeeded",
            epoch=auth.epoch,
            result={"pong": True},
            deadline_at=utcnow() - timedelta(seconds=5),
            finished_at=utcnow(),
        )
        pending = WorkerCommand(
            request_id="req-pending",
            worker_instance_id=enrolled.worker_instance_id,
            environment_id=environment_id,
            name="ping",
            payload={},
            status="pending",
            epoch=auth.epoch,
            deadline_at=utcnow() - timedelta(seconds=5),
        )
        session.add(succeeded)
        session.add(pending)
        await session.commit()

    async def finish():
        async with SessionLocal() as session:
            return await gateway.apply_response(
                session,
                worker_instance_id=enrolled.worker_instance_id,
                epoch=auth.epoch,
                message=envelope(
                    request_id="req-pending",
                    worker_instance_id=enrolled.worker_instance_id,
                    environment_id=environment_id,
                    session_id=None,
                    message_type="response",
                    payload={"stage": "result", "ok": True, "result": {"pong": True}, "error_code": None},
                ),
            )

    await asyncio.gather(finish(), gateway.sweep(now=utcnow()))
    async with SessionLocal() as session:
        kept = await session.scalar(select(WorkerCommand).where(WorkerCommand.request_id == "req-succeeded"))
        raced = await session.scalar(select(WorkerCommand).where(WorkerCommand.request_id == "req-pending"))
    assert kept is not None and kept.status == "succeeded" and kept.result == {"pong": True}
    assert raced is not None and raced.status in {"succeeded", "expired"}
    if raced.status == "succeeded":
        assert raced.result == {"pong": True}
        assert raced.error_code is None
    else:
        assert raced.error_code == "timeout"
    await gateway.sweep(now=utcnow())
    async with SessionLocal() as session:
        kept = await session.scalar(select(WorkerCommand).where(WorkerCommand.request_id == "req-succeeded"))
    assert kept is not None and kept.status == "succeeded"


async def test_owner_retries_idempotent_delivery_and_holds_prompt(environment_id: int):
    bus = MemoryRouteBus()
    gateway = gateway_for(bus, worker_gateway_dispatch_lease_seconds=10)
    async with SessionLocal() as session:
        enrolled = await gateway.enroll(session, environment_id)
    async with SessionLocal() as session:
        auth = await gateway.authenticate(
            session,
            envelope(
                request_id="auth-deliver",
                worker_instance_id=enrolled.worker_instance_id,
                environment_id=environment_id,
                session_id=None,
                message_type="command",
                payload={"name": "authenticate", "token": enrolled.token},
            ),
            enrolled.token,
        )
    assert await bus.set_owner(enrolled.worker_instance_id, gateway.owner_id, auth.epoch) is True
    queues = await bus.bind(enrolled.worker_instance_id, epoch=auth.epoch, owner_id=gateway.owner_id)
    assert queues is not None

    async def send(request_id: str, name: str):
        async with SessionLocal() as session:
            return await gateway.dispatch(
                session,
                worker_instance_id=enrolled.worker_instance_id,
                request_id=request_id,
                name=name,
                payload={"text": name},
            )

    ping = await send("req-ping", "ping")
    prompt = await send("req-prompt", "prompt")
    assert ping.delivered is True and prompt.delivered is True
    assert (await queues.wait_frame())["request_id"] == "req-ping"
    assert (await queues.wait_frame())["request_id"] == "req-prompt"
    await bus.unbind(enrolled.worker_instance_id, queues)
    rebound = await bus.bind(enrolled.worker_instance_id, epoch=auth.epoch, owner_id=gateway.owner_id)
    assert rebound is not None
    async with SessionLocal() as session:
        await session.execute(
            update(WorkerCommand)
            .where(WorkerCommand.request_id.in_(("req-ping", "req-prompt")))
            .values(last_dispatched_at=utcnow() - timedelta(seconds=30))
        )
        await session.commit()
    assert await gateway.dispatch_due(enrolled.worker_instance_id, auth.epoch) == 1
    retried = await rebound.wait_frame()
    assert retried["request_id"] == "req-ping"
    assert retried["epoch"] == auth.epoch
    assert await gateway.dispatch_due(enrolled.worker_instance_id, auth.epoch) == 0


async def test_agent_dedupes_commands_and_ping_timeout_reconnects():
    config = AgentConfig(
        gateway_url="ws://nexus.internal/api/worker-gateway/connect",
        worker_instance_id="wrk_agent",
        environment_id=7,
        token="wtk_test",
        ping_seconds=0.05,
        ping_timeout_seconds=0.05,
        heartbeat_misses=1,
        auth_timeout_seconds=1,
    )
    def auth_reply(ping: float) -> dict:
        return envelope(
            request_id="auth-wrk_agent",
            worker_instance_id="wrk_agent",
            environment_id=7,
            session_id=None,
            message_type="response",
            payload={
                "ok": True,
                "epoch": 3,
                "ping_seconds": ping,
                "ping_timeout_seconds": 0.05,
            },
        ).to_dict()

    reply = auth_reply(30)
    command = envelope(
        request_id="req-agent",
        worker_instance_id="wrk_agent",
        environment_id=7,
        session_id=None,
        message_type="command",
        payload={"name": "echo", "data": {"value": 1}},
    )
    command.epoch = 3
    command.expires_at = int(time.time()) + 60
    finished = ScriptedTransport([reply, command.to_dict()])
    executing = ScriptedTransport([reply, command.to_dict()])
    supervisor = RuntimeSupervisor()

    async def scenario():
        cursor = {"index": 0}
        transports = [finished, executing]

        async def connect():
            transport = transports[cursor["index"]]
            cursor["index"] += 1
            return transport

        manager = WorkerConnectionManager(
            config, supervisor=supervisor, sleep=lambda _seconds: asyncio.sleep(0)
        )
        manager.ledger.finish("req-agent", {"echo": {"value": 1}}, None, time.time())
        with pytest.raises(ConnectionError):
            await manager.run_session(finished)
        manager.ledger.begin("req-agent", time.time())
        with pytest.raises(ConnectionError):
            await manager.run_session(executing)
        quick = auth_reply(0.05)
        holding = HoldingTransport([quick])
        follow = ScriptedTransport([quick])

        async def reconnect():
            transport = holding if cursor["index"] == 2 else follow
            cursor["index"] += 1
            return transport

        cursor["index"] = 2
        await manager.run(reconnect, asyncio.Event(), max_sessions=2)
        return manager, holding

    manager, holding = await scenario()
    assert finished.sent[1]["payload"]["stage"] == "result"
    assert finished.sent[1]["payload"]["result"] == {"echo": {"value": 1}}
    assert executing.sent[1]["payload"]["stage"] == "duplicate"
    assert executing.sent[1]["payload"]["result"] == {"state": "already_executing"}
    assert manager.supervisor.restart_count == 0
    assert any(item["payload"].get("kind") == "ping" for item in holding.sent)


@pytest.mark.skipif(
    not REDIS_URL,
    reason="未提供 ASTRA_TEST_REDIS_URL：Worker 路由未在真实 Redis 上联调，默认验证进程内等价语义",
)
async def test_redis_old_consumer_stops_after_newer_epoch():
    prefix = f"astra:worker-gateway:test:{uuid4().hex}"
    older = RedisRouteBus(REDIS_URL, prefix=prefix, control_limit=4)
    newer = RedisRouteBus(REDIS_URL, prefix=prefix, control_limit=4)
    worker_id = f"wrk_{uuid4().hex}"
    try:
        assert await older.set_owner(worker_id, "gw-old", 1) is True
        old_queues = await older.bind(worker_id, epoch=1, owner_id="gw-old")
        assert old_queues is not None
        assert await newer.set_owner(worker_id, "gw-new", 2) is True
        assert await older.set_owner(worker_id, "gw-old", 1) is False
        new_queues = await newer.bind(worker_id, epoch=2, owner_id="gw-new")
        assert new_queues is not None
        assert await newer.publish_command(worker_id, live_frame({"request_id": "current"}, 2)) is True
        assert await newer.publish_command(worker_id, live_frame({"request_id": "stale"}, 1)) is False
        delivered = await asyncio.wait_for(new_queues.wait_frame(), 2)
        assert delivered["request_id"] == "current"
        assert delivered["epoch"] == 2
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(old_queues.wait_frame(), 0.3)
        await asyncio.sleep(0.1)
        assert older._pulls[id(old_queues)][1].done()
    finally:
        await older.delete_prefix()
        await newer.delete_prefix()
        await older.aclose()
        await newer.aclose()


def test_missing_admin_key_is_written_into_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ASTRA_REDIS_URL=redis://127.0.0.1:6379/0\n", encoding="utf-8")
    settings = get_settings().model_copy(update={"worker_gateway_admin_key": ""})
    previous = os.environ.get(ENV_NAME)
    try:
        key = ensure_worker_gateway_admin_key(settings, env_file)
        assert key.startswith("wgk_")
        assert f"{ENV_NAME}={key}" in env_file.read_text(encoding="utf-8")
        assert settings.worker_gateway_admin_key == key
    finally:
        if previous is None:
            os.environ.pop(ENV_NAME, None)
        else:
            os.environ[ENV_NAME] = previous


def test_admin_header_constant_matches_routes():
    assert ADMIN_HEADERS["X-Astra-Worker-Gateway-Key"] == "wgk_test"

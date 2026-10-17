"""Worker Agent 连接管理：主动连接、认证、心跳、退避重连。"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.worker_agent.supervisor import RuntimeSupervisor
from app.worker_agent.transport import WorkerTransportError
from app.worker_gateway.protocol import (
    WorkerGatewayError,
    WorkerMessage,
    dump_message,
    envelope,
    frame_acceptable,
    parse_message,
)
from app.worker_gateway.service import HeartbeatMonitor

Connect = Callable[[], Awaitable["FrameTransport"]]


class FrameTransport(Protocol):
    async def send(self, message: dict[str, Any]) -> None: ...

    async def recv(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class AgentConfig:
    gateway_url: str
    worker_instance_id: str
    environment_id: int
    token: str
    agent_version: str = "0.1.0"
    ping_seconds: float = 20
    ping_timeout_seconds: float = 10
    auth_timeout_seconds: float = 10
    heartbeat_misses: int = 2
    reconnect_min_seconds: float = 1
    reconnect_max_seconds: float = 30
    max_frame_bytes: int = 262144
    command_dedupe_limit: int = 256
    command_dedupe_ttl_seconds: float = 600


@dataclass(slots=True)
class _Executed:
    state: str
    result: dict[str, Any] | None
    error_code: str | None
    expires_at: float


class CommandLedger:
    """按 request_id 记住有限时间内的执行结果。重复投递返回上次结果或已在执行。"""

    def __init__(self, limit: int, ttl_seconds: float) -> None:
        self.limit = limit
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, _Executed] = {}
        self._order: deque[str] = deque()

    def lookup(self, request_id: str, now: float) -> _Executed | None:
        self._purge(now)
        return self._items.get(request_id)

    def begin(self, request_id: str, now: float) -> None:
        self._put(request_id, _Executed("executing", None, None, now + self.ttl_seconds))

    def finish(
        self,
        request_id: str,
        result: dict[str, Any] | None,
        error_code: str | None,
        now: float,
    ) -> None:
        self._put(request_id, _Executed("done", result, error_code, now + self.ttl_seconds))

    def _put(self, request_id: str, item: _Executed) -> None:
        if request_id not in self._items:
            self._order.append(request_id)
        self._items[request_id] = item
        self._purge(item.expires_at - self.ttl_seconds)

    def _purge(self, now: float) -> None:
        while self._order and (
            self._order[0] not in self._items or self._items[self._order[0]].expires_at <= now
        ):
            self._items.pop(self._order.popleft(), None)
        while len(self._order) > self.limit:
            self._items.pop(self._order.popleft(), None)


def reconnect_delay(attempt: int, minimum: float, maximum: float, rng: random.Random) -> float:
    step = min(maximum, minimum * (2 ** max(attempt - 1, 0)))
    if step >= maximum:
        return maximum
    return min(maximum, step + rng.uniform(0, minimum))


def handle_command(
    message: WorkerMessage, supervisor: RuntimeSupervisor
) -> tuple[dict[str, Any] | None, str | None]:
    name = message.payload.get("name")
    data = message.payload.get("data")
    if not isinstance(data, dict):
        data = {}
    if name == "ping":
        return {"pong": True}, None
    if name == "echo":
        return {"echo": data}, None
    if name == "status":
        return {
            "opencode": "unmanaged",
            "restart_on_disconnect": False,
            "restarts": supervisor.restart_count,
        }, None
    return None, "unsupported_command"


class WorkerConnectionManager:
    def __init__(
        self,
        config: AgentConfig,
        *,
        supervisor: RuntimeSupervisor | None = None,
        rng: random.Random | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self.supervisor = supervisor or RuntimeSupervisor()
        self.rng = rng or random.Random()
        self.sleep = sleep or asyncio.sleep
        self.clock = clock or time.time
        self.epoch: int | None = None
        self.epochs: list[int] = []
        self.delays: list[float] = []
        self.ledger = CommandLedger(config.command_dedupe_limit, config.command_dedupe_ttl_seconds)

    async def run(self, connect: Connect, stop: asyncio.Event, *, max_sessions: int | None = None) -> None:
        attempt = 1
        sessions = 0
        while not stop.is_set():
            try:
                await self.run_session(await connect())
                attempt = 1
            except (ConnectionError, TimeoutError, OSError):
                self.supervisor.on_connection_lost()
            sessions += 1
            if max_sessions is not None and sessions >= max_sessions:
                return
            if stop.is_set():
                return
            delay = reconnect_delay(
                attempt,
                self.config.reconnect_min_seconds,
                self.config.reconnect_max_seconds,
                self.rng,
            )
            self.delays.append(delay)
            attempt += 1
            await self.sleep(delay)

    async def run_session(self, transport: FrameTransport) -> None:
        config = self.config
        auth = envelope(
            request_id=f"auth-{config.worker_instance_id}",
            worker_instance_id=config.worker_instance_id,
            environment_id=config.environment_id,
            session_id=None,
            message_type="command",
            payload={
                "name": "authenticate",
                "token": config.token,
                "agent_version": config.agent_version,
            },
        )
        await transport.send(auth.to_dict())
        try:
            reply = await asyncio.wait_for(self._recv(transport), config.auth_timeout_seconds)
        except TimeoutError as exc:
            raise WorkerTransportError("auth_timeout") from exc
        if reply.type != "response" or not reply.payload.get("ok"):
            raise WorkerTransportError(str(reply.payload.get("error_code") or "auth_failed"))
        epoch = int(reply.payload["epoch"])
        self.epoch = epoch
        self.epochs.append(epoch)
        ping_seconds = float(reply.payload.get("ping_seconds") or config.ping_seconds)
        ping_timeout = float(reply.payload.get("ping_timeout_seconds") or config.ping_timeout_seconds)
        monitor = HeartbeatMonitor(config.heartbeat_misses)
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(transport, ping_seconds, ping_timeout, monitor, heartbeat_stop)
        )
        try:
            while True:
                incoming = await self._next_message(transport, heartbeat)
                if incoming.type == "heartbeat":
                    if not frame_acceptable(incoming, epoch, self.clock()):
                        continue
                    if incoming.payload.get("kind") == "pong":
                        monitor.resolve(incoming.request_id)
                        continue
                    if incoming.payload.get("kind") == "ping":
                        await transport.send(self._heartbeat_reply(incoming, "pong").to_dict())
                    continue
                if incoming.type != "command":
                    continue
                await self._handle_command(transport, incoming, epoch)
        finally:
            heartbeat_stop.set()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            try:
                await transport.close()
            except Exception:
                pass

    async def _next_message(self, transport: FrameTransport, heartbeat: asyncio.Task[None]) -> WorkerMessage:
        recv_task = asyncio.create_task(self._recv(transport))
        try:
            done, _pending = await asyncio.wait(
                {recv_task, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            recv_task.cancel()
            await asyncio.gather(recv_task, return_exceptions=True)
            raise
        if heartbeat in done:
            recv_task.cancel()
            await asyncio.gather(recv_task, return_exceptions=True)
            error = heartbeat.exception()
            if isinstance(error, (ConnectionError, TimeoutError, OSError)):
                raise error
            if error is not None:
                raise WorkerTransportError(error.__class__.__name__) from error
            raise WorkerTransportError("heartbeat_stopped")
        return recv_task.result()

    async def _handle_command(self, transport: FrameTransport, incoming: WorkerMessage, epoch: int) -> None:
        if not frame_acceptable(incoming, epoch, self.clock()):
            return
        now = self.clock()
        recorded = self.ledger.lookup(incoming.request_id, now)
        if recorded is not None and recorded.state == "executing":
            await transport.send(self._duplicate(incoming).to_dict())
            return
        if recorded is not None and recorded.state == "done":
            await transport.send(
                self._response(incoming, "result", recorded.result, recorded.error_code).to_dict()
            )
            return
        self.ledger.begin(incoming.request_id, now)
        await transport.send(self._response(incoming, "ack", None, None).to_dict())
        result, error_code = handle_command(incoming, self.supervisor)
        self.ledger.finish(incoming.request_id, result, error_code, self.clock())
        await transport.send(self._response(incoming, "result", result, error_code).to_dict())

    async def _recv(self, transport: FrameTransport) -> WorkerMessage:
        try:
            return WorkerMessage(**_message_fields(await transport.recv()))
        except WorkerGatewayError as exc:
            raise WorkerTransportError(str(exc)) from exc

    async def _heartbeat(
        self,
        transport: FrameTransport,
        interval: float,
        timeout: float,
        monitor: HeartbeatMonitor,
        stop: asyncio.Event,
    ) -> None:
        count = 0
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), interval)
                return
            except TimeoutError:
                pass
            if stop.is_set():
                return
            count += 1
            request_id = f"hb-{count}"
            event = monitor.track(request_id)
            await transport.send(self._agent_ping(request_id).to_dict())
            if not await self._wait_pong(event, timeout, stop) and monitor.timeout(request_id):
                raise WorkerTransportError("ping_timeout")

    async def _wait_pong(self, event: asyncio.Event, timeout: float, stop: asyncio.Event) -> bool:
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return False
        return not stop.is_set()

    def _agent_ping(self, request_id: str) -> WorkerMessage:
        message = envelope(
            request_id=request_id,
            worker_instance_id=self.config.worker_instance_id,
            environment_id=self.config.environment_id,
            session_id=None,
            message_type="heartbeat",
            payload={"kind": "ping"},
        )
        message.epoch = self.epoch
        message.expires_at = int(self.clock()) + int(self.config.ping_timeout_seconds) + 1
        return message

    def _heartbeat_reply(self, incoming: WorkerMessage, kind: str) -> WorkerMessage:
        message = envelope(
            request_id=incoming.request_id,
            worker_instance_id=self.config.worker_instance_id,
            environment_id=self.config.environment_id,
            session_id=incoming.session_id,
            message_type="heartbeat",
            payload={"kind": kind},
        )
        message.epoch = self.epoch
        message.expires_at = incoming.expires_at
        return message

    def _duplicate(self, command: WorkerMessage) -> WorkerMessage:
        return envelope(
            request_id=command.request_id,
            worker_instance_id=self.config.worker_instance_id,
            environment_id=self.config.environment_id,
            session_id=command.session_id,
            message_type="response",
            payload={
                "stage": "duplicate",
                "ok": True,
                "result": {"state": "already_executing"},
                "error_code": None,
            },
        )

    def _response(
        self,
        command: WorkerMessage,
        stage: str,
        result: dict[str, Any] | None,
        error_code: str | None,
    ) -> WorkerMessage:
        payload: dict[str, Any] = {"stage": stage, "ok": error_code is None}
        if stage == "result":
            payload["result"] = result
            payload["error_code"] = error_code
        return envelope(
            request_id=command.request_id,
            worker_instance_id=self.config.worker_instance_id,
            environment_id=self.config.environment_id,
            session_id=command.session_id,
            message_type="response",
            payload=payload,
        )


def _message_fields(data: dict[str, Any]) -> dict[str, Any]:
    message = parse_message(dump_message(data), max_bytes=1024 * 1024)
    return {
        "request_id": message.request_id,
        "worker_instance_id": message.worker_instance_id,
        "environment_id": message.environment_id,
        "session_id": message.session_id,
        "type": message.type,
        "payload": message.payload,
        "epoch": message.epoch,
        "expires_at": message.expires_at,
    }


def load_agent_config(environ: dict[str, str]) -> AgentConfig:
    token = environ.get("ASTRA_WORKER_TOKEN", "").strip()
    if not token:
        raise SystemExit("缺少 ASTRA_WORKER_TOKEN")
    url = environ.get("ASTRA_WORKER_GATEWAY_URL", "").strip()
    worker_id = environ.get("ASTRA_WORKER_INSTANCE_ID", "").strip()
    environment = environ.get("ASTRA_WORKER_ENVIRONMENT_ID", "").strip()
    if not url or not worker_id or not environment:
        raise SystemExit("缺少 Worker Gateway 地址、实例 ID 或环境 ID")
    return AgentConfig(
        gateway_url=url,
        worker_instance_id=worker_id,
        environment_id=int(environment),
        token=token,
        agent_version=environ.get("ASTRA_WORKER_AGENT_VERSION", "0.1.0"),
    )

"""Worker Agent 连接管理：主动连接、认证、心跳、退避重连。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.worker_agent.supervisor import RuntimeSupervisor
from app.worker_gateway.protocol import (
    WorkerGatewayError,
    WorkerMessage,
    dump_message,
    envelope,
    parse_message,
)

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
    reconnect_min_seconds: float = 1
    reconnect_max_seconds: float = 30
    max_frame_bytes: int = 262144


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
    ) -> None:
        self.config = config
        self.supervisor = supervisor or RuntimeSupervisor()
        self.rng = rng or random.Random()
        self.sleep = sleep or asyncio.sleep
        self.epoch: int | None = None
        self.epochs: list[int] = []
        self.delays: list[float] = []

    async def run(self, connect: Connect, stop: asyncio.Event, *, max_sessions: int | None = None) -> None:
        attempt = 1
        sessions = 0
        while not stop.is_set():
            try:
                await self.run_session(await connect())
                attempt = 1
            except ConnectionError:
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
        reply = await self._recv(transport)
        if reply.type != "response" or not reply.payload.get("ok"):
            raise ConnectionError(str(reply.payload.get("error_code") or "auth_failed"))
        epoch = int(reply.payload["epoch"])
        self.epoch = epoch
        self.epochs.append(epoch)
        ping_seconds = float(reply.payload.get("ping_seconds") or config.ping_seconds)
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(transport, ping_seconds, heartbeat_stop))
        try:
            while True:
                incoming = await self._recv(transport)
                if incoming.type == "heartbeat":
                    if incoming.payload.get("kind") == "ping":
                        await transport.send(
                            envelope(
                                request_id=incoming.request_id,
                                worker_instance_id=config.worker_instance_id,
                                environment_id=config.environment_id,
                                session_id=incoming.session_id,
                                message_type="heartbeat",
                                payload={"kind": "pong"},
                            ).to_dict()
                        )
                    continue
                if incoming.type != "command":
                    continue
                await transport.send(self._response(incoming, "ack", None, None).to_dict())
                result, error_code = handle_command(incoming, self.supervisor)
                await transport.send(self._response(incoming, "result", result, error_code).to_dict())
        finally:
            heartbeat_stop.set()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            try:
                await transport.close()
            except Exception:
                pass

    async def _recv(self, transport: FrameTransport) -> WorkerMessage:
        try:
            return WorkerMessage(**_message_fields(await transport.recv()))
        except WorkerGatewayError as exc:
            raise ConnectionError(str(exc)) from exc

    async def _heartbeat(self, transport: FrameTransport, interval: float, stop: asyncio.Event) -> None:
        count = 0
        while not stop.is_set():
            await asyncio.sleep(interval)
            if stop.is_set():
                return
            count += 1
            await transport.send(
                envelope(
                    request_id=f"hb-{count}",
                    worker_instance_id=self.config.worker_instance_id,
                    environment_id=self.config.environment_id,
                    session_id=None,
                    message_type="heartbeat",
                    payload={"kind": "ping"},
                ).to_dict()
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

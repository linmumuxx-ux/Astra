"""Worker Gateway 服务。

持有套接字的进程是连接所有者。其他进程只通过 RouteBus 投递已落库的指令。
认证成功会使 epoch 加一，旧连接的断开和迟到响应不能改写新 epoch 的状态。
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from secrets import token_hex, token_urlsafe
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from app.config.settings import Settings, get_settings
from app.database import SessionLocal
from app.gateway.security import gateway_key_digest, verify_gateway_key
from app.models import (
    OpenCodeExecutionEnvironment,
    WorkerCommand,
    WorkerConnection,
    WorkerInstance,
    utcnow,
)
from app.worker_gateway.bus import ConnectionQueues, build_route_bus
from app.worker_gateway.protocol import (
    WorkerGatewayError,
    WorkerMessage,
    dump_message,
    envelope,
    parse_message,
    validate_command_name,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuthOk:
    worker_instance_id: str
    environment_id: int
    epoch: int
    ack: WorkerMessage


@dataclass(slots=True)
class EnrollResult:
    worker_instance_id: str
    environment_id: int
    token: str = field(repr=False)
    epoch: int
    rotated: bool


@dataclass(slots=True)
class DispatchResult:
    command: WorkerCommand
    delivered: bool
    replayed: bool
    error_code: str | None


@dataclass
class HeartbeatMonitor:
    limit: int
    misses: int = 0
    pending: dict[str, asyncio.Event] = field(default_factory=dict)

    def track(self, request_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self.pending[request_id] = event
        return event

    def resolve(self, request_id: str) -> bool:
        event = self.pending.pop(request_id, None)
        if event is None:
            return False
        event.set()
        self.misses = 0
        return True

    def timeout(self, request_id: str) -> bool:
        self.pending.pop(request_id, None)
        self.misses += 1
        return self.misses >= self.limit


@dataclass
class _SocketLease:
    epoch: int
    websocket: Any
    inbound_events: deque[dict[str, Any]]
    event_limit: int
    dropped_events: int = 0
    superseded: bool = False

    def buffer_event(self, frame: dict[str, Any]) -> bool:
        if len(self.inbound_events) >= self.event_limit:
            self.dropped_events += 1
            return False
        self.inbound_events.append(frame)
        return True


class WorkerGateway:
    def __init__(self, *, settings: Settings | None = None, bus=None, owner_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.owner_id = owner_id or f"gw_{uuid4().hex[:12]}"
        self.bus = bus or build_route_bus(
            self.settings.worker_gateway_bus,
            self.settings.redis_url,
            control_limit=self.settings.worker_gateway_control_queue_size,
            event_limit=self.settings.worker_gateway_event_queue_size,
        )
        self.sockets: dict[str, _SocketLease] = {}

    async def enroll(self, session: AsyncSession, environment_id: int) -> EnrollResult:
        environment = await session.get(OpenCodeExecutionEnvironment, environment_id)
        if environment is None:
            raise WorkerGatewayError("unknown_environment", "执行环境不存在")
        token = f"wtk_{token_urlsafe(32)}"
        digest = gateway_key_digest(token)
        existing = await session.scalar(
            select(WorkerInstance).where(WorkerInstance.environment_id == environment_id)
        )
        now = utcnow()
        if existing is None:
            instance = WorkerInstance(
                id=f"wrk_{token_hex(16)}",
                environment_id=environment_id,
                token_digest=digest,
                status="offline",
                epoch=0,
            )
            session.add(instance)
            await session.commit()
            return EnrollResult(instance.id, environment_id, token, 0, False)

        previous_epoch = existing.epoch
        worker_id = existing.id
        new_epoch = previous_epoch + 1
        session.expire(existing)
        result = await session.execute(
            update(WorkerInstance)
            .where(WorkerInstance.id == worker_id, WorkerInstance.epoch == previous_epoch)
            .values(token_digest=digest, epoch=new_epoch, status="offline", updated_at=now)
        )
        if result.rowcount != 1:
            await session.rollback()
            raise WorkerGatewayError("epoch_conflict", "连接注册冲突")
        await self._supersede_connections(session, worker_id, now, "token_rotated")
        await session.commit()
        await self.bus.clear_owner(worker_id, previous_epoch, None)
        self._close_local_socket(worker_id)
        return EnrollResult(worker_id, environment_id, token, new_epoch, True)

    async def authenticate(self, session: AsyncSession, message: WorkerMessage, token: str) -> AuthOk:
        if message.type != "command" or message.payload.get("name") != "authenticate":
            raise WorkerGatewayError("unauthorized", "认证失败")
        instance = await session.get(WorkerInstance, message.worker_instance_id)
        if instance is None or instance.environment_id != message.environment_id:
            raise WorkerGatewayError("unauthorized", "认证失败")
        if not verify_gateway_key(token, instance.token_digest):
            raise WorkerGatewayError("unauthorized", "认证失败")
        expected = instance.epoch
        new_epoch = expected + 1
        now = utcnow()
        version = message.payload.get("agent_version")
        agent_version = version[:64] if isinstance(version, str) and version else instance.agent_version
        worker_id = instance.id
        environment_id = instance.environment_id
        session.expire(instance)
        result = await session.execute(
            update(WorkerInstance)
            .where(WorkerInstance.id == worker_id, WorkerInstance.epoch == expected)
            .values(
                epoch=new_epoch,
                status="online",
                last_heartbeat_at=now,
                connected_at=now,
                agent_version=agent_version,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            await session.rollback()
            raise WorkerGatewayError("epoch_conflict", "连接注册冲突")
        await self._supersede_connections(session, worker_id, now, "epoch_replaced")
        session.add(
            WorkerConnection(worker_instance_id=worker_id, epoch=new_epoch, state="active", opened_at=now)
        )
        await session.commit()
        ack = envelope(
            request_id=message.request_id,
            worker_instance_id=worker_id,
            environment_id=environment_id,
            session_id=None,
            message_type="response",
            payload={
                "ok": True,
                "epoch": new_epoch,
                "ping_seconds": self.settings.worker_gateway_ping_seconds,
                "ping_timeout_seconds": self.settings.worker_gateway_ping_timeout_seconds,
            },
        )
        return AuthOk(worker_id, environment_id, new_epoch, ack)

    async def disconnect(self, session: AsyncSession, worker_instance_id: str, epoch: int) -> None:
        now = utcnow()
        instance = await session.get(WorkerInstance, worker_instance_id)
        connection = await session.scalar(
            select(WorkerConnection).where(
                WorkerConnection.worker_instance_id == worker_instance_id,
                WorkerConnection.epoch == epoch,
            )
        )
        if connection is not None and connection.state == "active":
            connection.state = "closed"
            connection.close_reason = "disconnected"
            connection.closed_at = now
        if instance is not None and instance.epoch == epoch:
            instance.status = "offline"
            instance.updated_at = now
        await session.commit()

    async def note_heartbeat(self, session: AsyncSession, worker_instance_id: str, epoch: int) -> bool:
        now = utcnow()
        result = await session.execute(
            update(WorkerInstance)
            .where(WorkerInstance.id == worker_instance_id, WorkerInstance.epoch == epoch)
            .values(status="online", last_heartbeat_at=now, updated_at=now)
        )
        await session.commit()
        return result.rowcount == 1

    async def dispatch(
        self,
        session: AsyncSession,
        *,
        worker_instance_id: str,
        request_id: str,
        name: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> DispatchResult:
        validate_command_name(name)
        if not isinstance(payload, dict):
            raise WorkerGatewayError("invalid_message", "payload 必须是对象")
        existing = await session.scalar(select(WorkerCommand).where(WorkerCommand.request_id == request_id))
        if existing is not None:
            if existing.worker_instance_id != worker_instance_id:
                raise WorkerGatewayError("duplicate_request", "request_id 已用于其他 Worker")
            return DispatchResult(existing, False, True, None)
        instance = await session.get(WorkerInstance, worker_instance_id)
        if instance is None:
            raise WorkerGatewayError("unknown_worker", "Worker 不存在")
        frame = envelope(
            request_id=request_id,
            worker_instance_id=worker_instance_id,
            environment_id=instance.environment_id,
            session_id=session_id,
            message_type="command",
            payload={"name": name, "data": payload},
        )
        try:
            encoded = dump_message(frame).encode("utf-8")
        except TypeError as exc:
            raise WorkerGatewayError("invalid_message", "payload 不能序列化") from exc
        if len(encoded) > self.settings.worker_gateway_max_frame_bytes:
            raise WorkerGatewayError("frame_too_large", "单帧超过限制")
        now = utcnow()
        timeout = timeout_seconds or self.settings.worker_gateway_command_timeout_seconds
        owner = await self.bus.get_owner(worker_instance_id)
        online = instance.status == "online" and owner is not None and owner[1] == instance.epoch
        command = WorkerCommand(
            request_id=request_id,
            worker_instance_id=worker_instance_id,
            environment_id=instance.environment_id,
            session_id=session_id,
            name=name,
            payload=payload,
            status="pending" if online else "failed",
            epoch=instance.epoch,
            error_code=None if online else "offline",
            deadline_at=now + timedelta(seconds=timeout),
            finished_at=None if online else now,
        )
        session.add(command)
        await session.commit()
        if not online:
            return DispatchResult(command, False, False, "offline")
        delivered = await self.bus.publish_command(worker_instance_id, frame.to_dict())
        if not delivered:
            return DispatchResult(command, False, False, "queue_full")
        return DispatchResult(command, True, False, None)

    async def apply_response(
        self,
        session: AsyncSession,
        *,
        worker_instance_id: str,
        epoch: int,
        message: WorkerMessage,
    ) -> bool:
        command = await session.scalar(
            select(WorkerCommand).where(WorkerCommand.request_id == message.request_id)
        )
        instance = await session.get(WorkerInstance, worker_instance_id)
        if (
            command is None
            or instance is None
            or instance.epoch != epoch
            or command.epoch != epoch
            or command.worker_instance_id != worker_instance_id
        ):
            await session.rollback()
            return False
        stage = message.payload.get("stage")
        now = utcnow()
        if stage == "ack":
            if command.status != "pending":
                await session.rollback()
                return False
            command.status = "accepted"
            command.updated_at = now
            await session.commit()
            return True
        if stage != "result":
            await session.rollback()
            return False
        if command.status not in {"pending", "accepted"}:
            await session.rollback()
            return False
        error_code = message.payload.get("error_code")
        if error_code:
            command.status = "failed"
            command.error_code = str(error_code)[:64]
        else:
            command.status = "succeeded"
            command.error_code = None
        result = message.payload.get("result")
        command.result = result if isinstance(result, dict) else {"value": result}
        command.finished_at = now
        command.updated_at = now
        await session.commit()
        return True

    async def epoch_is_current(self, session: AsyncSession, worker_instance_id: str, epoch: int) -> bool:
        instance = await session.get(WorkerInstance, worker_instance_id)
        return instance is not None and instance.epoch == epoch

    async def sweep(self, *, now=None) -> int:
        current = now or utcnow()
        stale_after = timedelta(
            seconds=(
                self.settings.worker_gateway_ping_seconds
                + self.settings.worker_gateway_ping_timeout_seconds
            )
        )
        changed = 0
        async with SessionLocal() as session:
            instances = (
                await session.scalars(select(WorkerInstance).where(WorkerInstance.status == "online"))
            ).all()
            for instance in instances:
                heartbeat = instance.last_heartbeat_at
                if heartbeat is None or heartbeat <= current - stale_after:
                    instance.status = "offline"
                    instance.updated_at = current
                    changed += 1
            commands = (
                await session.scalars(
                    select(WorkerCommand).where(WorkerCommand.status.in_(("pending", "accepted")))
                )
            ).all()
            for command in commands:
                if command.deadline_at is not None and command.deadline_at <= current:
                    command.status = "expired"
                    command.error_code = "timeout"
                    command.finished_at = current
                    command.updated_at = current
                    changed += 1
            await session.commit()
        return changed

    async def serve_socket(self, websocket: Any) -> None:
        await websocket.accept()
        auth: AuthOk | None = None
        queues: ConnectionQueues | None = None
        stop = asyncio.Event()
        sender: asyncio.Task[None] | None = None
        pinger: asyncio.Task[None] | None = None
        try:
            auth = await self._read_auth(websocket)
            queues = self.bus.bind(auth.worker_instance_id)
            await self.bus.set_owner(auth.worker_instance_id, self.owner_id, auth.epoch)
            lease = _SocketLease(
                epoch=auth.epoch,
                websocket=websocket,
                inbound_events=deque(),
                event_limit=self.settings.worker_gateway_event_queue_size,
            )
            self._remember_socket(auth.worker_instance_id, lease)
            await websocket.send_text(dump_message(auth.ack))
            monitor = HeartbeatMonitor(self.settings.worker_gateway_heartbeat_misses)
            sender = asyncio.create_task(self._send_loop(websocket, queues, stop))
            pinger = asyncio.create_task(self._ping_loop(auth, queues, monitor, stop, websocket))
            await self._receive_loop(websocket, auth, lease, monitor, stop)
        except WorkerGatewayError as exc:
            if auth is None:
                await self._send_failure(websocket, exc)
                code = 1009 if exc.code == "frame_too_large" else 1008
                await self._try_close(websocket, code)
        except (WebSocketDisconnect, TimeoutError, ConnectionError):
            await self._try_close(websocket, 4000)
        finally:
            stop.set()
            tasks = [task for task in (sender, pinger) if task is not None]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if auth is not None:
                if queues is not None:
                    await self.bus.unbind(auth.worker_instance_id, queues)
                await self.bus.clear_owner(auth.worker_instance_id, auth.epoch, self.owner_id)
                self._forget_socket(auth.worker_instance_id, auth.epoch)
                async with SessionLocal() as session:
                    await self.disconnect(session, auth.worker_instance_id, auth.epoch)

    async def aclose(self) -> None:
        for lease in list(self.sockets.values()):
            lease.superseded = True
            await self._try_close(lease.websocket, 1001)
        self.sockets.clear()
        await self.bus.aclose()

    async def _read_auth(self, websocket: Any) -> AuthOk:
        raw = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=self.settings.worker_gateway_auth_timeout_seconds,
        )
        message = parse_message(raw, max_bytes=self.settings.worker_gateway_max_frame_bytes)
        token = message.payload.get("token")
        if not isinstance(token, str) or not token:
            raise WorkerGatewayError("unauthorized", "认证失败")
        async with SessionLocal() as session:
            return await self.authenticate(session, message, token)

    async def _receive_loop(
        self,
        websocket: Any,
        auth: AuthOk,
        lease: _SocketLease,
        monitor: HeartbeatMonitor,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            raw = await websocket.receive_text()
            try:
                message = parse_message(raw, max_bytes=self.settings.worker_gateway_max_frame_bytes)
            except WorkerGatewayError as exc:
                if exc.code == "frame_too_large":
                    raise
                continue
            if message.worker_instance_id != auth.worker_instance_id:
                continue
            if message.type == "heartbeat":
                await self._on_heartbeat(auth, message, monitor)
                if message.payload.get("kind") == "ping":
                    await self._queue_heartbeat(auth, message.request_id, "pong")
                continue
            if message.type == "event":
                lease.buffer_event(message.to_dict())
                continue
            if message.type != "response":
                continue
            async with SessionLocal() as session:
                applied = await self.apply_response(
                    session,
                    worker_instance_id=auth.worker_instance_id,
                    epoch=auth.epoch,
                    message=message,
                )
            if applied:
                continue
            async with SessionLocal() as session:
                current = await self.epoch_is_current(session, auth.worker_instance_id, auth.epoch)
            if not current:
                raise ConnectionError("epoch_stale")

    async def _on_heartbeat(self, auth: AuthOk, message: WorkerMessage, monitor: HeartbeatMonitor) -> None:
        if message.payload.get("kind") == "pong":
            monitor.resolve(message.request_id)
        async with SessionLocal() as session:
            current = await self.note_heartbeat(session, auth.worker_instance_id, auth.epoch)
        if not current:
            raise ConnectionError("epoch_stale")

    async def _queue_heartbeat(self, auth: AuthOk, request_id: str, kind: str) -> None:
        queues = self.bus.bound.get(auth.worker_instance_id)
        if queues is None:
            return
        frame = envelope(
            request_id=request_id,
            worker_instance_id=auth.worker_instance_id,
            environment_id=auth.environment_id,
            session_id=None,
            message_type="heartbeat",
            payload={"kind": kind},
        )
        await queues.put_control(frame.to_dict())

    async def _ping_loop(
        self,
        auth: AuthOk,
        queues: ConnectionQueues,
        monitor: HeartbeatMonitor,
        stop: asyncio.Event,
        websocket: Any,
    ) -> None:
        interval = self.settings.worker_gateway_ping_seconds
        timeout = self.settings.worker_gateway_ping_timeout_seconds
        while not stop.is_set():
            await asyncio.sleep(interval)
            if stop.is_set():
                return
            request_id = f"hb_{uuid4().hex}"
            event = monitor.track(request_id)
            frame = envelope(
                request_id=request_id,
                worker_instance_id=auth.worker_instance_id,
                environment_id=auth.environment_id,
                session_id=None,
                message_type="heartbeat",
                payload={"kind": "ping"},
            )
            queued = await queues.put_control(frame.to_dict())
            if not queued or not await self._wait_pong(event, timeout, stop):
                if monitor.timeout(request_id):
                    stop.set()
                    await self._try_close(websocket, 4001)
                    return

    async def _wait_pong(self, event: asyncio.Event, timeout: float, stop: asyncio.Event) -> bool:
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return False
        return not stop.is_set()

    async def _send_loop(self, websocket: Any, queues: ConnectionQueues, stop: asyncio.Event) -> None:
        while not stop.is_set():
            waiting = asyncio.create_task(queues.wait_frame())
            halted = asyncio.create_task(stop.wait())
            try:
                done, pending = await asyncio.wait(
                    {waiting, halted}, return_when=asyncio.FIRST_COMPLETED
                )
            except asyncio.CancelledError:
                waiting.cancel()
                halted.cancel()
                await asyncio.gather(waiting, halted, return_exceptions=True)
                raise
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            if waiting not in done or waiting.cancelled():
                return
            await websocket.send_text(dump_message(waiting.result()))

    async def _supersede_connections(self, session: AsyncSession, worker_id: str, now, reason: str) -> None:
        await session.execute(
            update(WorkerConnection)
            .where(WorkerConnection.worker_instance_id == worker_id, WorkerConnection.state == "active")
            .values(state="superseded", close_reason=reason, closed_at=now)
        )

    def _remember_socket(self, worker_instance_id: str, lease: _SocketLease) -> None:
        previous = self.sockets.get(worker_instance_id)
        self.sockets[worker_instance_id] = lease
        if previous is not None and previous is not lease:
            previous.superseded = True
            asyncio.create_task(self._try_close(previous.websocket, 4000))

    def _forget_socket(self, worker_instance_id: str, epoch: int) -> None:
        current = self.sockets.get(worker_instance_id)
        if current is not None and current.epoch == epoch:
            del self.sockets[worker_instance_id]

    def _close_local_socket(self, worker_instance_id: str) -> None:
        lease = self.sockets.get(worker_instance_id)
        if lease is None:
            return
        lease.superseded = True
        asyncio.create_task(self._try_close(lease.websocket, 4000))

    async def _send_failure(self, websocket: Any, exc: WorkerGatewayError) -> None:
        message = envelope(
            request_id="auth",
            worker_instance_id="",
            environment_id=0,
            session_id=None,
            message_type="response",
            payload={"ok": False, "error_code": exc.code},
        )
        try:
            await websocket.send_text(dump_message(message))
        except Exception:
            logger.debug("worker auth failure could not be sent", exc_info=True)

    async def _try_close(self, websocket: Any, code: int) -> None:
        try:
            await websocket.close(code=code)
        except Exception:
            logger.debug("worker socket close failed", exc_info=True)


_gateway: WorkerGateway | None = None


def get_gateway() -> WorkerGateway:
    global _gateway
    if _gateway is None:
        _gateway = WorkerGateway()
    return _gateway


async def sweep_worker_gateway() -> None:
    gateway = get_gateway()
    interval = gateway.settings.worker_gateway_ping_timeout_seconds
    while True:
        try:
            await gateway.sweep()
        except Exception:
            logger.exception("worker gateway sweep failed")
        await asyncio.sleep(interval)

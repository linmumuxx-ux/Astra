"""Worker Gateway 服务。

持有套接字的进程是连接所有者。其他进程只通过 RouteBus 投递已落库的指令。
认证成功会使 epoch 加一，旧连接的断开和迟到响应不能改写新 epoch 的状态。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from secrets import token_hex, token_urlsafe
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
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
    frame_acceptable,
    parse_message,
    validate_command_name,
)

# 有副作用且结果未知时不能盲重发。阶段 1 没有 OpenCode 对账，投递成功后就停在原命令上。
SIDE_EFFECT_COMMANDS = frozenset({"prompt"})

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
        if bus is None:
            self.bus, self.bus_mode, self.bus_warning = build_route_bus(
                self.settings.worker_gateway_bus,
                self.settings.redis_url,
                control_limit=self.settings.worker_gateway_control_queue_size,
                event_limit=self.settings.worker_gateway_event_queue_size,
            )
            if self.bus_warning:
                logger.warning("Worker Gateway 当前总线是 memory，%s", self.bus_warning)
        else:
            self.bus = bus
            self.bus_mode = getattr(bus, "mode", "memory")
            self.bus_warning = "仅单进程可用" if self.bus_mode == "memory" else None
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
        await session.execute(
            update(WorkerConnection)
            .where(
                WorkerConnection.worker_instance_id == worker_instance_id,
                WorkerConnection.epoch == epoch,
                WorkerConnection.state == "active",
            )
            .values(state="closed", close_reason="disconnected", closed_at=now)
        )
        await session.execute(
            update(WorkerInstance)
            .where(
                WorkerInstance.id == worker_instance_id,
                WorkerInstance.epoch == epoch,
                WorkerInstance.status == "online",
            )
            .values(status="offline", updated_at=now)
        )
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
            self._require_same_command(existing, worker_instance_id, name, payload)
            return DispatchResult(existing, False, True, None)
        instance = await session.get(WorkerInstance, worker_instance_id)
        if instance is None:
            raise WorkerGatewayError("unknown_worker", "Worker 不存在")
        now = utcnow()
        timeout = timeout_seconds or self.settings.worker_gateway_command_timeout_seconds
        frame = envelope(
            request_id=request_id,
            worker_instance_id=worker_instance_id,
            environment_id=instance.environment_id,
            session_id=session_id,
            message_type="command",
            payload={"name": name, "data": payload},
        )
        frame.epoch = instance.epoch
        frame.expires_at = int((now + timedelta(seconds=timeout)).timestamp())
        try:
            encoded = dump_message(frame).encode("utf-8")
        except TypeError as exc:
            raise WorkerGatewayError("invalid_message", "payload 不能序列化") from exc
        if len(encoded) > self.settings.worker_gateway_max_frame_bytes:
            raise WorkerGatewayError("frame_too_large", "单帧超过限制")
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
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            stored = await session.scalar(
                select(WorkerCommand).where(WorkerCommand.request_id == request_id)
            )
            if stored is None:
                raise
            self._require_same_command(stored, worker_instance_id, name, payload)
            return DispatchResult(stored, False, True, None)
        if not online:
            return DispatchResult(command, False, False, "offline")
        delivered, reason = await self._handoff(command.id, owner_only=False)
        return DispatchResult(command, delivered, False, None if delivered else reason)

    def _require_same_command(
        self, existing: WorkerCommand, worker_instance_id: str, name: str, payload: dict[str, Any]
    ) -> None:
        if (
            existing.worker_instance_id != worker_instance_id
            or existing.name != name
            or existing.payload != payload
        ):
            raise WorkerGatewayError("duplicate_request", "request_id 已用于其他指令")

    async def dispatch_due(self, worker_instance_id: str, epoch: int) -> int:
        """只有当前 owner 进程补投未确认的指令。prompt 一旦交出去就不再盲重发。"""

        owner = await self.bus.get_owner(worker_instance_id)
        if owner is None or owner[0] != self.owner_id or owner[1] != epoch:
            return 0
        lease_before = utcnow() - timedelta(seconds=self.settings.worker_gateway_dispatch_lease_seconds)
        async with SessionLocal() as session:
            rows = (
                await session.scalars(
                    select(WorkerCommand).where(
                        WorkerCommand.worker_instance_id == worker_instance_id,
                        WorkerCommand.epoch == epoch,
                        WorkerCommand.status.in_(("pending", "accepted")),
                        or_(
                            WorkerCommand.last_dispatched_at.is_(None),
                            WorkerCommand.last_dispatched_at <= lease_before,
                        ),
                    )
                )
            ).all()
            pending = [(row.id, row.name, row.delivery_attempts) for row in rows]
        delivered = 0
        for command_id, name, attempts in pending:
            if name in SIDE_EFFECT_COMMANDS and attempts > 0:
                continue
            ok, _reason = await self._handoff(command_id, owner_only=True)
            if ok:
                delivered += 1
        return delivered

    async def _handoff(self, command_id: int, *, owner_only: bool) -> tuple[bool, str]:
        async with SessionLocal() as session:
            command = await session.get(WorkerCommand, command_id)
            if command is None or command.status not in {"pending", "accepted"}:
                return False, "offline"
            if command.name in SIDE_EFFECT_COMMANDS and command.delivery_attempts > 0:
                return False, "needs_reconcile"
            owner = await self.bus.get_owner(command.worker_instance_id)
            if owner is None or owner[1] != command.epoch:
                return False, "offline"
            if owner_only and owner[0] != self.owner_id:
                return False, "offline"
            now = utcnow()
            lease_before = now - timedelta(seconds=self.settings.worker_gateway_dispatch_lease_seconds)
            attempts = command.delivery_attempts + 1
            claim = await session.execute(
                update(WorkerCommand)
                .where(
                    WorkerCommand.id == command.id,
                    WorkerCommand.epoch == command.epoch,
                    WorkerCommand.status.in_(("pending", "accepted")),
                    or_(
                        WorkerCommand.last_dispatched_at.is_(None),
                        WorkerCommand.last_dispatched_at <= lease_before,
                    ),
                )
                .values(
                    delivery_attempts=WorkerCommand.delivery_attempts + 1,
                    last_dispatched_at=now,
                    dispatched_epoch=command.epoch,
                    updated_at=now,
                )
            )
            if claim.rowcount != 1:
                await session.rollback()
                return False, "in_flight"
            worker_id = command.worker_instance_id
            epoch = command.epoch
            frame = self._command_frame(command)
            await session.commit()
        try:
            published = await self.bus.publish_command(worker_id, frame)
        except Exception:
            logger.warning("worker command publish failed", exc_info=True)
            published = False
        if published:
            return True, ""
        await self._revert_handoff(command_id, attempts, epoch)
        fresh_owner = await self.bus.get_owner(worker_id)
        if fresh_owner is None or fresh_owner[1] != epoch:
            return False, "offline"
        return False, "queue_full"

    async def _revert_handoff(self, command_id: int, attempts: int, epoch: int) -> None:
        async with SessionLocal() as session:
            await session.execute(
                update(WorkerCommand)
                .where(
                    WorkerCommand.id == command_id,
                    WorkerCommand.epoch == epoch,
                    WorkerCommand.delivery_attempts == attempts,
                    WorkerCommand.status.in_(("pending", "accepted")),
                )
                .values(
                    delivery_attempts=attempts - 1,
                    last_dispatched_at=None,
                    dispatched_epoch=None,
                    updated_at=utcnow(),
                )
            )
            await session.commit()

    def _command_frame(self, command: WorkerCommand) -> dict[str, Any]:
        deadline = command.deadline_at or (
            utcnow() + timedelta(seconds=self.settings.worker_gateway_command_timeout_seconds)
        )
        message = envelope(
            request_id=command.request_id,
            worker_instance_id=command.worker_instance_id,
            environment_id=command.environment_id,
            session_id=command.session_id,
            message_type="command",
            payload={"name": command.name, "data": command.payload},
        )
        message.epoch = command.epoch
        message.expires_at = int(deadline.timestamp())
        return message.to_dict()

    async def apply_response(
        self,
        session: AsyncSession,
        *,
        worker_instance_id: str,
        epoch: int,
        message: WorkerMessage,
    ) -> bool:
        stage = message.payload.get("stage")
        now = utcnow()
        current_instance = (
            select(WorkerInstance.id)
            .where(WorkerInstance.id == worker_instance_id, WorkerInstance.epoch == epoch)
            .scalar_subquery()
        )
        where = (
            WorkerCommand.request_id == message.request_id,
            WorkerCommand.worker_instance_id == worker_instance_id,
            WorkerCommand.epoch == epoch,
            WorkerCommand.worker_instance_id == current_instance,
        )
        if stage == "ack":
            result = await session.execute(
                update(WorkerCommand)
                .where(*where, WorkerCommand.status == "pending")
                .values(status="accepted", updated_at=now)
            )
            await session.commit()
            return result.rowcount == 1
        if stage != "result":
            await session.rollback()
            return False
        error_code = message.payload.get("error_code")
        values: dict[str, Any] = {
            "finished_at": now,
            "updated_at": now,
        }
        if error_code:
            values["status"] = "failed"
            values["error_code"] = str(error_code)[:64]
        else:
            values["status"] = "succeeded"
            values["error_code"] = None
        result_body = message.payload.get("result")
        values["result"] = result_body if isinstance(result_body, dict) else {"value": result_body}
        result = await session.execute(
            update(WorkerCommand)
            .where(*where, WorkerCommand.status.in_(("pending", "accepted")))
            .values(**values)
        )
        await session.commit()
        return result.rowcount == 1

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
        stale_before = current - stale_after
        async with SessionLocal() as session:
            offline = await session.execute(
                update(WorkerInstance)
                .where(
                    WorkerInstance.status == "online",
                    or_(
                        WorkerInstance.last_heartbeat_at.is_(None),
                        WorkerInstance.last_heartbeat_at <= stale_before,
                    ),
                )
                .values(status="offline", updated_at=current)
            )
            expired = await session.execute(
                update(WorkerCommand)
                .where(
                    WorkerCommand.status.in_(("pending", "accepted")),
                    WorkerCommand.deadline_at.is_not(None),
                    WorkerCommand.deadline_at <= current,
                )
                .values(
                    status="expired",
                    error_code="timeout",
                    finished_at=current,
                    updated_at=current,
                )
            )
            await session.commit()
        return int(offline.rowcount or 0) + int(expired.rowcount or 0)

    async def serve_socket(self, websocket: Any) -> None:
        await websocket.accept()
        auth: AuthOk | None = None
        queues: ConnectionQueues | None = None
        stop = asyncio.Event()
        sender: asyncio.Task[None] | None = None
        pinger: asyncio.Task[None] | None = None
        dispatcher: asyncio.Task[None] | None = None
        try:
            auth = await self._read_auth(websocket)
            owned = await self.bus.set_owner(auth.worker_instance_id, self.owner_id, auth.epoch)
            if not owned:
                raise ConnectionError("epoch_stale")
            queues = await self.bus.bind(
                auth.worker_instance_id, epoch=auth.epoch, owner_id=self.owner_id
            )
            if queues is None:
                raise ConnectionError("epoch_stale")
            lease = _SocketLease(
                epoch=auth.epoch,
                websocket=websocket,
                inbound_events=deque(),
                event_limit=self.settings.worker_gateway_event_queue_size,
            )
            if not self._remember_socket(auth.worker_instance_id, lease):
                raise ConnectionError("epoch_stale")
            await websocket.send_text(dump_message(auth.ack))
            monitor = HeartbeatMonitor(self.settings.worker_gateway_heartbeat_misses)
            sender = asyncio.create_task(self._send_loop(websocket, queues, auth, stop))
            pinger = asyncio.create_task(self._ping_loop(auth, queues, monitor, stop, websocket))
            dispatcher = asyncio.create_task(self._dispatch_loop(auth, stop, websocket))
            await self._receive_loop(websocket, auth, lease, monitor, stop)
        except WorkerGatewayError as exc:
            await self._send_failure(websocket, exc)
            code = 1009 if exc.code == "frame_too_large" else 1008
            await self._try_close(websocket, code)
        except (WebSocketDisconnect, TimeoutError, ConnectionError):
            await self._try_close(websocket, 4000)
        finally:
            stop.set()
            tasks = [task for task in (sender, pinger, dispatcher) if task is not None]
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
            message = parse_message(raw, max_bytes=self.settings.worker_gateway_max_frame_bytes)
            if message.worker_instance_id != auth.worker_instance_id:
                raise WorkerGatewayError("invalid_message", "worker_instance_id 与连接不一致")
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
                if message.payload.get("stage") == "result":
                    await self._route_response(message)
                continue
            async with SessionLocal() as session:
                current = await self.epoch_is_current(session, auth.worker_instance_id, auth.epoch)
            if not current:
                raise ConnectionError("epoch_stale")

    async def _route_response(self, message: WorkerMessage) -> None:
        try:
            await self.bus.publish_response(message.request_id, message.to_dict())
        except Exception:
            logger.warning("worker response route failed", exc_info=True)

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
        frame = self._heartbeat_frame(auth, request_id, kind)
        await queues.put_control(frame)

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
            try:
                refreshed = await self.bus.touch_owner(
                    auth.worker_instance_id, self.owner_id, auth.epoch
                )
            except Exception:
                logger.warning("worker owner lease refresh failed", exc_info=True)
                refreshed = False
            if not refreshed:
                stop.set()
                await self._try_close(websocket, 4000)
                return
            request_id = f"hb_{uuid4().hex}"
            event = monitor.track(request_id)
            queued = await queues.put_control(self._heartbeat_frame(auth, request_id, "ping"))
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

    def _heartbeat_frame(self, auth: AuthOk, request_id: str, kind: str) -> dict[str, Any]:
        message = envelope(
            request_id=request_id,
            worker_instance_id=auth.worker_instance_id,
            environment_id=auth.environment_id,
            session_id=None,
            message_type="heartbeat",
            payload={"kind": kind},
        )
        message.epoch = auth.epoch
        horizon = (
            self.settings.worker_gateway_ping_seconds
            + self.settings.worker_gateway_ping_timeout_seconds
        )
        message.expires_at = int(time.time()) + horizon
        return message.to_dict()

    async def _dispatch_loop(self, auth: AuthOk, stop: asyncio.Event, websocket: Any) -> None:
        interval = self.settings.worker_gateway_dispatch_lease_seconds
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), interval)
                return
            except TimeoutError:
                pass
            if stop.is_set():
                return
            try:
                if not await self.bus.touch_owner(auth.worker_instance_id, self.owner_id, auth.epoch):
                    stop.set()
                    await self._try_close(websocket, 4000)
                    return
                await self.dispatch_due(auth.worker_instance_id, auth.epoch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker command dispatch failed")

    async def _send_loop(
        self, websocket: Any, queues: ConnectionQueues, auth: AuthOk, stop: asyncio.Event
    ) -> None:
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
            frame = waiting.result()
            message = parse_message(
                dump_message(frame), max_bytes=self.settings.worker_gateway_max_frame_bytes
            )
            if not frame_acceptable(message, auth.epoch, time.time()):
                continue
            if not await self.bus.touch_owner(auth.worker_instance_id, self.owner_id, auth.epoch):
                stop.set()
                await self._try_close(websocket, 4000)
                return
            await websocket.send_text(dump_message(message))

    async def _supersede_connections(self, session: AsyncSession, worker_id: str, now, reason: str) -> None:
        await session.execute(
            update(WorkerConnection)
            .where(WorkerConnection.worker_instance_id == worker_id, WorkerConnection.state == "active")
            .values(state="superseded", close_reason=reason, closed_at=now)
        )

    def _remember_socket(self, worker_instance_id: str, lease: _SocketLease) -> bool:
        previous = self.sockets.get(worker_instance_id)
        if previous is not None and previous is not lease and previous.epoch >= lease.epoch:
            return False
        self.sockets[worker_instance_id] = lease
        if previous is not None and previous is not lease:
            previous.superseded = True
            asyncio.create_task(self._try_close(previous.websocket, 4000))
        return True

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

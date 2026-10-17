"""HTTP bodies for Worker commands. WebSocket frames only say a request is ready."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, WorkerCommand, WorkerInstance, utcnow
from app.runtime.submission import get_attempt, mark_body_fetched
from app.worker_gateway.http_limit import release_http_slot
from app.worker_gateway.protocol import WorkerGatewayError

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_CHUNK_BYTES = 256 * 1024
_READY = "ready"


def request_key(request_id: str) -> str:
    return f"body-request:{request_id}"


def response_key(request_id: str, upload_id: str) -> str:
    return f"body-response:{request_id}:{upload_id}"


def http_frame_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = {key: value for key, value in payload.items() if key != "body"}
    data[_READY] = True
    return data


def encoded_body(payload: dict[str, Any]) -> bytes:
    raw = payload.get("body")
    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
    else:
        encoded = json.dumps(raw if raw is not None else {}, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_BODY_BYTES:
        raise WorkerGatewayError("body_too_large", "请求体超过 8 MiB")
    return encoded


def side_effect_http(name: str, payload: dict[str, Any] | None) -> bool:
    if name != "http":
        return False
    method = str((payload or {}).get("method") or "GET").upper()
    return method not in {"GET", "HEAD"}


class UnfetchedSealError(RuntimeError):
    """The original command was fetched while a human retry tried to seal it."""


class DataChannel:
    def __init__(self, gateway) -> None:
        self.gateway = gateway

    async def stage_request(self, command: WorkerCommand) -> None:
        if command.name != "http":
            return
        body = encoded_body(command.payload or {})
        deadline = command.deadline_at or utcnow()
        margin = self.gateway.settings.worker_gateway_dispatch_lease_seconds
        ttl = max(1.0, (deadline - utcnow()).total_seconds() + margin)
        await self.gateway.bus.put_text(request_key(command.request_id), body.decode("utf-8"), ttl)

    async def fetch_request(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        worker_instance_id: str,
        epoch: int,
    ) -> dict[str, Any]:
        command, instance = await self._current_command(
            session, request_id=request_id, worker_instance_id=worker_instance_id, epoch=epoch
        )
        if command.status not in {"pending", "accepted"}:
            raise WorkerGatewayError("epoch_conflict", "指令已结束")
        if command.epoch != instance.epoch or command.epoch != epoch:
            raise WorkerGatewayError("epoch_conflict", "epoch 已切换")
        now = utcnow()
        if command.deadline_at is not None and command.deadline_at <= now:
            raise WorkerGatewayError("epoch_conflict", "指令已过期")
        already_fetched = command.body_fetched_at is not None
        stored = await self.gateway.bus.get_text(request_key(request_id))
        if stored is None:
            stored = encoded_body(command.payload or {}).decode("utf-8")
        now = utcnow()
        await self._require_current_attempt(session, command)
        current_instance = (
            select(WorkerInstance.id)
            .where(WorkerInstance.id == worker_instance_id, WorkerInstance.epoch == epoch)
            .scalar_subquery()
        )
        result = await session.execute(
            update(WorkerCommand)
            .where(
                WorkerCommand.id == command.id,
                WorkerCommand.epoch == epoch,
                WorkerCommand.status.in_(("pending", "accepted")),
                WorkerCommand.worker_instance_id == current_instance,
                or_(WorkerCommand.deadline_at.is_(None), WorkerCommand.deadline_at > now),
            )
            .values(body_fetched_at=func.coalesce(WorkerCommand.body_fetched_at, now), updated_at=now)
        )
        if result.rowcount != 1:
            await session.rollback()
            raise WorkerGatewayError("epoch_conflict", "指令已结束")
        if not already_fetched:
            await self.note_task_fetch(session, command, now)
        await session.commit()
        await session.refresh(command)
        payload = command.payload or {}
        return {
            "request_id": request_id,
            "method": payload.get("method") or "GET",
            "path": payload.get("path") or "/",
            "query": payload.get("query") or {},
            "body": stored,
            "epoch": command.epoch,
        }

    async def commit_upload(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        worker_instance_id: str,
        epoch: int,
        upload_id: str,
        http_status: int,
        headers: dict[str, str],
        content_type: str | None,
        chunk: str,
        complete: bool,
    ) -> dict[str, Any]:
        if len(chunk.encode("utf-8")) > MAX_CHUNK_BYTES:
            raise WorkerGatewayError("response_too_large", "分块超过 256 KiB")
        try:
            command, instance = await self._current_command(
                session, request_id=request_id, worker_instance_id=worker_instance_id, epoch=epoch
            )
        except WorkerGatewayError:
            await self.gateway.bus.delete_text(response_key(request_id, upload_id))
            raise
        if command.epoch != instance.epoch or epoch != instance.epoch:
            await self.gateway.bus.delete_text(response_key(request_id, upload_id))
            raise WorkerGatewayError("epoch_conflict", "epoch 已切换")
        staged = await self._read_stage(request_id, upload_id)
        staged["chunks"].append(chunk)
        staged["http_status"] = http_status
        staged["headers"] = headers
        staged["content_type"] = content_type
        raw = "".join(staged["chunks"])
        if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
            await self.gateway.bus.delete_text(response_key(request_id, upload_id))
            raise WorkerGatewayError("response_too_large", "响应体超过 8 MiB")
        ttl = self.gateway.settings.worker_gateway_command_timeout_seconds + (
            self.gateway.settings.worker_gateway_dispatch_lease_seconds
        )
        await self.gateway.bus.put_text(
            response_key(request_id, upload_id), json.dumps(staged), ttl
        )
        if not complete:
            await session.rollback()
            return {"status": "partial", "upload_id": upload_id}
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        meta = {
            "http_status": http_status,
            "size": len(raw.encode("utf-8")),
            "sha256": digest,
            "headers": headers,
            "upload_id": upload_id,
            "content_type": content_type,
        }
        if command.status == "succeeded" and (command.result or {}).get("sha256") == digest:
            stored = dict(command.result or {})
            await self.gateway.bus.delete_text(response_key(request_id, upload_id))
            await session.rollback()
            return {"status": "stored", "result": stored}
        current_instance = (
            select(WorkerInstance.id)
            .where(WorkerInstance.id == worker_instance_id, WorkerInstance.epoch == epoch)
            .scalar_subquery()
        )
        values = {
            "status": "succeeded",
            "result": meta,
            "error_code": None,
            "finished_at": utcnow(),
            "updated_at": utcnow(),
            "slot_held": False,
        }
        owned = (
            WorkerCommand.id == command.id,
            WorkerCommand.epoch == epoch,
            WorkerCommand.status.in_(("pending", "accepted")),
            WorkerCommand.worker_instance_id == current_instance,
        )
        released = await session.execute(
            update(WorkerCommand).where(*owned, WorkerCommand.slot_held.is_(True)).values(**values)
        )
        if released.rowcount == 1:
            await release_http_slot(session, worker_instance_id, epoch)
        else:
            result = await session.execute(update(WorkerCommand).where(*owned).values(**values))
            if result.rowcount != 1:
                await session.rollback()
                await self.gateway.bus.delete_text(response_key(request_id, upload_id))
                raise WorkerGatewayError("epoch_conflict", "上传没有提交")
        await session.commit()
        await self.gateway.bus.publish_response(request_id, {"result": meta, "body": raw})
        return {"status": "stored", "result": meta}

    async def _read_stage(self, request_id: str, upload_id: str) -> dict[str, Any]:
        raw = await self.gateway.bus.get_text(response_key(request_id, upload_id))
        if not raw:
            return {"chunks": [], "headers": {}}
        parsed = json.loads(raw)
        parsed.setdefault("chunks", [])
        return parsed

    async def _current_command(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        worker_instance_id: str,
        epoch: int,
    ) -> tuple[WorkerCommand, WorkerInstance]:
        instance = await session.get(WorkerInstance, worker_instance_id)
        command = await session.scalar(select(WorkerCommand).where(WorkerCommand.request_id == request_id))
        if instance is None or command is None or command.worker_instance_id != worker_instance_id:
            raise WorkerGatewayError("unknown_command", "指令不存在")
        if instance.epoch != epoch or command.epoch != epoch:
            raise WorkerGatewayError("epoch_conflict", "epoch 已切换")
        return command, instance

    async def _require_current_attempt(self, session: AsyncSession, command: WorkerCommand) -> None:
        ref = (command.payload or {}).get("attempt_ref")
        if not isinstance(ref, dict) or ref.get("message_id") is None or ref.get("attempt") is None:
            return
        try:
            attempt = int(ref["attempt"])
        except (TypeError, ValueError) as exc:
            raise WorkerGatewayError("epoch_conflict", "指令已不是当前提交") from exc
        task = await session.get(Task, ref.get("task_id"))
        if task is not None:
            await session.refresh(task)
        message_id = str(ref["message_id"])
        record = get_attempt(task, message_id, attempt) if task is not None else None
        current = (
            task is not None
            and task.pending_message_id == message_id
            and task.pending_attempt == attempt
            and record is not None
            and record.get("request_id") == command.request_id
        )
        if not current:
            await session.rollback()
            raise WorkerGatewayError("epoch_conflict", "指令已不是当前提交")

    async def note_task_fetch(self, session: AsyncSession, command: WorkerCommand, when: datetime) -> None:
        ref = (command.payload or {}).get("attempt_ref")
        if not isinstance(ref, dict):
            return
        task = await session.get(Task, ref.get("task_id"))
        if task is None or ref.get("message_id") is None or ref.get("attempt") is None:
            return
        try:
            mark_body_fetched(task, str(ref["message_id"]), int(ref["attempt"]), when)
        except KeyError:
            return


async def seal_unfetched_request(session: AsyncSession, request_id: str) -> None:
    """Fail the original command before a human retry, only while its body is unfetched.

    A fetch that wins the race leaves the body fetched and this call raises.
    A command that already finished without a fetch needs no seal: a late GET
    is rejected because the status is no longer pending.
    """

    command = await session.scalar(select(WorkerCommand).where(WorkerCommand.request_id == request_id))
    if command is None:
        return
    if command.body_fetched_at is not None:
        raise UnfetchedSealError("请求体已拉取，结果未知，不能重发")
    if command.status not in {"pending", "accepted"}:
        return
    now = utcnow()
    values = {
        "status": "failed",
        "error_code": "superseded",
        "finished_at": now,
        "updated_at": now,
        "slot_held": False,
    }
    held = await session.execute(
        update(WorkerCommand)
        .where(
            WorkerCommand.id == command.id,
            WorkerCommand.body_fetched_at.is_(None),
            WorkerCommand.status.in_(("pending", "accepted")),
            WorkerCommand.slot_held.is_(True),
        )
        .values(**values)
    )
    if held.rowcount == 1:
        await release_http_slot(session, command.worker_instance_id, command.epoch)
        session.expire(command)
        return
    sealed = await session.execute(
        update(WorkerCommand)
        .where(
            WorkerCommand.id == command.id,
            WorkerCommand.body_fetched_at.is_(None),
            WorkerCommand.status.in_(("pending", "accepted")),
        )
        .values(**values)
    )
    if sealed.rowcount != 1:
        raise UnfetchedSealError("原指令已被拉取或已结束，结果未知，不能重发")
    session.expire(command)

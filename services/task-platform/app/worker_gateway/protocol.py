"""Worker Gateway 与 Worker Agent 共用的消息信封。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

MESSAGE_TYPES = frozenset({"command", "response", "event", "heartbeat"})
COMMAND_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class WorkerGatewayError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(slots=True)
class WorkerMessage:
    request_id: str
    worker_instance_id: str
    environment_id: int
    session_id: str | None
    type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "worker_instance_id": self.worker_instance_id,
            "environment_id": self.environment_id,
            "session_id": self.session_id,
            "type": self.type,
            "payload": self.payload,
        }


def dump_message(message: WorkerMessage | dict[str, Any]) -> str:
    data = message.to_dict() if isinstance(message, WorkerMessage) else message
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def parse_message(raw: str, *, max_bytes: int) -> WorkerMessage:
    if len(raw.encode("utf-8")) > max_bytes:
        raise WorkerGatewayError("frame_too_large", "单帧超过限制")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkerGatewayError("invalid_message", "消息不是 JSON") from exc
    if not isinstance(data, dict):
        raise WorkerGatewayError("invalid_message", "消息必须是对象")
    for key in ("request_id", "worker_instance_id", "environment_id", "session_id", "type", "payload"):
        if key not in data:
            raise WorkerGatewayError("invalid_message", "消息缺少字段")
    if data["type"] not in MESSAGE_TYPES:
        raise WorkerGatewayError("invalid_message", "未知消息类型")
    if not isinstance(data["request_id"], str) or not data["request_id"].strip():
        raise WorkerGatewayError("invalid_message", "request_id 无效")
    if len(data["request_id"]) > 80:
        raise WorkerGatewayError("invalid_message", "request_id 过长")
    if not isinstance(data["worker_instance_id"], str) or not data["worker_instance_id"].strip():
        raise WorkerGatewayError("invalid_message", "worker_instance_id 无效")
    environment_id = data["environment_id"]
    if isinstance(environment_id, bool) or not isinstance(environment_id, int):
        raise WorkerGatewayError("invalid_message", "environment_id 无效")
    session_id = data["session_id"]
    if session_id is not None and not isinstance(session_id, str):
        raise WorkerGatewayError("invalid_message", "session_id 无效")
    if not isinstance(data["payload"], dict):
        raise WorkerGatewayError("invalid_message", "payload 必须是对象")
    return WorkerMessage(
        request_id=data["request_id"],
        worker_instance_id=data["worker_instance_id"],
        environment_id=environment_id,
        session_id=session_id,
        type=data["type"],
        payload=data["payload"],
    )


def envelope(
    *,
    request_id: str,
    worker_instance_id: str,
    environment_id: int,
    session_id: str | None,
    message_type: str,
    payload: dict[str, Any],
) -> WorkerMessage:
    return WorkerMessage(
        request_id=request_id,
        worker_instance_id=worker_instance_id,
        environment_id=environment_id,
        session_id=session_id,
        type=message_type,
        payload=payload,
    )


def validate_command_name(name: str) -> None:
    if not COMMAND_NAME.fullmatch(name):
        raise WorkerGatewayError("invalid_message", "指令名无效")
    if name == "authenticate":
        raise WorkerGatewayError("invalid_message", "authenticate 只能用于连接注册")

"""Deterministic OpenCode Session outcome derivation.

The Session is the execution fact source; this module turns raw native
observations into one durable result status without touching the database or
performing I/O. It never asserts a terminal failure without evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain import RuntimeSessionStatus, SessionTerminalReason

_TERMINAL_FINISH = {"stop", "end_turn"}


@dataclass(frozen=True, slots=True)
class SessionState:
    status: str
    terminal_reason: str | None = None
    finish_reason: str | None = None
    last_message_id: str | None = None
    finished_at: datetime | None = None


def _info(message: dict) -> dict:
    info = message.get("info")
    return info if isinstance(info, dict) else {}


def _messages_from(messages: list[dict], anchor_id: str | None) -> list[dict]:
    """Messages belonging to the current turn, including the submitted anchor."""
    if not anchor_id:
        return messages
    positions = [index for index, item in enumerate(messages) if _info(item).get("id") == anchor_id]
    if not positions:
        return []
    return messages[positions[-1] :]


def _last_with_role(messages: list[dict], role: str) -> tuple[int, dict] | None:
    for index in range(len(messages) - 1, -1, -1):
        if _info(messages[index]).get("role") == role:
            return index, messages[index]
    return None


def _has_visible_reply(message: dict) -> bool:
    return any(
        isinstance(part, dict)
        and part.get("type") == "text"
        and str(part.get("text") or "").strip()
        and not part.get("synthetic")
        and not part.get("ignored")
        for part in message.get("parts", [])
    )


def derive_session_state(
    *,
    messages: list[dict],
    server_status: str,
    has_pending_question: bool,
    has_pending_permission: bool,
    pending_ack: bool,
    turn_anchor_id: str | None = None,
    turn_started_at: datetime | None = None,
    aborted: bool = False,
    timed_out: bool = False,
    now: datetime | None = None,
    grace_seconds: int = 15,
) -> SessionState:
    """Resolve the current result status for one OpenCode Session.

    Priority order (first match wins): explicit interruption, pending human
    input, native busy, unacknowledged submission, assistant error, completed
    turn, an unanswered new turn, then the bounded no-reply window.
    """

    now = now or datetime.now(UTC)
    last_message_id = _info(messages[-1]).get("id") if messages else None
    if aborted:
        return SessionState(
            status=RuntimeSessionStatus.INTERRUPTED.value,
            terminal_reason=SessionTerminalReason.ABORTED.value,
            last_message_id=last_message_id,
            finished_at=now,
        )
    if timed_out:
        return SessionState(
            status=RuntimeSessionStatus.INTERRUPTED.value,
            terminal_reason=SessionTerminalReason.TIMEOUT.value,
            last_message_id=last_message_id,
            finished_at=now,
        )
    if has_pending_question or has_pending_permission:
        return SessionState(
            status=RuntimeSessionStatus.WAITING.value, last_message_id=last_message_id
        )
    if server_status in {"busy", "retry"}:
        return SessionState(
            status=RuntimeSessionStatus.RUNNING.value, last_message_id=last_message_id
        )
    if pending_ack:
        return SessionState(
            status=RuntimeSessionStatus.RUNNING.value, last_message_id=last_message_id
        )

    turn = _messages_from(messages, turn_anchor_id)
    assistant = _last_with_role(turn, "assistant")
    if assistant:
        _, assistant_message = assistant
        assistant_info = _info(assistant_message)
        if assistant_info.get("error"):
            return SessionState(
                status=RuntimeSessionStatus.FAILED.value,
                terminal_reason=SessionTerminalReason.ASSISTANT_ERROR.value,
                last_message_id=last_message_id or assistant_info.get("id"),
                finished_at=now,
            )
        finish = assistant_info.get("finish")
        completed = bool(assistant_info.get("time", {}).get("completed"))
        newer_user = _last_with_role(turn, "user")
        has_new_turn = bool(newer_user and newer_user[0] > assistant[0])
        if completed and finish in _TERMINAL_FINISH:
            if has_new_turn:
                return SessionState(
                    status=RuntimeSessionStatus.RUNNING.value, last_message_id=last_message_id
                )
            if not _has_visible_reply(assistant_message):
                return SessionState(
                    status=RuntimeSessionStatus.FAILED.value,
                    terminal_reason=SessionTerminalReason.NO_REPLY.value,
                    finish_reason=str(finish),
                    last_message_id=last_message_id or assistant_info.get("id"),
                    finished_at=now,
                )
            return SessionState(
                status=RuntimeSessionStatus.SUCCEEDED.value,
                terminal_reason=SessionTerminalReason.COMPLETED.value,
                finish_reason=str(finish),
                last_message_id=last_message_id or assistant_info.get("id"),
                finished_at=now,
            )
        return SessionState(
            status=RuntimeSessionStatus.RUNNING.value, last_message_id=last_message_id
        )

    # No assistant reply in this turn. A turn only counts as ended without a
    # reply once the native server is idle and the grace window has passed, so a
    # just-submitted prompt is never mistaken for a failed one.
    if server_status == "idle" and turn:
        started = turn_started_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            aged = (now - started).total_seconds() >= grace_seconds
        else:
            aged = True
        if aged:
            return SessionState(
                status=RuntimeSessionStatus.FAILED.value,
                terminal_reason=SessionTerminalReason.NO_REPLY.value,
                last_message_id=last_message_id,
                finished_at=now,
            )
    return SessionState(status=RuntimeSessionStatus.RUNNING.value, last_message_id=last_message_id)
"""IM 入站、出站和 ACK。公司 SDK 不在这里，调用方可以换一个模拟 Adapter。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .db import new_id, utcnow


class ImError(Exception):
    def __init__(self, detail: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def bind_bot(connection, employee_id: str, provider: str, bot_id: str) -> dict[str, str]:
    provider = provider.strip()
    bot_id = bot_id.strip()
    if not provider or not bot_id:
        raise ImError("缺少机器人标识", 422)
    connection.execute(
        "DELETE FROM im_bots WHERE employee_id = ? OR (provider = ? AND bot_id = ?)",
        (employee_id, provider, bot_id),
    )
    connection.execute(
        "INSERT INTO im_bots (employee_id, provider, bot_id) VALUES (?, ?, ?)",
        (employee_id, provider, bot_id),
    )
    connection.commit()
    return {"employee_id": employee_id, "provider": provider, "bot_id": bot_id}


def open_external(connection, employee_id: str, external_key: str, session_id: str) -> dict[str, str]:
    external_key = external_key.strip()
    session_id = session_id.strip()
    if not external_key or not session_id:
        raise ImError("外部群需要独立的会话", 422)
    private = connection.execute(
        """
        SELECT agentscope_session_id FROM conversations
        WHERE employee_id = ? AND kind = 'private' AND agentscope_session_id = ?
        """,
        (employee_id, session_id),
    ).fetchone()
    if private is not None:
        raise ImError("外部群不能复用私聊会话", 409)
    connection.execute(
        """
        INSERT INTO im_bindings (employee_id, kind, external_key, owner_uid, session_id)
        VALUES (?, 'external', ?, '', ?)
        ON CONFLICT(employee_id, kind, external_key, owner_uid)
        DO UPDATE SET session_id = excluded.session_id
        """,
        (employee_id, external_key, session_id),
    )
    connection.commit()
    return {"employee_id": employee_id, "external_key": external_key, "session_id": session_id}


async def accept_inbound(
    connection,
    *,
    provider: str,
    event_id: str,
    bot_id: str,
    sender_uid: str,
    text: str,
    accept: Callable[..., Any],
    external_key: str = "",
    conversation_key: str = "",
) -> dict[str, Any]:
    """AgentScope 接受输入之后才把这次入站标成成功。"""

    provider = provider.strip()
    event_id = event_id.strip()
    if not provider or not event_id:
        raise ImError("缺少入站事件", 422)
    bot = connection.execute(
        "SELECT employee_id FROM im_bots WHERE provider = ? AND bot_id = ?",
        (provider, bot_id.strip()),
    ).fetchone()
    if bot is None:
        raise ImError("这个员工没有绑定机器人，IM 不可用", 409)
    employee_id = bot["employee_id"]
    existing = connection.execute(
        "SELECT * FROM im_events WHERE provider = ? AND event_id = ?",
        (provider, event_id),
    ).fetchone()
    if existing is not None and existing["accepted"]:
        return {
            "accepted": True,
            "duplicate": True,
            "session_id": existing["session_id"],
            "employee_id": employee_id,
        }
    session_id = _session_for(
        connection,
        employee_id,
        sender_uid.strip(),
        external_key.strip(),
        conversation_key.strip(),
    )
    if not session_id:
        raise ImError("还没有可复用的会话", 409)
    connection.execute(
        """
        INSERT INTO im_events (provider, event_id, employee_id, session_id, accepted)
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(provider, event_id) DO UPDATE SET session_id = excluded.session_id
        """,
        (provider, event_id, employee_id, session_id),
    )
    connection.commit()
    await accept(employee_id, session_id, text)
    connection.execute(
        "UPDATE im_events SET accepted = 1, session_id = ? WHERE provider = ? AND event_id = ?",
        (session_id, provider, event_id),
    )
    connection.commit()
    return {"accepted": True, "duplicate": False, "session_id": session_id, "employee_id": employee_id}


def contact_human(
    connection,
    *,
    employee_id: str,
    conversation_key: str,
    session_id: str,
    body: str,
) -> dict[str, str]:
    conversation_key = conversation_key.strip()
    session_id = session_id.strip()
    if not conversation_key or not session_id or not body.strip():
        raise ImError("缺少主动联系的会话或正文", 422)
    connection.execute(
        """
        INSERT INTO im_threads (employee_id, conversation_key, session_id)
        VALUES (?, ?, ?)
        ON CONFLICT(employee_id, conversation_key) DO UPDATE SET session_id = excluded.session_id
        """,
        (employee_id, conversation_key, session_id),
    )
    inflight = connection.execute(
        """
        SELECT delivery_id FROM im_outbox
        WHERE conversation_key = ? AND state = 'inflight'
        """,
        (conversation_key,),
    ).fetchone()
    delivery_id = new_id("dlv")
    state = "queued" if inflight is not None else "inflight"
    connection.execute(
        """
        INSERT INTO im_outbox (
            delivery_id, employee_id, conversation_key, session_id, body, state, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (delivery_id, employee_id, conversation_key, session_id, body.strip(), state, utcnow()),
    )
    connection.commit()
    return {"delivery_id": delivery_id, "state": state, "session_id": session_id}


def acknowledge(connection, delivery_id: str) -> dict[str, str]:
    row = connection.execute("SELECT * FROM im_outbox WHERE delivery_id = ?", (delivery_id,)).fetchone()
    if row is None:
        raise ImError("没有这条投递", 404)
    if row["state"] != "acked":
        connection.execute("UPDATE im_outbox SET state = 'acked' WHERE delivery_id = ?", (delivery_id,))
        nxt = connection.execute(
            """
            SELECT delivery_id FROM im_outbox
            WHERE conversation_key = ? AND state = 'queued'
            ORDER BY created_at, delivery_id
            LIMIT 1
            """,
            (row["conversation_key"],),
        ).fetchone()
        if nxt is not None:
            connection.execute(
                "UPDATE im_outbox SET state = 'inflight' WHERE delivery_id = ?",
                (nxt["delivery_id"],),
            )
        connection.commit()
    return {"delivery_id": delivery_id, "state": "acked"}


def redeliver(connection, conversation_key: str) -> dict[str, str]:
    """ACK 丢失时仍用原来的 delivery_id。不新写一行，也不再次推理。"""

    row = connection.execute(
        """
        SELECT * FROM im_outbox
        WHERE conversation_key = ? AND state = 'inflight'
        ORDER BY created_at, delivery_id
        LIMIT 1
        """,
        (conversation_key,),
    ).fetchone()
    if row is None:
        raise ImError("没有待重投的消息", 404)
    return {
        "delivery_id": row["delivery_id"],
        "session_id": row["session_id"],
        "body": row["body"],
        "state": row["state"],
    }


def _session_for(
    connection,
    employee_id: str,
    sender_uid: str,
    external_key: str,
    conversation_key: str,
) -> str:
    if conversation_key:
        thread = connection.execute(
            """
            SELECT session_id FROM im_threads
            WHERE employee_id = ? AND conversation_key = ?
            """,
            (employee_id, conversation_key),
        ).fetchone()
        return thread["session_id"] if thread is not None else ""
    if external_key:
        binding = connection.execute(
            """
            SELECT session_id FROM im_bindings
            WHERE employee_id = ? AND kind = 'external' AND external_key = ?
            """,
            (employee_id, external_key),
        ).fetchone()
        return binding["session_id"] if binding is not None else ""
    private = connection.execute(
        """
        SELECT agentscope_session_id FROM conversations
        WHERE employee_id = ? AND owner_id = ? AND kind = 'private'
        """,
        (employee_id, sender_uid),
    ).fetchone()
    if private is None:
        return ""
    return private["agentscope_session_id"] or ""

"""员工目录与会话绑定。不保存 Agent 记忆。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    description TEXT NOT NULL,
    instructions TEXT NOT NULL,
    avatar TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    knowledge_json TEXT NOT NULL,
    skills_json TEXT NOT NULL,
    tools_json TEXT NOT NULL,
    agentscope_agent_id TEXT,
    mailbox_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    agentscope_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    channel_id TEXT,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    accepted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_members (
    channel_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    agentscope_session_id TEXT,
    PRIMARY KEY (channel_id, employee_id)
);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.executescript(SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
        if "accepted" not in columns:
            connection.execute("ALTER TABLE messages ADD COLUMN accepted INTEGER NOT NULL DEFAULT 0")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _loads(value: str) -> list[Any]:
    data = json.loads(value)
    return data if isinstance(data, list) else []


def employee_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "domain": row["domain"],
        "description": row["description"],
        "instructions": row["instructions"],
        "avatar": row["avatar"],
        "enabled": bool(row["enabled"]),
        "knowledge": _loads(row["knowledge_json"]),
        "skills": _loads(row["skills_json"]),
        "tools": _loads(row["tools_json"]),
        "agentscope_agent_id": row["agentscope_agent_id"],
        "mailbox_session_id": row["mailbox_session_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def message_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sender": row["sender"],
        "text": row["text"],
        "attachments": _loads(row["attachments_json"]),
        "accepted": bool(row["accepted"]),
        "created_at": row["created_at"],
    }

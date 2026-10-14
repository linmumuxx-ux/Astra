"""Nexus HTTP API. Agent 推理只通过 AgentScope HTTP 发生。"""

from __future__ import annotations

import base64
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agentscope import PINNED_VERSION, AgentScopeClient, AgentScopeError
from .db import connect, employee_from_row, init_db, message_from_row, new_id, utcnow
from .task_skill import TASK_SKILL_ID, attach_task_capability, with_builtin_skill

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 6
MAX_TEXT_CHARS = 64_000
STREAM_CURSOR = re.compile(r"^\d+-\d+$")
TEXT_SUFFIXES = {
    ".txt", ".md", ".log", ".py", ".json", ".yaml", ".yml", ".js", ".ts", ".vue",
    ".css", ".html", ".xml", ".csv", ".sh", ".toml", ".ini", ".cfg", ".sql",
}
IMAGE_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
SENDER_CONTACT_LIMIT = 2
SCOPE_CONTACT_LIMIT = 6
UNATTENDED_PERMISSION = "dont_ask"


class EmployeeBody(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    domain: str = Field(min_length=1, max_length=42)
    description: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    avatar: str = "🤖"
    enabled: bool = True
    knowledge: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class ConversationBody(BaseModel):
    name: str = Field(default="新对话", max_length=40)


class MessageBody(BaseModel):
    text: str = ""
    attachment_ids: list[str] = Field(default_factory=list)


class ChannelBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1)
    member_ids: list[str] = Field(min_length=1)


def package_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """数据目录不跟着启动时的工作目录走。

    未设置时用 API 包旁边的 data。相对路径按仓库根目录解析，
    这样从 nexus/api 启动也不会变成 nexus/api/nexus/api/data。
    """
    raw = os.environ.get("NEXUS_DATA_DIR", "").strip()
    if not raw:
        return package_dir() / "data"
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (repo_root() / path).resolve()


def db_path() -> Path:
    return data_dir() / "nexus.sqlite3"


def load_chat_model_config() -> dict[str, Any] | None:
    """部署环境里的 Agent Service 模型引用。页面不编辑这项。"""
    raw = os.environ.get("NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG 不是 JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG 必须是对象")
    required = {"type", "credential_id", "model", "parameters"}
    missing = sorted(required - set(parsed))
    if missing:
        raise RuntimeError("NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG 缺少 " + ", ".join(missing))
    return parsed


def system_prompt(body: EmployeeBody | dict[str, Any]) -> str:
    if isinstance(body, EmployeeBody):
        name, domain, description, instructions = (
            body.name,
            body.domain,
            body.description,
            body.instructions,
        )
    else:
        name = body["name"]
        domain = body["domain"]
        description = body["description"]
        instructions = body["instructions"]
    text = (
        f"你是{name}，责任领域是{domain}。\n"
        f"职责说明：\n{description}\n"
        f"工作指令：\n{instructions}\n"
        "需要其他员工协助时调用 contact_employee，不要代替对方编写答复。"
    )
    skills = body.skills if isinstance(body, EmployeeBody) else list(body.get("skills") or [])
    employee_id = None if isinstance(body, EmployeeBody) else body.get("id")
    if TASK_SKILL_ID in skills and employee_id:
        text += (
            f"\n你的员工编号是 {employee_id}。"
            "需要工程执行时使用任务工具；收到任务状态提示后先查询该任务，再决定下一步。"
        )
    return text


def resolved_media_type(name: str, declared: str) -> str:
    media = (declared or "").split(";", 1)[0].strip().lower()
    if media.startswith("image/") or media.startswith("text/") or media == "application/pdf":
        return media
    return IMAGE_BY_SUFFIX.get(Path(name).suffix.lower(), media or "application/octet-stream")


def readable_text(name: str, media: str, data: bytes) -> str | None:
    suffix = Path(name).suffix.lower()
    if not (media.startswith("text/") or suffix in TEXT_SUFFIXES):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def model_input_blocks(text: str, files: list[tuple[str, str, bytes]]) -> list[dict[str, Any]]:
    """把用户输入变成 AgentScope 的 content。读不到的文件不会被说成已经分析过。"""
    blocks: list[dict[str, Any]] = []
    if text.strip():
        blocks.append({"type": "text", "text": text.strip()})
    for name, declared, data in files:
        media = resolved_media_type(name, declared)
        if media.startswith("image/"):
            blocks.append({"type": "text", "text": f"附件 {name}"})
            blocks.append(
                {
                    "type": "data",
                    "name": name,
                    "source": {
                        "type": "base64",
                        "media_type": media,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )
            continue
        body = readable_text(name, media, data)
        if body is not None:
            omitted = ""
            if len(body) > MAX_TEXT_CHARS:
                body = body[:MAX_TEXT_CHARS]
                omitted = "\n其余内容没有放进这次输入。"
            blocks.append({"type": "text", "text": f"附件 {name}：\n{body}{omitted}"})
            continue
        if media == "application/pdf":
            blocks.append(
                {
                    "type": "text",
                    "text": f"附件 {name} 是 PDF。数据块已附上；如果当前模型不接收 PDF，不要描述文件内容。",
                }
            )
            blocks.append(
                {
                    "type": "data",
                    "name": name,
                    "source": {
                        "type": "base64",
                        "media_type": media,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )
            continue
        blocks.append(
            {
                "type": "text",
                "text": f"附件 {name}（{media}）没有放进模型输入。不要描述它的内容。",
            }
        )
    if not blocks:
        blocks.append({"type": "text", "text": "（空消息）"})
    return blocks


def block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(part for part in parts if part)


def content_strings(content: Any) -> list[str]:
    """取出正文和 hint 里的原文。不经过 json.dumps，因此保留换行。"""
    found: list[str] = []
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return found
    for block in content:
        if isinstance(block, str):
            found.append(block)
            continue
        if not isinstance(block, dict):
            continue
        for field in ("text", "hint"):
            value = block.get(field)
            if isinstance(value, str):
                found.append(value)
            elif isinstance(value, list):
                found.extend(content_strings(value))
    return found


def message_contains(message: dict[str, Any], key: str) -> bool:
    return any(key in text for text in content_strings(message.get("content")))


def assistant_replies_after(messages: list[Any], needle: str) -> list[str]:
    """取邮箱里紧跟在某条提示之后的助手正文。不生成新的答复。

    Agent Service 把收到的 hint 和答复写在同一条 assistant 消息里。
    下一条 assistant 是另一次唤醒，不能算进这一次。
    """
    key = needle.strip()
    if not key:
        return []
    found = False
    replies: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if not found:
            if not message_contains(message, key):
                continue
            found = True
            if message.get("role") == "assistant":
                text = block_text(message.get("content"))
                if text:
                    replies.append(text)
            continue
        if message.get("role") != "assistant" or replies:
            break
        text = block_text(message.get("content"))
        if text:
            replies.append(text)
    return replies


def canonical_timestamp(value: str) -> str:
    """把无时区的本地时间和带偏移的时间收成同一种 UTC 字符串。"""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC).isoformat()


def timestamp_order(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(canonical_timestamp(value)).timestamp()
    except ValueError:
        return 0.0


def assistant_turns(messages: list[Any]) -> list[list[str]]:
    turns: list[list[str]] = []
    current: list[str] | None = None
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "user":
            if current is not None:
                turns.append(current)
            current = []
        elif role == "assistant" and current is not None:
            text = block_text(message.get("content"))
            if text:
                current.append(text)
    if current is not None:
        turns.append(current)
    return turns


def merge_transcript(
    local: list[dict[str, Any]],
    turns: list[list[str]],
    employee_id: str,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index = 0
    for item in local:
        merged.append(item)
        if item.get("accepted") and index < len(turns):
            for text in turns[index]:
                merged.append(
                    {
                        "id": f"agent_{item['id']}_{len(merged)}",
                        "sender": employee_id,
                        "text": text,
                        "attachments": [],
                        "accepted": True,
                        "created_at": item["created_at"],
                    }
                )
            index += 1
    return merged


def assistant_messages(remote: list[Any], employee_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for message in remote:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        text = block_text(message.get("content"))
        if not text:
            continue
        raw_id = message.get("id")
        suffix = raw_id if isinstance(raw_id, str) and raw_id else str(len(found))
        created = message.get("created_at")
        found.append(
            {
                "id": f"agent_{employee_id}_{suffix}",
                "sender": employee_id,
                "text": text,
                "attachments": [],
                "accepted": True,
                "created_at": canonical_timestamp(created) if isinstance(created, str) else "",
            }
        )
    return found


def interleave_messages(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for group in groups:
        combined.extend(group)
    combined.sort(
        key=lambda item: (
            timestamp_order(item.get("created_at")),
            0 if item.get("sender") == "user" else 1,
            str(item.get("id") or ""),
        )
    )
    return combined


def reserve_peer_delivery(
    connection,
    scope: str,
    sender_agent_id: str,
    target_agent_id: str,
    message: str,
) -> None:
    """同一句话只投一次。每位发送方、每场讨论还有很小的次数上限。"""
    key = message.strip()
    duplicate = connection.execute(
        """
        SELECT 1 FROM peer_deliveries
        WHERE scope = ? AND sender_agent_id = ? AND target_agent_id = ? AND message_key = ?
        """,
        (scope, sender_agent_id, target_agent_id, key),
    ).fetchone()
    if duplicate:
        raise HTTPException(status_code=409, detail="已经把同样的话交给对方，不要再联系。")
    sender_count = connection.execute(
        "SELECT COUNT(*) AS count FROM peer_deliveries WHERE scope = ? AND sender_agent_id = ?",
        (scope, sender_agent_id),
    ).fetchone()["count"]
    if sender_count >= SENDER_CONTACT_LIMIT:
        raise HTTPException(status_code=409, detail="你在这次讨论里已经联系过同事，不要继续互相调用。")
    scope_count = connection.execute(
        "SELECT COUNT(*) AS count FROM peer_deliveries WHERE scope = ?",
        (scope,),
    ).fetchone()["count"]
    if scope_count >= SCOPE_CONTACT_LIMIT:
        raise HTTPException(status_code=409, detail="这次讨论的同事联系已经达到上限，停止继续联系。")
    connection.execute(
        """
        INSERT INTO peer_deliveries (
            id, scope, sender_agent_id, target_agent_id, message_key, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (new_id("peer"), scope, sender_agent_id, target_agent_id, key, utcnow()),
    )
    connection.commit()


def inbound_private_scope(connection, agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    row = connection.execute(
        """
        SELECT scope FROM peer_deliveries
        WHERE target_agent_id = ? AND scope LIKE 'private:%'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (agent_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["scope"])


async def hand_off(
    connection,
    client: AgentScopeClient,
    scope: str,
    sender: dict,
    target: dict,
    message: str,
    session_id: str,
):
    reserve_peer_delivery(
        connection,
        scope,
        sender["agentscope_agent_id"],
        target["agentscope_agent_id"],
        message,
    )
    await client.set_permission_mode(
        target["agentscope_agent_id"],
        session_id,
        UNATTENDED_PERMISSION,
    )
    return {
        "agent_id": target["agentscope_agent_id"],
        "session_id": session_id,
        "sender_name": sender["name"],
    }


async def peer_replies_for_conversation(
    connection,
    client: AgentScopeClient,
    conversation_id: str,
) -> list[dict[str, Any]]:
    """把同事在自己邮箱里写下的正文带回用户正在看的私聊。不由发送方代写。"""
    rows = connection.execute(
        "SELECT * FROM peer_deliveries WHERE scope = ? ORDER BY created_at, id",
        (f"private:{conversation_id}",),
    ).fetchall()
    visible: list[dict[str, Any]] = []
    transcripts: dict[str, list[Any]] = {}
    for row in rows:
        employee = connection.execute(
            "SELECT * FROM employees WHERE agentscope_agent_id = ?",
            (row["target_agent_id"],),
        ).fetchone()
        if employee is None or not employee["mailbox_session_id"]:
            continue
        agent_id = row["target_agent_id"]
        if agent_id not in transcripts:
            try:
                transcripts[agent_id] = await client.list_session_messages(
                    agent_id,
                    employee["mailbox_session_id"],
                )
            except AgentScopeError:
                transcripts[agent_id] = []
        for index, text in enumerate(assistant_replies_after(transcripts[agent_id], row["message_key"])):
            visible.append(
                {
                    "id": f"peer_{row['id']}_{index}",
                    "sender": employee["id"],
                    "text": text,
                    "attachments": [],
                    "accepted": True,
                    "created_at": row["created_at"],
                }
            )
    return visible


def session_owned_by(connection, employee_id: str, session_id: str, mailbox_session_id: str | None) -> bool:
    if mailbox_session_id and session_id == mailbox_session_id:
        return True
    conversation = connection.execute(
        """
        SELECT 1 FROM conversations
        WHERE employee_id = ? AND agentscope_session_id = ?
        """,
        (employee_id, session_id),
    ).fetchone()
    if conversation is not None:
        return True
    member = connection.execute(
        """
        SELECT 1 FROM channel_members
        WHERE employee_id = ? AND agentscope_session_id = ?
        """,
        (employee_id, session_id),
    ).fetchone()
    return member is not None


def lines(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = value.strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def require_owner(x_owner_id: str | None = Header(default=None)) -> str:
    if not x_owner_id or not x_owner_id.strip():
        raise HTTPException(status_code=400, detail="缺少 X-Owner-Id")
    return x_owner_id.strip()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        root = data_dir()
        root.mkdir(parents=True, exist_ok=True)
        (root / "files").mkdir(parents=True, exist_ok=True)
        init_db(db_path())
        app.state.agentscope = AgentScopeClient(
            os.environ.get("NEXUS_AGENTSCOPE_BASE_URL") or None,
            os.environ.get("NEXUS_AGENTSCOPE_USER_ID", "nexus"),
            chat_model_config=load_chat_model_config(),
        )
        yield
        await app.state.agentscope.aclose()

    app = FastAPI(title="Nexus", version="1.0.1", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def database():
        connection = connect(db_path())
        try:
            yield connection
        finally:
            connection.close()

    def client_of(request: Request) -> AgentScopeClient:
        return request.app.state.agentscope

    def load_employee(connection, employee_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="员工不存在")
        return employee_from_row(row)

    def find_duplicate(connection, name: str, domain: str, exclude: str | None) -> str | None:
        rows = connection.execute("SELECT id, name, domain FROM employees").fetchall()
        for row in rows:
            if exclude and row["id"] == exclude:
                continue
            if row["name"].lower() == name.lower():
                return "员工名称不可重复"
            if row["domain"].lower() == domain.lower():
                return "该职责已有员工"
        return None

    async def accepted_from_catalog(
        client: AgentScopeClient,
        requested: list[str],
        previous: list[str],
        *,
        load,
        unknown_detail: str,
        unavailable_detail: str,
    ) -> tuple[list[str], dict[str, Any]]:
        requested = lines(requested)
        catalog: list[dict[str, str]] | None = None
        if client.configured:
            try:
                catalog = await load()
            except AgentScopeError:
                catalog = None
        if catalog is not None:
            allowed = {item["id"] for item in catalog}
            unknown = [item for item in requested if item not in allowed]
            if unknown:
                raise HTTPException(status_code=422, detail=unknown_detail)
            return requested, {"available": True, "items": catalog}
        extras = [item for item in requested if item not in set(previous)]
        if extras:
            raise HTTPException(status_code=422, detail=unavailable_detail)
        return requested, {"available": False, "items": []}

    async def accepted_skills(client: AgentScopeClient, requested: list[str], previous: list[str]) -> list[str]:
        requested = lines(requested)
        catalog: list[dict[str, str]] | None = None
        if client.configured:
            try:
                catalog = await client.list_skills()
            except AgentScopeError:
                catalog = None
        if catalog is not None:
            allowed = {item["id"] for item in catalog} | {TASK_SKILL_ID}
            unknown = [item for item in requested if item not in allowed]
            if unknown:
                raise HTTPException(status_code=422, detail="技能不在 AgentScope 技能库中")
            return requested
        extras = [item for item in requested if item not in set(previous) and item != TASK_SKILL_ID]
        if extras:
            raise HTTPException(status_code=422, detail="当前无法读取技能库，不能新增技能")
        return requested

    async def chosen_resources(
        client: AgentScopeClient,
        body: EmployeeBody,
        previous: dict[str, list[str]],
    ) -> tuple[list[str], list[str], list[str]]:
        skills = await accepted_skills(client, body.skills, previous.get("skills", []))
        knowledge, _knowledge = await accepted_from_catalog(
            client,
            body.knowledge,
            previous.get("knowledge", []),
            load=client.list_knowledge_bases,
            unknown_detail="知识库不在 AgentScope 知识库中",
            unavailable_detail="当前无法读取知识库，不能新增知识库",
        )
        tools, _tools = await accepted_from_catalog(
            client,
            body.tools,
            previous.get("tools", []),
            load=client.list_launcher_tools,
            unknown_detail="工具不在 AgentScope 可关联工具中",
            unavailable_detail="当前无法确认 AgentScope 工具，不能新增工具",
        )
        return skills, knowledge, tools

    async def sync_agent(client: AgentScopeClient, employee: dict[str, Any]) -> dict[str, Any]:
        prompt = system_prompt(employee)
        agent_id = employee["agentscope_agent_id"]
        mailbox = employee["mailbox_session_id"]
        try:
            if agent_id:
                await client.update_agent(agent_id, employee["name"], prompt)
            elif client.configured:
                agent_id = await client.create_agent(employee["name"], prompt)
            else:
                raise AgentScopeError("AgentScope 未连接，员工目录已保存，Agent 尚未创建")
            if not mailbox and agent_id:
                mailbox = await client.create_session(agent_id, f"{employee['name']}的邮箱")
            if agent_id and mailbox:
                await client.set_permission_mode(agent_id, mailbox, UNATTENDED_PERMISSION)
                await attach_task_capability(client, employee, mailbox)
            return {"ok": True, "agent_id": agent_id, "mailbox_session_id": mailbox, "detail": ""}
        except AgentScopeError as exc:
            return {"ok": False, "agent_id": agent_id, "mailbox_session_id": mailbox, "detail": exc.detail}

    def save_agent_link(connection, employee_id: str, sync: dict[str, Any]) -> None:
        connection.execute(
            """
            UPDATE employees
            SET agentscope_agent_id = ?, mailbox_session_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (sync["agent_id"], sync["mailbox_session_id"], utcnow(), employee_id),
        )
        connection.commit()

    def insert_employee(
        connection,
        body: EmployeeBody,
        skills: list[str],
        knowledge: list[str],
        tools: list[str],
    ) -> dict[str, Any]:
        employee_id = new_id("emp")
        now = utcnow()
        connection.execute(
            """
            INSERT INTO employees (
                id, name, domain, description, instructions, avatar, enabled,
                knowledge_json, skills_json, tools_json, agentscope_agent_id,
                mailbox_session_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                employee_id,
                body.name.strip(),
                body.domain.strip(),
                body.description.strip(),
                body.instructions.strip(),
                body.avatar,
                int(body.enabled),
                json.dumps(knowledge, ensure_ascii=False),
                json.dumps(skills, ensure_ascii=False),
                json.dumps(tools, ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()
        return load_employee(connection, employee_id)

    def list_messages(connection, *, conversation_id: str | None = None, channel_id: str | None = None):
        if conversation_id:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM messages WHERE channel_id = ? ORDER BY created_at",
                (channel_id,),
            ).fetchall()
        return [message_from_row(row) for row in rows]

    def load_attachments(connection, attachment_ids: list[str]) -> list[dict[str, Any]]:
        if len(attachment_ids) > MAX_ATTACHMENTS:
            raise HTTPException(status_code=400, detail="每条消息最多添加 6 个附件")
        found: list[dict[str, Any]] = []
        for attachment_id in attachment_ids:
            row = connection.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="附件不存在")
            found.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "type": row["media_type"],
                    "size": row["size"],
                    "path": row["path"],
                }
            )
        return found

    def store_user_message(connection, text: str, attachments: list[dict[str, Any]], **scope: str | None):
        if not text.strip() and not attachments:
            raise HTTPException(status_code=400, detail="请输入消息或添加附件")
        message_id = new_id("msg")
        created_at = utcnow()
        visible = [
            {"id": item["id"], "name": item["name"], "type": item["type"], "size": item["size"]}
            for item in attachments
        ]
        connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, channel_id, sender, text, attachments_json, accepted, created_at
            ) VALUES (?, ?, ?, 'user', ?, ?, 0, ?)
            """,
            (
                message_id,
                scope.get("conversation_id"),
                scope.get("channel_id"),
                text.strip(),
                json.dumps(visible, ensure_ascii=False),
                created_at,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return message_from_row(row)

    async def ensure_session(
        connection,
        client: AgentScopeClient,
        agent_id: str,
        current: str | None,
        name: str,
        permission_mode: str | None = None,
    ) -> str:
        session_id = current or await client.create_session(agent_id, name)
        if permission_mode:
            await client.set_permission_mode(agent_id, session_id, permission_mode)
        return session_id

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "product": "nexus", "version": "1.0.1"}

    @app.get("/api/v1/runtime")
    async def runtime(request: Request) -> dict[str, Any]:
        client = client_of(request)
        return {
            "agentscope_version": PINNED_VERSION,
            "configured": client.configured,
            "reachable": await client.probe(),
        }

    async def publish_catalog(client: AgentScopeClient, load) -> dict[str, Any]:
        if not client.configured:
            return {"available": False, "items": []}
        try:
            items = await load()
        except AgentScopeError:
            return {"available": False, "items": []}
        return {"available": True, "items": items}

    @app.get("/api/v1/skills")
    async def skills(request: Request) -> dict[str, Any]:
        client = client_of(request)
        payload = await publish_catalog(client, client.list_skills)
        payload["items"] = with_builtin_skill(payload["items"])
        return payload

    @app.get("/api/v1/internal/wake-target")
    def wake_target(
        employee_id: str,
        session_id: str = "",
        connection=Depends(database),
    ) -> dict[str, str]:
        employee = load_employee(connection, employee_id)
        agent_id = employee["agentscope_agent_id"]
        if not agent_id:
            raise HTTPException(status_code=404, detail="员工还没有 Agent")
        requested = session_id.strip()
        if requested:
            if not session_owned_by(connection, employee_id, requested, employee["mailbox_session_id"]):
                raise HTTPException(status_code=404, detail="会话不属于该员工")
            target = requested
        else:
            target = employee["mailbox_session_id"]
            if not target:
                raise HTTPException(status_code=404, detail="员工还没有邮箱")
        return {"agent_id": agent_id, "session_id": target}

    @app.get("/api/v1/knowledge")
    async def knowledge(request: Request) -> dict[str, Any]:
        client = client_of(request)
        return await publish_catalog(client, client.list_knowledge_bases)

    @app.get("/api/v1/tools")
    async def tools(request: Request) -> dict[str, Any]:
        client = client_of(request)
        return await publish_catalog(client, client.list_launcher_tools)

    @app.get("/api/v1/employees")
    def employees(q: str = "", connection=Depends(database)) -> dict[str, Any]:
        rows = connection.execute("SELECT * FROM employees ORDER BY created_at").fetchall()
        items = [employee_from_row(row) for row in rows]
        needle = q.strip().lower()
        if needle:
            items = [
                item
                for item in items
                if needle in f"{item['name']} {item['domain']} {item['description']}".lower()
            ]
        return {"items": items}

    @app.post("/api/v1/employees", status_code=201)
    async def create_employee(
        body: EmployeeBody,
        request: Request,
        connection=Depends(database),
    ) -> dict[str, Any]:
        conflict = find_duplicate(connection, body.name.strip(), body.domain.strip(), None)
        if conflict:
            raise HTTPException(status_code=409, detail=conflict)
        client = client_of(request)
        skills, knowledge, tools = await chosen_resources(client, body, {})
        employee = insert_employee(connection, body, skills, knowledge, tools)
        sync = await sync_agent(client, employee)
        save_agent_link(connection, employee["id"], sync)
        employee = load_employee(connection, employee["id"])
        return {"employee": employee, "agentscope": {"ok": sync["ok"], "detail": sync["detail"]}}

    @app.patch("/api/v1/employees/{employee_id}")
    async def update_employee(
        employee_id: str,
        body: EmployeeBody,
        request: Request,
        connection=Depends(database),
    ) -> dict[str, Any]:
        current = load_employee(connection, employee_id)
        conflict = find_duplicate(connection, body.name.strip(), body.domain.strip(), employee_id)
        if conflict:
            raise HTTPException(status_code=409, detail=conflict)
        client = client_of(request)
        skills, knowledge, tools = await chosen_resources(client, body, current)
        connection.execute(
            """
            UPDATE employees
            SET name = ?, domain = ?, description = ?, instructions = ?, avatar = ?, enabled = ?,
                knowledge_json = ?, skills_json = ?, tools_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                body.name.strip(),
                body.domain.strip(),
                body.description.strip(),
                body.instructions.strip(),
                body.avatar,
                int(body.enabled),
                json.dumps(knowledge, ensure_ascii=False),
                json.dumps(skills, ensure_ascii=False),
                json.dumps(tools, ensure_ascii=False),
                utcnow(),
                employee_id,
            ),
        )
        connection.commit()
        employee = load_employee(connection, employee_id)
        sync = await sync_agent(client, employee)
        save_agent_link(connection, employee_id, sync)
        return {
            "employee": load_employee(connection, employee_id),
            "agentscope": {"ok": sync["ok"], "detail": sync["detail"]},
        }

    @app.delete("/api/v1/employees/{employee_id}")
    async def delete_employee(
        employee_id: str,
        request: Request,
        connection=Depends(database),
    ) -> dict[str, bool]:
        employee = load_employee(connection, employee_id)
        client = client_of(request)
        if employee["agentscope_agent_id"] and client.configured:
            try:
                await client.delete_agent(employee["agentscope_agent_id"])
            except AgentScopeError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        connection.execute("DELETE FROM channel_members WHERE employee_id = ?", (employee_id,))
        connection.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        connection.commit()
        return {"deleted": True}

    @app.post("/api/v1/attachments", status_code=201)
    async def upload_attachment(file: UploadFile = File(...), connection=Depends(database)) -> dict[str, Any]:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="不能添加空文件")
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=400, detail="单个附件不能超过 20 MB")
        attachment_id = new_id("att")
        target = data_dir() / "files" / attachment_id
        target.write_bytes(content)
        media_type = file.content_type or "application/octet-stream"
        filename = file.filename or "未命名文件"
        connection.execute(
            """
            INSERT INTO attachments (id, name, media_type, size, path, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (attachment_id, filename, media_type, len(content), str(target), utcnow()),
        )
        connection.commit()
        return {"id": attachment_id, "name": filename, "type": media_type, "size": len(content)}

    @app.get("/api/v1/attachments/{attachment_id}")
    def download_attachment(attachment_id: str, connection=Depends(database)) -> FileResponse:
        row = connection.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        if row is None or not Path(row["path"]).is_file():
            raise HTTPException(status_code=404, detail="附件内容不存在")
        disposition = "inline" if str(row["media_type"]).startswith("image/") else "attachment"
        return FileResponse(
            row["path"],
            media_type=row["media_type"],
            filename=row["name"],
            content_disposition_type=disposition,
        )

    @app.get("/api/v1/employees/{employee_id}/conversations")
    def list_conversations(
        employee_id: str,
        owner_id: str = Depends(require_owner),
        connection=Depends(database),
    ):
        load_employee(connection, employee_id)
        rows = connection.execute(
            """
            SELECT * FROM conversations
            WHERE employee_id = ? AND owner_id = ?
            ORDER BY created_at
            """,
            (employee_id, owner_id),
        ).fetchall()
        return {
            "items": [
                {
                    "id": row["id"],
                    "employee_id": row["employee_id"],
                    "name": row["name"],
                    "agentscope_session_id": row["agentscope_session_id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
        }

    @app.post("/api/v1/employees/{employee_id}/conversations", status_code=201)
    def create_conversation(
        employee_id: str,
        body: ConversationBody,
        owner_id: str = Depends(require_owner),
        connection=Depends(database),
    ):
        load_employee(connection, employee_id)
        conversation_id = new_id("conv")
        now = utcnow()
        connection.execute(
            """
            INSERT INTO conversations (
                id, employee_id, owner_id, name, agentscope_session_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (conversation_id, employee_id, owner_id, body.name.strip() or "新对话", now, now),
        )
        connection.commit()
        return {"id": conversation_id, "name": body.name.strip() or "新对话", "agentscope_session_id": None}

    def owned_conversation(connection, conversation_id: str, owner_id: str):
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ? AND owner_id = ?",
            (conversation_id, owner_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="对话不存在")
        return row

    @app.get("/api/v1/conversations/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        request: Request,
        owner_id: str = Depends(require_owner),
        connection=Depends(database),
    ):
        row = owned_conversation(connection, conversation_id, owner_id)
        employee = load_employee(connection, row["employee_id"])
        local = list_messages(connection, conversation_id=conversation_id)
        turns: list[list[str]] = []
        history_error = ""
        if row["agentscope_session_id"] and employee["agentscope_agent_id"]:
            try:
                remote = await client_of(request).list_session_messages(
                    employee["agentscope_agent_id"],
                    row["agentscope_session_id"],
                )
                turns = assistant_turns(remote)
            except AgentScopeError as exc:
                history_error = exc.detail
        return {
            "id": row["id"],
            "employee_id": row["employee_id"],
            "name": row["name"],
            "agentscope_session_id": row["agentscope_session_id"],
            "messages": interleave_messages(
                merge_transcript(local, turns, employee["id"]),
                await peer_replies_for_conversation(connection, client_of(request), conversation_id),
            ),
            "history_error": history_error,
        }

    @app.post("/api/v1/conversations/{conversation_id}/messages")
    async def send_private(
        conversation_id: str,
        body: MessageBody,
        request: Request,
        owner_id: str = Depends(require_owner),
        connection=Depends(database),
    ):
        row = owned_conversation(connection, conversation_id, owner_id)
        employee = load_employee(connection, row["employee_id"])
        if not employee["enabled"]:
            raise HTTPException(status_code=409, detail="该员工已禁用")
        attachments = load_attachments(connection, body.attachment_ids)
        message = store_user_message(
            connection,
            body.text,
            attachments,
            conversation_id=conversation_id,
            channel_id=None,
        )
        if message["text"] and row["name"] == "新对话":
            title = message["text"] if len(message["text"]) <= 20 else message["text"][:20] + "…"
            connection.execute(
                "UPDATE conversations SET name = ?, updated_at = ? WHERE id = ?",
                (title, utcnow(), conversation_id),
            )
            connection.commit()
        elif attachments and row["name"] == "新对话":
            connection.execute(
                "UPDATE conversations SET name = ?, updated_at = ? WHERE id = ?",
                (attachments[0]["name"], utcnow(), conversation_id),
            )
            connection.commit()
        client = client_of(request)
        outcome = {
            "accepted": False,
            "detail": "AgentScope 未连接，没有生成回复",
            "session_id": row["agentscope_session_id"],
        }
        if not employee["agentscope_agent_id"]:
            outcome["detail"] = "AgentScope 尚未创建该员工，没有生成回复"
        else:
            try:
                session_id = await ensure_session(
                    connection,
                    client,
                    employee["agentscope_agent_id"],
                    row["agentscope_session_id"],
                    row["name"],
                )
                connection.execute(
                    "UPDATE conversations SET agentscope_session_id = ?, updated_at = ? WHERE id = ?",
                    (session_id, utcnow(), conversation_id),
                )
                connection.commit()
                await attach_task_capability(
                    client,
                    employee,
                    session_id,
                    conversation_id=conversation_id,
                )
                files: list[tuple[str, str, bytes]] = []
                for item in attachments:
                    files.append((item["name"], item["type"], Path(item["path"]).read_bytes()))
                await client.trigger_chat(
                    employee["agentscope_agent_id"],
                    session_id,
                    model_input_blocks(body.text, files),
                    owner_id,
                )
                connection.execute("UPDATE messages SET accepted = 1 WHERE id = ?", (message["id"],))
                connection.commit()
                message = message_from_row(
                    connection.execute("SELECT * FROM messages WHERE id = ?", (message["id"],)).fetchone()
                )
                outcome = {"accepted": True, "detail": "", "session_id": session_id}
            except AgentScopeError as exc:
                outcome["detail"] = exc.detail
        return {"message": message, "agentscope": outcome}

    @app.get("/api/v1/conversations/{conversation_id}/stream")
    async def stream_private(
        conversation_id: str,
        request: Request,
        owner_id: str = Depends(require_owner),
        connection=Depends(database),
        after: str | None = None,
    ):
        row = owned_conversation(connection, conversation_id, owner_id)
        employee = load_employee(connection, row["employee_id"])
        if not row["agentscope_session_id"] or not employee["agentscope_agent_id"]:
            raise HTTPException(status_code=409, detail="这条对话还没有 AgentScope Session")
        return await proxy_stream(
            client_of(request),
            employee["agentscope_agent_id"],
            row["agentscope_session_id"],
            stream_cursor(after),
        )

    def channel_payload(connection, channel_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="讨论不存在")
        members = connection.execute(
            "SELECT employee_id, agentscope_session_id FROM channel_members WHERE channel_id = ?",
            (channel_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "members": [
                {"employee_id": item["employee_id"], "agentscope_session_id": item["agentscope_session_id"]}
                for item in members
            ],
            "created_at": row["created_at"],
        }

    def ensure_members_exist(connection, member_ids: list[str]) -> list[str]:
        unique: list[str] = []
        for member_id in member_ids:
            if member_id in unique:
                continue
            load_employee(connection, member_id)
            unique.append(member_id)
        if not unique:
            raise HTTPException(status_code=422, detail="至少选择一名员工")
        return unique

    @app.get("/api/v1/channels")
    def list_channels(connection=Depends(database)) -> dict[str, Any]:
        rows = connection.execute("SELECT id FROM channels ORDER BY created_at DESC").fetchall()
        return {"items": [channel_payload(connection, row["id"]) for row in rows]}

    @app.post("/api/v1/channels", status_code=201)
    def create_channel(body: ChannelBody, connection=Depends(database)) -> dict[str, Any]:
        member_ids = ensure_members_exist(connection, body.member_ids)
        channel_id = new_id("ch")
        now = utcnow()
        connection.execute(
            "INSERT INTO channels (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (channel_id, body.name.strip(), body.description.strip(), now, now),
        )
        for member_id in member_ids:
            connection.execute(
                """
                INSERT INTO channel_members (channel_id, employee_id, agentscope_session_id)
                VALUES (?, ?, NULL)
                """,
                (channel_id, member_id),
            )
        connection.commit()
        return channel_payload(connection, channel_id)

    @app.patch("/api/v1/channels/{channel_id}")
    def update_channel(channel_id: str, body: ChannelBody, connection=Depends(database)) -> dict[str, Any]:
        channel_payload(connection, channel_id)
        member_ids = ensure_members_exist(connection, body.member_ids)
        connection.execute(
            "UPDATE channels SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (body.name.strip(), body.description.strip(), utcnow(), channel_id),
        )
        existing = {
            row["employee_id"]: row["agentscope_session_id"]
            for row in connection.execute(
                "SELECT employee_id, agentscope_session_id FROM channel_members WHERE channel_id = ?",
                (channel_id,),
            ).fetchall()
        }
        connection.execute("DELETE FROM channel_members WHERE channel_id = ?", (channel_id,))
        for member_id in member_ids:
            connection.execute(
                """
                INSERT INTO channel_members (channel_id, employee_id, agentscope_session_id)
                VALUES (?, ?, ?)
                """,
                (channel_id, member_id, existing.get(member_id)),
            )
        connection.commit()
        return channel_payload(connection, channel_id)

    @app.get("/api/v1/channels/{channel_id}/messages")
    async def channel_messages(channel_id: str, request: Request, connection=Depends(database)):
        channel = channel_payload(connection, channel_id)
        local = list_messages(connection, channel_id=channel_id)
        replies: list[dict[str, Any]] = []
        errors: list[str] = []
        client = client_of(request)
        if client.configured:
            for member in channel["members"]:
                session_id = member["agentscope_session_id"]
                if not session_id:
                    continue
                employee = load_employee(connection, member["employee_id"])
                if not employee["agentscope_agent_id"]:
                    continue
                try:
                    remote = await client.list_session_messages(employee["agentscope_agent_id"], session_id)
                except AgentScopeError as exc:
                    errors.append(f"{employee['name']}：{exc.detail}")
                    continue
                replies.extend(assistant_messages(remote, employee["id"]))
        channel["messages"] = interleave_messages(local, replies)
        channel["history_error"] = " ".join(errors)
        return channel

    def mentions(text: str, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        remaining = text
        for employee in sorted(members, key=lambda item: len(item["name"]), reverse=True):
            token = f"@{employee['name']}"
            if token in remaining:
                found.append(employee)
                remaining = remaining.replace(token, "")
        return found

    @app.post("/api/v1/channels/{channel_id}/messages")
    async def send_channel(
        channel_id: str,
        body: MessageBody,
        request: Request,
        connection=Depends(database),
    ):
        channel = channel_payload(connection, channel_id)
        attachments = load_attachments(connection, body.attachment_ids)
        message = store_user_message(
            connection,
            body.text,
            attachments,
            conversation_id=None,
            channel_id=channel_id,
        )
        members = [load_employee(connection, item["employee_id"]) for item in channel["members"]]
        named = mentions(body.text, members)
        client = client_of(request)
        files = [(item["name"], item["type"], Path(item["path"]).read_bytes()) for item in attachments]
        content = model_input_blocks(body.text, files)
        triggered: list[dict[str, Any]] = []
        for employee in named:
            result = {
                "employee_id": employee["id"],
                "name": employee["name"],
                "accepted": False,
                "detail": "",
                "session_id": None,
            }
            if not employee["enabled"]:
                result["detail"] = f"{employee['name']} 已禁用，没有触发"
                triggered.append(result)
                continue
            if not employee["agentscope_agent_id"]:
                result["detail"] = "AgentScope 尚未创建该员工，没有生成回复"
                triggered.append(result)
                continue
            binding = next(item for item in channel["members"] if item["employee_id"] == employee["id"])
            try:
                session_id = await ensure_session(
                    connection,
                    client,
                    employee["agentscope_agent_id"],
                    binding["agentscope_session_id"],
                    channel["name"],
                    UNATTENDED_PERMISSION,
                )
                connection.execute(
                    """
                    UPDATE channel_members SET agentscope_session_id = ?
                    WHERE channel_id = ? AND employee_id = ?
                    """,
                    (session_id, channel_id, employee["id"]),
                )
                connection.commit()
                await attach_task_capability(client, employee, session_id, channel_id=channel_id)
                await client.trigger_chat(
                    employee["agentscope_agent_id"],
                    session_id,
                    content,
                    "user",
                )
                result.update(accepted=True, session_id=session_id)
            except AgentScopeError as exc:
                result["detail"] = exc.detail
                result["session_id"] = binding["agentscope_session_id"]
            triggered.append(result)
        if any(item["accepted"] for item in triggered):
            connection.execute("UPDATE messages SET accepted = 1 WHERE id = ?", (message["id"],))
            connection.commit()
            message = message_from_row(
                connection.execute("SELECT * FROM messages WHERE id = ?", (message["id"],)).fetchone()
            )
        employee_messages = connection.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE channel_id = ? AND sender != 'user'",
            (channel_id,),
        ).fetchone()
        if employee_messages["count"]:
            raise HTTPException(status_code=500, detail="团队消息写入了非用户发言")
        return {"message": message, "triggered": triggered}

    @app.get("/api/v1/channels/{channel_id}/members/{employee_id}/stream")
    async def stream_member(
        channel_id: str,
        employee_id: str,
        request: Request,
        connection=Depends(database),
        after: str | None = None,
    ):
        channel = channel_payload(connection, channel_id)
        employee = load_employee(connection, employee_id)
        binding = next((item for item in channel["members"] if item["employee_id"] == employee_id), None)
        if binding is None or not binding["agentscope_session_id"] or not employee["agentscope_agent_id"]:
            raise HTTPException(status_code=409, detail="该成员还没有 AgentScope Session")
        return await proxy_stream(
            client_of(request),
            employee["agentscope_agent_id"],
            binding["agentscope_session_id"],
            stream_cursor(after),
        )

    @app.get("/api/v1/peers/resolve")
    async def resolve_peer(
        session_id: str,
        name: str,
        request: Request,
        connection=Depends(database),
        message: str = "",
    ) -> dict[str, str]:
        target_name = name.strip()
        private = connection.execute(
            "SELECT * FROM conversations WHERE agentscope_session_id = ?",
            (session_id,),
        ).fetchone()
        if private is not None:
            sender = load_employee(connection, private["employee_id"])
            target = employee_by_name(connection, target_name)
            if target is not None and target["id"] != sender["id"] and not target["enabled"]:
                raise HTTPException(status_code=404, detail="该员工已禁用，不能开始新的运行")
            unreachable = (
                target is None
                or target["id"] == sender["id"]
                or not target["agentscope_agent_id"]
                or not target["mailbox_session_id"]
            )
            if unreachable:
                raise HTTPException(status_code=404, detail="没有找到可联系的员工")
            return await hand_off(
                connection,
                client_of(request),
                f"private:{private['id']}",
                sender,
                target,
                message,
                target["mailbox_session_id"],
            )
        member = connection.execute(
            "SELECT * FROM channel_members WHERE agentscope_session_id = ?",
            (session_id,),
        ).fetchone()
        if member is None:
            mailbox_owner = connection.execute(
                "SELECT id FROM employees WHERE mailbox_session_id = ?",
                (session_id,),
            ).fetchone()
            if mailbox_owner is None:
                raise HTTPException(status_code=404, detail="没有找到可联系的员工")
            sender = load_employee(connection, mailbox_owner["id"])
            target = employee_by_name(connection, target_name)
            if target is not None and target["id"] != sender["id"] and not target["enabled"]:
                raise HTTPException(status_code=404, detail="该员工已禁用，不能开始新的运行")
            unreachable = (
                target is None
                or target["id"] == sender["id"]
                or not target["agentscope_agent_id"]
                or not target["mailbox_session_id"]
            )
            if unreachable:
                raise HTTPException(status_code=404, detail="没有找到可联系的员工")
            scope = inbound_private_scope(connection, sender["agentscope_agent_id"])
            if scope is None:
                scope = f"mailbox:{sender['id']}"
            return await hand_off(
                connection,
                client_of(request),
                scope,
                sender,
                target,
                message,
                target["mailbox_session_id"],
            )
        sender = load_employee(connection, member["employee_id"])
        if not sender["agentscope_agent_id"]:
            raise HTTPException(status_code=404, detail="没有找到可联系的员工")
        channel = connection.execute(
            "SELECT name FROM channels WHERE id = ?",
            (member["channel_id"],),
        ).fetchone()
        peers = connection.execute(
            "SELECT * FROM channel_members WHERE channel_id = ?",
            (member["channel_id"],),
        ).fetchall()
        client = client_of(request)
        for peer in peers:
            employee = load_employee(connection, peer["employee_id"])
            if employee["name"] != target_name or employee["id"] == sender["id"]:
                continue
            if not employee["enabled"]:
                raise HTTPException(status_code=404, detail="该员工已禁用，不能开始新的运行")
            if not employee["agentscope_agent_id"]:
                raise HTTPException(status_code=404, detail="没有找到可联系的员工")
            peer_session = peer["agentscope_session_id"]
            if not peer_session:
                if not client.configured:
                    raise HTTPException(status_code=503, detail="AgentScope 未连接，没有生成回复")
                try:
                    peer_session = await client.create_session(
                        employee["agentscope_agent_id"],
                        channel["name"] if channel is not None else employee["name"],
                    )
                except AgentScopeError as exc:
                    raise HTTPException(status_code=503, detail=exc.detail) from exc
                connection.execute(
                    """
                    UPDATE channel_members SET agentscope_session_id = ?
                    WHERE channel_id = ? AND employee_id = ? AND agentscope_session_id IS NULL
                    """,
                    (peer_session, member["channel_id"], employee["id"]),
                )
                connection.commit()
                stored = connection.execute(
                    """
                    SELECT agentscope_session_id FROM channel_members
                    WHERE channel_id = ? AND employee_id = ?
                    """,
                    (member["channel_id"], employee["id"]),
                ).fetchone()
                peer_session = stored["agentscope_session_id"] or peer_session
            await attach_task_capability(
                client,
                employee,
                peer_session,
                channel_id=member["channel_id"],
            )
            return await hand_off(
                connection,
                client,
                member["channel_id"],
                sender,
                employee,
                message,
                peer_session,
            )
        raise HTTPException(status_code=404, detail="没有找到可联系的员工")

    async def proxy_stream(
        client: AgentScopeClient,
        agent_id: str,
        session_id: str,
        after: str | None = None,
    ) -> StreamingResponse:
        if not client.configured:
            raise HTTPException(status_code=503, detail="AgentScope 未连接，没有生成回复")
        if after is None:
            cursor = await client.latest_event_cursor(agent_id, session_id)
            if cursor and STREAM_CURSOR.fullmatch(cursor):
                after = cursor

        async def generate():
            started = 0
            pending = b""
            try:
                async with client.stream_session(agent_id, session_id, after) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")
                        payload = json.dumps(
                            {"type": "NEXUS_UPSTREAM_ERROR", "detail": detail},
                            ensure_ascii=False,
                        )
                        yield f"data: {payload}\n\n"
                        return
                    async for chunk in response.aiter_bytes():
                        pending += chunk
                        frames, pending = split_sse(pending)
                        for frame in frames:
                            yield frame + b"\n\n"
                            started, terminal, close = observe_stream_event(started, sse_payload(frame))
                            if terminal is not None:
                                encoded = json.dumps(terminal, ensure_ascii=False)
                                yield f"data: {encoded}\n\n".encode()
                            if close:
                                return
            except AgentScopeError as exc:
                payload = json.dumps(
                    {"type": "NEXUS_UPSTREAM_ERROR", "detail": exc.detail},
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app


def split_sse(buffer: bytes) -> tuple[list[bytes], bytes]:
    parts = buffer.split(b"\n\n")
    if buffer.endswith(b"\n\n"):
        return parts[:-1], b""
    return parts[:-1], parts[-1]


def sse_payload(frame: bytes) -> dict[str, Any] | None:
    for line in frame.decode("utf-8", "replace").split("\n"):
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def observe_stream_event(
    started: int,
    payload: dict[str, Any] | None,
) -> tuple[int, dict[str, Any] | None, bool]:
    """REPLY_END 是 AgentScope 暴露的一轮结束信号。

    重放日志里可能只剩上一轮的 REPLY_END。只有本连接里见过 REPLY_START 的那一轮结束时，
    才额外发出 NEXUS_RUN_FINISHED 并关掉这次 SSE。
    """
    if not payload:
        return started, None, False
    kind = payload.get("type")
    if kind == "REPLY_START":
        return started + 1, None, False
    if kind == "REPLY_END" and started > 0:
        started -= 1
        terminal = {
            "type": "NEXUS_RUN_FINISHED",
            "reply_id": payload.get("reply_id"),
            "finished_reason": payload.get("finished_reason"),
        }
        return started, terminal, started == 0
    return started, None, False


def stream_cursor(after: str | None) -> str | None:
    """Agent Service 的 after 是 Redis 回放游标，不是 AgentEvent.id。"""
    if after and STREAM_CURSOR.fullmatch(after):
        return after
    return None


def employee_by_name(connection, name: str) -> dict[str, Any] | None:
    rows = connection.execute("SELECT * FROM employees").fetchall()
    for row in rows:
        employee = employee_from_row(row)
        if employee["name"] == name:
            return employee
    return None


app = create_app()

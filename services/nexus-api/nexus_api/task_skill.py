"""内置任务技能。安装失败不能挡住员工保存或发消息。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .agentscope import AgentScopeClient, AgentScopeError

TASK_SKILL_ID = "task-management"
TASK_SKILL_NAME = "任务管理"
logger = logging.getLogger("nexus.task_skill")


def skill_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "agent-service" / "skills" / "task-management"


def with_builtin_skill(items: list[dict[str, str]]) -> list[dict[str, str]]:
    if any(item.get("id") == TASK_SKILL_ID for item in items):
        return items
    return [{"id": TASK_SKILL_ID, "name": TASK_SKILL_NAME}, *items]


def task_mcp_url() -> str:
    return os.environ.get("NEXUS_TASK_MCP_URL", "http://127.0.0.1:8202/mcp")


def task_mcp_headers(
    employee_id: str,
    session_id: str,
    *,
    conversation_id: str = "",
    channel_id: str = "",
) -> dict[str, str]:
    headers = {
        "X-Nexus-Employee-Id": employee_id,
        "X-Nexus-Session-Id": session_id,
        "X-Nexus-Conversation-Id": conversation_id,
        "X-Nexus-Channel-Id": channel_id,
    }
    key = os.environ.get("NEXUS_TASK_MCP_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    else:
        logger.warning("NEXUS_TASK_MCP_KEY 未设置，Task MCP 会拒绝这次挂接")
    return headers


async def attach_task_capability(
    client: AgentScopeClient,
    employee: dict,
    session_id: str,
    *,
    conversation_id: str = "",
    channel_id: str = "",
) -> None:
    if TASK_SKILL_ID not in (employee.get("skills") or []):
        return
    agent_id = employee.get("agentscope_agent_id")
    if not client.configured or not agent_id or not session_id:
        return
    try:
        await client.upload_workspace_skill(agent_id, session_id, skill_directory())
        await client.add_workspace_mcp(
            agent_id,
            session_id,
            url=task_mcp_url(),
            headers=task_mcp_headers(
                employee["id"],
                session_id,
                conversation_id=conversation_id,
                channel_id=channel_id,
            ),
        )
    except AgentScopeError as exc:
        logger.warning("任务技能或 MCP 未挂上：%s", exc.detail)


async def sync_task_capability(client: AgentScopeClient, employee: dict, sessions: list[dict]) -> None:
    """员工保存时安装或收回任务技能。收回要覆盖已有 Session，重新勾选后再装回去。"""

    agent_id = employee.get("agentscope_agent_id")
    if not client.configured or not agent_id:
        return
    usable = [item for item in sessions if (item.get("session_id") or "").strip()]
    if not usable:
        return
    enabled = TASK_SKILL_ID in (employee.get("skills") or [])
    if enabled:
        try:
            await client.upload_workspace_skill(agent_id, usable[0]["session_id"], skill_directory())
        except AgentScopeError as exc:
            logger.warning("任务技能未装上：%s", exc.detail)
        for item in usable:
            try:
                await client.add_workspace_mcp(
                    agent_id,
                    item["session_id"],
                    url=task_mcp_url(),
                    headers=task_mcp_headers(
                        employee["id"],
                        item["session_id"],
                        conversation_id=item.get("conversation_id") or "",
                        channel_id=item.get("channel_id") or "",
                    ),
                )
            except AgentScopeError as exc:
                logger.warning("任务 MCP 未挂上：%s", exc.detail)
        return
    try:
        await client.remove_workspace_skill(agent_id, usable[0]["session_id"], TASK_SKILL_ID)
    except AgentScopeError as exc:
        logger.warning("任务技能未收回：%s", exc.detail)
    for item in usable:
        try:
            await client.remove_workspace_mcp(agent_id, item["session_id"])
        except AgentScopeError as exc:
            logger.warning("任务 MCP 未收回：%s", exc.detail)

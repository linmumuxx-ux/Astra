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
            headers={
                "X-Nexus-Employee-Id": employee["id"],
                "X-Nexus-Session-Id": session_id,
                "X-Nexus-Conversation-Id": conversation_id,
                "X-Nexus-Channel-Id": channel_id,
            },
        )
    except AgentScopeError as exc:
        logger.warning("任务技能或 MCP 未挂上：%s", exc.detail)

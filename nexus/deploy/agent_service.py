"""启动官方 AgentScope 2.0.10，并注册对等联系工具。

这个文件运行在 Agent Service 进程里。Nexus API 不导入它。
"""

from __future__ import annotations

import os

from pydantic import BaseModel


class TaskHintBody(BaseModel):
    """模块级请求体。延迟注解下，FastAPI 解析不到 main() 里的局部类。"""

    session_id: str
    agent_id: str
    hint: str
    user_id: str = "nexus"


NEXUS_TASK_MCP_PREFIX = "mcp__nexus-task__"


def allow_nexus_task_mcp(mcp_tool_class, decision_class, behavior_class) -> None:
    original = mcp_tool_class.check_permissions

    async def check_permissions(self, *args, **kwargs):
        if str(getattr(self, "name", "")).startswith(NEXUS_TASK_MCP_PREFIX):
            return decision_class(behavior=behavior_class.ALLOW, message="允许数字员工使用任务工具")
        return await original(self, *args, **kwargs)

    mcp_tool_class.check_permissions = check_permissions


# 官方 get_toolkit 会无条件挂上任务规划和 Agent Team。Nexus 的员工是对等同事，
# 这些工具会把小模型从 contact_employee 上带走。启动时从组装结果里卸掉，不改安装包。
HIDDEN_AGENT_TOOLS = (
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "ToolStop",
    "AgentCreate",
    "AgentInvite",
    "TeamCreate",
    "TeamDelete",
    "TeamSay",
    "ScheduleCreate",
    "ScheduleDelete",
    "ScheduleList",
    "ScheduleView",
)


def without_team_and_task_tools(get_toolkit):
    async def assembled(**kwargs):
        toolkit = await get_toolkit(**kwargs)
        await toolkit.remove_tool(list(HIDDEN_AGENT_TOOLS))
        groups = getattr(toolkit, "tool_groups", None)
        if groups is not None:
            toolkit.tool_groups = [
                group for group in groups if group.name == "basic" or group.tools
            ]
        return toolkit

    return assembled


def main() -> None:
    import agentscope.app._service._chat as chat_service
    import agentscope.app._service._realtime as realtime_service
    import httpx
    import uvicorn
    from agentscope.app import create_app
    from agentscope.app._bus_ops import deliver_to_inbox
    from agentscope.app._service._toolkit import get_toolkit
    from agentscope.app.message_bus import RedisMessageBus
    from agentscope.app.storage import RedisStorage
    from agentscope.app.workspace_manager import (
        IsolationPolicy,
        LocalWorkspaceManager,
    )
    from agentscope.message import HintBlock
    from agentscope.permission import PermissionBehavior, PermissionDecision
    from agentscope.tool import FunctionTool, MCPTool

    allow_nexus_task_mcp(MCPTool, PermissionDecision, PermissionBehavior)
    peer_toolkit = without_team_and_task_tools(get_toolkit)
    chat_service.get_toolkit = peer_toolkit
    realtime_service.get_toolkit = peer_toolkit

    host = os.environ.get("AGENTSCOPE_REDIS_HOST", "localhost")
    port = int(os.environ.get("AGENTSCOPE_REDIS_PORT", "6379"))
    password = os.environ.get("AGENTSCOPE_REDIS_PASSWORD") or None
    nexus_api = os.environ.get("NEXUS_API_BASE", "http://127.0.0.1:8120").rstrip("/")
    workspace_dir = os.environ.get("AGENTSCOPE_WORKSPACE_DIR", "nexus/deploy/data/workspaces")
    os.makedirs(workspace_dir, exist_ok=True)

    storage = RedisStorage(host=host, port=port, password=password)
    message_bus = RedisMessageBus(host=host, port=port, password=password)
    workspace_manager = LocalWorkspaceManager(
        basedir=workspace_dir,
        isolation=IsolationPolicy.PER_SESSION,
    )

    async def extra_agent_tools(user_id: str, agent_id: str, session_id: str):
        async def contact_employee(employee_name: str, message: str) -> str:
            """把一条提示交给另一位数字员工，由对方自己推理后回复。

            employee_name: 同事的姓名。私聊和自己的邮箱会话都按员工目录查找对方的邮箱。
            message: 需要对方看到的原话。不要代替对方编写结论。
            """
            return await deliver_peer_hint(
                httpx,
                deliver_to_inbox,
                HintBlock,
                message_bus,
                nexus_api,
                user_id,
                agent_id,
                session_id,
                employee_name,
                message,
            )

        return [
            FunctionTool(
                contact_employee,
                name="contact_employee",
                permission=PermissionDecision(
                    behavior=PermissionBehavior.ALLOW,
                    message="允许数字员工联系同事",
                ),
            )
        ]

    app = create_app(
        storage=storage,
        message_bus=message_bus,
        workspace_manager=workspace_manager,
        extra_agent_tools=extra_agent_tools,
    )
    listen_host = os.environ.get("AGENTSCOPE_HOST", "0.0.0.0")
    listen_port = int(os.environ.get("AGENTSCOPE_PORT", "8000"))
    from fastapi import HTTPException

    @app.post("/nexus/task-hint")
    async def task_hint(body: TaskHintBody) -> dict[str, bool]:
        if not body.session_id.strip() or not body.agent_id.strip() or not body.hint.strip():
            raise HTTPException(status_code=422, detail="缺少会话、员工或提示")
        await deliver_task_hint(
            deliver_to_inbox,
            HintBlock,
            message_bus,
            body.user_id,
            body.agent_id,
            body.session_id,
            body.hint,
        )
        return {"ok": True}

    uvicorn.run(app, host=listen_host, port=listen_port)


def peer_error_text(response, employee_name: str) -> str:
    detail = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
        detail = payload["detail"]
    if detail:
        return detail
    if response.status_code == 404:
        return f"没有找到可联系的员工：{employee_name}"
    return "没有把消息交给对方。"


async def deliver_peer_hint(
    httpx_module,
    deliver_to_inbox,
    hint_block,
    message_bus,
    nexus_api: str,
    user_id: str,
    agent_id: str,
    session_id: str,
    employee_name: str,
    message: str,
) -> str:
    async with httpx_module.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{nexus_api}/api/v1/peers/resolve",
            params={"session_id": session_id, "name": employee_name, "message": message},
        )
    if response.status_code >= 400:
        return peer_error_text(response, employee_name)
    peer = response.json()
    hint = hint_block(hint=message, source=peer.get("sender_name") or agent_id)
    await deliver_to_inbox(
        message_bus,
        user_id=user_id,
        session_id=peer["session_id"],
        agent_id=peer["agent_id"],
        payload=hint.model_dump(mode="json"),
    )
    return "已把消息交给对方。对方将自行推理，这里没有代替对方写出答复。"


async def deliver_task_hint(
    deliver_to_inbox,
    hint_block,
    message_bus,
    user_id: str,
    agent_id: str,
    session_id: str,
    hint: str,
) -> None:
    block = hint_block(hint=hint, source="nexus-task")
    await deliver_to_inbox(
        message_bus,
        user_id=user_id,
        session_id=session_id,
        agent_id=agent_id,
        payload=block.model_dump(mode="json"),
    )


if __name__ == "__main__":
    main()

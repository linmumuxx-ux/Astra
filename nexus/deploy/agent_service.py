"""启动官方 AgentScope 2.0.10，并注册对等联系工具。

这个文件运行在 Agent Service 进程里。Nexus API 不导入它。
"""

from __future__ import annotations

import os


def main() -> None:
    import httpx
    import uvicorn
    from agentscope.app import create_app
    from agentscope.app._bus_ops import deliver_to_inbox
    from agentscope.app.message_bus import RedisMessageBus
    from agentscope.app.storage import RedisStorage
    from agentscope.app.workspace_manager import (
        IsolationPolicy,
        LocalWorkspaceManager,
    )
    from agentscope.message import HintBlock
    from agentscope.permission import PermissionBehavior, PermissionDecision
    from agentscope.tool import FunctionTool

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

            employee_name: 同一讨论中的员工名称。私聊时按员工目录查找对方的邮箱会话。
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
    uvicorn.run(app, host=listen_host, port=listen_port)


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
    async with httpx_module.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{nexus_api}/api/v1/peers/resolve",
            params={"session_id": session_id, "name": employee_name},
        )
    if response.status_code == 404:
        detail = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
            detail = payload["detail"]
        return detail or f"没有找到可联系的员工：{employee_name}"
    response.raise_for_status()
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


if __name__ == "__main__":
    main()

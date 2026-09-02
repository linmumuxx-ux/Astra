from app.assistant.tools import task_tools
from mcp.server.mcpserver import MCPServer as Server


def register_task_tools(server: Server, SessionLocal):
    @server.tool(name="nexus_task_search", structured_output=True)
    async def nexus_task_search(task_id: str | None = None, keyword: str | None = None):
        return await task_tools.nexus_task_search({"task_id": task_id, "keyword": keyword})

    @server.tool(name="nexus_task_get", structured_output=True)
    async def nexus_task_get(task_id: str):
        return await task_tools.nexus_task_get({"task_id": task_id})

    @server.tool(name="nexus_task_prepare_create", structured_output=True)
    async def nexus_task_prepare_create(task_type: str, employee_id: str):
        async with SessionLocal() as db_session:
            return await task_tools.nexus_task_prepare_create(
                {"task_type": task_type, "employee_id": employee_id}, "test_user", db_session
            )

    @server.tool(name="nexus_task_cancel", structured_output=True)
    async def nexus_task_cancel(task_id: str):
        async with SessionLocal() as db_session:
            return await task_tools.nexus_task_cancel({"task_id": task_id}, "test_user", db_session)

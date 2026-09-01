from mcp.server.mcpserver import MCPServer as Server
from app.assistant.tools import task_tools

def register_task_tools(server: Server, db_session):
    @server.tool(name="nexus_task_search", )
    async def nexus_task_search(task_id: str | None = None, keyword: str | None = None) :
        return await task_tools.nexus_task_search({"task_id": task_id, "keyword": keyword})

    @server.tool(name="nexus_task_get", )
    async def nexus_task_get(task_id: str) :
        return await task_tools.nexus_task_get({"task_id": task_id})

    @server.tool(name="nexus_task_prepare_create", )
    async def nexus_task_prepare_create(task_type: str, employee_id: str) :
        return await task_tools.nexus_task_prepare_create({"task_type": task_type, "employee_id": employee_id}, "test_user", db_session)

    @server.tool(name="nexus_task_cancel", )
    async def nexus_task_cancel(task_id: str) :
        return await task_tools.nexus_task_cancel({"task_id": task_id}, "test_user", db_session)

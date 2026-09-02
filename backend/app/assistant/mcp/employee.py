from app.assistant.tools import employee_tools
from mcp.server.mcpserver import MCPServer as Server


def register_employee_tools(server: Server, SessionLocal):
    @server.tool(name="nexus_employee_search", structured_output=True)
    async def nexus_employee_search(keyword: str | None = None):
        return await employee_tools.nexus_employee_search({"keyword": keyword})

    @server.tool(name="nexus_employee_recommend", structured_output=True)
    async def nexus_employee_recommend(task_type: str):
        return await employee_tools.nexus_employee_recommend({"task_type": task_type})

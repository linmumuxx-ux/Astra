from mcp.server.mcpserver import MCPServer as Server
from app.assistant.tools import employee_tools

def register_employee_tools(server: Server, db_session):
    @server.tool(name="nexus_employee_search", )
    async def nexus_employee_search(keyword: str | None = None) :
        return await employee_tools.nexus_employee_search({"keyword": keyword})

    @server.tool(name="nexus_employee_recommend", )
    async def nexus_employee_recommend(task_type: str) :
        return await employee_tools.nexus_employee_recommend({"task_type": task_type})

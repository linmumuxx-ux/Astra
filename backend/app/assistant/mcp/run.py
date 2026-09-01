from mcp.server.mcpserver import MCPServer as Server
from app.assistant.tools import run_tools

def register_run_tools(server: Server, db_session):
    @server.tool(name="nexus_run_search", )
    async def nexus_run_search(task_id: str | None = None) :
        return await run_tools.nexus_run_search({"task_id": task_id})

    @server.tool(name="nexus_run_failure_summary", )
    async def nexus_run_failure_summary(run_id: str) :
        return await run_tools.nexus_run_failure_summary({"run_id": run_id})

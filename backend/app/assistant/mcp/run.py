from app.assistant.tools import run_tools
from mcp.server.mcpserver import MCPServer as Server


def register_run_tools(server: Server, SessionLocal):
    @server.tool(name="nexus_run_search", structured_output=True)
    async def nexus_run_search(task_id: str | None = None):
        return await run_tools.nexus_run_search({"task_id": task_id})

    @server.tool(name="nexus_run_failure_summary", structured_output=True)
    async def nexus_run_failure_summary(run_id: str):
        return await run_tools.nexus_run_failure_summary({"run_id": run_id})

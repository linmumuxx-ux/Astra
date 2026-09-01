import asyncio
from mcp.server.mcpserver import MCPServer as Server
from .task import register_task_tools
from .employee import register_employee_tools
from .run import register_run_tools
from .knowledge import register_knowledge_tools
from .operations import register_operation_tools
from mcp.server.stdio import stdio_server

class AssistantMCPServer:
    def __init__(self, db_session=None):
        self.server = Server("nexus-assistant")
        self.db_session = db_session
        self._register_tools()

    def _register_tools(self):
        register_task_tools(self.server, self.db_session)
        register_employee_tools(self.server, self.db_session)
        register_run_tools(self.server, self.db_session)
        register_knowledge_tools(self.server, self.db_session)
        register_operation_tools(self.server, self.db_session)

    async def run(self):
        # Starts the MCP server over stdio
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )

async def start_mcp_server():
    server = AssistantMCPServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(start_mcp_server())

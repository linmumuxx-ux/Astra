from app.assistant.tools import knowledge_tools
from mcp.server.mcpserver import MCPServer as Server


def register_knowledge_tools(server: Server, db_session):
    @server.tool(name="nexus_knowledge_search", )
    async def nexus_knowledge_search(query: str) :
        return await knowledge_tools.nexus_knowledge_search({"query": query})

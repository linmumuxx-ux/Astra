from __future__ import annotations

import hmac
from typing import Any

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from app.config.settings import get_settings
from app.database import SessionLocal
from app.library_schemas import (
    LibraryFeedbackInput,
    LibrarySearchInput,
    LibrarySubmitExperienceInput,
)
from app.library_service import KnowledgeService, LibraryError
from app.llm_wiki import LlmWikiError
from app.runtime.runtime_context import RuntimeContextError


class StaticTokenVerifier:
    """Validate the deployment-provided bearer token without persisting it."""

    def __init__(self, expected_token: str):
        self.expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self.expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="nexus-digital-employee",
            subject="nexus-library-client",
            scopes=["library:read", "library:feedback", "library:submit"],
        )


def build_mcp_server() -> MCPServer:
    settings = get_settings()
    auth = None
    verifier = None
    if settings.mcp_api_key:
        verifier = StaticTokenVerifier(settings.mcp_api_key)
        auth = AuthSettings(
            issuer_url=settings.mcp_issuer_url,
            resource_server_url=settings.mcp_resource_server_url,
            required_scopes=["library:read"],
        )
    server = MCPServer(
        name="NEXUS Digital Library",
        title="NEXUS 数字图书馆",
        version="1.0.0",
        description="统一查询、引用、反馈和提交候选经验的知识服务。",
        instructions=(
            "先使用 library_search 查找正式知识，再用 library_get 将选中的 Markdown 放入任务上下文。"
            "可复用经验只能通过 library_submit_experience 提交为 candidate，不能直接发布。"
        ),
        token_verifier=verifier,
        auth=auth,
    )

    @server.tool(name="library_search", structured_output=True)
    async def library_search(
        runtime_context: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """搜索 Wiki；runtime_context 用于记录本次知识读取所属 Task/Session。"""
        try:
            payload = LibrarySearchInput(query=query, limit=limit)
        except ValidationError as exc:
            raise ToolError(str(exc)) from None
        async with SessionLocal() as session:
            try:
                results = await KnowledgeService(session).mcp_search(
                    payload, runtime_context=runtime_context
                )
            except (LibraryError, LlmWikiError, RuntimeContextError) as exc:
                raise ToolError(str(exc)) from None
        return [result.model_dump(mode="json") for result in results]

    @server.tool(name="library_get", structured_output=True)
    async def library_get(runtime_context: str, resource_id: str) -> dict[str, Any]:
        """读取 Wiki 完整 Markdown，并记录本次读取所属 Task/Session。"""
        async with SessionLocal() as session:
            try:
                result = await KnowledgeService(session).mcp_get(
                    resource_id, runtime_context=runtime_context
                )
            except (LibraryError, LlmWikiError, RuntimeContextError) as exc:
                raise ToolError(str(exc)) from None
        return result.model_dump(mode="json")

    @server.tool(name="library_related", structured_output=True)
    async def library_related(resource_id: str) -> dict[str, Any]:
        """查询相关知识能力状态；当前不支持可靠的按页 Graph 邻居查询。"""
        async with SessionLocal() as session:
            try:
                return await KnowledgeService(session).mcp_related(resource_id)
            except (LibraryError, LlmWikiError) as exc:
                raise ToolError(str(exc)) from None

    @server.tool(name="library_submit_experience", structured_output=True)
    async def library_submit_experience(
        runtime_context: str,
        title: str,
        summary: str,
        content_md: str,
        experience_type: str | None = None,
        scope: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        experience_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """提交可复用经验；来源身份由服务端根据 runtime_context 解析，始终创建候选。"""

        try:
            payload = LibrarySubmitExperienceInput(
                title=title,
                summary=summary,
                content_md=content_md,
                experience_type=experience_type,
                scope=scope or {},
                evidence=evidence or [],
                tags=tags or [],
                experience_data=experience_data or {},
            )
        except ValidationError as exc:
            raise ToolError(str(exc)) from None
        async with SessionLocal() as session:
            try:
                result = await KnowledgeService(session).mcp_submit_experience(
                    payload, runtime_context=runtime_context
                )
            except (LibraryError, RuntimeContextError) as exc:
                raise ToolError(str(exc)) from None
        return result.model_dump(mode="json")

    @server.tool(name="library_feedback", structured_output=True)
    async def library_feedback(
        resource_id: str,
        feedback_type: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """在 Astra 记录 helpful、incorrect、outdated、missing 或 mismatch 反馈。"""
        try:
            payload = LibraryFeedbackInput(
                resource_id=resource_id,
                feedback_type=feedback_type,
                comment=comment,
            )
        except ValidationError as exc:
            raise ToolError(str(exc)) from None
        async with SessionLocal() as session:
            try:
                result = await KnowledgeService(session).mcp_feedback(payload)
            except (LibraryError, LlmWikiError) as exc:
                raise ToolError(str(exc)) from None
        return result.model_dump(mode="json")

    return server


mcp = build_mcp_server()


def main() -> None:
    settings = get_settings()
    try:
        if settings.mcp_transport == "stdio":
            mcp.run(transport="stdio")
            return
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
            streamable_http_path=settings.mcp_streamable_http_path,
            stateless_http=True,
            json_response=True,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

from __future__ import annotations

import hmac
from typing import Any

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from app.config.settings import get_settings
from app.database import SessionLocal
from app.library_schemas import (
    LibraryFeedbackInput,
    LibrarySearchInput,
    LibrarySubmitExperienceInput,
)
from app.library_service import KnowledgeService, LibraryError


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
        query: str,
        space_id: str | None = None,
        types: list[str] | None = None,
        limit: int = 10,
        employee_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """搜索所有可访问的已发布知识；精确错误码、参数名和中文关键词均参与排序。"""

        payload = LibrarySearchInput(
            query=query,
            space_id=space_id,
            types=types or [],
            limit=limit,
            employee_id=employee_id,
            task_id=task_id,
            run_id=run_id,
        )
        async with SessionLocal() as session:
            try:
                results = await KnowledgeService(session).mcp_search(payload)
            except LibraryError as exc:
                raise ValueError(str(exc)) from exc
        return [result.model_dump(mode="json") for result in results]

    @server.tool(name="library_get", structured_output=True)
    async def library_get(
        knowledge_id: str,
        employee_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """读取一条已发布知识的完整元数据和 Markdown，并记为实际引用。"""

        async with SessionLocal() as session:
            try:
                result = await KnowledgeService(session).mcp_get(
                    knowledge_id,
                    employee_id=employee_id,
                    task_id=task_id,
                    run_id=run_id,
                )
            except LibraryError as exc:
                raise ValueError(str(exc)) from exc
        return result.model_dump(mode="json")

    @server.tool(name="library_related", structured_output=True)
    async def library_related(
        knowledge_id: str,
        limit: int = 10,
        employee_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """根据显式关系、标签和知识类型返回相关的已发布知识。"""

        async with SessionLocal() as session:
            try:
                results = await KnowledgeService(session).mcp_related(
                    knowledge_id,
                    limit=limit,
                    employee_id=employee_id,
                    task_id=task_id,
                    run_id=run_id,
                )
            except LibraryError as exc:
                raise ValueError(str(exc)) from exc
        return [result.model_dump(mode="json") for result in results]

    @server.tool(name="library_submit_experience", structured_output=True)
    async def library_submit_experience(
        title: str,
        summary: str,
        content_md: str,
        source_employee_id: str,
        source_task_id: str,
        source_run_id: str,
        evidence: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        experience_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """提交可复用经验；服务端始终创建 type=experience、status=candidate。"""

        payload = LibrarySubmitExperienceInput(
            title=title,
            summary=summary,
            content_md=content_md,
            source_employee_id=source_employee_id,
            source_task_id=source_task_id,
            source_run_id=source_run_id,
            evidence=evidence or [],
            tags=tags or [],
            experience_data=experience_data or {},
        )
        async with SessionLocal() as session:
            try:
                result = await KnowledgeService(session).mcp_submit_experience(payload)
            except LibraryError as exc:
                raise ValueError(str(exc)) from exc
        return result.model_dump(mode="json")

    @server.tool(name="library_feedback", structured_output=True)
    async def library_feedback(
        knowledge_id: str,
        feedback_type: str,
        employee_id: str,
        comment: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """提交有帮助、内容错误、已过期、缺少内容或与执行不符反馈。"""

        payload = LibraryFeedbackInput(
            knowledge_id=knowledge_id,
            feedback_type=feedback_type,
            employee_id=employee_id,
            comment=comment,
            task_id=task_id,
            run_id=run_id,
        )
        async with SessionLocal() as session:
            try:
                result = await KnowledgeService(session).mcp_feedback(payload)
            except LibraryError as exc:
                raise ValueError(str(exc)) from exc
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

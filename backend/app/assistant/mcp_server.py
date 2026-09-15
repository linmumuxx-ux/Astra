"""NEXUS 平台助手 MCP Server。

OpenCode → MCP 调用时使用服务认证；用户身份由 Backend 注入
（``settings.assistant_user_id``），不信任模型自己提供的 user_id。
MCP 不直接访问数据库表，统一调用 Tool Gateway / Domain Service，
避免形成“助手 SQL”和“正常后端服务”两套业务规则。
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

from app.assistant import tool_gateway
from app.assistant.operations import OperationError
from app.config.settings import get_settings
from app.database import SessionLocal
from app.library_schemas import LibrarySubmitExperienceInput
from app.library_service import KnowledgeService, LibraryError


def build_assistant_mcp_server() -> MCPServer:
    settings = get_settings()
    acting_user = settings.assistant_user_id
    server = MCPServer(
        name="NEXUS Assistant Tools",
        title="NEXUS 平台助手工具",
        version="1.1.0",
        description="查询和操作 NEXUS 数字员工平台，并提交经证据约束的 Skill 经验候选。",
        instructions=(
            "查询类工具直接调用；业务变更必须先调用 prepare 工具，"
            "等待平台向用户展示确认卡，禁止重复调用 prepare，也不要自己执行确认。"
            "只有 Skill 明确定义的学习信号出现时，才允许提交经验候选；候选不会直接发布。"
        ),
    )

    async def _run(coro_factory) -> Any:
        async with SessionLocal() as session:
            try:
                return await coro_factory(session)
            except (OperationError, LibraryError) as exc:
                raise ValueError(str(exc)) from exc

    # ── Task Tools ────────────────────────────────────────────

    @server.tool(name="nexus_task_search", structured_output=True)
    async def nexus_task_search(
        task_id: str | None = None,
        keyword: str | None = None,
        employee_id: str | None = None,
        task_type: str | None = None,
        status: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """按任务 ID、关键词、员工、类型和状态搜索平台任务。"""
        return await _run(
            lambda session: tool_gateway.task_search(
                session,
                task_id=task_id,
                keyword=keyword,
                employee_id=employee_id,
                task_type=task_type,
                status=status,
                limit=limit,
            )
        )

    @server.tool(name="nexus_task_get", structured_output=True)
    async def nexus_task_get(task_id: str) -> dict[str, Any]:
        """获取单个任务的完整详情。"""
        return await _run(lambda session: tool_gateway.task_get(session, task_id))

    @server.tool(name="nexus_task_prepare_create", structured_output=True)
    async def nexus_task_prepare_create(
        task_type: str,
        employee_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        category_id: str | None = None,
        acceptance_criteria: list[str] | None = None,
        priority: str | None = None,
    ) -> dict[str, Any]:
        """准备创建任务：校验参数与员工资格并生成预览，等待用户确认后才真正创建。"""
        return await _run(
            lambda session: tool_gateway.task_prepare_create(
                session,
                acting_user_id=acting_user,
                conversation_id=None,
                task_type=task_type,
                employee_id=employee_id,
                title=title,
                description=description,
                category_id=category_id,
                acceptance_criteria=acceptance_criteria,
                priority=priority,
            )
        )

    @server.tool(name="nexus_task_prepare_cancel", structured_output=True)
    async def nexus_task_prepare_cancel(task_id: str, reason: str | None = None) -> dict[str, Any]:
        """准备取消任务：运行中的任务按高风险处理，需用户确认。"""
        return await _run(
            lambda session: tool_gateway.task_prepare_action(
                session,
                acting_user_id=acting_user,
                conversation_id=None,
                action="cancel",
                task_id=task_id,
                reason=reason,
            )
        )

    @server.tool(name="nexus_task_prepare_retry", structured_output=True)
    async def nexus_task_prepare_retry(task_id: str, reason: str | None = None) -> dict[str, Any]:
        """准备重试失败或执行异常的任务，需用户确认。"""
        return await _run(
            lambda session: tool_gateway.task_prepare_action(
                session,
                acting_user_id=acting_user,
                conversation_id=None,
                action="retry",
                task_id=task_id,
                reason=reason,
            )
        )

    @server.tool(name="nexus_task_prepare_resume", structured_output=True)
    async def nexus_task_prepare_resume(task_id: str, reason: str | None = None) -> dict[str, Any]:
        """准备恢复挂起或待人工的任务，需用户确认。"""
        return await _run(
            lambda session: tool_gateway.task_prepare_action(
                session,
                acting_user_id=acting_user,
                conversation_id=None,
                action="resume",
                task_id=task_id,
                reason=reason,
            )
        )

    @server.tool(name="nexus_task_prepare_reassign", structured_output=True)
    async def nexus_task_prepare_reassign(
        task_id: str,
        employee_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """准备把待领取或已挂起任务重新分配给指定员工，需用户确认。"""
        return await _run(
            lambda session: tool_gateway.task_prepare_reassign(
                session,
                acting_user_id=acting_user,
                conversation_id=None,
                task_id=task_id,
                employee_id=employee_id,
                reason=reason,
            )
        )

    # ── Employee Tools ────────────────────────────────────────

    @server.tool(name="nexus_employee_search", structured_output=True)
    async def nexus_employee_search(keyword: str | None = None, limit: int = 20) -> dict[str, Any]:
        """按名字或岗位搜索数字员工。"""
        return await _run(lambda session: tool_gateway.employee_search(session, keyword=keyword, limit=limit))

    @server.tool(name="nexus_employee_get", structured_output=True)
    async def nexus_employee_get(employee_id: str) -> dict[str, Any]:
        """获取单个数字员工的详情、环境和当前任务。"""
        return await _run(lambda session: tool_gateway.employee_get(session, employee_id))

    @server.tool(name="nexus_employee_recommend", structured_output=True)
    async def nexus_employee_recommend(
        task_type: str | None = None,
        category_id: str | None = None,
        only_available: bool = True,
    ) -> dict[str, Any]:
        """由平台规则推荐执行员工并给出推荐原因；不要按名字猜测员工。"""
        return await _run(
            lambda session: tool_gateway.employee_recommend(
                session, task_type=task_type, category_id=category_id, only_available=only_available
            )
        )

    # ── Run Tools ─────────────────────────────────────────────

    @server.tool(name="nexus_run_search", structured_output=True)
    async def nexus_run_search(
        task_id: str | None = None, status: list[str] | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """搜索任务执行记录。"""
        return await _run(
            lambda session: tool_gateway.run_search(session, task_id=task_id, status=status, limit=limit)
        )

    @server.tool(name="nexus_run_get", structured_output=True)
    async def nexus_run_get(run_id: str) -> dict[str, Any]:
        """获取单次执行记录详情。"""
        return await _run(lambda session: tool_gateway.run_get(session, run_id))

    @server.tool(name="nexus_run_failure_summary", structured_output=True)
    async def nexus_run_failure_summary(task_id: str | None = None) -> dict[str, Any]:
        """后端汇总失败现场（执行错误、退出码、当前进展），再交给模型解释。"""
        return await _run(lambda session: tool_gateway.run_failure_summary(session, task_id=task_id))

    # ── Knowledge Tools ───────────────────────────────────────

    @server.tool(name="nexus_knowledge_search", structured_output=True)
    async def nexus_knowledge_search(keyword: str, limit: int = 10) -> dict[str, Any]:
        """搜索数字图书馆已发布知识。"""
        return await _run(
            lambda session: tool_gateway.knowledge_search(session, keyword=keyword, limit=limit)
        )

    @server.tool(name="nexus_knowledge_get", structured_output=True)
    async def nexus_knowledge_get(knowledge_id: str) -> dict[str, Any]:
        """读取一条知识的完整内容；只根据真实返回内容回答。"""
        return await _run(lambda session: tool_gateway.knowledge_get(session, knowledge_id))

    # ── Skill Learning Tool ───────────────────────────────────

    @server.tool(name="nexus_experience_submit", structured_output=True)
    async def nexus_experience_submit(
        skill_name: str,
        title: str,
        summary: str,
        content_md: str,
        source_employee_id: str | None = None,
        source_task_id: str | None = None,
        source_run_id: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        experience_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """提交 Skill 可复用经验候选；服务端统一标记来源 Skill，且永远不会直接发布。"""
        normalized_skill = skill_name.strip().lower()
        if not normalized_skill.startswith("nexus-"):
            raise ValueError("skill_name 必须是 nexus-* Skill")

        normalized_title = title.strip()
        prefix = f"[{normalized_skill}]"
        if not normalized_title.startswith(prefix):
            normalized_title = f"{prefix} {normalized_title}"
        normalized_tags = list(
            dict.fromkeys(["assistant-skill", normalized_skill, *(tags or [])])
        )
        learning_data = {"skill": normalized_skill, **(experience_data or {})}
        try:
            payload = LibrarySubmitExperienceInput(
                title=normalized_title,
                summary=summary,
                content_md=content_md,
                source_employee_id=source_employee_id,
                source_task_id=source_task_id,
                source_run_id=source_run_id,
                evidence=evidence or [],
                tags=normalized_tags,
                experience_data=learning_data,
            )
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

        async def _submit(session):
            result = await KnowledgeService(session).mcp_submit_experience(payload)
            return result.model_dump(mode="json")

        return await _run(_submit)

    # ── Operations Tools ──────────────────────────────────────

    @server.tool(name="nexus_operation_overview", structured_output=True)
    async def nexus_operation_overview() -> dict[str, Any]:
        """平台任务整体统计，由数据库计算，不要让模型自己数。"""
        return await _run(lambda session: tool_gateway.operation_overview(session))

    @server.tool(name="nexus_operation_pending_actions", structured_output=True)
    async def nexus_operation_pending_actions() -> dict[str, Any]:
        """待人工、执行异常、待确认等需要关注的任务数量。"""
        return await _run(lambda session: tool_gateway.operation_pending_actions(session))

    @server.tool(name="nexus_operation_employee_load", structured_output=True)
    async def nexus_operation_employee_load() -> dict[str, Any]:
        """各数字员工当前任务负载。"""
        return await _run(lambda session: tool_gateway.operation_employee_load(session))

    return server


mcp = build_assistant_mcp_server()


def main() -> None:
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

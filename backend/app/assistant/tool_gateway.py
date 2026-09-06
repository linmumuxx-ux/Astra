"""平台 Tool 的业务实现：统一采用平台业务语义，不暴露数据库表和内部
Repository 方法。查询返回真实数据；统计由数据库 / Backend 计算，不先把
大量任务全部发给模型再让模型自己数。

这些函数同时被助手 MCP Server 和后端测试复用。用户身份只能由后端注入
（``acting_user_id``），不接受模型提供的 user_id。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assistant.cards import employee_card, knowledge_card, run_card, task_card
from app.assistant.operations import OperationService
from app.domain import RunStatus, TaskStatus
from app.models import DigitalEmployee, KnowledgeItem, Run, Task

MAX_LIMIT = 50


def _task_summary(task: Task) -> dict[str, Any]:
    employee = task.employee
    return {
        "task_id": task.id,
        "title": task.title,
        "task_type": task.task_type,
        "status": task.status,
        "priority": task.priority,
        "employee_id": task.employee_id,
        "employee_name": employee.name if employee else None,
        "current_progress": task.current_progress,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


async def task_search(
    session: AsyncSession,
    *,
    task_id: str | None = None,
    keyword: str | None = None,
    employee_id: str | None = None,
    task_type: str | None = None,
    status: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    query = select(Task).options(selectinload(Task.employee))
    if task_id:
        query = query.where(Task.id == task_id.strip())
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.where(or_(Task.title.like(like), Task.description.like(like)))
    if employee_id:
        query = query.where(Task.employee_id == employee_id)
    if task_type:
        query = query.where(Task.task_type == str(task_type).upper())
    if status:
        query = query.where(Task.status.in_([str(item).upper() for item in status]))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await session.execute(query.order_by(Task.created_at.desc()).limit(limit))).scalars().all()
    return {"items": [_task_summary(task) for task in rows], "total": int(total)}


async def task_get(session: AsyncSession, task_id: str) -> dict[str, Any]:
    task = await session.scalar(select(Task).options(selectinload(Task.employee)).where(Task.id == task_id))
    if not task:
        raise ValueError(f"任务不存在：{task_id}")
    criteria = [item.get("content") for item in task.acceptance_criteria if item.get("content")]
    detail = {
        **_task_summary(task),
        "description": task.description,
        "acceptance_criteria": criteria,
        "completion_policy": task.completion_policy,
        "failure_reason": task.failure_reason,
        "human_required_reason": task.human_required_reason,
        "card": task_card(task),
    }
    return detail


async def task_prepare_create(
    session: AsyncSession,
    *,
    acting_user_id: str,
    conversation_id: str | None,
    task_type: str,
    employee_id: str | None,
    title: str | None = None,
    description: str | None = None,
    category_id: str | None = None,
    acceptance_criteria: list[str] | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    operation = await OperationService(session).prepare_task_create(
        user_id=acting_user_id,
        task_type=task_type,
        employee_id=employee_id,
        title=title,
        description=description,
        category_id=category_id,
        acceptance_criteria=acceptance_criteria,
        priority=priority,
        conversation_id=conversation_id,
    )
    return {
        "operation_id": operation.operation_id,
        "requires_confirmation": True,
        "risk_level": operation.risk_level,
        "expires_at": operation.expires_at.isoformat() if operation.expires_at else None,
        "preview": operation.preview_json,
    }


async def task_prepare_action(
    session: AsyncSession,
    *,
    acting_user_id: str,
    conversation_id: str | None,
    action: str,
    task_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    operation = await OperationService(session).prepare_task_action(
        user_id=acting_user_id,
        action=action,
        task_id=task_id,
        reason=reason,
        conversation_id=conversation_id,
    )
    return {
        "operation_id": operation.operation_id,
        "requires_confirmation": True,
        "risk_level": operation.risk_level,
        "expires_at": operation.expires_at.isoformat() if operation.expires_at else None,
        "preview": operation.preview_json,
    }


async def task_prepare_reassign(
    session: AsyncSession,
    *,
    acting_user_id: str,
    conversation_id: str | None,
    task_id: str,
    employee_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    operation = await OperationService(session).prepare_task_reassign(
        user_id=acting_user_id,
        task_id=task_id,
        employee_id=employee_id,
        reason=reason,
        conversation_id=conversation_id,
    )
    return {
        "operation_id": operation.operation_id,
        "requires_confirmation": True,
        "risk_level": operation.risk_level,
        "expires_at": operation.expires_at.isoformat() if operation.expires_at else None,
        "preview": operation.preview_json,
    }


def _employee_summary(employee: DigitalEmployee) -> dict[str, Any]:
    return {
        "employee_id": employee.id,
        "name": employee.name,
        "role": employee.role,
        "status": employee.status,
        "task_types": employee.task_types,
        "category_ids": employee.category_ids,
        "enabled": employee.enabled,
        "current_task_count": employee.current_task_count,
    }


async def employee_search(
    session: AsyncSession, *, keyword: str | None = None, limit: int = 20
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    query = select(DigitalEmployee)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.where(or_(DigitalEmployee.name.like(like), DigitalEmployee.role.like(like)))
    rows = (await session.execute(query.order_by(DigitalEmployee.id).limit(limit))).scalars().all()
    return {"items": [_employee_summary(employee) for employee in rows], "total": len(rows)}


async def employee_get(session: AsyncSession, employee_id: str) -> dict[str, Any]:
    employee = await session.scalar(
        select(DigitalEmployee)
        .options(selectinload(DigitalEmployee.execution_environment))
        .where(DigitalEmployee.id == employee_id)
    )
    if not employee:
        raise ValueError(f"数字员工不存在：{employee_id}")
    environment = employee.execution_environment
    active_tasks = (
        (
            await session.execute(
                select(Task)
                .where(
                    Task.employee_id == employee.id,
                    Task.status.in_(
                        [
                            TaskStatus.ASSIGNED,
                            TaskStatus.QUEUED,
                            TaskStatus.RUNNING,
                            TaskStatus.WAIT_HUMAN,
                            TaskStatus.EXECUTION_ERROR,
                        ]
                    ),
                )
                .order_by(Task.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    return {
        **_employee_summary(employee),
        "description": employee.description,
        "environment_status": environment.status if environment else None,
        "environment_mode": environment.mode if environment else None,
        "active_tasks": [_task_summary(task) for task in active_tasks],
        "card": employee_card(employee),
    }


async def employee_recommend(
    session: AsyncSession,
    *,
    task_type: str | None = None,
    category_id: str | None = None,
    only_available: bool = True,
) -> dict[str, Any]:
    """候选员工由平台规则决定，不让模型按名字猜。"""
    query = select(DigitalEmployee).where(DigitalEmployee.enabled.is_(True))
    if only_available:
        query = query.where(DigitalEmployee.status.in_(["IDLE", "WORKING", "WAIT_HUMAN"]))
    rows = (await session.execute(query.order_by(DigitalEmployee.current_task_count))).scalars().all()
    candidates = []
    wanted_type = str(task_type or "").upper() or None
    for employee in rows:
        if wanted_type and wanted_type not in employee.task_types:
            continue
        if category_id and employee.category_ids and category_id not in employee.category_ids:
            continue
        reasons = []
        if employee.status == "IDLE":
            reasons.append("当前空闲")
        elif employee.current_task_count == 0:
            reasons.append("当前没有进行中任务")
        if wanted_type in employee.task_types:
            reasons.append(f"支持任务类型 {wanted_type}")
        if category_id in employee.category_ids:
            reasons.append("支持该任务分类")
        candidates.append({**_employee_summary(employee), "recommend_reasons": reasons})
    candidates.sort(key=lambda item: (item["current_task_count"], item["employee_id"]))
    return {"items": candidates[:10], "total": len(candidates)}


def _run_summary(run: Run) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "task_id": run.task_id,
        "employee_id": run.employee_id,
        "run_number": run.run_number,
        "status": run.status,
        "model_name": run.model_name,
        "exit_code": run.exit_code,
        "worker_id": run.worker_id,
        "executor_status": run.executor_status,
        "failure_type": run.failure_type,
        "total_tokens": run.total_tokens,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


async def run_search(
    session: AsyncSession,
    *,
    task_id: str | None = None,
    status: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    query = select(Run)
    if task_id:
        query = query.where(Run.task_id == task_id)
    if status:
        query = query.where(Run.status.in_([str(item).upper() for item in status]))
    rows = (await session.execute(query.order_by(Run.started_at.desc()).limit(limit))).scalars().all()
    return {"items": [_run_summary(run) for run in rows], "total": len(rows)}


async def run_get(session: AsyncSession, run_id: str) -> dict[str, Any]:
    run = await session.get(Run, run_id)
    if not run:
        raise ValueError(f"运行记录不存在：{run_id}")
    return {**_run_summary(run), "card": run_card(run)}


async def run_failure_summary(session: AsyncSession, *, task_id: str | None = None) -> dict[str, Any]:
    """后端汇总失败现场，再交给模型解释。"""
    query = select(Run).where(
        Run.status.in_(
            [RunStatus.FAILED, RunStatus.TIMEOUT, RunStatus.LOST, RunStatus.BLOCKED]
        )
    )
    if task_id:
        query = query.where(Run.task_id == task_id)
    runs = (await session.execute(query.order_by(Run.started_at.desc()).limit(5))).scalars().all()
    items = []
    for run in runs:
        task = await session.get(Task, run.task_id)
        error = task.execution_error or {}
        items.append(
            {
                **_run_summary(run),
                "executor_type": run.executor_type,
                "task_status": task.status if task else None,
                "execution_error": error.get("reason") or error.get("message") or error.get("error"),
                "failure_reason": task.failure_reason if task else None,
                "current_progress": task.current_progress if task else None,
            }
        )
    return {"items": items, "total": len(items)}


async def knowledge_search(session: AsyncSession, *, keyword: str, limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(int(limit or 10), MAX_LIMIT))
    like = f"%{keyword.strip()}%"
    rows = (
        (
            await session.execute(
                select(KnowledgeItem)
                .where(
                    KnowledgeItem.status == "published",
                    or_(
                        KnowledgeItem.title.like(like),
                        KnowledgeItem.summary.like(like),
                        KnowledgeItem.content_md.like(like),
                    ),
                )
                .order_by(KnowledgeItem.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "knowledge_id": item.id,
            "title": item.title,
            "summary": item.summary,
            "space": item.space_id,
            "tags": item.tags,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "route": "/library",
        }
        for item in rows
    ]
    return {"items": items, "total": len(items)}


async def knowledge_get(session: AsyncSession, knowledge_id: str) -> dict[str, Any]:
    item = await session.get(KnowledgeItem, knowledge_id)
    if not item:
        raise ValueError(f"知识不存在：{knowledge_id}")
    return {
        "knowledge_id": item.id,
        "title": item.title,
        "type": item.type,
        "summary": item.summary,
        "content_md": item.content_md,
        "tags": item.tags,
        "status": item.status,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "card": knowledge_card(item),
    }


async def operation_overview(session: AsyncSession, *, since: datetime | None = None) -> dict[str, Any]:
    query = select(Task.status, func.count(Task.id)).group_by(Task.status)
    if since:
        query = query.where(Task.created_at >= since)
    distribution = dict((await session.execute(query)).all())
    completed = distribution.get(TaskStatus.COMPLETED.value, 0)
    failed = distribution.get(TaskStatus.FAILED.value, 0)
    total = sum(distribution.values())
    return {
        "total_tasks": total,
        "status_distribution": distribution,
        "completed": completed,
        "failed": failed,
        "success_rate": round(completed / total, 3) if total else None,
    }


async def operation_pending_actions(session: AsyncSession) -> dict[str, Any]:
    wait_human = (
        await session.scalar(select(func.count(Task.id)).where(Task.status == TaskStatus.WAIT_HUMAN)) or 0
    )
    execution_error = (
        await session.scalar(select(func.count(Task.id)).where(Task.status == TaskStatus.EXECUTION_ERROR))
        or 0
    )
    pending_confirmation = (
        await session.scalar(
            select(func.count(Task.id)).where(Task.status == TaskStatus.PENDING_CONFIRMATION)
        )
        or 0
    )
    return {
        "wait_human_tasks": int(wait_human),
        "execution_error_tasks": int(execution_error),
        "pending_confirmation_tasks": int(pending_confirmation),
    }


async def operation_employee_load(session: AsyncSession) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(DigitalEmployee).order_by(
                    DigitalEmployee.current_task_count.desc(), DigitalEmployee.id
                )
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "employee_id": employee.id,
            "name": employee.name,
            "status": employee.status,
            "current_task_count": employee.current_task_count,
        }
        for employee in rows
    ]
    return {"items": items, "total": len(items)}

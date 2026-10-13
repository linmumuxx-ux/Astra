from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domains.core import DomainError, now
from domains.governance.models import AuditEvent, Mutation, Operation
from domains.identity.service import Principal, authorize, current_principal, revalidate_principal
from domains.knowledge.models import KnowledgeItem
from domains.organization.models import Employee, Team
from domains.work.models import Task


async def get_required(session, model, object_id):
    obj = await session.get(model, object_id, populate_existing=True)
    if not obj:
        raise DomainError(404, "对象不存在")
    return obj


async def audit(session, principal, team_id, type_, obj, summary, *, channel_id=None):
    await session.flush()
    session.add(
        AuditEvent(
            actor_id=principal.id,
            team_id=team_id,
            channel_id=channel_id,
            type=type_,
            entity_ref=f"{obj.__tablename__}/{obj.id}",
            revision=obj.revision,
            summary=summary,
        )
    )


def serialize(obj):
    hidden = {"digest", "credential_ref", "fingerprint", "dm_key"}
    return {
        column.key: getattr(obj, column.key) for column in obj.__table__.columns if column.key not in hidden
    }


async def mutate(session, principal, key, route, body, handler):
    if not key or not 1 <= len(key) <= 120:
        raise DomainError(400, "写入必须提供 1–120 字符 Idempotency-Key")
    request_hash = hashlib.sha256(
        json.dumps([route, body], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    # 同主体写操作先获得数据库写锁；事务中不调用网络/模型/文件服务。
    fresh = await revalidate_principal(session, principal)
    previous = await session.scalar(
        select(Mutation).where(Mutation.actor_id == principal.id, Mutation.operation_key == key)
    )
    if previous:
        if previous.request_hash != request_hash:
            raise DomainError(409, "同一个幂等键不可用于不同操作")
        await revalidate_replay(session, fresh, route, previous.response)
        return previous.response
    result = await handler(fresh)
    await session.flush()
    response = serialize(result) if hasattr(result, "__table__") else result
    session.add(
        Mutation(actor_id=principal.id, operation_key=key, request_hash=request_hash, response=response)
    )
    await session.commit()
    return response


async def revalidate_replay(session, principal, route, response):
    """幂等响应也受当前权限控制，不能让撤权后的缓存成为数据旁路。"""
    prefix = route.split("/")[0]
    if prefix == "memory":
        from domains.knowledge.memory import memory_access

        await memory_access(session, principal, response["employee_id"], write=True)
        return
    if prefix in {"teams", "workers", "actors", "system-identities", "credentials"}:
        if not principal.admin:
            raise DomainError(403, "原操作的管理权限已经撤销")
        return
    if prefix in {"members", "workspace-grants"}:
        action = "workspace.grant" if prefix == "workspace-grants" else "organization.manage"
        await authorize(session, principal, action, response["team_id"], human_only=True)
        return
    if prefix == "routine-sweep":
        from domains.personas.routines import _authorize_signal

        await _authorize_signal(session, principal, response["team_id"])
        return
    if prefix in {"messages", "dm", "channels"}:
        from domains.messaging.service import channel_access

        channel_id = response["channel_id"] if prefix == "messages" else response["id"]
        channel = await channel_access(session, principal, channel_id)
        await authorize(session, principal, "channel.send", channel.team_id)
        return
    if prefix == "operations":
        operation = await get_required(session, Operation, response["id"])
        action = "operation.prepare" if "/" not in route else "operation.approve"
        await authorize(
            session, principal, action, operation.team_id, human_only=action == "operation.approve"
        )
        return
    if prefix in {"handoff", "accept"}:
        from domains.work.models import Handoff
        from domains.work.service import authorize_handoff

        handoff = await get_required(session, Handoff, response["id"])
        task = await get_required(session, Task, handoff.task_id)
        await authorize_handoff(session, principal, task)
        if prefix == "accept":
            await authorize_handoff(
                session, await current_principal(session, handoff.target_employee_id), task
            )
        return
    permissions = {
        "employees": "organization.manage",
        "roles": "organization.manage",
        "goals": "organization.manage",
        "knowledge": "knowledge.manage",
        "source-events": "event.ingest",
        "tasks": "task.create",
        "routines": "routine.manage",
    }
    action = permissions.get(prefix)
    if not action:
        raise DomainError(403, "无法确认原操作的当前授权")
    project = None
    team_id = response.get("team_id")
    if prefix == "routines":
        from domains.personas.models import Routine
        from domains.personas.routines import validate_routine_change

        routine = await get_required(session, Routine, response.get("routine_id") or response["id"])
        team_id = (await validate_routine_change(session, principal, routine)).team_id
    if prefix == "tasks":
        if route.endswith("/dispatch"):
            task_id = response["execution"]["task_id"]
        elif route.endswith("/review"):
            task_id = response["task_id"]
        else:
            task_id = response["id"]
        task = await get_required(session, Task, task_id)
        if route.endswith("/review"):
            from domains.work.review import review_authority

            await review_authority(session, principal, task)
        team_id = task.team_id
        project = task.asset_scope.get("project_id")
        if "/" in route:
            action = f"task.{route.split('/')[-1]}"
    await authorize(
        session,
        principal,
        action,
        team_id,
        project_id=project,
        human_only=prefix in {"employees", "roles", "goals"},
    )


async def cas(session, obj, values):
    result = await session.execute(
        update(type(obj))
        .where(type(obj).id == obj.id, type(obj).revision == obj.revision)
        .values(**values, revision=obj.revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise DomainError(409, "对象已被其他操作修改，请刷新后重试")
    await session.refresh(obj)
    return obj


TARGETS = {"task": Task, "employee": Employee, "knowledge": KnowledgeItem}


async def prepare(session, principal, data):
    await authorize(session, principal, "operation.prepare", data.team_id)
    target = await get_required(session, TARGETS[data.action.split(".")[0]], data.target_id)
    if target.team_id != data.team_id:
        raise DomainError(403, "审批目标不在授权团队")
    await authorize(
        session,
        principal,
        data.action,
        data.team_id,
        project_id=target.asset_scope.get("project_id") if isinstance(target, Task) else None,
    )
    if data.payload:
        raise DomainError(400, "当前具体操作不接受额外副作用参数")
    team = await session.get(Team, data.team_id)
    operation = Operation(
        initiator_id=principal.id,
        team_id=data.team_id,
        action=data.action,
        target_id=target.id,
        target_revision=target.revision,
        policy_revision=team.revision,
        payload=data.payload,
        expires_at=now() + data.expires_in,
    )
    session.add(operation)
    await audit(session, principal, data.team_id, "operation.prepared", operation, "具体操作等待人工决定")
    return operation


async def decide_operation(
    session: AsyncSession, principal: Principal, operation_id: str, decision: str, reason: str = ""
):
    operation = await get_required(session, Operation, operation_id)
    await authorize(session, principal, "operation.approve", operation.team_id, human_only=True)
    if operation.status != "WAIT_HUMAN":
        raise DomainError(409, "该审批已有决定，请读取权威结果")
    if operation.expires_at <= now():
        await cas(session, operation, {"status": "EXPIRED"})
        await audit(session, principal, operation.team_id, "operation.expired", operation, "审批已过期")
        return operation
    if decision == "reject":
        await cas(
            session, operation, {"status": "REJECTED", "decided_by": principal.id, "decision_note": reason}
        )
        await audit(
            session, principal, operation.team_id, "operation.rejected", operation, "人工拒绝具体操作"
        )
        return operation
    team = await session.get(Team, operation.team_id, populate_existing=True)
    target = await get_required(session, TARGETS[operation.action.split(".")[0]], operation.target_id)
    if team.revision != operation.policy_revision or target.revision != operation.target_revision:
        raise DomainError(409, "目标或组织政策已经变化，需重新准备审批")
    initiator = await current_principal(session, operation.initiator_id)
    await authorize(
        session,
        initiator,
        operation.action,
        team.id,
        project_id=target.asset_scope.get("project_id") if isinstance(target, Task) else None,
    )
    if operation.action.startswith("task."):
        from domains.work.service import transition_task

        await transition_task(session, principal, target, operation.action.split(".")[1])
    elif operation.action == "employee.pause":
        from domains.organization.service import transition_employee

        await transition_employee(session, principal, target, "pause")
    elif operation.action == "knowledge.publish":
        if target.verification != "VERIFIED" or not target.source_refs:
            raise DomainError(409, "知识尚未通过来源证据验证")
        if target.kind == "SKILL":
            raise DomainError(409, "Skill 需按版本及验证任务独立发布")
        await cas(session, target, {"status": "PUBLISHED"})
    await cas(
        session,
        operation,
        {
            "status": "EXECUTED",
            "decision_note": reason,
            "decided_by": principal.id,
            "result": {"target_id": target.id, "revision": target.revision},
        },
    )
    await audit(
        session, principal, operation.team_id, "operation.executed", operation, "人工批准的具体操作已执行"
    )
    return operation

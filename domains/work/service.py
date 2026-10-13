from sqlalchemy import select

from domains.core import DomainError, new_id, now
from domains.governance.service import audit, cas, get_required
from domains.identity.service import authorize, current_principal
from domains.organization.models import Employee, Goal
from domains.organization.service import lock_active_employee
from domains.personas.models import SourceEvent
from domains.personas.service import admit
from domains.work.models import Handoff, Task, TaskExecution


async def create_task(session, principal, data):
    project_id = data.asset_scope.get("project_id")
    await authorize(session, principal, "task.create", data.team_id, project_id=project_id)
    employee = await lock_active_employee(session, data.owner_employee_id)
    if employee.team_id != data.team_id or employee.lifecycle != "ACTIVE":
        raise DomainError(409, "业务主责须为同团队的有效员工")
    if principal.kind == "EMPLOYEE" and employee.id != principal.id:
        raise DomainError(403, "跨岗位委派须经正式交接")
    if data.goal_id:
        goal = await get_required(session, Goal, data.goal_id)
        if goal.team_id != data.team_id:
            raise DomainError(403, "目标不在当前团队")
    task = Task(**data.model_dump(), created_by_actor=principal.id, continuity_key=new_id())
    session.add(task)
    await audit(session, principal, data.team_id, "task.created", task, "业务任务已创建")
    return task


async def transition_task(session, principal, task, action):
    await authorize(
        session, principal, f"task.{action}", task.team_id, project_id=task.asset_scope.get("project_id")
    )
    if task.read_only or task.status in {"COMPLETED", "CANCELLED"}:
        raise DomainError(409, "只读历史或终态任务不可更改")
    if action in {"pause", "cancel"}:
        execution = await session.scalar(
            select(TaskExecution).where(
                TaskExecution.task_id == task.id,
                TaskExecution.superseded_by.is_(None),
                TaskExecution.state.in_(["BOUND", "RUNNING"]),
            )
        )
        if execution:
            # 原生 abort 尚未回执时，业务不能把未知副作用标成已取消。
            status = "RECONCILE_REQUIRED"
            await cas(session, execution, {"stop_requested": action.upper()})
        else:
            status = "PAUSED" if action == "pause" else "CANCELLED"
    elif action == "resume":
        if task.status != "PAUSED":
            raise DomainError(409, "仅可恢复已暂停且无未知执行的任务")
        status = "QUEUED"
    else:
        raise DomainError(400, "未知任务动作")
    await cas(session, task, {"status": status})
    await audit(session, principal, task.team_id, f"task.{action}", task, "任务业务状态已更新")
    return task


async def propose_handoff(session, principal, task_id, data):
    task = await get_required(session, Task, task_id)
    await authorize_handoff(session, principal, task)
    if task.read_only or not task.owner_employee_id or task.status in {"COMPLETED", "CANCELLED"}:
        raise DomainError(409, "此任务不可交接")
    if principal.kind == "EMPLOYEE" and principal.id != task.owner_employee_id:
        raise DomainError(403, "仅主责员工能提出交接")
    target = await lock_active_employee(session, data.target_employee_id)
    if target.id == task.owner_employee_id or target.team_id != task.team_id or target.lifecycle != "ACTIVE":
        raise DomainError(409, "交接须指定同团队另一位有效员工")
    pending = await session.scalar(
        select(Handoff.id).where(
            Handoff.task_id == task.id, Handoff.status.in_(["PROPOSED", "NEEDS_CLARIFICATION"])
        )
    )
    if pending:
        raise DomainError(409, "已有待签收交接")
    # 提案也锁定任务版本，防止不同主体同时提出两个有效交接。
    await cas(session, task, {})
    handoff = Handoff(
        task_id=task.id,
        source_employee_id=task.owner_employee_id,
        target_employee_id=target.id,
        task_revision=task.revision,
        reason=data.reason,
    )
    session.add(handoff)
    await audit(session, principal, task.team_id, "handoff.proposed", handoff, "正式交接等待签收")
    await handoff_event(session, principal, task, handoff, "proposed", data.reason)
    return handoff


async def accept_handoff(session, principal, handoff_id):
    handoff = await get_required(session, Handoff, handoff_id)
    task = await get_required(session, Task, handoff.task_id)
    target = await get_required(session, Employee, handoff.target_employee_id)
    await authorize_handoff(session, principal, task)
    if principal.id != target.id and principal.id != target.manager_id:
        raise DomainError(403, "仅接收员工或其授权负责人可以签收")
    target = await lock_active_employee(session, target.id)
    await authorize_handoff(session, await current_principal(session, target.id), task)
    if (
        handoff.status != "PROPOSED"
        or task.revision != handoff.task_revision
        or target.lifecycle != "ACTIVE"
        or task.owner_employee_id != handoff.source_employee_id
    ):
        raise DomainError(409, "交接或任务责任已经变化，需重新确认")
    await cas(session, task, {"owner_employee_id": target.id})
    await cas(session, handoff, {"status": "ACCEPTED"})
    await audit(session, principal, task.team_id, "handoff.accepted", handoff, "签收后业务主责已转移")
    await handoff_event(session, principal, task, handoff, "accepted", "已签收业务主责")
    return handoff


async def authorize_handoff(session, principal, task):
    await authorize(
        session, principal, "task.handoff", task.team_id, project_id=task.asset_scope.get("project_id")
    )


async def respond_handoff(session, principal, handoff_id, action, reason):
    handoff = await get_required(session, Handoff, handoff_id)
    task = await get_required(session, Task, handoff.task_id)
    await authorize_handoff(session, principal, task)
    source = await get_required(session, Employee, handoff.source_employee_id)
    target = await get_required(session, Employee, handoff.target_employee_id)
    if handoff.status not in {"PROPOSED", "NEEDS_CLARIFICATION"}:
        raise DomainError(409, "交接已结束，不能重复处理")
    if action in {"reject", "request-clarification"}:
        allowed = {target.id, target.manager_id}
        status = "REJECTED" if action == "reject" else "NEEDS_CLARIFICATION"
    elif action in {"withdraw", "clarify"}:
        allowed = {source.id, source.manager_id}
        status = "WITHDRAWN" if action == "withdraw" else "PROPOSED"
        if action == "clarify":
            if handoff.status != "NEEDS_CLARIFICATION" or task.owner_employee_id != source.id:
                raise DomainError(409, "交接不在可澄清状态或原主责已变化")
            if task.read_only or task.status in {"COMPLETED", "CANCELLED"}:
                raise DomainError(409, "已结束工作不可重新交接")
            await cas(session, task, {})
    else:
        raise DomainError(404, "未知交接处理动作")
    if principal.id not in allowed:
        raise DomainError(403, "只有交接当事员工或其负责人可以处理此动作")
    values = {"status": status}
    if action == "clarify":
        values["task_revision"] = task.revision
    await cas(session, handoff, values)
    await handoff_event(session, principal, task, handoff, action, reason)
    await audit(session, principal, task.team_id, f"handoff.{action}", handoff, "交接处理已记录，主责未转移")
    return handoff


async def handoff_event(session, principal, task, handoff, action, reason):
    event = SourceEvent(
        source="handoff",
        source_id=handoff.id,
        revision=handoff.revision,
        actor_id=principal.id,
        team_id=task.team_id,
        object_ref=f"handoffs/{handoff.id}",
        causal_root=task.continuity_key,
        payload_ref={"task_id": task.id, "action": action, "reason": reason},
        occurred_at=now(),
    )
    session.add(event)
    await session.flush()
    for employee_id in {handoff.source_employee_id, handoff.target_employee_id}:
        await admit(session, event, employee_id, reason="正式交接变化")
    from domains.personas.routines import admit_event_routines

    await admit_event_routines(session, event)


async def task_event(session, principal, task, execution, action):
    """原生结果/业务验收变化只投递引用，不复制工程输出到长期对话。"""
    event = SourceEvent(
        source="task",
        source_id=execution.id,
        revision=execution.revision,
        actor_id=principal.id,
        team_id=task.team_id,
        object_ref=f"tasks/{task.id}",
        causal_root=task.continuity_key,
        payload_ref={"task_id": task.id, "execution_id": execution.id, "action": action},
        occurred_at=now(),
    )
    session.add(event)
    await session.flush()
    await admit(session, event, task.owner_employee_id, reason="任务执行或验收结果")
    from domains.personas.routines import admit_event_routines

    await admit_event_routines(session, event)

from sqlalchemy import select, update

from domains.core import DomainError, now
from domains.governance.service import audit, get_required
from domains.identity.service import authorize
from domains.organization.models import Employee
from domains.personas.models import EmployeeState, EmployeeTurn, InboxAdmission, SourceEvent


async def admit(session, event, employee_id, *, reason="业务事件", wake_policy="IMMEDIATE"):
    employee = await get_required(session, Employee, employee_id)
    if employee.team_id != event.team_id:
        raise DomainError(403, "事件不能投递到其他团队员工")
    previous = await session.scalar(
        select(InboxAdmission).where(
            InboxAdmission.employee_id == employee_id, InboxAdmission.source_event_id == event.id
        )
    )
    if previous:
        return previous
    admission = InboxAdmission(
        employee_id=employee_id, source_event_id=event.id, reason=reason, wake_policy=wake_policy
    )
    session.add(admission)
    return admission


async def ingest(session, principal, data):
    await authorize(session, principal, "event.ingest", data.team_id)
    if data.source in {"channel", "routine", "task", "approval", "handoff"}:
        raise DomainError(400, "保留事件来源只能由对应领域服务生成")
    old = await session.scalar(
        select(SourceEvent).where(
            SourceEvent.source == data.source,
            SourceEvent.source_id == data.source_id,
            SourceEvent.revision == data.revision,
        )
    )
    if old:
        fields = ["team_id", "object_ref", "payload_ref", "causal_root"]
        if old.actor_id != principal.id or any(
            getattr(old, field) != getattr(data, field) for field in fields
        ):
            raise DomainError(409, "相同事件版本不得覆盖原有来源事实")
        return old
    event = SourceEvent(**data.model_dump(exclude={"recipients"}), actor_id=principal.id, occurred_at=now())
    session.add(event)
    await session.flush()
    for employee_id in set(data.recipients):
        await admit(session, event, employee_id)
    from domains.personas.routines import admit_event_routines

    await admit_event_routines(session, event)
    await audit(session, principal, data.team_id, "source_event.received", event, "来源事件已接收")
    return event


async def acquire_turn(session, employee_id, *, lease_seconds=120):
    await get_required(session, Employee, employee_id)
    from domains.organization.service import lock_active_employee

    await lock_active_employee(session, employee_id)
    state = await session.scalar(select(EmployeeState).where(EmployeeState.employee_id == employee_id))
    if not state:
        raise DomainError(409, "员工长期工作状态缺失")
    old_fence = state.fence
    changed = await session.execute(
        update(EmployeeState)
        .where(
            EmployeeState.id == state.id, EmployeeState.fence == old_fence, EmployeeState.lease_until <= now()
        )
        .values(fence=old_fence + 1, lease_until=now() + lease_seconds)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise DomainError(409, "员工已有有效 Persona Turn")
    await session.execute(
        update(EmployeeTurn)
        .where(EmployeeTurn.employee_id == employee_id, EmployeeTurn.status == "RUNNING")
        .values(status="SUPERSEDED")
    )
    turn = EmployeeTurn(employee_id=employee_id, fence=old_fence + 1)
    session.add(turn)
    await session.flush()
    return turn


async def finish_turn(session, turn_id, actions):
    turn = await get_required(session, EmployeeTurn, turn_id)
    await get_required(session, Employee, turn.employee_id)
    state = await session.scalar(select(EmployeeState).where(EmployeeState.employee_id == turn.employee_id))
    from domains.organization.service import lock_active_employee

    await lock_active_employee(session, turn.employee_id)
    if turn.status != "RUNNING":
        raise DomainError(409, "员工回合已停止或失效")
    allowed = {"reply", "no_action", "remember", "dispatch", "follow_up", "ask_human", "handoff"}
    if any(action.get("type") not in allowed for action in actions):
        raise DomainError(400, "未知 Persona 决策类型")
    changed = await session.execute(
        update(EmployeeState)
        .where(
            EmployeeState.id == state.id, EmployeeState.fence == turn.fence, EmployeeState.lease_until > now()
        )
        .values(lease_until=0, revision=EmployeeState.revision + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise DomainError(409, "过期 Persona Turn 不可提交")
    turn.actions, turn.status, turn.finished_at = actions, "FINISHED", now()
    return turn

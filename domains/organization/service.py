from sqlalchemy import or_, select, update

from domains.core import DomainError, new_id
from domains.governance.models import Operation
from domains.governance.service import audit, cas, get_required
from domains.identity.models import Actor
from domains.identity.service import authorize
from domains.organization.models import Employee, Goal, Role, TeamMember
from domains.personas.models import EmployeeState
from domains.work.models import Handoff, Task


async def create_employee(session, principal, data):
    await authorize(session, principal, "organization.manage", data.team_id, human_only=True)
    role = await get_required(session, Role, data.role_id)
    if role.team_id != data.team_id or not set(data.permissions) <= set(role.permissions):
        raise DomainError(403, "员工授权不能超出岗位最大权限")
    actor_id = new_id()
    session.add(Actor(id=actor_id, kind="EMPLOYEE", name=data.name, permissions=data.permissions))
    await session.flush()
    employee = Employee(
        id=actor_id,
        name=data.name,
        team_id=data.team_id,
        role_id=role.id,
        manager_id=principal.id,
        scope=data.scope,
        permissions=data.permissions,
        daily_token_budget=data.daily_token_budget,
    )
    session.add(employee)
    session.add(TeamMember(team_id=data.team_id, actor_id=actor_id))
    await session.flush()
    session.add(EmployeeState(employee_id=actor_id))
    await audit(session, principal, data.team_id, "employee.created", employee, "独立员工身份已创建")
    return employee


async def transition_employee(session, principal, employee, action):
    await authorize(session, principal, "organization.manage", employee.team_id, human_only=True)
    await session.execute(
        update(Employee)
        .where(Employee.id == employee.id)
        .values(revision=Employee.revision)
        .execution_options(synchronize_session=False)
    )
    await session.refresh(employee)
    if employee.lifecycle == "ARCHIVED":
        raise DomainError(409, "归档员工不可重新激活或复用身份")
    if action == "archive":
        tasks = await session.scalar(
            select(Task.id)
            .where(Task.owner_employee_id == employee.id, Task.status.not_in(["COMPLETED", "CANCELLED"]))
            .limit(1)
        )
        goals = await session.scalar(
            select(Goal.id).where(Goal.owner_employee_id == employee.id, Goal.status == "ACTIVE").limit(1)
        )
        operations = await session.scalar(
            select(Operation.id)
            .where(Operation.initiator_id == employee.id, Operation.status == "WAIT_HUMAN")
            .limit(1)
        )
        handoffs = await session.scalar(
            select(Handoff.id)
            .where(
                Handoff.status.in_(["PROPOSED", "NEEDS_CLARIFICATION"]),
                or_(Handoff.source_employee_id == employee.id, Handoff.target_employee_id == employee.id),
            )
            .limit(1)
        )
        if tasks or goals or operations or handoffs:
            raise DomainError(409, "有未结束 Task/Goal/审批/交接，须先明确交接或处理")
    lifecycle = {"pause": "PAUSED", "resume": "ACTIVE", "archive": "ARCHIVED"}[action]
    await cas(session, employee, {"lifecycle": lifecycle})
    # 暂停不撤销只读历史身份；新的自主操作由 authorize 中的 lifecycle 阻止。
    await audit(session, principal, employee.team_id, f"employee.{action}", employee, "员工履职状态已变更")
    return employee


async def lock_active_employee(session, employee_id):
    """授权生命周期的条件写锁：读后暂停/归档不能与新委派/决策/签收交错。"""
    changed = await session.execute(
        update(Employee)
        .where(Employee.id == employee_id, Employee.lifecycle == "ACTIVE")
        .values(revision=Employee.revision)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise DomainError(409, "停用员工不可被唤醒、委派或签收")
    return await get_required(session, Employee, employee_id)

"""持续职责的计划与投递；仅写业务 Inbox，不执行模型或创建 Task。"""

import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery.schedules import crontab
from sqlalchemy import select

from domains.core import DomainError, new_id, now
from domains.governance.service import audit, cas, get_required
from domains.identity.service import authorize
from domains.messaging.models import ChannelMember
from domains.organization.models import Employee, Goal
from domains.organization.service import lock_active_employee
from domains.personas.models import Routine, SourceEvent
from domains.personas.service import admit


def next_due_after(kind, schedule, timezone, at):
    try:
        zone = ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise DomainError(422, "无效 Routine 时区") from exc
    if kind == "EVENT":
        if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,79}", schedule):
            raise DomainError(422, "EVENT 规则必须为明确事件来源名")
        return None
    if kind == "INTERVAL":
        if not re.fullmatch(r"[1-9][0-9]{0,7}", schedule):
            raise DomainError(422, "INTERVAL 规则须为正整数秒数")
        return at + int(schedule)
    if kind != "CRON" or len(schedule.split()) != 5:
        raise DomainError(422, "CRON 规则须为分钟、小时、日、月、星期五个字段")
    minute, hour, day, month, weekday = schedule.split()
    try:
        cron = crontab(minute, hour, weekday, day, month)
    except (ValueError, TypeError, KeyError) as exc:
        raise DomainError(422, "无效 CRON 规则") from exc
    local = datetime.fromtimestamp(at, UTC).astimezone(zone)
    # 复用 Celery 的字段解析与 AND 日期语义；按本地日期查找，显式排除 DST 不存在时刻。
    for offset in range(366 * 8):
        date = local.date() + timedelta(days=offset)
        if (
            date.month not in cron.month_of_year
            or date.day not in cron.day_of_month
            or (date.weekday() + 1) % 7 not in cron.day_of_week
        ):
            continue
        candidates = []
        for h in sorted(cron.hour):
            for m in sorted(cron.minute):
                wall = datetime.combine(date, time(h, m), zone)
                for fold in (0, 1):
                    candidate = wall.replace(fold=fold)
                    stamp = int(candidate.timestamp())
                    back = datetime.fromtimestamp(stamp, zone)
                    if stamp > at and back.replace(tzinfo=None) == wall.replace(tzinfo=None):
                        candidates.append(stamp)
        if candidates:
            return min(candidates)
    raise DomainError(422, "CRON 在八年内没有有效触发时刻")


def validate_schedule(kind, schedule, timezone, *, at=None):
    return next_due_after(kind, schedule, timezone, now() if at is None else at)


async def validate_routine_change(session, principal, routine, changes=None):
    changes = changes or {}
    employee = await get_required(session, Employee, routine.employee_id)
    if principal.kind not in {"HUMAN", "EMPLOYEE"}:
        raise DomainError(403, "系统调度身份不可修改履职计划")
    await authorize(session, principal, "routine.manage", employee.team_id)
    if employee.lifecycle == "ARCHIVED":
        raise DomainError(409, "归档员工不能更改持续职责")
    if principal.kind == "EMPLOYEE" and (
        principal.id != employee.id or routine.locked or changes.get("locked", False)
    ):
        raise DomainError(403, "员工不可修改组织锁定或他人 Routine")
    goal_id = changes.get("goal_id", routine.goal_id)
    if goal_id:
        goal = await get_required(session, Goal, goal_id)
        if goal.team_id != employee.team_id:
            raise DomainError(403, "Routine 目标不在当前团队")
        if principal.kind == "EMPLOYEE" and goal.owner_employee_id != employee.id:
            raise DomainError(403, "员工仅可安排自己主责目标的 Routine")
    validate_schedule(
        changes.get("kind", routine.kind),
        changes.get("schedule", routine.schedule),
        changes.get("timezone", routine.timezone),
    )
    return employee


async def _authorize_signal(session, principal, team_id):
    if principal.kind == "SYSTEM":
        await authorize(session, principal, "routine.signal", team_id)
    elif principal.kind == "HUMAN":
        await authorize(session, principal, "routine.manage", team_id)
    else:
        raise DomainError(403, "定时投递仅限授权系统或人类管理者")


async def signal_due_routine(session, principal, routine, *, team_id, at=None):
    at = now() if at is None else at
    await _authorize_signal(session, principal, team_id)
    employee = await get_required(session, Employee, routine.employee_id)
    if employee.team_id != team_id:
        raise DomainError(403, "不能触发其他团队 Routine")
    if not routine.enabled or routine.kind == "EVENT" or routine.next_due_at > at:
        return None
    if employee.lifecycle != "ACTIVE":
        return None
    await lock_active_employee(session, employee.id)
    scheduled_for = routine.next_due_at
    # 条件版本写入使同一次到期最多创建一个 SourceEvent；积压只汇总一条并推进到未来。
    await cas(
        session,
        routine,
        {"next_due_at": next_due_after(routine.kind, routine.schedule, routine.timezone, at)},
    )
    event = SourceEvent(
        source="routine",
        source_id=f"{routine.id}:{scheduled_for}",
        actor_id=principal.id,
        team_id=team_id,
        object_ref=f"routines/{routine.id}",
        causal_root=routine.id,
        payload_ref={"scheduled_for": scheduled_for, "observed_at": at},
        occurred_at=at,
    )
    session.add(event)
    await session.flush()
    await admit(session, event, employee.id, reason="持续职责到期")
    await audit(session, principal, team_id, "routine.signaled", routine, "到期职责已汇总进入员工 Inbox")
    return event


async def sweep_due_routines(session, principal, *, team_id, at=None):
    at = now() if at is None else at
    await _authorize_signal(session, principal, team_id)
    routines = (
        await session.scalars(
            select(Routine)
            .join(Employee, Employee.id == Routine.employee_id)
            .where(
                Employee.team_id == team_id,
                Employee.lifecycle == "ACTIVE",
                Routine.enabled.is_(True),
                Routine.kind.in_(["INTERVAL", "CRON"]),
                Routine.next_due_at <= at,
            )
            .order_by(Routine.id)
            .with_for_update()
        )
    ).all()
    return [
        event.id
        for routine in routines
        if (event := await signal_due_routine(session, principal, routine, team_id=team_id, at=at))
        is not None
    ]


async def signal_routine_now(session, principal, routine):
    employee = await validate_routine_change(session, principal, routine)
    if not routine.enabled:
        raise DomainError(409, "停用 Routine 不能立即唤醒")
    await lock_active_employee(session, employee.id)
    event = SourceEvent(
        source="routine",
        source_id=new_id(),
        actor_id=principal.id,
        team_id=employee.team_id,
        object_ref=f"routines/{routine.id}",
        payload_ref={"manual": True},
        causal_root=routine.id,
        occurred_at=now(),
    )
    session.add(event)
    await session.flush()
    await admit(session, event, employee.id, reason="手动运行 Routine")
    await audit(session, principal, employee.team_id, "routine.signaled", routine, "Routine 已进入员工 Inbox")
    return {"routine_id": routine.id, "source_event_id": event.id}


async def admit_event_routines(session, event):
    routines = (
        await session.scalars(
            select(Routine)
            .join(Employee, Employee.id == Routine.employee_id)
            .where(
                Employee.team_id == event.team_id,
                Employee.lifecycle == "ACTIVE",
                Routine.enabled.is_(True),
                Routine.kind == "EVENT",
                Routine.schedule == event.source,
            )
        )
    ).all()
    for routine in routines:
        if event.source == "channel" and not await session.scalar(
            select(ChannelMember.id).where(
                ChannelMember.channel_id == event.payload_ref.get("channel_id"),
                ChannelMember.actor_id == routine.employee_id,
            )
        ):
            continue
        await admit(session, event, routine.employee_id, reason="持续职责关注的事件")

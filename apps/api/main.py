from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from apps.api import schemas as s
from domains.core import DomainError, now
from domains.database import Database
from domains.governance.models import AuditEvent, BudgetUsage, HistoricalArtifact, Operation
from domains.governance.service import audit, cas, decide_operation, get_required, mutate, prepare, serialize
from domains.identity.models import Actor, Credential, WorkspaceGrant
from domains.identity.service import authenticate, authorize, team_visible
from domains.knowledge.memory import GitMemory, memory_access, publish_memory, verify_sources
from domains.knowledge.models import KnowledgeItem, SkillVersion
from domains.messaging.models import Channel, ChannelMember, Message
from domains.messaging.service import channel_access, create_channel, send_message
from domains.organization.models import Employee, Goal, Role, Team, TeamMember
from domains.organization.service import create_employee, transition_employee
from domains.personas.models import EmployeeState, EmployeeTurn, InboxAdmission, Routine, SourceEvent
from domains.personas.routines import (
    signal_routine_now,
    sweep_due_routines,
    validate_routine_change,
    validate_schedule,
)
from domains.personas.service import ingest
from domains.runtime.models import Worker, WorkerLease
from domains.work.models import Handoff, Task, TaskExecution, TaskReview
from domains.work.service import (
    accept_handoff,
    create_task,
    propose_handoff,
    respond_handoff,
    transition_task,
)

COLLECTIONS = {
    "teams": Team,
    "roles": Role,
    "employees": Employee,
    "goals": Goal,
    "channels": Channel,
    "tasks": Task,
    "routines": Routine,
    "workers": Worker,
    "knowledge": KnowledgeItem,
    "operations": Operation,
    "handoffs": Handoff,
    "worker-leases": WorkerLease,
    "source-events": SourceEvent,
    "historical-artifacts": HistoricalArtifact,
    "workspace-grants": WorkspaceGrant,
}
INPUTS = {
    "teams": s.TeamInput,
    "roles": s.RoleInput,
    "employees": s.EmployeeInput,
    "goals": s.GoalInput,
    "channels": s.ChannelInput,
    "tasks": s.TaskInput,
    "routines": s.RoutineInput,
    "workers": s.WorkerInput,
    "knowledge": s.KnowledgeInput,
    "operations": s.OperationInput,
    "source-events": s.EventInput,
}
PATCHES = {
    "goals": s.GoalPatch,
    "roles": s.RolePatch,
    "employees": s.EmployeePatch,
    "routines": s.RoutinePatch,
    "knowledge": s.KnowledgePatch,
}


def create_app(database_url: str | None = None):
    db = Database(
        database_url or os.environ.get("ASTRA_V1_DATABASE_URL", "sqlite+aiosqlite:///.astra/astra-1.0.db")
    )

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await db.engine.dispose()

    app = FastAPI(title="Astra 1.0", version="1.0.0.dev0", lifespan=lifespan)
    app.state.db = db
    router = APIRouter(prefix="/api/v1")

    @app.exception_handler(DomainError)
    async def domain_error(_request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.exception_handler(IntegrityError)
    async def conflict(_request, _exc):
        return JSONResponse({"detail": "关联不存在或并发操作冲突，请刷新后用原幂等键重试"}, status_code=409)

    @app.exception_handler(OperationalError)
    async def database_unavailable(_request, exc):
        code = exc.orig.args[0] if exc.orig.args else None
        if code in {1205, 1213}:
            return JSONResponse(
                {"detail": "数据库并发冲突，事务已回滚；请刷新后用原幂等键重试"}, status_code=409
            )
        return JSONResponse({"detail": "数据库当前不可用，请稍后重试"}, status_code=503)

    async def session_dep():
        async with db.sessions() as session:
            try:
                yield session
            finally:
                await session.rollback()

    async def principal_dep(authorization: str | None = Header(default=None), session=Depends(session_dep)):
        if not authorization or not authorization.startswith("Bearer "):
            raise DomainError(401, "请提供有效 Bearer 凭据")
        return await authenticate(session, authorization[7:])

    async def visible(session, principal, obj):
        if isinstance(obj, WorkspaceGrant):
            if obj.actor_id != principal.id:
                await authorize(session, principal, "workspace.grant", obj.team_id, human_only=True)
            elif not await team_visible(session, principal, obj.team_id):
                raise DomainError(403, "没有当前工程授权的团队访问权限")
            return obj
        if isinstance(obj, HistoricalArtifact):
            if (
                not await team_visible(session, principal, obj.team_id)
                or (obj.visibility == "AUDIT" and not principal.admin)
                or (obj.visibility == "PRIVATE" and principal.id != obj.owner_actor_id)
            ):
                raise DomainError(403, "没有历史归档授权")
            return obj
        if isinstance(obj, Channel):
            await channel_access(session, principal, obj.id)
        elif isinstance(obj, (Worker, WorkerLease)):
            if not principal.admin:
                raise DomainError(403, "资源诊断仅管理员可见")
        else:
            if isinstance(obj, Routine):
                team_id = (await get_required(session, Employee, obj.employee_id)).team_id
            elif isinstance(obj, Handoff):
                team_id = (await get_required(session, Task, obj.task_id)).team_id
            else:
                team_id = obj.id if isinstance(obj, Team) else obj.team_id
            if not await team_visible(session, principal, team_id):
                raise DomainError(403, "没有此团队的访问权限")
            if isinstance(obj, SourceEvent) and obj.source == "channel":
                await channel_access(session, principal, obj.payload_ref["channel_id"])
        return obj

    @router.get("/health")
    async def health():
        async with db.sessions() as session:
            await session.execute(text("SELECT 1"))
            await session.execute(select(Actor.id).limit(1))
        return {"healthy": True, "product": "Astra", "version": "1.0.0.dev0"}

    @router.get("/me")
    async def me(principal=Depends(principal_dep)):
        return {
            "id": principal.id,
            "kind": principal.kind,
            "name": principal.name,
            "permissions": sorted(principal.permissions),
        }

    @router.get("/teams/overview")
    async def overview(principal=Depends(principal_dep), session=Depends(session_dep)):
        teams = [
            team
            for team in (await session.scalars(select(Team))).all()
            if await team_visible(session, principal, team.id)
        ]
        team_ids = [team.id for team in teams]
        employees = (await session.scalars(select(Employee).where(Employee.team_id.in_(team_ids)))).all()
        tasks = (await session.scalars(select(Task).where(Task.team_id.in_(team_ids)))).all()
        goals = (await session.scalars(select(Goal).where(Goal.team_id.in_(team_ids)))).all()
        pending = await session.scalar(
            select(func.count())
            .select_from(Operation)
            .where(Operation.team_id.in_(team_ids), Operation.status == "WAIT_HUMAN")
        )
        return {
            "teams": [serialize(x) for x in teams],
            "employees": [serialize(x) for x in employees],
            "goals": [serialize(x) for x in goals],
            "tasks": [serialize(x) for x in tasks],
            "pending_decisions": pending,
            "snapshot_at": now(),
        }

    @router.get("/human-inbox")
    async def human_inbox(principal=Depends(principal_dep), session=Depends(session_dep)):
        if principal.kind != "HUMAN":
            raise DomainError(403, "此收件箱仅供人类使用")
        rows = (await session.scalars(select(Operation).where(Operation.status == "WAIT_HUMAN"))).all()
        return [serialize(x) for x in rows if await team_visible(session, principal, x.team_id)]

    @router.get("/audit-events")
    async def audit_events(after: int = 0, principal=Depends(principal_dep), session=Depends(session_dep)):
        rows = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.seq > after).order_by(AuditEvent.seq).limit(500)
            )
        ).all()
        return [serialize(x) for x in rows if await event_visible(session, principal, x)]

    async def event_visible(session, principal, event):
        if event.team_id is None:
            return principal.admin
        if not await team_visible(session, principal, event.team_id):
            return False
        if event.channel_id:
            return bool(
                await session.scalar(
                    select(ChannelMember.id).where(
                        ChannelMember.channel_id == event.channel_id, ChannelMember.actor_id == principal.id
                    )
                )
            )
        return True

    @router.get("/events")
    async def events(
        request: Request, after: int = 0, principal=Depends(principal_dep), session=Depends(session_dep)
    ):
        if after < 0:
            raise DomainError(400, "事件游标不能小于零")
        token = request.headers["authorization"][7:]
        await session.rollback()

        async def read_events(cursor):
            async with db.sessions() as current:
                try:
                    authenticated = await authenticate(current, token)
                except DomainError:
                    return None, cursor
                rows = (
                    await current.scalars(
                        select(AuditEvent).where(AuditEvent.seq > cursor).order_by(AuditEvent.seq).limit(100)
                    )
                ).all()
                visible_events = []
                for event in rows:
                    cursor = event.seq
                    if await event_visible(current, authenticated, event):
                        visible_events.append((event.seq, json.dumps(serialize(event), ensure_ascii=False)))
                return visible_events, cursor

        async def stream():
            cursor = after
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                visible_events, cursor = await read_events(cursor)
                if visible_events is None:
                    yield "event: auth_revoked\ndata: {}\n\n"
                    return
                # 数据库读取结束后再发送网络帧，客户端背压不占用数据库事务。
                for seq, payload in visible_events:
                    yield f"id: {seq}\nevent: business\ndata: {payload}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/governance/metrics")
    async def metrics(principal=Depends(principal_dep), session=Depends(session_dep)):
        team_ids = [
            t.id
            for t in (await session.scalars(select(Team))).all()
            if await team_visible(session, principal, t.id)
        ]
        tasks = (await session.scalars(select(Task).where(Task.team_id.in_(team_ids)))).all()
        goals = (await session.scalars(select(Goal).where(Goal.team_id.in_(team_ids)))).all()
        handoffs = (
            await session.scalars(
                select(Handoff).join(Task, Handoff.task_id == Task.id).where(Task.team_id.in_(team_ids))
            )
        ).all()
        return {
            "tasks": len(tasks),
            "completed_tasks": sum(t.status == "COMPLETED" for t in tasks),
            "active_goals": sum(g.status == "ACTIVE" for g in goals),
            "accepted_handoffs": sum(h.status == "ACCEPTED" for h in handoffs),
            "pending_handoffs": sum(h.status == "PROPOSED" for h in handoffs),
            "snapshot_at": now(),
        }

    @router.get("/governance/policies")
    async def policies(principal=Depends(principal_dep), session=Depends(session_dep)):
        return [
            serialize(t)
            for t in (await session.scalars(select(Team))).all()
            if await team_visible(session, principal, t.id)
        ]

    @router.get("/governance/budgets")
    async def budgets(principal=Depends(principal_dep), session=Depends(session_dep)):
        rows = (await session.scalars(select(Employee))).all()
        result = []
        for employee in rows:
            if await team_visible(session, principal, employee.team_id):
                usages = (
                    await session.scalars(
                        select(BudgetUsage).where(
                            BudgetUsage.actor_id == employee.id, BudgetUsage.created_at >= now() - 86400
                        )
                    )
                ).all()
                result.append(
                    {
                        "employee_id": employee.id,
                        "name": employee.name,
                        "daily_token_budget": employee.daily_token_budget,
                        "decision_tokens": sum(x.tokens for x in usages if x.purpose == "PERSONA"),
                        "execution_tokens": sum(x.tokens for x in usages if x.purpose == "TASK"),
                    }
                )
        return result

    @router.get("/resource-metrics")
    async def resource_metrics(principal=Depends(principal_dep), session=Depends(session_dep)):
        if not principal.admin:
            raise DomainError(403, "资源指标仅管理员可见")
        workers = (await session.scalars(select(Worker))).all()
        leases = (await session.scalars(select(WorkerLease))).all()
        return {
            "workers": len(workers),
            "healthy_workers": sum(w.health == "HEALTHY" for w in workers),
            "active_leases": sum(x.state == "ACTIVE" for x in leases),
            "reconciliation_required": sum(x.state == "RECONCILE_REQUIRED" for x in leases),
        }

    @router.get("/skill-proposals")
    async def skills(principal=Depends(principal_dep), session=Depends(session_dep)):
        items = (await session.scalars(select(KnowledgeItem).where(KnowledgeItem.kind == "SKILL"))).all()
        return [serialize(x) for x in items if await team_visible(session, principal, x.team_id)]

    @router.get("/knowledge/{object_id}/versions")
    async def versions(object_id: str, principal=Depends(principal_dep), session=Depends(session_dep)):
        await visible(session, principal, await get_required(session, KnowledgeItem, object_id))
        return [
            serialize(x)
            for x in (
                await session.scalars(
                    select(SkillVersion)
                    .where(SkillVersion.knowledge_id == object_id)
                    .order_by(SkillVersion.version)
                )
            ).all()
        ]

    @router.get("/historical-artifacts/{object_id}/content")
    async def historical_content(
        object_id: str,
        request: Request,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
    ):
        artifact = await visible(
            session, principal, await get_required(session, HistoricalArtifact, object_id)
        )
        expected = (artifact.revision, artifact.content_ref, artifact.sha256)
        await session.rollback()
        from domains.governance.history import read_artifact

        content = await asyncio.to_thread(
            read_artifact,
            os.environ.get("ASTRA_V1_HISTORY_ARTIFACT_ROOT"),
            expected[1],
            expected[2],
        )
        fresh = await authenticate(session, request.headers["authorization"][7:])
        current = await visible(session, fresh, await get_required(session, HistoricalArtifact, object_id))
        if (current.revision, current.content_ref, current.sha256) != expected:
            raise DomainError(409, "历史索引发生变化，请重新核验")
        return {"artifact_id": object_id, "sha256": expected[2], "content": content}

    @router.post("/employees/{object_id}/memory")
    async def write_memory(
        object_id: str,
        data: s.MemoryWriteInput,
        request: Request,
        key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal=Depends(principal_dep),
        session=Depends(session_dep),
    ):
        if not key or not 1 <= len(key) <= 120:
            raise DomainError(400, "记忆写入必须使用稳定幂等键")
        employee, _ = await memory_access(session, principal, object_id, write=True)
        await verify_sources(session, principal, employee, data.source_refs)
        identity = f"# {employee.name}\n\nEmployee ID: {employee.id}\n\n身份描述不授予业务权限。\n"
        await session.rollback()
        prepared_head = await asyncio.to_thread(
            GitMemory.configured().prepare,
            object_id,
            data,
            actor_id=principal.id,
            identity=identity,
            operation_key=key,
        )
        authenticated = await authenticate(session, request.headers["authorization"][7:])

        async def execute(fresh):
            return await publish_memory(session, fresh, object_id, data, prepared_head)

        return await mutate(session, authenticated, key, f"memory/{object_id}", data.model_dump(), execute)

    @router.get("/employees/{object_id}/memory/history")
    @router.get("/employees/{object_id}/memory/diff")
    async def memory_versions(
        object_id: str,
        request: Request,
        previous: str | None = None,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
    ):
        _, state = await memory_access(session, principal, object_id)
        head = state.memory_head
        await session.rollback()
        store = GitMemory.configured()
        if request.url.path.endswith("/diff"):
            result = {"diff": await asyncio.to_thread(store.diff, object_id, head, previous)}
        else:
            result = await asyncio.to_thread(store.history, object_id, head)
        fresh = await authenticate(session, request.headers["authorization"][7:])
        _, state = await memory_access(session, fresh, object_id)
        if state.memory_head != head:
            raise DomainError(409, "记忆版本已变化，请刷新")
        return result

    @router.get("/employees/{object_id}/{section}")
    async def employee_section(
        object_id: str,
        section: str,
        request: Request,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
    ):
        employee = await visible(session, principal, await get_required(session, Employee, object_id))
        if section in {"goals", "work", "routines", "inbox", "turns"}:
            model, attr = {
                "goals": (Goal, Goal.owner_employee_id),
                "work": (Task, Task.owner_employee_id),
                "routines": (Routine, Routine.employee_id),
                "inbox": (InboxAdmission, InboxAdmission.employee_id),
                "turns": (EmployeeTurn, EmployeeTurn.employee_id),
            }[section]
            if section in {"inbox", "turns"} and principal.id not in {employee.id, employee.manager_id}:
                raise DomainError(403, "员工收件箱仅本人及负责人可见")
            return [
                serialize(x) for x in (await session.scalars(select(model).where(attr == object_id))).all()
            ]
        if section == "dashboard":
            state = await session.scalar(select(EmployeeState).where(EmployeeState.employee_id == object_id))
            private_state = (
                serialize(state) if state and principal.id in {employee.id, employee.manager_id} else None
            )
            return {"employee": serialize(employee), "state": private_state}
        if section == "memory":
            _, state = await memory_access(session, principal, object_id)
            head = state.memory_head
            if not os.getenv("ASTRA_V1_MEMORY_ROOT"):
                return {"employee_id": object_id, "memory_head": head, "configured": False}
            await session.rollback()
            content = await asyncio.to_thread(GitMemory.configured().read, object_id, head)
            fresh = await authenticate(session, request.headers["authorization"][7:])
            _, state = await memory_access(session, fresh, object_id)
            if state.memory_head != head:
                raise DomainError(409, "记忆版本已变化，请刷新")
            return {"employee_id": object_id, "memory_head": head, "configured": True, **content}
        raise DomainError(404, "未知员工视图")

    @router.get("/tasks/{object_id}/{section}")
    async def task_section(
        object_id: str, section: str, principal=Depends(principal_dep), session=Depends(session_dep)
    ):
        task = await visible(session, principal, await get_required(session, Task, object_id))
        executions = (
            await session.scalars(
                select(TaskExecution)
                .where(TaskExecution.task_id == object_id)
                .order_by(TaskExecution.attempt_no)
            )
        ).all()
        if section == "executions":
            return [serialize(x) for x in executions]
        if section == "evidence":
            return [{"execution_id": x.id, "refs": x.evidence_refs} for x in executions]
        if section == "reviews":
            return [
                serialize(x)
                for x in (
                    await session.scalars(
                        select(TaskReview)
                        .where(TaskReview.task_id == object_id)
                        .order_by(TaskReview.created_at)
                    )
                ).all()
            ]
        if section == "workspace":
            latest = executions[-1] if executions else None
            return {
                "task_id": task.id,
                "native_session_id": latest.native_session_id if latest else None,
                "workspace_ref": latest.workspace_ref if latest else None,
                "connected": False,
            }
        if section == "handoff-events":
            ids = select(Handoff.id).where(Handoff.task_id == object_id)
            return [
                serialize(event)
                for event in (
                    await session.scalars(
                        select(SourceEvent)
                        .where(SourceEvent.source == "handoff", SourceEvent.source_id.in_(ids))
                        .order_by(SourceEvent.created_at, SourceEvent.revision)
                    )
                ).all()
            ]
        raise DomainError(404, "未知任务视图")

    @router.get("/channels/{object_id}/members")
    async def channel_members(object_id: str, principal=Depends(principal_dep), session=Depends(session_dep)):
        await channel_access(session, principal, object_id)
        members = (
            await session.scalars(
                select(Actor)
                .join(ChannelMember, ChannelMember.actor_id == Actor.id)
                .where(ChannelMember.channel_id == object_id)
                .order_by(Actor.name, Actor.id)
            )
        ).all()
        return [{"id": actor.id, "name": actor.name, "kind": actor.kind} for actor in members]

    @router.get("/channels/{object_id}/messages")
    async def messages(
        object_id: str, after: int = 0, principal=Depends(principal_dep), session=Depends(session_dep)
    ):
        await channel_access(session, principal, object_id)
        return [
            serialize(x)
            for x in (
                await session.scalars(
                    select(Message)
                    .where(Message.channel_id == object_id, Message.seq > after)
                    .order_by(Message.seq)
                    .limit(500)
                )
            ).all()
        ]

    @router.post("/channels/{object_id}/messages")
    async def post_message(
        object_id: str,
        data: s.MessageInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        return await mutate(
            session,
            principal,
            idempotency_key,
            f"messages/{object_id}",
            data.model_dump(),
            lambda p: send_message(session, p, object_id, data),
        )

    @router.post("/employees/{object_id}/dm")
    async def employee_dm(
        object_id: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        employee = await visible(session, principal, await get_required(session, Employee, object_id))
        data = s.ChannelInput(
            team_id=employee.team_id, kind="DM", name=f"与{employee.name}的对话", member_ids=[employee.id]
        )
        return await mutate(
            session,
            principal,
            idempotency_key,
            f"dm/{object_id}",
            {},
            lambda p: create_channel(session, p, data),
        )

    @router.post("/employees/{object_id}/{action}")
    async def employee_action(
        object_id: str,
        action: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        if action not in {"pause", "resume", "archive"}:
            raise DomainError(404, "未知员工操作")

        async def handle(p):
            return await transition_employee(
                session, p, await get_required(session, Employee, object_id), action
            )

        return await mutate(
            session, principal, idempotency_key, f"employees/{object_id}/{action}", {}, handle
        )

    @router.post("/tasks/{object_id}/handoff")
    async def handoff(
        object_id: str,
        data: s.HandoffInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        return await mutate(
            session,
            principal,
            idempotency_key,
            f"handoff/{object_id}",
            data.model_dump(),
            lambda p: propose_handoff(session, p, object_id, data),
        )

    @router.post("/handoffs/{object_id}/accept")
    async def accept(
        object_id: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        return await mutate(
            session,
            principal,
            idempotency_key,
            f"accept/{object_id}",
            {},
            lambda p: accept_handoff(session, p, object_id),
        )

    @router.post("/handoffs/{object_id}/{action}")
    async def handoff_response(
        object_id: str,
        action: str,
        data: s.HandoffResponse,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        if action not in {"reject", "request-clarification", "clarify", "withdraw"}:
            raise DomainError(404, "未知交接操作")
        return await mutate(
            session,
            principal,
            idempotency_key,
            f"handoff/{object_id}/{action}",
            data.model_dump(),
            lambda p: respond_handoff(session, p, object_id, action, data.reason),
        )

    @router.post("/tasks/{object_id}/dispatch")
    async def dispatch(
        object_id: str,
        data: s.DispatchInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        from domains.runtime.service import dispatch_task

        return await mutate(
            session,
            principal,
            idempotency_key,
            f"tasks/{object_id}/dispatch",
            data.model_dump(),
            lambda p: dispatch_task(session, p, object_id, data.worker_id),
        )

    @router.get("/executions/{object_id}/native-evidence")
    async def execution_evidence(
        object_id: str, principal=Depends(principal_dep), session=Depends(session_dep)
    ):
        from apps.services.reviews import evidence_payload, read_evidence, review_snapshot
        from domains.runtime.execution_config import configured_settings

        settings = await asyncio.to_thread(configured_settings)
        snapshot = await review_snapshot(session, principal, object_id, settings, for_review=False)
        await session.rollback()
        messages = await read_evidence(snapshot)
        payload = evidence_payload(snapshot, messages)
        # 网络读取结束后重新认证/授权和核验业务版本，再把原生内容交给当前审核人。
        current = await review_snapshot(session, principal, object_id, settings, for_review=False)
        if (current[0]["revision"], current[1]["revision"]) != (
            snapshot[0]["revision"],
            snapshot[1]["revision"],
        ):
            raise DomainError(409, "读取期间任务或执行已变化")
        return payload

    @router.post("/tasks/{object_id}/review")
    async def review_task(
        object_id: str,
        data: s.TaskReviewInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        from apps.services.reviews import read_evidence, review_snapshot
        from domains.governance.models import Mutation
        from domains.runtime.execution_config import configured_settings
        from domains.work.review import apply_review, validate_review

        # 成功重放无需再次连接 Runtime，但仍由 mutate 复验当前授权。
        old = await session.scalar(
            select(Mutation).where(
                Mutation.actor_id == principal.id,
                Mutation.operation_key == idempotency_key,
            )
        )
        if old:
            return await mutate(
                session,
                principal,
                idempotency_key,
                f"tasks/{object_id}/review",
                data.model_dump(),
                lambda _p: None,
            )
        settings = await asyncio.to_thread(configured_settings)
        snapshot = await review_snapshot(session, principal, data.execution_id, settings)
        if snapshot[0]["id"] != object_id:
            raise DomainError(409, "执行不属于当前业务任务")
        await session.rollback()
        messages = await read_evidence(snapshot)
        refs = validate_review(data, snapshot[0], snapshot[1], messages)
        return await mutate(
            session,
            principal,
            idempotency_key,
            f"tasks/{object_id}/review",
            data.model_dump(),
            lambda p: apply_review(session, p, object_id, data, snapshot, refs),
        )

    @router.post("/tasks/{object_id}/{action}")
    async def task_action(
        object_id: str,
        action: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        if action not in {"pause", "resume", "cancel", "rework"}:
            raise DomainError(404, "未知任务操作")

        async def handle(p):
            return await transition_task(session, p, await get_required(session, Task, object_id), action)

        return await mutate(session, principal, idempotency_key, f"tasks/{object_id}/{action}", {}, handle)

    @router.post("/operations/{object_id}/{action}")
    async def operation_action(
        object_id: str,
        action: str,
        data: s.DecisionNote | None = None,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        if action not in {"approve", "reject", "request-changes"}:
            raise DomainError(404, "未知审批动作")
        decision = "reject" if action == "request-changes" else action
        return await mutate(
            session,
            principal,
            idempotency_key,
            f"operations/{object_id}/{action}",
            data.model_dump() if data else {},
            lambda p: decide_operation(session, p, object_id, decision, data.reason if data else ""),
        )

    @router.post("/routines/{object_id}/{action}")
    async def routine_action(
        object_id: str,
        action: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        if action not in {"run-now", "pause", "resume"}:
            raise DomainError(404, "未知 Routine 操作")

        async def handle(p):
            routine = await get_required(session, Routine, object_id)
            if action == "run-now":
                return await signal_routine_now(session, p, routine)
            employee = await validate_routine_change(session, p, routine)
            values = {"enabled": action == "resume"}
            if action == "resume":
                values["next_due_at"] = (
                    validate_schedule(routine.kind, routine.schedule, routine.timezone) or 0
                )
            await cas(session, routine, values)
            await audit(session, p, employee.team_id, f"routine.{action}", routine, "Routine 状态已更新")
            return routine

        return await mutate(session, principal, idempotency_key, f"routines/{object_id}/{action}", {}, handle)

    @router.post("/teams/{object_id}/routines/sweep")
    async def sweep_routines(
        object_id: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            ids = await sweep_due_routines(session, p, team_id=object_id)
            return {"team_id": object_id, "source_event_ids": ids}

        return await mutate(session, principal, idempotency_key, f"routine-sweep/{object_id}", {}, handle)

    async def patch_resource(resource, object_id, data, principal, session, idempotency_key):
        values = data.model_dump(exclude_unset=True, exclude={"revision"})
        nullable = (
            {"deadline", "owner_employee_id"}
            if resource == "goals"
            else {"goal_id"}
            if resource == "routines"
            else set()
        )
        if not values or any(value is None and key not in nullable for key, value in values.items()):
            raise DomainError(422, "更新不能为空或把必需字段设为空")

        async def handle(p):
            obj = await get_required(session, COLLECTIONS[resource], object_id)
            if resource == "routines":
                employee = await validate_routine_change(session, p, obj, values)
                team_id, action = employee.team_id, "routine.manage"
                if {"kind", "schedule", "timezone", "enabled"} & values.keys():
                    values["next_due_at"] = (
                        validate_schedule(
                            values.get("kind", obj.kind),
                            values.get("schedule", obj.schedule),
                            values.get("timezone", obj.timezone),
                        )
                        or 0
                    )
            else:
                team_id = obj.team_id
                action = "knowledge.manage" if resource == "knowledge" else "organization.manage"
            await authorize(
                session, p, action, team_id, human_only=resource in {"roles", "goals", "employees"}
            )
            if obj.revision != data.revision:
                raise DomainError(409, "对象版本已经变化，请刷新")
            if resource == "employees":
                if obj.lifecycle == "ARCHIVED":
                    raise DomainError(409, "归档身份不可修改")
                role = await get_required(session, Role, obj.role_id)
                if "permissions" in values and not set(values["permissions"]) <= set(role.permissions):
                    raise DomainError(403, "员工权限不能突破岗位上限")
                actor = await get_required(session, Actor, obj.id)
                await cas(session, actor, {k: v for k, v in values.items() if k in {"name", "permissions"}})
            if resource == "goals" and values.get("owner_employee_id"):
                employee = await get_required(session, Employee, values["owner_employee_id"])
                if employee.team_id != team_id or employee.lifecycle != "ACTIVE":
                    raise DomainError(409, "目标负责人必须同团队且有效")
            if resource == "knowledge" and obj.status == "PUBLISHED":
                raise DomainError(409, "已发布内容需走新版本审核，不可原地覆盖")
            if resource == "knowledge" and {"content", "source_refs"} & values.keys():
                values["verification"] = "UNVERIFIED"
            await cas(session, obj, values)
            await audit(session, p, team_id, f"{resource}.updated", obj, "业务对象版本已更新")
            return obj

        return await mutate(
            session,
            principal,
            idempotency_key,
            f"{resource}/{object_id}/update",
            data.model_dump(exclude_unset=True),
            handle,
        )

    @router.get("/actors")
    async def actors(principal=Depends(principal_dep), session=Depends(session_dep)):
        if not principal.admin:
            raise DomainError(403, "人员管理仅管理员可见")
        return [serialize(x) for x in (await session.scalars(select(Actor))).all()]

    @router.post("/actors")
    async def create_human(
        data: s.HumanInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            if not p.admin:
                raise DomainError(403, "人员身份与初始权限由人类管理员配置")
            from domains.core import new_id

            actor = Actor(id=new_id(), kind="HUMAN", name=data.name, permissions=data.permissions)
            session.add(actor)
            await session.flush()
            credential = Credential(
                actor_id=actor.id, digest=data.credential_digest, expires_at=now() + 86400
            )
            session.add(credential)
            await audit(session, p, None, "human.created", actor, "独立人类登录身份已建立")
            return actor

        return await mutate(session, principal, idempotency_key, "actors", data.model_dump(), handle)

    @router.patch("/actors/{object_id}")
    async def update_human(
        object_id: str,
        data: s.HumanPatch,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            if not p.admin:
                raise DomainError(403, "只有管理员可以配置人类登录授权")
            actor = await get_required(session, Actor, object_id)
            if actor.kind != "HUMAN":
                raise DomainError(409, "非人类主体必须按自身领域管理授权")
            if object_id == p.id and "*" not in data.permissions:
                raise DomainError(409, "不能通过当前会话移除自身管理权限")
            if actor.revision != data.revision:
                raise DomainError(409, "登录身份版本已变化")
            await cas(session, actor, data.model_dump(exclude={"revision"}))
            await audit(session, p, None, "human.updated", actor, "人员名称与操作权限已更新")
            return actor

        return await mutate(
            session, principal, idempotency_key, f"actors/{object_id}/update", data.model_dump(), handle
        )

    @router.post("/system-identities/schedulers")
    @router.post("/system-identities/personas")
    @router.post("/system-identities/executors")
    async def create_scheduler(
        data: s.SchedulerInput,
        request: Request,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            if not p.admin:
                raise DomainError(403, "只有人类管理员可以建立可信调度身份")
            for team_id in set(data.team_ids):
                await authorize(session, p, "organization.manage", team_id, human_only=True)
            actions = {
                "personas": ["persona.run"],
                "schedulers": ["routine.signal"],
                "executors": ["runtime.execute", "task.reconcile"],
            }[request.url.path.split("/")[-1]]
            actor = Actor(name=data.name, kind="SYSTEM", permissions=actions)
            session.add(actor)
            await session.flush()
            for team_id in set(data.team_ids):
                session.add(TeamMember(team_id=team_id, actor_id=actor.id))
            session.add(
                Credential(actor_id=actor.id, digest=data.credential_digest, expires_at=now() + 86400)
            )
            await audit(session, p, None, "system_identity.created", actor, "指定团队的可信系统身份已建立")
            return actor

        return await mutate(
            session,
            principal,
            idempotency_key,
            f"system-identities/{request.url.path.split('/')[-1]}",
            data.model_dump(),
            handle,
        )

    @router.post("/actors/{object_id}/credentials")
    async def issue_actor_credential(
        object_id: str,
        data: s.CredentialInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            if not p.admin:
                raise DomainError(403, "凭据签发必须经人类管理员")
            actor = await get_required(session, Actor, object_id)
            if not actor.active:
                raise DomainError(409, "停用身份不得签发新凭据")
            credential = Credential(
                actor_id=actor.id, digest=data.credential_digest, expires_at=now() + data.lifetime_seconds
            )
            session.add(credential)
            await audit(
                session, p, None, "credential.issued", credential, "主体短期凭据已签发，服务端只存哈希"
            )
            return credential

        return await mutate(
            session, principal, idempotency_key, f"actors/{object_id}/credentials", data.model_dump(), handle
        )

    @router.post("/credentials/{object_id}/revoke")
    async def revoke_credential(
        object_id: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            if not p.admin:
                raise DomainError(403, "凭据撤销必须经人类管理员")
            credential = await get_required(session, Credential, object_id)
            await cas(session, credential, {"revoked": True})
            await audit(session, p, None, "credential.revoked", credential, "具体登录凭据已撤销")
            return credential

        return await mutate(
            session, principal, idempotency_key, f"credentials/{object_id}/revoke", {}, handle
        )

    @router.post("/teams/{object_id}/members")
    async def add_member(
        object_id: str,
        data: s.MemberInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            await authorize(session, p, "organization.manage", object_id, human_only=True)
            actor = await get_required(session, Actor, data.actor_id)
            if actor.kind != "HUMAN" or not actor.active:
                raise DomainError(409, "人类成员接口不能替代员工入职流程")
            member = TeamMember(team_id=object_id, actor_id=actor.id, role=data.role)
            session.add(member)
            await audit(session, p, object_id, "member.added", member, "人类成员已加入团队")
            return member

        return await mutate(
            session, principal, idempotency_key, f"members/{object_id}", data.model_dump(), handle
        )

    @router.get("/teams/{object_id}/members")
    async def team_members(object_id: str, principal=Depends(principal_dep), session=Depends(session_dep)):
        if not await team_visible(session, principal, object_id):
            raise DomainError(403, "没有团队成员查询权限")
        rows = (
            await session.execute(
                select(TeamMember, Actor)
                .join(Actor, Actor.id == TeamMember.actor_id)
                .where(TeamMember.team_id == object_id)
                .order_by(Actor.name, Actor.id)
            )
        ).all()
        return [
            {
                "id": member.id,
                "actor_id": actor.id,
                "name": actor.name,
                "kind": actor.kind,
                "role": member.role,
                "active": actor.active,
            }
            for member, actor in rows
        ]

    @router.post("/workspace-grants")
    async def create_grant(
        data: s.GrantInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            await authorize(session, p, "workspace.grant", data.team_id, human_only=True)
            actor = await get_required(session, Actor, data.actor_id)
            from domains.identity.service import current_principal

            if not await team_visible(session, await current_principal(session, actor.id), data.team_id):
                raise DomainError(403, "被授权主体不在当前团队")
            if data.expires_at <= now() or data.expires_at > now() + 86400 * 30:
                raise DomainError(422, "授权必须在30天内到期")
            grant = WorkspaceGrant(**data.model_dump())
            session.add(grant)
            await audit(session, p, data.team_id, "workspace.granted", grant, "具体工程授权已创建")
            return grant

        return await mutate(
            session, principal, idempotency_key, "workspace-grants", data.model_dump(), handle
        )

    @router.post("/workers/{object_id}/credential")
    async def worker_credential(
        object_id: str,
        data: s.WorkerCredentialInput,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            if not p.admin:
                raise DomainError(403, "仅人类管理员可配置 Worker 部署凭据引用")
            worker = await get_required(session, Worker, object_id)
            if worker.revision != data.revision:
                raise DomainError(409, "Worker 配置版本已变化")
            await cas(session, worker, {"credential_ref": data.credential_ref, "health": "UNKNOWN"})
            await audit(session, p, None, "worker.credential_bound", worker, "部署凭据引用已更新，未显示密钥")
            return worker

        return await mutate(
            session, principal, idempotency_key, f"workers/{object_id}/credential", data.model_dump(), handle
        )

    @router.post("/workers/{object_id}/probe")
    async def probe_worker(
        object_id: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        worker = await visible(session, principal, await get_required(session, Worker, object_id))
        if not idempotency_key:
            raise DomainError(400, "写入必须提供 Idempotency-Key")
        if not worker.workspace_roots:
            raise DomainError(409, "Worker 尚未配置工作区边界")
        from domains.runtime.client import OpenCodeClient
        from domains.runtime.config import OpenCodeConfig, RuntimePurpose
        from domains.runtime.errors import (
            OpenCodeAuthenticationError,
            OpenCodeIncompatible,
            OpenCodeUnavailable,
        )

        expected_revision = worker.revision
        worker_data = serialize(worker)
        credential_ref = worker.credential_ref
        await session.rollback()
        from domains.runtime.execution_config import worker_password

        password = await asyncio.to_thread(worker_password, credential_ref)
        config = OpenCodeConfig(
            base_url=worker_data["base_url"],
            runtime_id=worker_data["id"],
            purpose=RuntimePurpose.TASK,
            workspace_roots=tuple(worker_data["workspace_roots"]),
            control_timeout_seconds=3,
            password=password,
        )
        # 真实 Runtime 网络检查在事务外执行，不能持有数据库行锁。
        try:
            result = await OpenCodeClient(config).verify_contract()
            values = {"health": "HEALTHY", "runtime_version": result["version"], "last_seen_at": now()}
        except OpenCodeIncompatible:
            values = {"health": "INCOMPATIBLE"}
        except (OpenCodeUnavailable, OpenCodeAuthenticationError):
            values = {"health": "UNREACHABLE"}

        async def handle(p):
            if not p.admin:
                raise DomainError(403, "仅管理员可检查执行资源")
            current = await get_required(session, Worker, object_id)
            if current.revision != expected_revision:
                raise DomainError(409, "Worker 配置已变化，请重新检查")
            await cas(session, current, values)
            await audit(session, p, None, "worker.probed", current, "已执行真实 Runtime 健康与版本契约检查")
            return current

        return await mutate(session, principal, idempotency_key, f"workers/{object_id}/probe", {}, handle)

    @router.post("/workspace-grants/{object_id}/revoke")
    async def revoke_grant(
        object_id: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            grant = await get_required(session, WorkspaceGrant, object_id)
            await authorize(session, p, "workspace.grant", grant.team_id, human_only=True)
            await cas(session, grant, {"expires_at": now()})
            await audit(session, p, grant.team_id, "workspace.revoked", grant, "具体工程授权已撤销")
            return grant

        return await mutate(
            session, principal, idempotency_key, f"workspace-grants/{object_id}/revoke", {}, handle
        )

    @router.patch("/workspace-grants/{object_id}")
    async def update_grant(
        object_id: str,
        data: s.GrantPatch,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            grant = await get_required(session, WorkspaceGrant, object_id)
            await authorize(session, p, "workspace.grant", grant.team_id, human_only=True)
            if grant.revision != data.revision:
                raise DomainError(409, "工程授权版本已变化")
            if data.expires_at <= now() or data.expires_at > now() + 86400 * 30:
                raise DomainError(422, "授权必须在30天内到期")
            from domains.identity.service import current_principal

            target = await current_principal(session, grant.actor_id)
            if not await team_visible(session, target, grant.team_id):
                raise DomainError(403, "被授权主体已离开团队")
            await cas(session, grant, data.model_dump(exclude={"revision"}))
            await audit(session, p, grant.team_id, "workspace.updated", grant, "工程授权范围和到期时间已更新")
            return grant

        return await mutate(
            session,
            principal,
            idempotency_key,
            f"workspace-grants/{object_id}/update",
            data.model_dump(),
            handle,
        )

    @router.post("/actors/{object_id}/revoke")
    async def revoke_actor(
        object_id: str,
        principal=Depends(principal_dep),
        session=Depends(session_dep),
        idempotency_key: str | None = Header(default=None),
    ):
        async def handle(p):
            if not p.admin or object_id == p.id:
                raise DomainError(403, "仅管理员可以停用其他人类或系统登录身份")
            actor = await get_required(session, Actor, object_id)
            if actor.kind not in {"HUMAN", "SYSTEM"}:
                raise DomainError(409, "员工与 Worker 须按其领域生命周期管理")
            await cas(session, actor, {"active": False})
            await audit(session, p, None, "actor.revoked", actor, "主体登录及操作权限已停用")
            return actor

        return await mutate(session, principal, idempotency_key, f"actors/{object_id}/revoke", {}, handle)

    @router.get("/{resource}")
    async def list_resource(resource: str, principal=Depends(principal_dep), session=Depends(session_dep)):
        model = COLLECTIONS.get(resource)
        if not model:
            raise DomainError(404, "未知资源")
        if model in {Worker, WorkerLease} and not principal.admin:
            raise DomainError(403, "资源诊断仅管理员可见")
        rows = (await session.scalars(select(model).limit(1000))).all()
        result = []
        for obj in rows:
            try:
                await visible(session, principal, obj)
                result.append(serialize(obj))
            except DomainError as exc:
                if exc.status != 403:
                    raise
        return result

    @router.get("/{resource}/{object_id}")
    async def detail(
        resource: str, object_id: str, principal=Depends(principal_dep), session=Depends(session_dep)
    ):
        model = COLLECTIONS.get(resource)
        if not model:
            raise DomainError(404, "未知资源")
        return serialize(await visible(session, principal, await get_required(session, model, object_id)))

    async def create_resource(resource, data, principal, session, idempotency_key):
        async def handle(p):
            if resource == "employees":
                return await create_employee(session, p, data)
            if resource == "tasks":
                return await create_task(session, p, data)
            if resource == "channels":
                return await create_channel(session, p, data)
            if resource == "operations":
                return await prepare(session, p, data)
            if resource == "source-events":
                return await ingest(session, p, data)
            if resource == "teams":
                if not p.admin:
                    raise DomainError(403, "仅人类管理员可建立团队")
                obj = Team(**data.model_dump())
                session.add(obj)
                await session.flush()
                session.add(TeamMember(team_id=obj.id, actor_id=p.id, role="ADMIN"))
                team_id = obj.id
            elif resource == "workers":
                if not p.admin:
                    raise DomainError(403, "仅管理员可注册 Worker")
                obj = Worker(**data.model_dump())
                session.add(obj)
                await session.flush()
                for slot in range(obj.concurrent_slots):
                    session.add(WorkerLease(worker_id=obj.id, slot=slot))
                await audit(session, p, None, "worker.registered", obj, "Worker 执行资源已注册，健康未知")
                return obj
            elif resource == "routines":
                obj = Routine(**data.model_dump())
                employee = await validate_routine_change(session, p, obj)
                team_id = employee.team_id
                obj.next_due_at = validate_schedule(obj.kind, obj.schedule, obj.timezone) or 0
                session.add(obj)
            else:
                team_id = data.team_id
                action = "knowledge.manage" if resource == "knowledge" else "organization.manage"
                await authorize(session, p, action, team_id, human_only=resource in {"roles", "goals"})
                values = data.model_dump()
                if resource == "goals" and data.owner_employee_id:
                    employee = await get_required(session, Employee, data.owner_employee_id)
                    if employee.team_id != team_id or employee.lifecycle != "ACTIVE":
                        raise DomainError(409, "目标负责人须为同团队有效员工")
                if resource == "knowledge":
                    values["created_by_actor"] = p.id
                obj = COLLECTIONS[resource](**values)
                session.add(obj)
            await audit(session, p, team_id, f"{resource}.created", obj, "业务对象已创建")
            return obj

        return await mutate(session, principal, idempotency_key, resource, data.model_dump(), handle)

    def register_write_routes(resource, schema, *, patch=False):
        # 每个新领域资源注册具体路径和强类型请求契约；运行时没有旧路由或字段 alias。
        if patch:

            async def endpoint(
                object_id: str,
                data,
                principal=Depends(principal_dep),
                session=Depends(session_dep),
                idempotency_key: str | None = Header(default=None),
            ):
                return await patch_resource(resource, object_id, data, principal, session, idempotency_key)
        else:

            async def endpoint(
                data,
                principal=Depends(principal_dep),
                session=Depends(session_dep),
                idempotency_key: str | None = Header(default=None),
            ):
                return await create_resource(resource, data, principal, session, idempotency_key)

        endpoint.__annotations__["data"] = schema
        router.add_api_route(
            f"/{resource}" + ("/{object_id}" if patch else ""),
            endpoint,
            methods=["PATCH" if patch else "POST"],
            name=f"{'update' if patch else 'create'}_{resource}",
        )

    for resource, schema in INPUTS.items():
        register_write_routes(resource, schema)
    for resource, schema in PATCHES.items():
        register_write_routes(resource, schema, patch=True)

    app.include_router(router)
    return app


app = create_app()

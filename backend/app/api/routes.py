import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.library_routes import library_principal
from app.config.settings import get_settings
from app.dashboard import (
    dashboard_activity,
    dashboard_attention,
    dashboard_employees,
    dashboard_overview,
    dashboard_tasks,
)
from app.database import SessionLocal, get_session
from app.domain import CompletionPolicy, EmployeeStatus, EnvironmentStatus, RunStatus, TaskStatus
from app.executors.opencode_remote_server import RemoteOpenCodeServerExecutor
from app.executors.opencode_server import OpenCodeServerClient
from app.library_service import KnowledgeService, LibraryPrincipal
from app.models import (
    DigitalEmployee,
    Event,
    Evidence,
    OpenCodeExecutionEnvironment,
    Run,
    RunInquiry,
    SessionMessage,
    Task,
    TaskCategory,
    TaskSession,
)
from app.runtime.environment import (
    CheckItem,
    ExecutionEnvironmentRuntime,
    checks_status,
    environment_from_snapshot,
)
from app.runtime.lifecycle import RuntimeService, RuntimeStateError
from app.runtime.recovery import environment_checked_after_error
from app.schemas import (
    EmployeeCreate,
    EmployeePatch,
    EmployeeRead,
    EnvironmentCheckResult,
    EventRead,
    EvidenceRead,
    ExecutionEnvironmentRead,
    ExecutionEnvironmentWrite,
    HumanInterventionWrite,
    InquiryAnswerWrite,
    RunInquiryRead,
    RunRead,
    RuntimeEventRead,
    SessionBlockRead,
    SessionMessageRead,
    SessionMessageWrite,
    TaskAction,
    TaskCategoryCreate,
    TaskCategoryPatch,
    TaskCategoryRead,
    TaskCompletionWrite,
    TaskCreate,
    TaskProgressUpdate,
    TaskRead,
    TaskRejectWrite,
    TaskSessionRead,
    TaskSuspendWrite,
    TaskWorkbenchRead,
)
from app.services import (
    EmployeeService,
    TaskService,
    WorkbenchService,
    dashboard_metrics,
    ensure_task_session,
)
from app.state_machine import InvalidTransition
from app.usage import (
    day_bounds,
    employee_usage,
    load_runs,
    summarize_runs,
    task_usage,
    tool_breakdown,
)

router = APIRouter(prefix="/api")


async def require_task(task_id: str, session: AsyncSession) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


async def require_employee(employee_id: str, session: AsyncSession) -> DigitalEmployee:
    employee = await session.scalar(
        select(DigitalEmployee)
        .where(DigitalEmployee.id == employee_id)
        .options(selectinload(DigitalEmployee.execution_environment))
    )
    if not employee:
        raise HTTPException(status_code=404, detail="数字员工不存在")
    return employee


def runtime_event_type(event: Event) -> str:
    if event.event_type == "TOOL_ACTIVITY":
        semantic_type = str(event.detail.get("semantic_event_type") or "")
        if semantic_type.startswith("tool."):
            return semantic_type
        status_value = str(event.detail.get("status") or "").lower()
        if any(value in status_value for value in ("fail", "error", "reject")):
            return "tool.failed"
        if any(value in status_value for value in ("complete", "success", "done")):
            return "tool.completed"
        return "tool.started"
    if event.event_type == "TASK_RUNNING" and event.detail.get("from") in {
        TaskStatus.WAIT_HUMAN,
        TaskStatus.SUSPENDED,
    }:
        return "run.resumed"
    return {
        "TASK_CREATED": "run.created",
        "TASK_READY": "run.created",
        "TASK_ASSIGNED": "run.assigned",
        "TASK_QUEUED": "run.queued",
        "RUN_DISPATCHED": "run.dispatched",
        "RUN_DISPATCH_FAILED": "runtime.error",
        "TASK_RUNNING": "run.started",
        "WORK_STARTED": "agent.started",
        "OPENCODE_STARTED": "runtime.session",
        "OPENCODE_SESSION_BOUND": "runtime.session",
        "OPENCODE_ABORTED": "runtime.abort",
        "WORK_PROGRESS": "message.agent",
        "AGENT_STARTED": "agent.started",
        "AGENT_PROGRESS": "agent.progress",
        "AGENT_COMPLETED": "agent.completed",
        "AGENT_FAILED": "agent.failed",
        "SUBAGENT_STARTED": "subagent.started",
        "SUBAGENT_PROGRESS": "subagent.progress",
        "SUBAGENT_COMPLETED": "subagent.completed",
        "SUBAGENT_FAILED": "subagent.failed",
        "MODEL_ACTIVITY": "runtime.metadata",
        "RUNTIME_METADATA": "runtime.metadata",
        "WAIT_HUMAN": "run.waiting_input",
        "INQUIRY_CREATED": "inquiry.created",
        "INQUIRY_ANSWERED": "inquiry.answered",
        "MESSAGE_USER": "message.user",
        "MESSAGE_AGENT": "message.agent",
        "WORK_RETRY": "run.resumed",
        "SESSION_RECOVERY": "run.resumed",
        "RUN_CONTINUED": "run.resumed",
        "RUN_ORPHANED_BUSY": "runtime.metadata",
        "STATE_RECONCILED": "runtime.metadata",
        "STATE_CONFLICT": "runtime.error",
        "TASK_SUSPENDED": "run.paused",
        "TASK_COMPLETED": "run.completed",
        "RESULT_SUBMITTED": "agent.completed",
        "TASK_FAILED": "run.failed",
        "EXECUTION_ERROR": "run.failed",
        "TASK_CANCELLED": "run.cancelled",
        "ARTIFACT_CREATED": "artifact.created",
        "ARTIFACT_UPDATED": "artifact.updated",
    }.get(event.event_type, event.event_type.lower().replace("_", "."))


def runtime_event(event: Event, work_session: TaskSession) -> RuntimeEventRead:
    detail = event.detail or {}
    semantic_type = runtime_event_type(event)
    agent_name = detail.get("agent_name") or detail.get("agent")
    if not agent_name and semantic_type.startswith(("agent.", "subagent.", "tool.")):
        agent_name = event.employee_id
    return RuntimeEventRead(
        id=f"evt_{event.id}",
        session_id=work_session.id,
        run_id=event.run_id,
        sequence=event.id,
        event_type=semantic_type,
        agent_name=str(agent_name) if agent_name else None,
        timestamp=event.created_at,
        phase=event.phase,
        summary=event.message,
        payload={"source_event_type": event.event_type, **detail},
    )


def _derived_subagent_event(event: Event, work_session: TaskSession) -> RuntimeEventRead | None:
    """Compatibility projection for Task Tool events captured before plural semantics."""
    detail = event.detail or {}
    tool_input = detail.get("input") if isinstance(detail.get("input"), dict) else {}
    if str(detail.get("tool") or "").lower() != "task":
        return None
    agent_name = str(
        tool_input.get("subagent_type") or tool_input.get("subagentType") or tool_input.get("agent") or ""
    ).strip()
    if not agent_name:
        return None
    status_value = str(detail.get("status") or "started").lower()
    if any(value in status_value for value in ("fail", "error", "reject", "cancel")):
        semantic_type = "subagent.failed"
        verb = "执行失败"
    elif any(value in status_value for value in ("complete", "success", "done", "finished")):
        semantic_type = "subagent.completed"
        verb = "已完成"
    elif any(value in status_value for value in ("progress", "running", "working")):
        semantic_type = "subagent.progress"
        verb = "正在执行"
    else:
        semantic_type = "subagent.started"
        verb = "已启动"
    metadata = detail.get("metadata") if isinstance(detail.get("metadata"), dict) else {}
    title = str(detail.get("title") or tool_input.get("description") or "子任务")
    return RuntimeEventRead(
        id=f"evt_{event.id}_subagent",
        session_id=work_session.id,
        run_id=event.run_id,
        sequence=event.id,
        event_type=semantic_type,
        agent_name=agent_name,
        timestamp=event.created_at,
        phase="agent",
        summary=f"{agent_name} {verb}子任务：{title}",
        payload={
            "source_event_type": event.event_type,
            "source_event_id": event.id,
            "source_tool": "task",
            "source_call_id": detail.get("call_id"),
            "status": status_value,
            "role": agent_name,
            "description": tool_input.get("description"),
            "prompt": tool_input.get("prompt"),
            "input": tool_input,
            "output": detail.get("output"),
            "error": detail.get("error"),
            "parent_session_id": metadata.get("parentSessionId") or metadata.get("parent_session_id"),
            "child_session_id": metadata.get("sessionId") or metadata.get("session_id"),
            "model": metadata.get("model"),
            "compatibility_projection": True,
        },
    )


def runtime_events(events: list[Event], work_session: TaskSession) -> list[RuntimeEventRead]:
    """Expand persisted events into canonical runtime events without semantic loss."""
    projected = [runtime_event(item, work_session) for item in events]
    observed_source_ids = {
        item.payload.get("source_event_id") for item in projected if item.event_type.startswith("subagent.")
    }
    observed_call_ids = {
        item.payload.get("source_call_id")
        for item in projected
        if item.event_type.startswith("subagent.") and item.payload.get("source_call_id")
    }
    observed_run_agents = {
        (item.run_id, item.agent_name) for item in projected if item.event_type.startswith("subagent.")
    }
    for row in events:
        derived = _derived_subagent_event(row, work_session)
        if not derived:
            continue
        source_call_id = derived.payload.get("source_call_id")
        if row.id in observed_source_ids:
            continue
        if source_call_id and source_call_id in observed_call_ids:
            continue
        if not source_call_id and (derived.run_id, derived.agent_name) in observed_run_agents:
            continue
        projected.append(derived)
    return sorted(projected, key=lambda item: (item.sequence, item.id))


def session_blocks(
    work_session: TaskSession,
    events: list[RuntimeEventRead],
    messages: list[SessionMessage],
    inquiries: list[RunInquiry],
) -> list[SessionBlockRead]:
    """Project canonical events and durable conversation facts into SessionBlocks."""
    blocks: list[SessionBlockRead] = []
    for message in messages:
        message_read = SessionMessageRead.model_validate(message)
        blocks.append(
            SessionBlockRead(
                id=f"block_{message.id}",
                session_id=work_session.id,
                run_id=message.run_id,
                sequence=None,
                block_type="message",
                semantic_type=f"message.{message.role}",
                actor_name=message.role,
                status=message.status,
                timestamp=message.created_at,
                summary=message.content,
                message=message_read,
            )
        )
    for inquiry in inquiries:
        inquiry_read = RunInquiryRead.model_validate(inquiry)
        blocks.append(
            SessionBlockRead(
                id=f"block_{inquiry.id}",
                session_id=work_session.id,
                run_id=inquiry.run_id,
                sequence=None,
                block_type="inquiry",
                semantic_type="inquiry.requested",
                actor_name=inquiry.agent_name,
                status=inquiry.status,
                timestamp=inquiry.created_at,
                summary=inquiry.question,
                inquiry=inquiry_read,
            )
        )

    tool_groups: dict[str, list[RuntimeEventRead]] = {}
    for event in events:
        if event.event_type.startswith("tool."):
            key = event.run_id or "unassigned"
            tool_groups.setdefault(key, []).append(event)
            continue
        diagnostic = (
            event.event_type.startswith(("runtime.", "message.", "inquiry."))
            and event.event_type != "runtime.error"
        )
        blocks.append(
            SessionBlockRead(
                id=f"block_{event.id}",
                session_id=work_session.id,
                run_id=event.run_id,
                sequence=event.sequence,
                block_type="event",
                semantic_type=event.event_type,
                visibility="diagnostic" if diagnostic else "primary",
                actor_name=event.agent_name,
                status=str(event.payload.get("status") or "") or None,
                timestamp=event.timestamp,
                summary=event.summary,
                payload={"phase": event.phase},
                events=[event],
            )
        )
    for run_key, tool_events in tool_groups.items():
        failed = any(item.event_type == "tool.failed" for item in tool_events)
        active = any(item.event_type in {"tool.started", "tool.progress"} for item in tool_events)
        blocks.append(
            SessionBlockRead(
                id=f"block_tools_{run_key}",
                session_id=work_session.id,
                run_id=None if run_key == "unassigned" else run_key,
                sequence=min(item.sequence for item in tool_events),
                block_type="operation_group",
                semantic_type="tool.group",
                actor_name=next((item.agent_name for item in tool_events if item.agent_name), None),
                status="failed" if failed else "running" if active else "completed",
                timestamp=min(item.timestamp for item in tool_events),
                summary=f"{len(tool_events)} 项实际操作",
                payload={"count": len(tool_events)},
                events=tool_events,
            )
        )
    return sorted(
        blocks,
        key=lambda item: (
            item.timestamp,
            item.sequence if item.sequence is not None else -1,
            item.id,
        ),
    )


async def load_task_workbench(
    task: Task,
    session: AsyncSession,
    *,
    before_sequence: int | None = None,
    event_limit: int = 120,
) -> TaskWorkbenchRead:
    work_session = await ensure_task_session(session, task)
    if task.status == TaskStatus.WAIT_HUMAN and task.human_intervention:
        await WorkbenchService(session).create_inquiry(
            task,
            question=str(task.human_intervention.get("requested_input") or "请补充继续任务所需的信息"),
            description=str(task.human_intervention.get("blocking_reason") or ""),
            options=task.human_intervention.get("options") or [],
            agent_name=task.employee_id,
            run_id=work_session.current_run_id,
            commit=False,
        )
    event_query = select(Event).where(Event.task_id == task.id)
    if before_sequence is not None:
        event_query = event_query.where(Event.id < before_sequence)
    event_rows = (
        (await session.execute(event_query.order_by(Event.id.desc()).limit(event_limit + 1))).scalars().all()
    )
    has_more = len(event_rows) > event_limit
    event_rows = list(reversed(event_rows[:event_limit]))
    messages = (
        (
            await session.execute(
                select(SessionMessage)
                .where(SessionMessage.session_id == work_session.id)
                .order_by(SessionMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    inquiries = (
        (
            await session.execute(
                select(RunInquiry)
                .where(RunInquiry.session_id == work_session.id)
                .order_by(RunInquiry.created_at)
            )
        )
        .scalars()
        .all()
    )
    artifacts = (
        (
            await session.execute(
                select(Evidence).where(Evidence.task_id == task.id).order_by(Evidence.created_at)
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (await session.execute(select(Run).where(Run.task_id == task.id).order_by(Run.run_number.desc())))
        .scalars()
        .all()
    )
    canonical_events = runtime_events(event_rows, work_session)
    await session.commit()
    return TaskWorkbenchRead(
        task=TaskRead.model_validate(task),
        session=TaskSessionRead.model_validate(work_session),
        messages=[SessionMessageRead.model_validate(item) for item in messages],
        events=canonical_events,
        blocks=session_blocks(work_session, canonical_events, messages, inquiries),
        inquiries=[RunInquiryRead.model_validate(item) for item in inquiries],
        artifacts=artifacts,
        runs=runs,
        has_more_events=has_more,
    )


async def _abort_opencode_session(task: Task, session: AsyncSession) -> bool:
    settings = get_settings()
    snapshot = task.execution_environment_snapshot or {}
    if (
        settings.executor_type != "opencode_server"
        or not task.opencode_session_id
        or not snapshot.get("workspace_root")
    ):
        return False
    try:
        if str(snapshot.get("mode") or "").upper() == "LINUX_REMOTE":
            if not task.employee_id:
                return False
            employee = await session.scalar(
                select(DigitalEmployee)
                .where(DigitalEmployee.id == task.employee_id)
                .options(selectinload(DigitalEmployee.execution_environment))
            )
            if not employee or not employee.execution_environment:
                return False
            environment = environment_from_snapshot(snapshot, task.employee_id)
            environment.ssh_password = employee.execution_environment.ssh_password
            if "opencode_server_port" not in snapshot:
                environment.opencode_server_port = employee.execution_environment.opencode_server_port
            executor = RemoteOpenCodeServerExecutor(
                environment,
                settings,
                ExecutionEnvironmentRuntime(settings),
            )
            return await asyncio.wait_for(
                executor.abort_session(task.opencode_session_id),
                timeout=max(15, settings.ssh_connect_timeout_seconds + 5),
            )
        workspace = settings.employee_workspace_path(str(snapshot["workspace_root"]))
        return await asyncio.wait_for(
            OpenCodeServerClient(settings).abort(workspace, task.opencode_session_id),
            timeout=3,
        )
    except Exception:
        # The state transition remains authoritative when the runtime is already gone.
        return False


async def employee_read(employee: DigitalEmployee, session: AsyncSession) -> EmployeeRead:
    start, end = day_bounds()
    runs = await load_runs(session, employee_id=employee.id, start=start, end=end)
    usage = await summarize_runs(session, runs)
    base = EmployeeRead.model_validate(employee)
    return EmployeeRead.model_validate(
        {
            **base.model_dump(),
            "today_usage": usage,
            "today_completed": usage["completed_tasks"],
        }
    )


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(select(1))
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


@router.get("/system/metrics")
async def metrics(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_metrics(session)


@router.get("/dashboard/overview")
async def home_dashboard_overview(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_overview(session)


@router.get("/dashboard/employees")
async def home_dashboard_employees(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_employees(session)


@router.get("/dashboard/attention")
async def home_dashboard_attention(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_attention(session)


@router.get("/dashboard/tasks")
async def home_dashboard_tasks(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_tasks(session)


@router.get("/dashboard/activity")
async def home_dashboard_activity(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_activity(session)


@router.get("/dashboard/knowledge")
async def home_dashboard_knowledge(
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
) -> dict:
    return await KnowledgeService(session).dashboard_summary(principal)


@router.get("/task-categories", response_model=list[TaskCategoryRead])
async def list_task_categories(
    include_disabled: bool = False,
    session: AsyncSession = Depends(get_session),
):
    query = select(TaskCategory)
    if not include_disabled:
        query = query.where(TaskCategory.enabled.is_(True))
    return (
        (await session.execute(query.order_by(TaskCategory.sort_order, TaskCategory.created_at)))
        .scalars()
        .all()
    )


@router.post(
    "/task-categories",
    response_model=TaskCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task_category(
    payload: TaskCategoryCreate,
    session: AsyncSession = Depends(get_session),
):
    category = TaskCategory(id=f"CAT-{uuid4().hex[:8].upper()}", **payload.model_dump())
    session.add(category)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="任务分类名称已存在") from exc
    await session.refresh(category)
    return category


@router.patch("/task-categories/{category_id}", response_model=TaskCategoryRead)
async def patch_task_category(
    category_id: str,
    payload: TaskCategoryPatch,
    session: AsyncSession = Depends(get_session),
):
    category = await session.get(TaskCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="任务分类不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, key, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="任务分类名称已存在") from exc
    await session.refresh(category)
    return category


async def validate_category_ids(category_ids: list[str], session: AsyncSession) -> None:
    if not category_ids:
        raise HTTPException(status_code=422, detail="至少选择一个任务分类")
    existing = set(
        (
            await session.execute(
                select(TaskCategory.id).where(
                    TaskCategory.id.in_(category_ids), TaskCategory.enabled.is_(True)
                )
            )
        ).scalars()
    )
    missing = set(category_ids) - existing
    if missing:
        raise HTTPException(status_code=422, detail=f"任务分类不存在或已停用：{', '.join(sorted(missing))}")


@router.get("/employees", response_model=list[EmployeeRead])
async def list_employees(session: AsyncSession = Depends(get_session)):
    employees = (
        (
            await session.execute(
                select(DigitalEmployee)
                .options(selectinload(DigitalEmployee.execution_environment))
                .order_by(DigitalEmployee.id)
            )
        )
        .scalars()
        .all()
    )
    return [await employee_read(employee, session) for employee in employees]


@router.post("/employees", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
async def create_employee(payload: EmployeeCreate, session: AsyncSession = Depends(get_session)):
    await validate_category_ids(payload.category_ids, session)
    environment_payload = payload.execution_environment.model_dump()
    employee_payload = payload.model_dump(exclude={"execution_environment"})
    employee_payload["task_types"] = [item.value for item in payload.task_types]
    employee = DigitalEmployee(
        **employee_payload,
        status=EmployeeStatus.IDLE,
        online_since=datetime.now(UTC),
        last_heartbeat=datetime.now(UTC),
    )
    session.add(employee)
    try:
        await session.flush()
        session.add(
            OpenCodeExecutionEnvironment(
                employee_id=employee.id,
                **environment_payload,
                status=EnvironmentStatus.UNKNOWN,
            )
        )
        session.add(
            Event(
                employee_id=employee.id,
                event_type="EMPLOYEE_CREATED",
                phase="business",
                message=f"新增数字员工：{employee.name}",
                detail={"role": employee.role},
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="员工 ID 已存在") from exc
    return await employee_read(await require_employee(employee.id, session), session)


@router.get("/employees/{employee_id}", response_model=EmployeeRead)
async def get_employee(employee_id: str, session: AsyncSession = Depends(get_session)):
    return await employee_read(await require_employee(employee_id, session), session)


@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
async def patch_employee(
    employee_id: str, payload: EmployeePatch, session: AsyncSession = Depends(get_session)
):
    employee = await require_employee(employee_id, session)
    updates = payload.model_dump(exclude_unset=True)
    if payload.category_ids is not None:
        await validate_category_ids(payload.category_ids, session)
    if payload.task_types is not None:
        updates["task_types"] = [item.value for item in payload.task_types]
    for key, value in updates.items():
        setattr(employee, key, value)
    await session.commit()
    return await employee_read(await require_employee(employee.id, session), session)


@router.put("/employees/{employee_id}/environment", response_model=ExecutionEnvironmentRead)
async def update_employee_environment(
    employee_id: str,
    payload: ExecutionEnvironmentWrite,
    session: AsyncSession = Depends(get_session),
):
    employee = await require_employee(employee_id, session)
    environment = employee.execution_environment
    if environment is None:
        environment = OpenCodeExecutionEnvironment(employee_id=employee.id)
        session.add(environment)
    updates = payload.model_dump()
    if not updates.get("ssh_password"):
        updates.pop("ssh_password", None)
    for key, value in updates.items():
        setattr(environment, key, value)
    environment.status = EnvironmentStatus.UNKNOWN
    environment.status_detail = {
        "message": "配置已更新，等待测试连接",
        "applies_to": "future_tasks" if employee.current_task_count else "all_new_runs",
    }
    await session.commit()
    await session.refresh(environment)
    session.add(
        Event(
            employee_id=employee.id,
            event_type="ENVIRONMENT_UPDATED",
            phase="environment",
            message="Agent 工作环境已更新",
            detail={
                "mode": environment.mode,
                "name": environment.name,
                "applies_to_future_tasks": bool(employee.current_task_count),
            },
        )
    )
    await session.commit()
    return environment


@router.post("/employees/{employee_id}/environment/test", response_model=EnvironmentCheckResult)
async def test_employee_environment(employee_id: str, session: AsyncSession = Depends(get_session)):
    employee = await require_employee(employee_id, session)
    environment = employee.execution_environment
    if not environment:
        raise HTTPException(status_code=409, detail="员工尚未配置 Agent 工作环境")
    environment.status = EnvironmentStatus.CHECKING
    await session.commit()
    checked_at = datetime.now(UTC)
    try:
        checks = await ExecutionEnvironmentRuntime().test(environment)
    except Exception as exc:
        checks = [CheckItem("环境检查", False, str(exc))]
    environment.status = checks_status(checks)
    environment.last_checked_at = checked_at
    environment.status_detail = {
        "checks": [{"name": item.name, "passed": item.passed, "detail": item.detail} for item in checks]
    }
    session.add(
        Event(
            employee_id=employee.id,
            event_type="ENVIRONMENT_CHECKED",
            phase="environment",
            message="Agent 工作环境检查完成",
            detail={"status": environment.status, **environment.status_detail},
        )
    )
    await session.commit()
    return {
        "status": environment.status,
        "checked_at": checked_at,
        "checks": environment.status_detail["checks"],
    }


@router.get("/employees/{employee_id}/usage")
async def get_employee_usage(
    employee_id: str,
    days: int = Query(default=7, ge=1, le=30),
    session: AsyncSession = Depends(get_session),
):
    await require_employee(employee_id, session)
    return await employee_usage(session, employee_id, days)


@router.post("/employees/{employee_id}/pause", response_model=EmployeeRead)
async def pause_employee(employee_id: str, session: AsyncSession = Depends(get_session)):
    employee = await require_employee(employee_id, session)
    if employee.current_task_count:
        raise HTTPException(status_code=409, detail="员工有当前任务，请先在任务详情中暂停或处理该任务")
    await EmployeeService(session).set_status(employee, EmployeeStatus.PAUSED)
    return employee


@router.post("/employees/{employee_id}/resume", response_model=EmployeeRead)
async def resume_employee(employee_id: str, session: AsyncSession = Depends(get_session)):
    employee = await require_employee(employee_id, session)
    target = EmployeeStatus.WORKING if employee.current_task_count else EmployeeStatus.IDLE
    await EmployeeService(session).set_status(employee, target)
    return employee


@router.get("/tasks", response_model=list[TaskRead])
async def list_tasks(
    q: str | None = None,
    source: str | None = None,
    task_type: str | None = None,
    category_id: str | None = None,
    task_status: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    employee_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    query = select(Task)
    if q:
        query = query.where(or_(Task.id.ilike(f"%{q}%"), Task.title.ilike(f"%{q}%")))
    if source:
        query = query.where(Task.source == source)
    if task_type:
        query = query.where(Task.task_type == task_type)
    if category_id:
        query = query.where(Task.category_id == category_id)
    if task_status:
        query = query.where(Task.status == task_status)
    if priority:
        query = query.where(Task.priority == priority)
    if employee_id:
        query = query.where(Task.employee_id == employee_id)
    if created_from:
        query = query.where(Task.created_at >= created_from)
    if created_to:
        query = query.where(Task.created_at <= created_to)
    return (await session.execute(query.order_by(desc(Task.created_at)).limit(limit))).scalars().all()


@router.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, session: AsyncSession = Depends(get_session)):
    category = await session.get(TaskCategory, payload.category_id)
    if not category or not category.enabled:
        raise HTTPException(status_code=422, detail="请选择已启用的任务分类")
    if payload.employee_id:
        employee = await require_employee(payload.employee_id, session)
        if not employee.enabled:
            raise HTTPException(status_code=409, detail="指定员工未启用")
        if payload.task_type.value not in employee.task_types:
            raise HTTPException(status_code=409, detail="指定员工不支持该任务类型")
        if payload.category_id not in employee.category_ids:
            raise HTTPException(status_code=409, detail="指定员工不支持该任务分类")
    try:
        return await TaskService(session).create(payload)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="来源任务已导入") from exc


@router.get("/tasks/{task_id}", response_model=TaskRead)
async def get_task(task_id: str, session: AsyncSession = Depends(get_session)):
    return await require_task(task_id, session)


async def transition_task(
    task: Task,
    target: TaskStatus,
    message: str,
    session: AsyncSession,
    payload: TaskAction | None = None,
    current_progress: str | None = None,
) -> Task:
    try:
        return await TaskService(session).transition(
            task,
            target,
            current_progress=current_progress,
            message=message,
            detail={"reason": payload.reason if payload else None, "note": payload.note if payload else None},
        )
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/pause", response_model=TaskRead)
async def pause_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    result = await RuntimeService(session).stop_task(
        task,
        target=TaskStatus.SUSPENDED,
        message="任务已由人工挂起",
        current_progress="任务已挂起",
        detail={"reason": payload.reason if payload else None, "note": payload.note if payload else None},
    )
    runtime_aborted = await _abort_opencode_session(result, session)
    if runtime_aborted:
        await TaskService(session).add_event(
            result,
            "OPENCODE_ABORTED",
            "runtime",
            "OpenCode Session 已中止",
            {"session_id": result.opencode_session_id, "reason": "pause"},
        )
    return result


@router.post("/tasks/{task_id}/resume", response_model=TaskRead)
async def resume_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {TaskStatus.WAIT_HUMAN, TaskStatus.SUSPENDED}:
        raise HTTPException(status_code=409, detail="只有等待人工或已挂起任务可以继续")
    task.human_required_reason = None
    if payload and payload.note:
        task.human_intervention = {
            **(task.human_intervention or {}),
            "response": payload.note,
            "responded_at": datetime.now(UTC).isoformat(),
        }
    if task.status == TaskStatus.SUSPENDED:
        task.suspension = {
            **(task.suspension or {}),
            "resume_note": payload.note if payload else None,
            "resumed_at": datetime.now(UTC).isoformat(),
        }
    if not task.employee_id:
        task.claimed_at = None
        return await transition_task(
            task,
            TaskStatus.READY,
            "任务已继续，等待员工领取",
            session,
            payload,
            "等待领取",
        )

    employee = await require_employee(task.employee_id, session)
    if (
        not employee.execution_environment
        or employee.execution_environment.status != EnvironmentStatus.AVAILABLE
    ):
        RuntimeService.release_employee(employee)
        task.claimed_at = None
        return await transition_task(
            task,
            TaskStatus.READY,
            "任务已继续，等待可用的员工工作环境",
            session,
            payload,
            "等待领取",
        )
    try:
        if task.status == TaskStatus.WAIT_HUMAN:
            try:
                run = await runtime.queue_waiting_run(
                    task,
                    employee,
                    current_progress="已收到回复，运行正在排队继续",
                    message="任务已收到人工回复并进入 Agent 队列",
                    detail={"note": payload.note if payload else None},
                )
            except RuntimeStateError:
                run = await runtime.queue_new_run(
                    task,
                    employee,
                    current_progress="已收到回复，新运行正在排队",
                    message="任务已收到人工回复并创建新运行",
                    detail={"note": payload.note if payload else None},
                )
        else:
            run = await runtime.queue_new_run(
                task,
                employee,
                current_progress="任务已恢复，新运行正在排队",
                message="已挂起任务创建新的继续运行",
                detail={"note": payload.note if payload else None, "resume": True},
            )
    except RuntimeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await runtime.enqueue(task, run)
    await session.refresh(task)
    return task


@router.post("/tasks/{task_id}/suspend", response_model=TaskRead)
async def suspend_task(
    task_id: str,
    payload: TaskSuspendWrite,
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
    task.suspension = {
        **payload.model_dump(),
        "employee_id": task.employee_id,
        "opencode_session_id": task.opencode_session_id,
        "last_activity_at": task.last_activity_at.isoformat() if task.last_activity_at else None,
        "suspended_at": datetime.now(UTC).isoformat(),
    }
    result = await RuntimeService(session).stop_task(
        task,
        target=TaskStatus.SUSPENDED,
        message="任务已安全挂起",
        current_progress=payload.current_state or task.current_progress,
        detail=payload.model_dump(),
    )
    runtime_aborted = await _abort_opencode_session(result, session)
    if runtime_aborted:
        await TaskService(session).add_event(
            result,
            "OPENCODE_ABORTED",
            "runtime",
            "OpenCode Session 已中止",
            {"session_id": result.opencode_session_id, "reason": "suspend"},
        )
    return result


@router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    result = await RuntimeService(session).stop_task(
        task,
        target=TaskStatus.CANCELLED,
        message="任务已由人工取消",
        current_progress="任务已取消",
        detail={"reason": payload.reason if payload else None, "note": payload.note if payload else None},
    )
    runtime_aborted = await _abort_opencode_session(result, session)
    if runtime_aborted:
        await TaskService(session).add_event(
            result,
            "OPENCODE_ABORTED",
            "runtime",
            "OpenCode Session 已中止",
            {"session_id": result.opencode_session_id, "reason": "cancel"},
        )
    return result


@router.post("/tasks/{task_id}/handoff", response_model=TaskRead)
async def handoff_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.human_required_reason = (payload.reason if payload else None) or "人工主动接管"
    task.human_intervention = {
        "blocking_reason": task.human_required_reason,
        "completed_work": "详见工作记录",
        "current_state": task.current_progress,
        "requested_input": (payload.note if payload else None) or "请人工检查并补充后继信息",
    }
    if task.employee_id:
        employee = await runtime.lock_employee(task.employee_id)
        run = await runtime.active_run(task.id)
        if employee and run:
            await runtime.mark_waiting(
                task,
                employee,
                run,
                current_progress="等待人工补充信息",
                message="任务已转人工处理",
            )
            return task
    return await transition_task(
        task,
        TaskStatus.WAIT_HUMAN,
        "任务已转人工处理",
        session,
        payload,
        "等待人工补充信息",
    )


@router.post("/tasks/{task_id}/start", response_model=TaskRead)
async def start_task(task_id: str, session: AsyncSession = Depends(get_session)):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if (
        task.status != TaskStatus.ASSIGNED
        and not (task.status == TaskStatus.READY and task.claimed_at)
    ) or not task.employee_id:
        raise HTTPException(status_code=409, detail="只有已分配且待启动的任务可以启动")
    employee = await require_employee(task.employee_id, session)
    if (
        not employee.execution_environment
        or employee.execution_environment.status != EnvironmentStatus.AVAILABLE
    ):
        raise HTTPException(status_code=409, detail="员工 Agent 工作环境不可用")
    try:
        run = await runtime.queue_new_run(
            task,
            employee,
            current_progress=f"{employee.name} 的运行已排队",
            message="人工启动任务，运行已进入 Agent 队列",
            detail={"dispatch": "manual"},
        )
    except RuntimeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await runtime.enqueue(task, run)
    await session.refresh(task)
    return task


@router.post("/tasks/{task_id}/progress", response_model=TaskRead)
async def report_task_progress(
    task_id: str,
    payload: TaskProgressUpdate,
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
    if task.status != TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="只有处理中的任务可以上报工作进展")
    task.current_progress = payload.current_progress
    await TaskService(session).add_event(
        task,
        "WORK_PROGRESS",
        "work",
        payload.current_progress,
    )
    await session.refresh(task)
    return task


@router.post("/tasks/{task_id}/request-human", response_model=TaskRead)
async def request_human_intervention(
    task_id: str,
    payload: HumanInterventionWrite,
    session: AsyncSession = Depends(get_session),
):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.human_required_reason = payload.blocking_reason
    task.human_intervention = payload.model_dump()
    target = TaskStatus.SUSPENDED if payload.can_suspend else TaskStatus.WAIT_HUMAN
    if payload.can_suspend:
        task.suspension = {
            "reason": payload.blocking_reason,
            "current_state": payload.current_state,
            "scene_context": payload.scene_context,
            "requested_input": payload.requested_input,
            "employee_id": task.employee_id,
            "opencode_session_id": task.opencode_session_id,
            "last_activity_at": task.last_activity_at.isoformat() if task.last_activity_at else None,
            "suspended_at": datetime.now(UTC).isoformat(),
        }
    if payload.can_suspend:
        result = await runtime.stop_task(
            task,
            target=TaskStatus.SUSPENDED,
            current_progress=payload.current_state or "任务已安全挂起",
            message="员工请求人工协助并安全挂起",
            detail=payload.model_dump(),
        )
        runtime_aborted = await _abort_opencode_session(result, session)
        if runtime_aborted:
            await TaskService(session).add_event(
                result,
                "OPENCODE_ABORTED",
                "runtime",
                "OpenCode Session 已中止",
                {"session_id": result.opencode_session_id, "reason": "request-human"},
            )
        return result
    if task.employee_id:
        employee = await runtime.lock_employee(task.employee_id)
        run = await runtime.active_run(task.id)
        if employee and run:
            await runtime.mark_waiting(
                task,
                employee,
                run,
                current_progress=payload.current_state or "等待人工补充信息",
                message="员工请求人工协助",
            )
            return task
    return await transition_task(
        task,
        target,
        "员工请求人工协助",
        session,
        current_progress=payload.current_state or "等待人工补充信息",
    )


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
async def complete_task(
    task_id: str,
    payload: TaskCompletionWrite,
    session: AsyncSession = Depends(get_session),
):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    expected_ids = {item["id"] for item in task.acceptance_criteria}
    actual_ids = {item.criterion_id for item in payload.acceptance_results}
    if actual_ids != expected_ids or len(payload.acceptance_results) != len(expected_ids):
        raise HTTPException(status_code=422, detail="验收结果必须与验收标准逐项对应")
    task.result = {
        **payload.result.model_dump(),
        "acceptance_results": [item.model_dump(mode="json") for item in payload.acceptance_results],
    }
    task.submitted_at = datetime.now(UTC)
    requires_confirmation = task.completion_policy == CompletionPolicy.MANUAL_CONFIRM
    target = TaskStatus.PENDING_CONFIRMATION if requires_confirmation else TaskStatus.COMPLETED
    if task.employee_id:
        employee = await runtime.lock_employee(task.employee_id)
        run = await runtime.active_run(task.id)
        if employee and run:
            run.result = {**(run.result or {}), "work_result": task.result}
            await runtime.finalize_run(
                task,
                employee,
                run,
                run_status=RunStatus.COMPLETED,
                task_status=target,
                current_progress=(
                    "结果已提交，等待确认" if requires_confirmation else "任务已完成"
                ),
                message=(
                    f"{task.employee_id} 已提交结果，等待确认"
                    if requires_confirmation
                    else f"{task.employee_id} 完成任务"
                ),
            )
            return task
    return await transition_task(
        task,
        target,
        (
            f"{task.employee_id or '数字员工'} 已提交结果，等待确认"
            if requires_confirmation
            else f"{task.employee_id or '数字员工'} 完成任务"
        ),
        session,
        current_progress="结果已提交，等待确认" if requires_confirmation else "任务已完成",
    )


@router.post("/tasks/{task_id}/confirm", response_model=TaskRead)
async def confirm_task(task_id: str, session: AsyncSession = Depends(get_session)):
    task = await require_task(task_id, session)
    if task.status != TaskStatus.PENDING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="只有待确认任务可以签收")
    task.confirmed_at = datetime.now(UTC)
    task.review_history = [
        *(task.review_history or []),
        {"action": "CONFIRMED", "created_at": task.confirmed_at.isoformat()},
    ]
    return await transition_task(
        task,
        TaskStatus.COMPLETED,
        "任务结果已确认签收",
        session,
        current_progress="任务已确认完成",
    )


@router.post("/tasks/{task_id}/reject", response_model=TaskRead)
async def reject_task(
    task_id: str,
    payload: TaskRejectWrite,
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
    if task.status != TaskStatus.PENDING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="只有待确认任务可以退回继续")
    task.review_history = [
        *(task.review_history or []),
        {
            "action": "REJECTED",
            "feedback": payload.feedback,
            "submitted_result": task.result,
            "created_at": datetime.now(UTC).isoformat(),
        },
    ]
    task.human_intervention = {
        "response": payload.feedback,
        "responded_at": datetime.now(UTC).isoformat(),
        "blocking_reason": "结果被退回继续",
        "completed_work": task.result.get("summary", "") if task.result else "",
        "current_state": "等待原员工接续处理",
        "requested_input": payload.feedback,
    }
    task.result = None
    task.submitted_at = None
    task.confirmed_at = None
    task.claimed_at = None
    result = await transition_task(
        task,
        TaskStatus.READY,
        "任务结果已退回，将由原员工继续处理",
        session,
        current_progress=f"结果已退回：{payload.feedback}",
    )
    return result


@router.post("/tasks/{task_id}/recover", response_model=TaskRead)
async def recover_task(task_id: str, session: AsyncSession = Depends(get_session)):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.EXECUTION_ERROR or not task.employee_id:
        raise HTTPException(status_code=409, detail="只有已分配的执行异常任务可以恢复")
    employee = await require_employee(task.employee_id, session)
    if not environment_checked_after_error(task, employee):
        raise HTTPException(status_code=409, detail="请先重新测试员工工作环境，确认异常已恢复")
    task.execution_error = {
        **(task.execution_error or {}),
        "recovered_at": datetime.now(UTC).isoformat(),
    }
    try:
        run = await runtime.queue_new_run(
            task,
            employee,
            current_progress="执行环境已恢复，运行正在排队",
            message="执行环境已恢复，创建继续运行",
            detail={"recovery": "manual"},
        )
    except RuntimeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await runtime.enqueue(task, run)
    await session.refresh(task)
    return task


@router.post("/tasks/{task_id}/rerun", response_model=TaskRead)
async def rerun_task(task_id: str, session: AsyncSession = Depends(get_session)):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.EXECUTION_ERROR,
    }:
        raise HTTPException(status_code=409, detail="只有已完成或失败的任务可以重新执行")
    if not task.employee_id:
        raise HTTPException(status_code=409, detail="任务没有可重新执行的员工")
    employee = await require_employee(task.employee_id, session)
    if employee.status in {EmployeeStatus.OFFLINE, EmployeeStatus.PAUSED}:
        raise HTTPException(status_code=409, detail="原员工当前不可用")
    if (
        not employee.execution_environment
        or employee.execution_environment.status != EnvironmentStatus.AVAILABLE
    ):
        raise HTTPException(status_code=409, detail="原员工的 Agent 工作环境不可用")

    previous_run = await session.scalar(
        select(Run).where(Run.task_id == task.id).order_by(Run.run_number.desc()).limit(1)
    )
    now = datetime.now(UTC)
    task.review_history = [
        *(task.review_history or []),
        {
            "action": "RERUN",
            "previous_run_id": previous_run.id if previous_run else None,
            "previous_result": task.result,
            "created_at": now.isoformat(),
        },
    ]
    task.result = None
    task.submitted_at = None
    task.confirmed_at = None
    task.failure_reason = None
    task.execution_error = None
    task.human_required_reason = None
    try:
        run = await runtime.queue_new_run(
            task,
            employee,
            current_progress="重新执行已排队",
            message="用户发起重新执行，已创建全新运行",
            detail={"rerun": True, "previous_run_id": previous_run.id if previous_run else None},
            reset_runtime_session=True,
        )
    except RuntimeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await runtime.enqueue(task, run)
    await session.refresh(task)
    return task


@router.post("/tasks/{task_id}/fail", response_model=TaskRead)
async def fail_task(
    task_id: str,
    payload: TaskAction,
    session: AsyncSession = Depends(get_session),
):
    runtime = RuntimeService(session)
    task = await runtime.lock_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.failure_reason = payload.reason or "数字员工未能完成任务"
    if task.employee_id:
        employee = await runtime.lock_employee(task.employee_id)
        run = await runtime.active_run(task.id)
        if employee and run:
            await runtime.finalize_run(
                task,
                employee,
                run,
                run_status=RunStatus.FAILED,
                task_status=TaskStatus.FAILED,
                current_progress="任务未完成",
                message="数字员工提交任务未完成",
                failure_type="BUSINESS_FAILURE",
            )
            return task
    return await transition_task(
        task,
        TaskStatus.FAILED,
        "数字员工提交任务未完成",
        session,
        payload,
        "任务未完成",
    )


@router.get("/tasks/{task_id}/runs", response_model=list[RunRead])
async def task_runs(task_id: str, session: AsyncSession = Depends(get_session)):
    await require_task(task_id, session)
    return (
        (await session.execute(select(Run).where(Run.task_id == task_id).order_by(Run.run_number.desc())))
        .scalars()
        .all()
    )


@router.get("/runs", response_model=list[RunRead])
async def list_runs(session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(Run).order_by(Run.created_at.desc()).limit(200))).scalars().all()


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@router.get("/runs/{run_id}/usage")
async def get_run_usage(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {
        "summary": await summarize_runs(session, [run]),
        "tools": await tool_breakdown(session, [run]),
    }


@router.get("/runs/{run_id}/events", response_model=list[EventRead])
async def run_events(run_id: str, session: AsyncSession = Depends(get_session)):
    """Expose the per-run event history for the status trajectory panel.

    The Event table already carries run_id for lifecycle transitions (task
    status changes, recovery syncs, run orphan detection). This is a pure read
    surface for the Run detail drawer so the frontend can build a real state
    timeline without inventing data.
    """
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return (
        (await session.execute(select(Event).where(Event.run_id == run_id).order_by(Event.created_at)))
        .scalars()
        .all()
    )


@router.get("/tasks/{task_id}/usage")
async def get_task_usage(task_id: str, session: AsyncSession = Depends(get_session)):
    await require_task(task_id, session)
    return await task_usage(session, task_id)


@router.get("/tasks/{task_id}/events", response_model=list[EventRead])
async def task_events(task_id: str, session: AsyncSession = Depends(get_session)):
    await require_task(task_id, session)
    return (
        (await session.execute(select(Event).where(Event.task_id == task_id).order_by(Event.created_at)))
        .scalars()
        .all()
    )


@router.get("/events", response_model=list[EventRead])
async def list_events(limit: int = Query(50, ge=1, le=500), session: AsyncSession = Depends(get_session)):
    return (
        (await session.execute(select(Event).order_by(Event.created_at.desc()).limit(limit))).scalars().all()
    )


@router.get("/tasks/{task_id}/evidence", response_model=list[EvidenceRead])
async def task_evidence(task_id: str, session: AsyncSession = Depends(get_session)):
    await require_task(task_id, session)
    return (
        (
            await session.execute(
                select(Evidence).where(Evidence.task_id == task_id).order_by(Evidence.created_at)
            )
        )
        .scalars()
        .all()
    )


@router.get("/tasks/{task_id}/workspace", response_model=TaskWorkbenchRead)
async def task_workbench(
    task_id: str,
    before_sequence: int | None = Query(default=None, ge=1),
    event_limit: int = Query(default=120, ge=20, le=300),
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
    return await load_task_workbench(
        task,
        session,
        before_sequence=before_sequence,
        event_limit=event_limit,
    )


async def continue_task_with_message(task: Task, content: str, session: AsyncSession) -> None:
    task.human_intervention = {
        **(task.human_intervention or {}),
        "response": content,
        "responded_at": datetime.now(UTC).isoformat(),
    }
    if task.status in {TaskStatus.WAIT_HUMAN, TaskStatus.SUSPENDED}:
        await resume_task(task.id, TaskAction(note=content), session)
        return
    if task.status == TaskStatus.PENDING_CONFIRMATION:
        await reject_task(task.id, TaskRejectWrite(feedback=content), session)
        return
    if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        await session.commit()
        return

    runtime = RuntimeService(session)
    task = await runtime.lock_task(task.id) or task
    now = datetime.now(UTC)
    task.review_history = [
        *(task.review_history or []),
        {
            "action": "CONTINUED",
            "feedback": content,
            "previous_result": task.result,
            "created_at": now.isoformat(),
        },
    ]
    task.submitted_at = None
    task.confirmed_at = None
    task.failure_reason = None
    employee = None
    if task.employee_id:
        employee = await require_employee(task.employee_id, session)
        if (
            employee.execution_environment
            and employee.execution_environment.status == EnvironmentStatus.AVAILABLE
            and employee.status not in {EmployeeStatus.OFFLINE, EmployeeStatus.PAUSED}
        ):
            try:
                run = await runtime.queue_new_run(
                    task,
                    employee,
                    message="用户在同一会话中提出继续处理要求",
                    current_progress=f"已收到后续要求，运行已排队：{content[:200]}",
                    detail={"note": content, "continue": True},
                )
            except RuntimeStateError:
                return
            await runtime.enqueue(task, run)
            return
    task.claimed_at = None
    await TaskService(session).reopen(
        task,
        TaskStatus.READY,
        message="用户提出继续处理要求，等待员工领取",
        current_progress=f"已收到后续要求：{content[:240]}",
        detail={"note": content},
    )


@router.post("/tasks/{task_id}/messages", response_model=TaskWorkbenchRead)
async def post_task_message(
    task_id: str,
    payload: SessionMessageWrite,
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
    content = payload.content.strip()
    command = content.split(maxsplit=1)[0].lower() if content.startswith("/") else ""
    informational_commands = {"/status", "/agents", "/files"}
    control_commands = {"/pause", "/stop"}
    task_session = await ensure_task_session(session, task)
    active_inquiry = await session.scalar(
        select(RunInquiry)
        .where(
            RunInquiry.session_id == task_session.id,
            RunInquiry.status.in_(["OPEN", "PENDING"]),
        )
        .order_by(RunInquiry.created_at.desc())
    )
    message_status = (
        "APPLIED"
        if command in informational_commands | control_commands
        else "ANSWERED"
        if active_inquiry and not command
        else "PENDING"
        if task.status == TaskStatus.RUNNING
        else "QUEUED"
    )
    workbench_service = WorkbenchService(session)
    inquiry_command_blocked = bool(
        active_inquiry and command and command not in informational_commands | {"/stop"}
    )
    await workbench_service.add_message(
        task,
        content,
        status=message_status,
        run_id=active_inquiry.run_id if active_inquiry and not command else None,
        commit=False,
    )
    if not command:
        await workbench_service.answer_inquiry(task, content, commit=False)
    if active_inquiry and command == "/stop":
        active_inquiry.status = "CANCELLED"
    if command in informational_commands:
        if command == "/status":
            response = f"当前任务状态：{task.status}；当前进展：{task.current_progress}"
        elif command == "/agents":
            response = f"主 Agent：{task.employee_id or '等待分配'}。Subagent 仅在运行时产生真实事件后展示。"
        else:
            evidence_names = (
                (
                    await session.execute(
                        select(Evidence.name).where(Evidence.task_id == task.id).order_by(Evidence.created_at)
                    )
                )
                .scalars()
                .all()
            )
            result_files = task.result.get("files", []) if task.result else []
            file_names = list(dict.fromkeys([*evidence_names, *result_files]))
            response = "当前产物：" + ("、".join(file_names) if file_names else "尚未生成产物")
        await workbench_service.add_message(
            task,
            response,
            role="agent",
            status="APPLIED",
            commit=False,
        )
    elif inquiry_command_blocked:
        await workbench_service.add_message(
            task,
            "当前仍在等待你的业务回答，请直接输入答案后再使用其他执行命令。",
            role="agent",
            status="APPLIED",
            run_id=active_inquiry.run_id if active_inquiry else None,
            commit=False,
        )
    await session.commit()

    if command == "/pause" and task.status in {
        TaskStatus.ASSIGNED,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
    }:
        await pause_task(task.id, TaskAction(reason="用户通过会话暂停"), session)
    elif command == "/stop" and task.status not in {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }:
        await cancel_task(task.id, TaskAction(reason="用户通过会话终止"), session)
    elif command in informational_commands:
        pass
    elif inquiry_command_blocked:
        pass
    elif command == "/retry" and task.status == TaskStatus.EXECUTION_ERROR:
        await recover_task(task.id, session)
    else:
        await continue_task_with_message(task, content, session)
    await session.refresh(task)
    return await load_task_workbench(task, session)


@router.get("/sessions/{session_id}", response_model=TaskWorkbenchRead)
async def get_session_workbench(
    session_id: str,
    before_sequence: int | None = Query(default=None, ge=1),
    event_limit: int = Query(default=120, ge=20, le=300),
    session: AsyncSession = Depends(get_session),
):
    work_session = await session.get(TaskSession, session_id)
    if not work_session:
        raise HTTPException(status_code=404, detail="任务会话不存在")
    task = await require_task(work_session.task_id, session)
    return await load_task_workbench(
        task,
        session,
        before_sequence=before_sequence,
        event_limit=event_limit,
    )


@router.get("/sessions/{session_id}/events", response_model=list[RuntimeEventRead])
async def get_session_events(
    session_id: str,
    before_sequence: int | None = Query(default=None, ge=1),
    limit: int = Query(default=120, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
):
    work_session = await session.get(TaskSession, session_id)
    if not work_session:
        raise HTTPException(status_code=404, detail="任务会话不存在")
    await require_task(work_session.task_id, session)
    query = select(Event).where(Event.task_id == work_session.task_id)
    if before_sequence is not None:
        query = query.where(Event.id < before_sequence)
    rows = (await session.execute(query.order_by(Event.id.desc()).limit(limit))).scalars().all()
    return runtime_events(list(reversed(rows)), work_session)


@router.post("/sessions/{session_id}/messages", response_model=TaskWorkbenchRead)
async def post_session_message(
    session_id: str,
    payload: SessionMessageWrite,
    session: AsyncSession = Depends(get_session),
):
    work_session = await session.get(TaskSession, session_id)
    if not work_session:
        raise HTTPException(status_code=404, detail="任务会话不存在")
    return await post_task_message(work_session.task_id, payload, session)


@router.post("/inquiries/{inquiry_id}/answer", response_model=TaskWorkbenchRead)
async def answer_inquiry(
    inquiry_id: str,
    payload: InquiryAnswerWrite,
    session: AsyncSession = Depends(get_session),
):
    inquiry = await session.get(RunInquiry, inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="确认问题不存在")
    if inquiry.status not in {"OPEN", "PENDING"}:
        raise HTTPException(status_code=409, detail="确认问题已处理")
    work_session = await session.get(TaskSession, inquiry.session_id)
    if not work_session:
        raise HTTPException(status_code=404, detail="任务会话不存在")
    return await post_task_message(work_session.task_id, SessionMessageWrite(content=payload.answer), session)


def task_event_stream(
    task_id: str, work_session: TaskSession, after_sequence: int | None
) -> StreamingResponse:
    async def generate():
        yield f"event: connected\ndata: {json.dumps({'session_id': work_session.id})}\n\n"
        keepalive_ticks = 0
        async with SessionLocal() as stream_session:
            last_id = after_sequence
            if last_id is None:
                last_id = (
                    await stream_session.scalar(select(func.max(Event.id)).where(Event.task_id == task_id))
                    or 0
                )
            while True:
                await asyncio.sleep(1)
                rows = (
                    (
                        await stream_session.execute(
                            select(Event)
                            .where(Event.task_id == task_id, Event.id > last_id)
                            .order_by(Event.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                if rows:
                    keepalive_ticks = 0
                    for event in rows:
                        last_id = event.id
                        payload = runtime_event(event, work_session).model_dump(mode="json")
                        yield f"event: update\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                else:
                    keepalive_ticks += 1
                if keepalive_ticks >= 15:
                    keepalive_ticks = 0
                    yield ": keepalive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks/{task_id}/workspace/stream")
async def task_workbench_stream(
    task_id: str,
    after_sequence: int | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
    work_session = await ensure_task_session(session, task)
    await session.commit()
    return task_event_stream(task.id, work_session, after_sequence)


@router.get("/sessions/{session_id}/events/stream")
async def session_event_stream(
    session_id: str,
    after_sequence: int | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_session),
):
    work_session = await session.get(TaskSession, session_id)
    if not work_session:
        raise HTTPException(status_code=404, detail="任务会话不存在")
    return task_event_stream(work_session.task_id, work_session, after_sequence)


@router.get("/events/stream")
async def event_stream() -> StreamingResponse:
    async def generate():
        yield "event: connected\ndata: {}\n\n"
        keepalive_ticks = 0
        async with SessionLocal() as stream_session:
            last_id = await stream_session.scalar(select(func.max(Event.id))) or 0
            while True:
                await asyncio.sleep(1)
                rows = (
                    (await stream_session.execute(select(Event).where(Event.id > last_id).order_by(Event.id)))
                    .scalars()
                    .all()
                )
                if rows:
                    keepalive_ticks = 0
                    for event in rows:
                        last_id = event.id
                        payload = {
                            "id": event.id,
                            "type": event.event_type,
                            "task_id": event.task_id,
                            "employee_id": event.employee_id,
                            "phase": event.phase,
                            "message": event.message,
                            "created_at": event.created_at.isoformat(),
                        }
                        yield f"event: update\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                else:
                    keepalive_ticks += 1
                if keepalive_ticks >= 15:
                    keepalive_ticks = 0
                    yield ": keepalive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/evidence/{evidence_id}/content")
async def evidence_content(evidence_id: int, session: AsyncSession = Depends(get_session)):
    evidence = await session.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="证据不存在")
    # Deliberately do not expose arbitrary employee workspace files through a generic file server.
    return Response(
        content=json.dumps({"name": evidence.name, "path": evidence.path, "size": evidence.size}),
        media_type="application/json",
    )

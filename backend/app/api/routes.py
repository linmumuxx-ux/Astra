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

from app.database import SessionLocal, get_session
from app.domain import CompletionPolicy, EmployeeStatus, EnvironmentStatus, TaskStatus
from app.models import (
    DigitalEmployee,
    Event,
    Evidence,
    OpenCodeExecutionEnvironment,
    Run,
    Task,
    TaskCategory,
)
from app.runtime.environment import CheckItem, ExecutionEnvironmentRuntime, checks_status
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
    RunRead,
    TaskAction,
    TaskCategoryCreate,
    TaskCategoryPatch,
    TaskCategoryRead,
    TaskCompletionWrite,
    TaskCreate,
    TaskProgressUpdate,
    TaskRead,
    TaskRejectWrite,
    TaskSuspendWrite,
)
from app.services import EmployeeService, TaskService, dashboard_metrics
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
    for key, value in payload.model_dump().items():
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


async def enqueue_running_task(task: Task, session: AsyncSession) -> Task:
    try:
        from app.runtime.celery_app import process_task

        process_task.delay(task.id)
    except Exception as exc:
        task.human_required_reason = f"运行队列不可用: {exc}"
        result = await TaskService(session).transition(
            task,
            TaskStatus.WAIT_HUMAN,
            current_progress="运行队列不可用，等待人工处理",
            message="任务已恢复，但运行队列不可用",
            detail={"error": str(exc)},
        )
        if task.employee_id:
            employee = await session.get(DigitalEmployee, task.employee_id)
            if employee:
                employee.status = EmployeeStatus.WAIT_HUMAN
                await session.commit()
        return result
    return task


@router.post("/tasks/{task_id}/pause", response_model=TaskRead)
async def pause_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    result = await transition_task(
        task,
        TaskStatus.SUSPENDED,
        "任务已由人工挂起",
        session,
        payload,
        "任务已挂起",
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.IDLE
            employee.current_task_count = max(0, employee.current_task_count - 1)
            await session.commit()
    return result


@router.post("/tasks/{task_id}/resume", response_model=TaskRead)
async def resume_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    queue_for_employee = task.status == TaskStatus.SUSPENDED
    target = TaskStatus.READY if queue_for_employee or not task.employee_id else TaskStatus.RUNNING
    task.human_required_reason = None
    if payload and payload.note:
        task.human_intervention = {
            **(task.human_intervention or {}),
            "response": payload.note,
            "responded_at": datetime.now(UTC).isoformat(),
        }
    if queue_for_employee:
        task.claimed_at = None
        task.suspension = {
            **(task.suspension or {}),
            "resume_note": payload.note if payload else None,
            "resumed_at": datetime.now(UTC).isoformat(),
        }
    result = await transition_task(
        task,
        target,
        "任务已继续",
        session,
        payload,
        "已恢复并进入员工任务队列"
        if queue_for_employee
        else ("员工已继续处理" if task.employee_id else "等待领取"),
    )
    if target is TaskStatus.RUNNING and task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.WORKING
            employee.current_task_count = 1
            await session.commit()
        result = await enqueue_running_task(task, session)
    return result


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
    result = await transition_task(
        task,
        TaskStatus.SUSPENDED,
        "任务已安全挂起",
        session,
        current_progress=payload.current_state or task.current_progress,
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.IDLE
            employee.current_task_count = max(0, employee.current_task_count - 1)
            await session.commit()
    return result


@router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    result = await transition_task(
        task,
        TaskStatus.CANCELLED,
        "任务已由人工取消",
        session,
        payload,
        "任务已取消",
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.current_task_count = max(0, employee.current_task_count - 1)
            employee.status = EmployeeStatus.IDLE
            await session.commit()
    return result


@router.post("/tasks/{task_id}/handoff", response_model=TaskRead)
async def handoff_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    task.human_required_reason = (payload.reason if payload else None) or "人工主动接管"
    task.human_intervention = {
        "blocking_reason": task.human_required_reason,
        "completed_work": "详见工作记录",
        "current_state": task.current_progress,
        "requested_input": (payload.note if payload else None) or "请人工检查并补充后继信息",
    }
    result = await transition_task(
        task,
        TaskStatus.WAIT_HUMAN,
        "任务已转人工处理",
        session,
        payload,
        "等待人工补充信息",
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.WAIT_HUMAN
            await session.commit()
    return result


@router.post("/tasks/{task_id}/start", response_model=TaskRead)
async def start_task(task_id: str, session: AsyncSession = Depends(get_session)):
    task = await require_task(task_id, session)
    if task.status != TaskStatus.READY or not task.employee_id:
        raise HTTPException(status_code=409, detail="只有已分配且待领取的任务可以启动")
    employee = await require_employee(task.employee_id, session)
    if (
        not employee.execution_environment
        or employee.execution_environment.status != EnvironmentStatus.AVAILABLE
    ):
        raise HTTPException(status_code=409, detail="员工 Agent 工作环境不可用")
    employee.status = EmployeeStatus.WORKING
    employee.current_task_count = 1
    result = await transition_task(
        task,
        TaskStatus.RUNNING,
        "员工开始处理任务",
        session,
        current_progress=f"{employee.name} 已开始处理",
    )
    return await enqueue_running_task(result, session)


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
    task = await require_task(task_id, session)
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
    result = await transition_task(
        task,
        target,
        "员工请求人工协助并安全挂起" if payload.can_suspend else "员工请求人工协助",
        session,
        current_progress=payload.current_state or "等待人工补充信息",
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.IDLE if payload.can_suspend else EmployeeStatus.WAIT_HUMAN
            if payload.can_suspend:
                employee.current_task_count = max(0, employee.current_task_count - 1)
            await session.commit()
    return result


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
async def complete_task(
    task_id: str,
    payload: TaskCompletionWrite,
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
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
    result = await transition_task(
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
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.current_task_count = max(0, employee.current_task_count - 1)
            employee.status = EmployeeStatus.IDLE
            await session.commit()
    return result


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
    task = await require_task(task_id, session)
    if task.status != TaskStatus.EXECUTION_ERROR or not task.employee_id:
        raise HTTPException(status_code=409, detail="只有已分配的执行异常任务可以恢复")
    employee = await require_employee(task.employee_id, session)
    if not environment_checked_after_error(task, employee):
        raise HTTPException(status_code=409, detail="请先重新测试员工工作环境，确认异常已恢复")
    employee.status = EmployeeStatus.WORKING
    employee.current_task_count = 1
    task.execution_error = {
        **(task.execution_error or {}),
        "recovered_at": datetime.now(UTC).isoformat(),
    }
    result = await transition_task(
        task,
        TaskStatus.RUNNING,
        "执行环境已恢复，继续原任务",
        session,
        current_progress="正在恢复原 Agent 会话",
    )
    return await enqueue_running_task(result, session)


@router.post("/tasks/{task_id}/fail", response_model=TaskRead)
async def fail_task(
    task_id: str,
    payload: TaskAction,
    session: AsyncSession = Depends(get_session),
):
    task = await require_task(task_id, session)
    task.failure_reason = payload.reason or "数字员工未能完成任务"
    result = await transition_task(
        task,
        TaskStatus.FAILED,
        "数字员工提交任务未完成",
        session,
        payload,
        "任务未完成",
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.current_task_count = max(0, employee.current_task_count - 1)
            employee.status = EmployeeStatus.IDLE
            await session.commit()
    return result


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

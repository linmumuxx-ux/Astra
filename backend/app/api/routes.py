import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, get_session
from app.domain import EmployeeStatus, TaskStatus
from app.models import DigitalEmployee, Event, Evidence, Run, Task
from app.schemas import (
    EmployeeCreate,
    EmployeePatch,
    EmployeeRead,
    EventRead,
    EvidenceRead,
    RunRead,
    TaskAction,
    TaskCreate,
    TaskRead,
)
from app.services import EmployeeService, TaskService, dashboard_metrics
from app.state_machine import InvalidTransition

router = APIRouter(prefix="/api")


async def require_task(task_id: str, session: AsyncSession) -> Task:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


async def require_employee(employee_id: str, session: AsyncSession) -> DigitalEmployee:
    employee = await session.get(DigitalEmployee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="数字员工不存在")
    return employee


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(select(1))
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


@router.get("/system/metrics")
async def metrics(session: AsyncSession = Depends(get_session)) -> dict:
    return await dashboard_metrics(session)


@router.get("/employees", response_model=list[EmployeeRead])
async def list_employees(session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(DigitalEmployee).order_by(DigitalEmployee.id))).scalars().all()


@router.post("/employees", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
async def create_employee(payload: EmployeeCreate, session: AsyncSession = Depends(get_session)):
    employee = DigitalEmployee(
        **payload.model_dump(),
        status=EmployeeStatus.IDLE,
        online_since=datetime.now(UTC),
        last_heartbeat=datetime.now(UTC),
    )
    session.add(employee)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="员工 ID 已存在") from exc
    await session.refresh(employee)
    return employee


@router.get("/employees/{employee_id}", response_model=EmployeeRead)
async def get_employee(employee_id: str, session: AsyncSession = Depends(get_session)):
    return await require_employee(employee_id, session)


@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
async def patch_employee(
    employee_id: str, payload: EmployeePatch, session: AsyncSession = Depends(get_session)
):
    employee = await require_employee(employee_id, session)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(employee, key, value)
    await session.commit()
    await session.refresh(employee)
    return employee


@router.post("/employees/{employee_id}/pause", response_model=EmployeeRead)
async def pause_employee(employee_id: str, session: AsyncSession = Depends(get_session)):
    employee = await require_employee(employee_id, session)
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
    task_status: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    employee_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    query = select(Task)
    if q:
        query = query.where(or_(Task.id.ilike(f"%{q}%"), Task.title.ilike(f"%{q}%")))
    if source:
        query = query.where(Task.source == source)
    if task_status:
        query = query.where(Task.status == task_status)
    if priority:
        query = query.where(Task.priority == priority)
    if employee_id:
        query = query.where(Task.employee_id == employee_id)
    return (
        (await session.execute(query.order_by(desc(Task.created_at)).limit(limit))).scalars().all()
    )


@router.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, session: AsyncSession = Depends(get_session)):
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
    phase: str,
    message: str,
    session: AsyncSession,
    payload: TaskAction | None = None,
) -> Task:
    if payload and payload.input_patch:
        task.input = {**task.input, **payload.input_patch}
    try:
        return await TaskService(session).transition(
            task,
            target,
            phase=phase,
            progress=task.progress,
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
            phase="runtime_queue",
            progress=task.progress,
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
        task, TaskStatus.PAUSED, "paused", "任务已由人工暂停", session, payload
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.PAUSED
            await session.commit()
    return result


@router.post("/tasks/{task_id}/resume", response_model=TaskRead)
async def resume_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    target = TaskStatus.RUNNING if task.employee_id else TaskStatus.READY
    result = await transition_task(task, target, "resuming", "任务已继续", session, payload)
    if target is TaskStatus.RUNNING and task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.WORKING
            await session.commit()
        result = await enqueue_running_task(task, session)
    return result


@router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    result = await transition_task(
        task, TaskStatus.CANCELLED, "cancelled", "任务已由人工终止", session, payload
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
    result = await transition_task(
        task, TaskStatus.WAIT_HUMAN, "human_handoff", "任务已转人工处理", session, payload
    )
    if task.employee_id:
        employee = await session.get(DigitalEmployee, task.employee_id)
        if employee:
            employee.status = EmployeeStatus.WAIT_HUMAN
            await session.commit()
    return result


@router.post("/tasks/{task_id}/retry", response_model=TaskRead)
async def retry_task(
    task_id: str, payload: TaskAction | None = None, session: AsyncSession = Depends(get_session)
):
    task = await require_task(task_id, session)
    if task.status == TaskStatus.FAILED:
        await transition_task(task, TaskStatus.RETRY, "manual_retry", "人工触发任务重试", session, payload)
        target = TaskStatus.RUNNING if task.employee_id else TaskStatus.READY
    elif task.status == TaskStatus.WAIT_HUMAN and not task.employee_id:
        target = TaskStatus.READY
    else:
        target = TaskStatus.RUNNING
    task.human_required_reason = None
    result = await transition_task(
        task, target, "manual_retry", "任务已进入人工重试流程", session, payload
    )
    if target is TaskStatus.RUNNING:
        result = await enqueue_running_task(task, session)
    return result


@router.get("/tasks/{task_id}/runs", response_model=list[RunRead])
async def task_runs(task_id: str, session: AsyncSession = Depends(get_session)):
    await require_task(task_id, session)
    return (
        (
            await session.execute(
                select(Run).where(Run.task_id == task_id).order_by(Run.run_number.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/runs", response_model=list[RunRead])
async def list_runs(session: AsyncSession = Depends(get_session)):
    return (
        (await session.execute(select(Run).order_by(Run.created_at.desc()).limit(200))).scalars().all()
    )


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@router.get("/tasks/{task_id}/events", response_model=list[EventRead])
async def task_events(task_id: str, session: AsyncSession = Depends(get_session)):
    await require_task(task_id, session)
    return (
        (
            await session.execute(
                select(Event).where(Event.task_id == task_id).order_by(Event.created_at)
            )
        )
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
                    (
                        await stream_session.execute(
                            select(Event).where(Event.id > last_id).order_by(Event.id)
                        )
                    )
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
    # Deliberately do not expose arbitrary task workspace files through a generic file server.
    return Response(
        content=json.dumps({"name": evidence.name, "path": evidence.path, "size": evidence.size}),
        media_type="application/json",
    )

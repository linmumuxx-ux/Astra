import asyncio

from celery import Celery

from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.runtime.coordinator import TaskCoordinator
from app.runtime.dispatcher import Dispatcher
from app.runtime.heartbeat import heartbeat_active_employees, mark_stale_employees_offline
from app.runtime.scout import TaskScout
from app.sources.nr_test_system import NrTestSystemSource

settings = get_settings()
celery = Celery("astra", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    beat_schedule={
        "astra-scout": {"task": "astra.scout", "schedule": settings.scout_interval},
        "astra-dispatch": {"task": "astra.dispatch", "schedule": settings.dispatcher_interval},
        "astra-heartbeat-check": {
            "task": "astra.heartbeat-check",
            "schedule": settings.heartbeat_interval,
        },
        "astra-employee-heartbeat": {
            "task": "astra.employee-heartbeat",
            "schedule": settings.heartbeat_interval,
        },
    },
)


def run_async(coro):
    return asyncio.run(coro)


@celery.task(name="astra.scout")
def scout() -> list[str]:
    async def execute():
        await init_database()
        async with SessionLocal() as session:
            return await TaskScout(session, [NrTestSystemSource(settings)]).poll_once()

    return run_async(execute())


@celery.task(name="astra.dispatch")
def dispatch() -> str | None:
    async def execute():
        await init_database()
        async with SessionLocal() as session:
            task = await Dispatcher(session).claim_once()
            return task.id if task else None

    task_id = run_async(execute())
    if task_id:
        process_task.delay(task_id)
    return task_id


@celery.task(name="astra.process-task")
def process_task(task_id: str) -> None:
    run_async(TaskCoordinator().process(task_id))


@celery.task(name="astra.heartbeat-check")
def heartbeat_check() -> list[str]:
    async def execute():
        async with SessionLocal() as session:
            return await mark_stale_employees_offline(session, settings)

    return run_async(execute())


@celery.task(name="astra.employee-heartbeat")
def employee_heartbeat() -> list[str]:
    async def execute():
        async with SessionLocal() as session:
            return await heartbeat_active_employees(session)

    return run_async(execute())

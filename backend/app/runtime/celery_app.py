import asyncio

from celery import Celery

from app.config.settings import get_settings
from app.database import init_database, worker_session
from app.runtime.dispatcher import Dispatcher
from app.runtime.heartbeat import heartbeat_active_employees, mark_stale_employees_offline
from app.runtime.lifecycle import RuntimeService
from app.runtime.scout import TaskScout
from app.sources.nr_test_system import NrTestSystemSource

settings = get_settings()
celery = Celery("astra", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    task_default_queue="control",
    task_routes={
        "astra.scout": {"queue": "control"},
        "astra.dispatch": {"queue": "control"},
        "astra.heartbeat-check": {"queue": "control"},
        "astra.employee-heartbeat": {"queue": "control"},
    },
    beat_schedule={
        "astra-library-sync": {"task": "astra.library-sync", "schedule": 5},
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

_loop: asyncio.AbstractEventLoop | None = None


def run_async(coro):
    """Run Celery async work on one persistent loop.

    SQLAlchemy's async engine and its pool retain loop-bound futures. Reusing the
    loop also preserves Windows' default Proactor implementation, which is
    required by ``asyncio.create_subprocess_exec``.
    """

    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


@celery.task(name="astra.scout")
def scout() -> list[str]:
    async def execute():
        await init_database()
        async with worker_session() as session:
            return await TaskScout(session, [NrTestSystemSource(settings)]).poll_once()

    return run_async(execute())


@celery.task(name="astra.dispatch")
def dispatch() -> str | None:
    async def execute():
        await init_database()
        async with worker_session() as session:
            task = await Dispatcher(session).claim_once()
            if not task:
                return None
            if task.employee_id:
                from app.models import DigitalEmployee
                employee = await session.get(DigitalEmployee, task.employee_id)
                if employee.auto_execute:
                    await RuntimeService(session).start(task.id)
            return task.id

    return run_async(execute())


@celery.task(name="astra.heartbeat-check")
def heartbeat_check() -> list[str]:
    async def execute():
        async with worker_session() as session:
            return await mark_stale_employees_offline(session, settings)

    return run_async(execute())


@celery.task(name="astra.employee-heartbeat")
def employee_heartbeat() -> list[str]:
    async def execute():
        async with worker_session() as session:
            return await heartbeat_active_employees(session)

    return run_async(execute())



@celery.task(name="astra.library-sync")
def library_sync() -> int:
    from app.library_sync import sync_pending

    async def execute():
        await init_database()
        async with worker_session() as session:
            return await sync_pending(session, settings)

    return run_async(execute())

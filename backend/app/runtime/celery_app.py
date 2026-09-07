import asyncio

from celery import Celery

from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.runtime.dispatcher import Dispatcher
from app.runtime.heartbeat import heartbeat_active_employees, mark_stale_employees_offline
from app.runtime.lifecycle import RuntimeService
from app.runtime.recovery import (
    audit_incomplete_tasks,
    reconcile_runtime_state,
    recover_available_tasks,
    retry_stale_queued_runs,
    watchdog_stale_runs,
)
from app.runtime.run_coordinator import RunCoordinator
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
        "astra.process-task": {"queue": "agent"},
        "astra.scout": {"queue": "control"},
        "astra.dispatch": {"queue": "control"},
        "astra.heartbeat-check": {"queue": "control"},
        "astra.employee-heartbeat": {"queue": "control"},
        "astra.recovery": {"queue": "control"},
        "astra.outbox-dispatch": {"queue": "control"},
    },
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
        "astra-recovery": {"task": "astra.recovery", "schedule": settings.recovery_interval},
        "astra-outbox-dispatch": {
            "task": "astra.outbox-dispatch",
            "schedule": settings.outbox_interval,
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
        async with SessionLocal() as session:
            return await TaskScout(session, [NrTestSystemSource(settings)]).poll_once()

    return run_async(execute())


@celery.task(name="astra.dispatch")
def dispatch() -> str | None:
    async def execute():
        await init_database()
        async with SessionLocal() as session:
            task = await Dispatcher(session).claim_once()
            if not task:
                return None
            run = await RuntimeService(session).active_run(task.id)
            if run:
                await RuntimeService(session).enqueue(task, run)
            return task.id

    return run_async(execute())


@celery.task(bind=True, name="astra.process-task")
def process_task(self, run_id: str) -> None:
    worker_id = str(getattr(self.request, "hostname", "") or "agent-worker")
    run_async(RunCoordinator().process(run_id, worker_id=worker_id))


@celery.task(name="astra.outbox-dispatch")
def outbox_dispatch() -> list[str]:
    async def execute():
        await init_database()
        async with SessionLocal() as session:
            return await RuntimeService(session).publish_pending_outbox()

    return run_async(execute())


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


@celery.task(name="astra.recovery")
def recovery() -> dict[str, list[str]]:
    async def execute():
        await init_database()
        async with SessionLocal() as session:
            inactive = await audit_incomplete_tasks(session, settings)
            resumed = await recover_available_tasks(session)
            redispatched = await retry_stale_queued_runs(session, settings)
            watchdog = await watchdog_stale_runs(session, settings)
            reconciled = await reconcile_runtime_state(session)
            return {
                "inactive": inactive,
                "resumed": resumed,
                "redispatched": redispatched,
                "watchdog": watchdog,
                "reconciled": reconciled,
            }

    return run_async(execute())

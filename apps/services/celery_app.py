"""1.0 独立 Celery/Beat；不引用旧应用，也不扫描旧队列。"""

import asyncio
import os

from celery import Celery

from apps.services.executions import candidates_authenticated as execution_candidates
from apps.services.executions import run_authenticated as execute_authenticated
from apps.services.personas import candidates_authenticated, run_authenticated
from apps.services.routines import sweep_authenticated

app = Celery("astra-1-0", broker=os.environ["ASTRA_V1_BROKER_URL"])
app.conf.update(
    task_default_queue="astra-v1",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    timezone="UTC",
    beat_schedule={"routine-inbox-sweep": {"task": "astra.v1.routines.sweep", "schedule": 30.0}},
)
if os.getenv("ASTRA_V1_PERSONA_CREDENTIAL_FILE"):
    app.conf.beat_schedule["persona-input-sweep"] = {"task": "astra.v1.personas.sweep", "schedule": 10.0}
if os.getenv("ASTRA_V1_EXECUTOR_CREDENTIAL_FILE"):
    app.conf.beat_schedule["engineering-sweep"] = {"task": "astra.v1.executions.sweep", "schedule": 10.0}


@app.task(name="astra.v1.executions.run", ignore_result=True)
def run_execution(execution_id):
    return asyncio.run(execute_authenticated(execution_id))


@app.task(name="astra.v1.executions.sweep", ignore_result=True)
def sweep_executions():
    ids = asyncio.run(execution_candidates())
    for execution_id in ids:
        run_execution.delay(execution_id)
    return {"queued_executions": len(ids)}


@app.task(name="astra.v1.personas.run", ignore_result=True)
def run_persona(employee_id):
    return asyncio.run(run_authenticated(employee_id))


@app.task(name="astra.v1.personas.sweep", ignore_result=True)
def sweep_personas():
    ids = asyncio.run(candidates_authenticated())
    for employee_id in ids:
        run_persona.delay(employee_id)
    return {"queued_employees": len(ids)}


@app.task(name="astra.v1.routines.sweep", ignore_result=True)
def sweep_routines():
    return asyncio.run(
        sweep_authenticated(
            os.environ["ASTRA_V1_DATABASE_URL"],
            os.environ["ASTRA_V1_SCHEDULER_CREDENTIAL_FILE"],
        )
    )

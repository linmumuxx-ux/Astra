from __future__ import annotations

from app.database import SessionLocal
from app.models import Run
from app.runtime.coordinator import TaskCoordinator


class RunCoordinator(TaskCoordinator):
    """Run-first execution entry.

    Runtime execution is valid only for a persisted Run. Task ids are never accepted
    as execution identifiers, which keeps Task and Employee as projections of Run.
    """

    async def process(self, run_id: str, *, worker_id: str | None = None) -> None:
        async with SessionLocal() as session:
            run = await session.get(Run, run_id)
            if run is None:
                return
        await super().process(run_id, worker_id=worker_id)

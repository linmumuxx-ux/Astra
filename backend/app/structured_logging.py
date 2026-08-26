import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger("astra.runtime")


def runtime_log(
    level: int,
    message: str,
    *,
    employee_id: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    phase: str = "system",
    **detail,
) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": logging.getLevelName(level),
        "employee_id": employee_id,
        "task_id": task_id,
        "run_id": run_id,
        "phase": phase,
        "message": message,
        "detail": detail,
    }
    logger.log(level, json.dumps(payload, ensure_ascii=False, default=str))

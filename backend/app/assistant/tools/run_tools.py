from typing import Any


async def nexus_run_search(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": [
            {"id": "RUN-001", "task_id": "TASK-002", "status": "RUNNING"}
        ],
        "total": 1
    }

async def nexus_run_failure_summary(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": params.get("run_id"),
        "error_type": "worker_error",
        "summary": "Timeout waiting for resource."
    }

from typing import Any

async def nexus_operation_overview(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "tasks": {"new": 10, "completed": 8, "running": 2, "failed": 0},
        "employees": {"online": 5, "working": 2, "idle": 3},
        "runs": {"total": 12, "success": 10, "failed": 0}
    }

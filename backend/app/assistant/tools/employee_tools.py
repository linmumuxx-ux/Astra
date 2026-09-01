from typing import Any


async def nexus_employee_search(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": [
            {"id": "EMP-001", "name": "图丫丫", "status": "IDLE"},
            {"id": "EMP-002", "name": "星野", "status": "WORKING"}
        ],
        "total": 2
    }

async def nexus_employee_recommend(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendations": [
            {"employee_id": "EMP-001", "name": "图丫丫", "reason": "空闲且擅长该任务类型"}
        ]
    }

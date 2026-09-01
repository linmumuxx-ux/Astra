from typing import Any


async def nexus_knowledge_search(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": [
            {"id": "KB-001", "title": "参数升级规范", "summary": "参数升级相关要求..."}
        ],
        "total": 1
    }

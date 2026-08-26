from typing import Any

import httpx

from app.config.settings import Settings, get_settings
from app.sources.base import ExternalTask, TaskSource


class NrTestSystemSource(TaskSource):
    id = "nr_test_system"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.settings.nr_test_system_token:
            return {}
        return {"Authorization": f"Bearer {self.settings.nr_test_system_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client:
            response = await self._client.request(method, path, headers=self._headers(), **kwargs)
        else:
            async with httpx.AsyncClient(
                base_url=self.settings.nr_test_system_endpoint, timeout=20
            ) as client:
                response = await client.request(method, path, headers=self._headers(), **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _map(item: dict[str, Any]) -> ExternalTask:
        external_id = item.get("external_task_id") or item.get("id")
        if not external_id:
            raise ValueError("nr_test_system task is missing id")
        return ExternalTask(
            external_task_id=str(external_id),
            task_type=item.get("task_type", "script_generate"),
            title=item.get("title", f"外部任务 {external_id}"),
            description=item.get("description", ""),
            input=item.get("input", item),
            definition_of_done=item.get("definition_of_done", []),
            priority=item.get("priority", "P2"),
        )

    async def discover_tasks(self) -> list[ExternalTask]:
        response = await self._request(
            "GET", self.settings.nr_test_system_discover_path, params={"status": "READY"}
        )
        payload = response.json()
        items = payload.get("items", payload.get("results", [])) if isinstance(payload, dict) else payload
        return [self._map(item) for item in items]

    async def get_task(self, external_task_id: str) -> ExternalTask:
        response = await self._request(
            "GET", f"{self.settings.nr_test_system_discover_path.rstrip('/')}/{external_task_id}"
        )
        return self._map(response.json())

    async def update_task(self, external_task_id: str, result: dict[str, Any]) -> None:
        path = self.settings.nr_test_system_result_path.format(external_task_id=external_task_id)
        await self._request("POST", path, json=result)

    async def heartbeat(self) -> bool:
        try:
            response = await self._request("GET", "/api/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

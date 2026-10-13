"""AgentScope 2.0.10 的 HTTP 客户端。不导入 agentscope 包。"""

from __future__ import annotations

from typing import Any

import httpx

PINNED_VERSION = "2.0.10"


class AgentScopeError(Exception):
    def __init__(self, detail: str, status_code: int = 503) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class AgentScopeClient:
    def __init__(
        self,
        base_url: str | None,
        user_id: str,
        http: httpx.AsyncClient | None = None,
        chat_model_config: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.user_id = user_id
        self.chat_model_config = chat_model_config
        self._http = http
        self._owns_http = http is None

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()

    def _client(self) -> httpx.AsyncClient:
        if not self.base_url:
            raise AgentScopeError("AgentScope 未连接，没有生成回复")
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=20)
        return self._http

    def _headers(self) -> dict[str, str]:
        return {"X-User-ID": self.user_id}

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        client = self._client()
        headers = dict(self._headers())
        headers.update(kwargs.pop("headers", {}))
        try:
            response = await client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentScopeError("AgentScope 未连接，没有生成回复") from exc
        if response.status_code >= 400:
            detail = response.text.strip() or response.reason_phrase
            raise AgentScopeError(f"AgentScope 返回 {response.status_code}：{detail}", response.status_code)
        return response

    async def probe(self) -> bool:
        if not self.configured:
            return False
        try:
            await self.request("GET", "/health")
        except AgentScopeError:
            return False
        return True

    async def create_agent(self, name: str, system_prompt: str) -> str:
        response = await self.request(
            "POST",
            "/agent/",
            json={"name": name, "system_prompt": system_prompt},
        )
        payload = response.json()
        agent_id = payload.get("agent_id")
        if not agent_id:
            raise AgentScopeError("AgentScope 创建员工后没有返回 agent_id")
        return str(agent_id)

    async def update_agent(self, agent_id: str, name: str, system_prompt: str) -> None:
        await self.request(
            "PATCH",
            f"/agent/{agent_id}",
            json={"name": name, "system_prompt": system_prompt},
        )

    async def delete_agent(self, agent_id: str) -> None:
        await self.request("DELETE", f"/agent/{agent_id}")

    async def create_session(self, agent_id: str, name: str) -> str:
        body: dict[str, Any] = {"agent_id": agent_id, "name": name}
        if self.chat_model_config:
            body["chat_model_config"] = self.chat_model_config
        response = await self.request(
            "POST",
            "/sessions/",
            json=body,
        )
        payload = response.json()
        session_id = payload.get("session_id")
        if not session_id:
            raise AgentScopeError("AgentScope 创建会话后没有返回 session_id")
        return str(session_id)

    async def trigger_chat(self, agent_id: str, session_id: str, text: str, user_name: str) -> str:
        response = await self.request(
            "POST",
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "name": user_name,
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                },
            },
        )
        payload = response.json()
        if payload.get("status") != "started":
            raise AgentScopeError("AgentScope 没有接受这次运行")
        return str(payload.get("session_id") or session_id)

    async def list_skills(self) -> list[dict[str, str]]:
        response = await self.request("GET", "/skill")
        payload = response.json()
        if not isinstance(payload, list):
            raise AgentScopeError("AgentScope 技能库返回的不是列表")
        items: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            skill_id = str(item.get("id") or item.get("skill_id") or item.get("name") or "")
            name = str(item.get("name") or skill_id)
            if skill_id:
                items.append({"id": skill_id, "name": name})
        return items

    def stream_session(self, agent_id: str, session_id: str, after: str | None = None) -> Any:
        client = self._client()
        params = {"agent_id": agent_id}
        if after:
            params["after"] = after
        return client.stream(
            "GET",
            f"/sessions/{session_id}/stream",
            params=params,
            headers=self._headers(),
            timeout=None,
        )

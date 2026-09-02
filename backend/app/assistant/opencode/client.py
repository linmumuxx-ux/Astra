import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx


class OpenCodeClientError(Exception):
    pass

class OpenCodeClient:
    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None
    ):
        base_url = base_url or os.environ.get("OPENCODE_SERVER_URL", "http://127.0.0.1:4096")
        username = username or os.environ.get("OPENCODE_SERVER_USERNAME")
        password = password or os.environ.get("OPENCODE_SERVER_PASSWORD")
        self.base_url = base_url
        self.auth = (username, password) if username and password else None

    async def create_session(self) -> str:
        async with httpx.AsyncClient(auth=self.auth) as client:
            resp = await client.post(f"{self.base_url}/session")
            resp.raise_for_status()
            data = resp.json()
            return data["id"]

    async def prompt_async(self, session_id: str, prompt: str, context: dict[str, Any] | None = None) -> None:
        payload = {"prompt": prompt}
        if context:
            payload["context"] = context

        async with httpx.AsyncClient(auth=self.auth) as client:
            resp = await client.post(f"{self.base_url}/session/{session_id}/prompt_async", json=payload)
            resp.raise_for_status()

    async def abort(self, session_id: str) -> None:
        async with httpx.AsyncClient(auth=self.auth) as client:
            resp = await client.post(f"{self.base_url}/session/{session_id}/abort")
            resp.raise_for_status()

    async def stream_events(self, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        async with httpx.AsyncClient(auth=self.auth, timeout=httpx.Timeout(None)) as client:
            async with client.stream("GET", f"{self.base_url}/session/{session_id}/events") as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            yield json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(auth=self.auth, timeout=5.0) as client:
            resp = await client.get(f"{self.base_url}/global/health")
            resp.raise_for_status()
            return resp.json()

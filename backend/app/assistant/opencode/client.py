import os
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
        self.base_url = base_url or os.environ.get("OPENCODE_SERVER_URL", "http://127.0.0.1:4096")
        self.auth = None
        if username or password:
             self.auth = (username, password)
        elif os.environ.get("OPENCODE_SERVER_USERNAME"):
             self.auth = (
                 os.environ.get("OPENCODE_SERVER_USERNAME"),
                 os.environ.get("OPENCODE_SERVER_PASSWORD")
             )

    async def create_session(self) -> str:
        async with httpx.AsyncClient(auth=self.auth) as client:
            resp = await client.post(f"{self.base_url}/session")
            resp.raise_for_status()
            data = resp.json()
            return data["id"]

    async def prompt_async(self, session_id: str, prompt: str, context: dict[str, Any] | None = None) -> None:
        # Correctly uses 'parts' instead of 'prompt'
        payload = {
            "parts": [
                {"type": "text", "text": prompt}
            ]
        }
        # Assuming context might be passed via system or another property based on OpenCode docs
        if context:
            pass # Skipping for now to strictly follow parts schema

        async with httpx.AsyncClient(auth=self.auth) as client:
            resp = await client.post(f"{self.base_url}/session/{session_id}/prompt_async", json=payload)
            resp.raise_for_status()

    async def abort(self, session_id: str) -> None:
        async with httpx.AsyncClient(auth=self.auth) as client:
            resp = await client.post(f"{self.base_url}/session/{session_id}/abort")
            resp.raise_for_status()

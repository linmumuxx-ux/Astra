"""Talk to the OpenCode process on 127.0.0.1 and return the body to the Gateway."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx

from app.worker_gateway.data_channel import MAX_CHUNK_BYTES

_PASS_HEADERS = {"x-next-cursor", "link", "x-has-more", "content-type"}


def gateway_http_base(gateway_url: str) -> str:
    if gateway_url.startswith("wss://"):
        http = "https://" + gateway_url.removeprefix("wss://")
    else:
        http = "http://" + gateway_url.removeprefix("ws://")
    if http.endswith("/connect"):
        http = http[: -len("/connect")]
    return http.rstrip("/")


def bind_local_opencode(manager, *, timeout: float = 60) -> None:
    base = gateway_http_base(manager.config.gateway_url)
    token = manager.config.token
    opencode = manager.config.opencode_url.rstrip("/")

    async def fetch_body(request_id: str, epoch: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/api/worker-gateway/data/{request_id}/request",
                headers=_auth(token, epoch),
            )
            response.raise_for_status()
            return response.json()

    async def local_request(method: str, path: str, fetched: Any) -> dict[str, Any]:
        query: dict[str, Any] = {}
        raw = fetched
        if isinstance(fetched, dict) and "query" in fetched:
            query = dict(fetched.get("query") or {})
            raw = fetched.get("body")
        content = raw if isinstance(raw, str) else json.dumps(raw if raw is not None else {})
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{opencode}{path}",
                params=query,
                content=content.encode("utf-8"),
                headers={"content-type": "application/json"},
            )
        headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower() in _PASS_HEADERS
        }
        return {
            "status": response.status_code,
            "body": response.text,
            "headers": headers,
            "content_type": response.headers.get("content-type"),
        }

    async def upload_body(request_id: str, epoch: int, result: dict[str, Any]) -> None:
        text = str(result.get("body") or "")
        upload_id = uuid4().hex
        pieces = _chunks(text)
        if not pieces:
            pieces = [""]
        async with httpx.AsyncClient(timeout=timeout) as client:
            for index, piece in enumerate(pieces):
                response = await client.put(
                    f"{base}/api/worker-gateway/data/{request_id}/response",
                    headers=_auth(token, epoch),
                    json={
                        "upload_id": upload_id,
                        "http_status": int(result.get("status") or 200),
                        "headers": result.get("headers") or {},
                        "content_type": result.get("content_type"),
                        "chunk": piece,
                        "complete": index == len(pieces) - 1,
                    },
                )
                response.raise_for_status()

    manager.fetch_body = fetch_body
    manager.local_request = local_request
    manager.upload_body = upload_body


def _auth(token: str, epoch: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Astra-Worker-Epoch": str(epoch)}


def _chunks(text: str) -> list[str]:
    pieces: list[str] = []
    current = ""
    for char in text:
        if len((current + char).encode("utf-8")) > MAX_CHUNK_BYTES:
            pieces.append(current)
            current = char
        else:
            current += char
    if current:
        pieces.append(current)
    return pieces

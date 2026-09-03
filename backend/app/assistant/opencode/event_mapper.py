import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx


class EventMapper:
    def __init__(self, opencode_client):
        self.client = opencode_client

    async def stream_and_map(
        self, opencode_session_id: str, conversation_id: str
    ) -> AsyncGenerator[str, None]:
        # Connect to the global /event stream per OpenCode docs
        url = f"{self.client.base_url}/event"
        async with httpx.AsyncClient(auth=self.client.auth, timeout=httpx.Timeout(None)) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            event = json.loads(data_str)
                            # Filter for this specific session
                            properties = event.get("properties", {})
                            if properties.get("sessionID") != opencode_session_id:
                                continue

                            mapped_event = self._map_event(event, conversation_id)
                            if mapped_event:
                                yield f"data: {json.dumps(mapped_event)}\n\n"
                        except json.JSONDecodeError:
                            continue

    def _map_event(self, opencode_event: dict[str, Any], conversation_id: str) -> dict[str, Any] | None:
        event_type = opencode_event.get("type")
        if not event_type:
            return None

        properties = opencode_event.get("properties", {})
        info = properties.get("info", {})

        base_event = {
            "conversation_id": conversation_id,
            "timestamp": opencode_event.get("timestamp"),
            "data": properties
        }

        # Mapping OpenCode events to Assistant events
        if event_type == "message.updated" or event_type == "message.part.updated":
            # Just emit a delta to frontend
            base_event["event"] = "assistant.message.delta"
            base_event["message_id"] = info.get("id")
        elif event_type == "session.idle":
            base_event["event"] = "assistant.message.completed"
        elif event_type == "tool.execute.before":
            base_event["event"] = "assistant.tool.started"
        elif event_type == "tool.execute.after":
            base_event["event"] = "assistant.tool.completed"
        elif event_type == "session.status":
            base_event["event"] = "assistant.status"
        else:
            base_event["event"] = f"assistant.{event_type}"

        return base_event

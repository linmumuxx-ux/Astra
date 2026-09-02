import json
from collections.abc import AsyncGenerator
from typing import Any

from .client import OpenCodeClient


class EventMapper:
    def __init__(self, opencode_client: OpenCodeClient):
        self.client = opencode_client

    async def stream_and_map(
        self, opencode_session_id: str, conversation_id: str
    ) -> AsyncGenerator[str, None]:
        async for event in self.client.stream_events(opencode_session_id):
            mapped_event = self._map_event(event, conversation_id)
            if mapped_event:
                # SSE format
                yield f"data: {json.dumps(mapped_event)}\n\n"

    def _map_event(self, opencode_event: dict[str, Any], conversation_id: str) -> dict[str, Any] | None:
        event_type = opencode_event.get("type")
        if not event_type:
            return None

        base_event = {
            "conversation_id": conversation_id,
            "timestamp": opencode_event.get("timestamp"),
            "data": opencode_event.get("data", {})
        }

        # Mapping OpenCode events to Assistant events
        if event_type == "message.created":
            base_event["event"] = "assistant.message.created"
            base_event["message_id"] = opencode_event.get("message_id")
        elif event_type == "message.delta":
            base_event["event"] = "assistant.message.delta"
            base_event["message_id"] = opencode_event.get("message_id")
        elif event_type == "message.completed":
            base_event["event"] = "assistant.message.completed"
            base_event["message_id"] = opencode_event.get("message_id")
        elif event_type == "tool.started":
            base_event["event"] = "assistant.tool.started"
        elif event_type == "tool.completed":
            base_event["event"] = "assistant.tool.completed"
        elif event_type == "tool.failed":
            base_event["event"] = "assistant.tool.failed"
        elif event_type == "status":
            base_event["event"] = "assistant.status"
        else:
            base_event["event"] = f"assistant.{event_type}"

        return base_event

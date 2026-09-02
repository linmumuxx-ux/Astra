import uuid
import json
from collections.abc import AsyncGenerator
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import AssistantMessage, AssistantMessagePart
from app.assistant.schemas import MessageCreate
from app.assistant.opencode.client import OpenCodeClient
from app.assistant.opencode.event_mapper import EventMapper
from app.assistant.services.conversation_service import ConversationService


class AssistantService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.opencode_client = OpenCodeClient()
        self.event_mapper = EventMapper(self.opencode_client)
        self.conversation_service = ConversationService(db)

    async def send_message(
        self, conversation_id: str, user_id: str, message_in: MessageCreate
    ) -> AssistantMessage:
        conv = await self.conversation_service.get_conversation(conversation_id)
        if not conv or conv.user_id != user_id:
            raise ValueError("Conversation not found")

        # 1. Save user message
        msg_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
        msg = AssistantMessage(
            id=msg_id,
            conversation_id=conversation_id,
            role="USER",
            message_type="TEXT",
            content=message_in.content,
            status="COMPLETED"
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)

        # 2. Build Agent Context
        context = {
            "current_user_id": user_id,
            "page_context": message_in.page_context,
            # Additional context like references can be added here
        }

        # 3. Send async prompt to OpenCode
        await self.opencode_client.prompt_async(conv.opencode_session_id, message_in.content, context)

        return msg

    async def stream_events(self, conversation_id: str, request: Request) -> AsyncGenerator[str, None]:
        conv = await self.conversation_service.get_conversation(conversation_id)
        if not conv:
            yield "data: {\"error\": \"Conversation not found\"}\n\n"
            return

        async for sse_msg in self.event_mapper.stream_and_map(conv.opencode_session_id, conversation_id):
            if await request.is_disconnected():
                break

            # Intercept specific events to persist
            if sse_msg.startswith("data: "):
                data_str = sse_msg[6:].strip()
                if data_str:
                    try:
                        event_data = json.loads(data_str)
                        await self._persist_event(conversation_id, event_data)
                    except Exception:
                        pass

            yield sse_msg

    async def _persist_event(self, conversation_id: str, event_data: dict):
        event_type = event_data.get("event")
        msg_id = event_data.get("message_id")

        if event_type == "assistant.message.completed" and msg_id:
            data = event_data.get("data", {})
            parts = data.get("parts", [])

            # create assistant message
            assistant_msg = AssistantMessage(
                id=f"MSG-{uuid.uuid4().hex[:8].upper()}",
                conversation_id=conversation_id,
                role="ASSISTANT",
                message_type="MIXED",
                status="COMPLETED",
                opencode_message_id=msg_id
            )
            self.db.add(assistant_msg)

            # parse parts
            for i, p in enumerate(parts):
                part_type = p.get("type", "TEXT").upper()
                if part_type == "TOOL":
                    # Simple heuristic
                    content_val = p.get("content", {})
                    if "operation_id" in content_val:
                        part_type = "CONFIRM_CARD"
                    elif "items" in content_val and len(content_val["items"]) > 0:
                        part_type = "TASK_CARD"
                        content_val = content_val["items"][0]
                    else:
                        part_type = "TEXT"

                    msg_part = AssistantMessagePart(
                        id=f"PRT-{uuid.uuid4().hex[:8].upper()}",
                        message_id=assistant_msg.id,
                        part_type=part_type,
                        seq=i,
                        payload_json=content_val
                    )
                    self.db.add(msg_part)
                else:
                    msg_part = AssistantMessagePart(
                        id=f"PRT-{uuid.uuid4().hex[:8].upper()}",
                        message_id=assistant_msg.id,
                        part_type="TEXT",
                        seq=i,
                        payload_json={"text": p.get("text", "")}
                    )
                    self.db.add(msg_part)

            await self.db.commit()

    async def list_messages(self, conversation_id: str) -> list[AssistantMessage]:
        result = await self.db.execute(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation_id)
            .options(selectinload(AssistantMessage.parts))
            .order_by(AssistantMessage.created_at.asc())
        )
        return list(result.scalars().all())

    async def abort_generation(self, conversation_id: str) -> None:
        conv = await self.conversation_service.get_conversation(conversation_id)
        if conv:
            await self.opencode_client.abort(conv.opencode_session_id)

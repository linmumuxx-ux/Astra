import uuid
from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assistant.models import AssistantMessage
from app.assistant.opencode.client import OpenCodeClient
from app.assistant.opencode.event_mapper import EventMapper
from app.assistant.schemas import MessageCreate
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
            yield sse_msg

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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.services.assistant_service import AssistantService
from app.database import get_session as get_db

router = APIRouter(prefix="/conversations/{conversation_id}/events", tags=["Assistant Events"])

@router.get("")
async def stream_events(conversation_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    service = AssistantService(db)
    return StreamingResponse(service.stream_events(conversation_id, request), media_type="text/event-stream")

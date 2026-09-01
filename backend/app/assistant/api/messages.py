from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_session as get_db
from app.assistant.schemas import MessageResponse, MessageCreate
from app.assistant.services.assistant_service import AssistantService

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["Assistant Messages"])

@router.post("", response_model=MessageResponse)
async def create_message(conversation_id: str, message_in: MessageCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.headers.get("X-Astra-User-Id", "admin")
    service = AssistantService(db)
    try:
        return await service.send_message(conversation_id, user_id, message_in)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=List[MessageResponse])
async def list_messages(conversation_id: str, db: AsyncSession = Depends(get_db)):
    service = AssistantService(db)
    return await service.list_messages(conversation_id)

@router.post("/abort")
async def abort_message(conversation_id: str, db: AsyncSession = Depends(get_db)):
    service = AssistantService(db)
    await service.abort_generation(conversation_id)
    return {"status": "ok"}

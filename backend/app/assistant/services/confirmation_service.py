
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import AssistantOperation
from app.models import utcnow

# from app.services import TaskService

class ConfirmationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_operation(self, operation_id: str) -> AssistantOperation | None:
        result = await self.db.execute(
            select(AssistantOperation).where(AssistantOperation.operation_id == operation_id)
        )
        return result.scalar_one_or_none()

    async def confirm_operation(self, operation_id: str, user_id: str) -> AssistantOperation:
        op = await self.get_operation(operation_id)
        if not op:
            raise ValueError("Operation not found")

        # Security checks
        if op.user_id != user_id:
            raise ValueError("Unauthorized")
        if op.status != "PREPARED" and op.status != "WAITING_CONFIRM":
            raise ValueError(f"Operation cannot be confirmed in status {op.status}")

        op.status = "CONFIRMED"
        op.confirmed_at = utcnow()
        await self.db.commit()
        await self.db.refresh(op)

        # Actually execute the operation based on type
        op.status = "EXECUTING"
        await self.db.commit()

        try:
            if op.operation_type == "task_create":
                # Mock execution, in real life call TaskService
                op.result_json = {"task_id": "TASK-XXX", "status": "PENDING"}
            elif op.operation_type == "task_cancel":
                op.result_json = {"status": "CANCELLED"}
            else:
                op.result_json = {"message": "Executed"}

            op.status = "SUCCESS"
            op.executed_at = utcnow()
        except Exception as e:
            op.status = "FAILED"
            op.result_json = {"error": str(e)}

        await self.db.commit()
        await self.db.refresh(op)
        return op

    async def cancel_operation(self, operation_id: str, user_id: str) -> AssistantOperation:
        op = await self.get_operation(operation_id)
        if not op:
            raise ValueError("Operation not found")

        if op.user_id != user_id:
            raise ValueError("Unauthorized")

        op.status = "CANCELLED"
        await self.db.commit()
        await self.db.refresh(op)
        return op

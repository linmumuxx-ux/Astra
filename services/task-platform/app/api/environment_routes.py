import asyncio
import json
from typing import Literal

from anyio import CancelScope
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.database import get_session
from app.runtime.remote_provisioning import RemoteProvisioner, reserve_operation

router = APIRouter(prefix="/api/employees")


@router.post("/{employee_id}/environment/{action}")
async def maintain_remote_environment(
    employee_id: str,
    action: Literal["deploy", "restart"],
    session=Depends(get_session),
):
    environment, operation = await reserve_operation(employee_id, action, session)
    provisioner = RemoteProvisioner(environment, operation)

    async def stream():
        queue = asyncio.Queue()
        task = asyncio.create_task(provisioner.run(queue.put))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    if task.done():
                        try:
                            await task
                        except Exception as exc:
                            yield (
                                json.dumps(
                                    {"type": "result", "success": False, "message": provisioner.redact(exc)},
                                    ensure_ascii=False,
                                )
                                + "\n"
                            ).encode()
                        break
                    event = {"type": "heartbeat"}
                yield (json.dumps(event, ensure_ascii=False) + "\n").encode()
                if event["type"] == "result":
                    break
        finally:
            with CancelScope(shield=True):
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

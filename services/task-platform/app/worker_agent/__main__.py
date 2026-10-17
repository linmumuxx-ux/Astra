"""python -m app.worker_agent

凭据只从环境变量读取，不写进仓库。
"""

from __future__ import annotations

import asyncio
import os

from app.worker_agent.connection import WorkerConnectionManager, load_agent_config
from app.worker_agent.supervisor import RuntimeSupervisor


async def _main() -> None:
    config = load_agent_config(dict(os.environ))
    manager = WorkerConnectionManager(config, supervisor=RuntimeSupervisor())

    async def connect():
        import websockets

        socket = await websockets.connect(config.gateway_url, max_size=config.max_frame_bytes)
        return _WebSocketTransport(socket)

    await manager.run(connect, asyncio.Event())


class _WebSocketTransport:
    def __init__(self, socket) -> None:
        self.socket = socket

    async def send(self, message: dict) -> None:
        import json

        await self.socket.send(json.dumps(message, separators=(",", ":")))

    async def recv(self) -> dict:
        import json

        return json.loads(await self.socket.recv())

    async def close(self) -> None:
        await self.socket.close()


if __name__ == "__main__":
    asyncio.run(_main())

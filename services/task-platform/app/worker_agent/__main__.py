"""python -m app.worker_agent

凭据只从环境变量读取，不写进仓库。
"""

from __future__ import annotations

import asyncio
import os

from app.config.settings import get_settings
from app.worker_agent.connection import WorkerConnectionManager, load_agent_config
from app.worker_agent.local_opencode import bind_local_opencode
from app.worker_agent.supervisor import RuntimeSupervisor
from app.worker_agent.transport import connect_websocket


async def _main() -> None:
    config = load_agent_config(dict(os.environ))
    manager = WorkerConnectionManager(config, supervisor=RuntimeSupervisor())
    bind_local_opencode(manager, timeout=get_settings().opencode_control_timeout_seconds)

    async def connect():
        return await connect_websocket(config.gateway_url, max_size=config.max_frame_bytes)

    await manager.run(connect, asyncio.Event())


if __name__ == "__main__":
    asyncio.run(_main())

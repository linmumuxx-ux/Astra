import asyncio
import os
import tempfile
from pathlib import Path

import pytest

TEMP_ROOT = Path(tempfile.gettempdir())
TEST_DB = TEMP_ROOT / f"astra-test-{os.getpid()}.db"
TEST_WORKSPACES = TEMP_ROOT / f"astra-workspaces-{os.getpid()}"
os.environ["ASTRA_DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["ASTRA_SEED_DEMO"] = "false"
os.environ["ASTRA_WORKER_GATEWAY_ADMIN_KEY"] = "wgk_test"
os.environ["ASTRA_LLM_WIKI_ENABLED"] = "false"
os.environ["ASTRA_WORKSPACE_ROOT"] = str(TEST_WORKSPACES)


@pytest.fixture(autouse=True)
def isolate_assistant_command_test(request, monkeypatch):
    """Keep command-construction tests independent from a local OpenCode install."""

    if request.node.name == "test_assistant_server_manager_configures_isolated_runtime":
        monkeypatch.setattr(
            "app.executors.process.resolve_executable",
            lambda executable: executable,
        )


def pytest_sessionfinish(session, exitstatus):
    from app.database import engine

    asyncio.run(engine.dispose())
    TEST_DB.unlink(missing_ok=True)
    url = os.environ.get("ASTRA_TEST_REDIS_URL")
    if not url:
        return
    from redis import Redis

    client = Redis.from_url(url)
    try:
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match="astra:worker-gateway:test:*", count=500)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
    finally:
        client.close()

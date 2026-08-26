import os
from pathlib import Path

TEST_DB = Path(f"/tmp/astra-test-{os.getpid()}.db")
os.environ["ASTRA_DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["ASTRA_SEED_DEMO"] = "false"
os.environ["ASTRA_WORKSPACE_ROOT"] = f"/tmp/astra-workspaces-{os.getpid()}"


def pytest_sessionfinish(session, exitstatus):
    TEST_DB.unlink(missing_ok=True)

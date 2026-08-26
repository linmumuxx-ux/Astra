import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bootstrap import bootstrap_employees
from app.config.settings import Settings
from app.models import Base, DigitalEmployee
from app.sources.nr_test_system import NrTestSystemSource


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def test_bootstrap_employee_from_yaml(tmp_path, session):
    (tmp_path / "employees.yaml").write_text(
        """employees:
  - id: astra-config
    name: Astra Config
    role: 测试执行员工
    capabilities: [script_generate]
    sources: [nr_test_system, manual]
    max_concurrency: 1
""",
        encoding="utf-8",
    )

    await bootstrap_employees(session, tmp_path)
    employee = await session.get(DigitalEmployee, "astra-config")

    assert employee is not None
    assert employee.status == "IDLE"
    assert employee.source_scope == ["nr_test_system", "manual"]


async def test_nr_test_system_adapter_maps_discovers_and_backfills():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "EXT-42",
                            "task_type": "script_generate",
                            "title": "生成登录脚本",
                            "priority": "P1",
                            "input": {"case_id": "TC-42"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"ok": True})

    settings = Settings(
        nr_test_system_endpoint="http://nr-test.local",
        nr_test_system_token="test-token",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=settings.nr_test_system_endpoint
    ) as client:
        source = NrTestSystemSource(settings, client)
        tasks = await source.discover_tasks()
        await source.update_task("EXT-42", {"status": "COMPLETED"})

    assert tasks[0].external_task_id == "EXT-42"
    assert tasks[0].input == {"case_id": "TC-42"}
    assert requests[0].url.params["status"] == "READY"
    assert requests[0].headers["authorization"] == "Bearer test-token"
    assert requests[1].url.path == "/api/astra/tasks/EXT-42/result"
    assert json.loads(requests[1].content) == {"status": "COMPLETED"}

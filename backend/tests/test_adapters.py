import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bootstrap import bootstrap_employees
from app.config.settings import Settings
from app.models import Base, DigitalEmployee, OpenCodeExecutionEnvironment
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


async def test_bootstrap_employee_from_v03_yaml(tmp_path, session):
    (tmp_path / "employees.yaml").write_text(
        """employees:
  - id: astra-config
    name: Astra Config
    role: 测试平台员工
    task_types: [ISSUE, REQUIREMENT]
    category_ids: [testing-platform]
    policy:
      auto_claim: true
      auto_execute: false
      max_auto_retries: 2
    execution_environment:
      mode: LOCAL
      workspace_root: ./workspaces/astra-config
""",
        encoding="utf-8",
    )

    await bootstrap_employees(session, tmp_path)
    employee = await session.get(DigitalEmployee, "astra-config")

    assert employee is not None
    assert employee.status == "IDLE"
    assert employee.task_types == ["ISSUE", "REQUIREMENT"]
    assert employee.category_ids == ["testing-platform"]
    assert employee.auto_execute is False
    environment = await session.scalar(
        select(OpenCodeExecutionEnvironment).where(OpenCodeExecutionEnvironment.employee_id == employee.id)
    )
    assert environment.workspace_root == "./workspaces/astra-config"


async def test_nr_test_system_adapter_maps_v03_task_and_backfills():
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
                            "task_type": "ISSUE",
                            "category_id": "testing-platform",
                            "title": "修复登录接口异常",
                            "description": "登录接口偶发返回 500",
                            "acceptance_criteria": ["异常已修复", "原能力正常"],
                            "priority": "P1",
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
    assert tasks[0].task_type == "ISSUE"
    assert tasks[0].category_id == "testing-platform"
    assert tasks[0].priority == "HIGH"
    assert tasks[0].acceptance_criteria == ["异常已修复", "原能力正常"]
    assert requests[0].url.params["status"] == "READY"
    assert requests[0].headers["authorization"] == "Bearer test-token"
    assert requests[1].url.path == "/api/astra/tasks/EXT-42/result"
    assert json.loads(requests[1].content) == {"status": "COMPLETED"}

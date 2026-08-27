import asyncio
import sys

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.domain import TaskStatus
from app.main import app
from app.models import Task


def task_payload(**overrides):
    payload = {
        "task_type": "ISSUE",
        "category_id": "testing-platform",
        "title": "API 集成任务",
        "description": "验证 V0.4 任务事实、状态和结果契约",
        "acceptance_criteria": [{"content": "任务结果可追溯"}],
        "priority": "HIGH",
        "completion_policy": "AUTO",
    }
    payload.update(overrides)
    return payload


def test_task_api_uses_v04_business_fields_and_statuses():
    with TestClient(app) as client:
        created = client.post("/api/tasks", json=task_payload())
        assert created.status_code == 201
        task = created.json()
        assert task["status"] == "READY"
        assert task["task_type"] == "ISSUE"
        assert task["category_id"] == "testing-platform"
        assert task["acceptance_criteria"] == [{"id": "AC-01", "content": "任务结果可追溯"}]
        assert "workspace" not in task
        assert "current_phase" not in task
        assert "progress" not in task

        filtered = client.get(
            "/api/tasks",
            params={"q": "API 集成", "status": "READY", "task_type": "ISSUE"},
        )
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()] == [task["id"]]

        paused = client.post(f"/api/tasks/{task['id']}/pause", json={"reason": "测试暂停"})
        assert paused.status_code == 200
        assert paused.json()["status"] == "SUSPENDED"

        resumed = client.post(f"/api/tasks/{task['id']}/resume", json={})
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "READY"


def test_employee_scope_environment_and_category_configuration(tmp_path):
    with TestClient(app) as client:
        category = client.post(
            "/api/task-categories",
            json={"name": "接口治理", "description": "接口治理类任务", "sort_order": 40},
        )
        assert category.status_code == 201
        category_id = category.json()["id"]

        created = client.post(
            "/api/employees",
            json={
                "id": "astra-api-v03",
                "name": "Astra API V0.4",
                "role": "接口治理员工",
                "task_types": ["ISSUE", "REQUIREMENT"],
                "category_ids": [category_id],
                "auto_claim": True,
                "auto_execute": False,
                "max_auto_retries": 2,
                "execution_environment": {
                    "mode": "LOCAL",
                    "name": "API 本地工作空间",
                    "opencode_path": sys.executable,
                    "workspace_root": str(tmp_path / "employee-workspace"),
                },
            },
        )
        assert created.status_code == 201
        employee = created.json()
        assert employee["task_types"] == ["ISSUE", "REQUIREMENT"]
        assert employee["category_ids"] == [category_id]
        assert employee["execution_environment"]["workspace_root"].endswith("employee-workspace")
        assert "skills" not in employee
        assert "capabilities" not in employee

        checked = client.post("/api/employees/astra-api-v03/environment/test")
        assert checked.status_code == 200
        assert checked.json()["status"] == "AVAILABLE"
        assert all(item["passed"] for item in checked.json()["checks"])


def test_employee_can_submit_structured_completion():
    with TestClient(app) as client:
        employees = client.get("/api/employees").json()
        employee = next(
            item
            for item in employees
            if "ISSUE" in item["task_types"] and "testing-platform" in item["category_ids"]
        )
        created = client.post(
            "/api/tasks",
            json=task_payload(employee_id=employee["id"], title="结构化结果任务"),
        )
        assert created.status_code == 201
        task = created.json()

        async def mark_running():
            async with SessionLocal() as session:
                row = await session.get(Task, task["id"])
                row.status = TaskStatus.RUNNING
                await session.commit()

        asyncio.run(mark_running())
        completed = client.post(
            f"/api/tasks/{task['id']}/complete",
            json={
                "result": {
                    "summary": "已完成接口治理",
                    "changes": ["补充状态记录"],
                    "files": ["app/service.py"],
                    "commits": ["abc1234"],
                },
                "acceptance_results": [
                    {
                        "criterion_id": "AC-01",
                        "status": "SATISFIED",
                        "description": "已提供任务记录",
                        "evidence": ["commit abc1234"],
                    }
                ],
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "COMPLETED"
        assert completed.json()["result"]["acceptance_results"][0]["status"] == "SATISFIED"

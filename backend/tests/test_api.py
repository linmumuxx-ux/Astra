import sys

from fastapi.testclient import TestClient

from app.main import app


def test_task_api_create_filter_and_control():
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={
                "task_type": "script_generate",
                "title": "API 集成任务",
                "description": "验证任务 API 与集中状态机",
                "priority": "P1",
            },
        )
        assert created.status_code == 201
        task = created.json()
        assert task["status"] == "READY"

        filtered = client.get("/api/tasks", params={"q": "API 集成", "status": "READY"})
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()] == [task["id"]]

        paused = client.post(f"/api/tasks/{task['id']}/pause", json={"reason": "测试暂停"})
        assert paused.status_code == 200
        assert paused.json()["status"] == "PAUSED"

        resumed = client.post(f"/api/tasks/{task['id']}/resume", json={})
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "READY"

        events = client.get(f"/api/tasks/{task['id']}/events")
        assert [item["event_type"] for item in events.json()] == [
            "TASK_CREATED",
            "TASK_READY",
            "TASK_PAUSED",
            "TASK_READY",
        ]


def test_employee_environment_configuration_connection_and_usage():
    with TestClient(app) as client:
        created = client.post(
            "/api/employees",
            json={
                "id": "astra-api-v02",
                "name": "Astra API V0.2",
                "role": "环境验收员工",
                "capabilities": ["script_execute"],
                "skills": ["api-testing"],
                "source_scope": ["manual"],
                "execution_environment": {
                    "mode": "LOCAL",
                    "name": "API 本地环境",
                    "opencode_path": sys.executable,
                    "workspace_root": "/tmp/astra-api-v02-workspaces",
                },
            },
        )
        assert created.status_code == 201
        employee = created.json()
        assert employee["execution_environment"]["mode"] == "LOCAL"
        assert employee["execution_environment"]["status"] == "UNKNOWN"

        checked = client.post("/api/employees/astra-api-v02/environment/test")
        assert checked.status_code == 200
        assert checked.json()["status"] == "AVAILABLE"
        assert all(item["passed"] for item in checked.json()["checks"])

        usage = client.get("/api/employees/astra-api-v02/usage", params={"days": 7})
        assert usage.status_code == 200
        assert usage.json()["summary"]["total_tokens"] is None
        assert len(usage.json()["trend"]) == 7

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

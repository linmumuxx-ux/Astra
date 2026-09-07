import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Run


def test_run_page_aggregates_full_filter_before_pagination():
    with TestClient(app) as client:
        employee = client.get("/api/employees").json()[0]["id"]
        task = client.post(
            "/api/tasks",
            json={
                "task_type": "ISSUE",
                "category_id": "testing-platform",
                "title": "分页统计验收",
                "description": "统计完整筛选范围",
                "acceptance_criteria": [{"content": "统计正确"}],
                "priority": "HIGH",
                "completion_policy": "AUTO",
            },
        ).json()
        statuses = [
            "COMPLETED",
            "PASSED",
            "FAILED",
            "TIMEOUT",
            "LOST",
            "BLOCKED",
            "QUEUED",
            "STARTING",
            "RUNNING",
            "WAITING_INPUT",
            "SUSPENDED",
            "CANCELLED",
        ]

        async def insert():
            async with SessionLocal() as session:
                for index, status in enumerate(statuses):
                    start = datetime(2026, 9, 1, tzinfo=UTC)
                    session.add(
                        Run(
                            id=f"PAGE-TEST-{index:02}",
                            task_id=task["id"],
                            employee_id=employee,
                            run_number=index + 1,
                            status=status,
                            previous_run_id="PAGE-TEST-00" if index else None,
                            created_at=start + timedelta(days=index),
                            started_at=start if index < 6 else None,
                            finished_at=start + timedelta(seconds=365) if index < 6 else None,
                            total_tokens=100 if index < 6 else None,
                        )
                    )
                await session.commit()

        asyncio.run(insert())
        params = {"q": task["id"], "page_size": 2}
        first = client.get("/api/runs/page", params=params).json()
        second = client.get("/api/runs/page", params={**params, "page": 2}).json()
        assert len(first["items"]) == 2
        assert first["items"][0]["task_title"] == task["title"]
        assert first["items"] != second["items"]
        assert first["stats"] == second["stats"]
        assert first["total"] == 12
        assert first["stats"] == {
            "run_count": 12,
            "task_count": 1,
            "completed_count": 2,
            "failed_count": 4,
            "retry_count": 11,
            "waiting_input_count": 1,
            "success_rate": 33.3,
            "avg_duration_seconds": 365,
            "total_tokens": 600,
        }
        for filters, expected in [
            ({"level": "COMPLETED"}, 2),
            ({"level": "FAILED"}, 4),
            ({"level": "WAITING_INPUT"}, 1),
            ({"retry": "true"}, 11),
            ({"retry": "false"}, 1),
            ({"employee": employee}, 12),
            ({"employee": "missing"}, 0),
            ({"category": "testing-platform"}, 12),
            ({"category": "missing"}, 0),
            ({"date_from": "2026-09-02", "date_to": "2026-09-03"}, 2),
        ]:
            result = client.get("/api/runs/page", params={**params, **filters}).json()
            assert result["total"] == result["stats"]["run_count"] == expected
        waiting = client.get("/api/runs/page", params={**params, "level": "WAITING_INPUT"}).json()
        assert waiting["stats"]["success_rate"] is None
        assert waiting["stats"]["avg_duration_seconds"] is None
        assert waiting["stats"]["total_tokens"] is None
        assert client.get("/api/runs/page", params={"page": 0}).status_code == 422
        assert client.get("/api/runs/page", params={"level": "BAD"}).status_code == 422
        assert (
            client.get(
                "/api/runs/page",
                params={
                    "date_from": "2026-09-03",
                    "date_to": "2026-09-01",
                },
            ).status_code
            == 422
        )

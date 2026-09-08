import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.library_schemas import (
    LibrarySubmitExperienceInput,
)
from app.library_service import KnowledgeService
from app.main import app
from app.mcp_server import mcp
from app.models import KnowledgeAudit, KnowledgeItem, Run


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def test_library_web_api_browses_drafts_publishes_and_enforces_review_permission():
    with TestClient(app) as client:
        spaces = client.get("/api/library/spaces")
        assert spaces.status_code == 200
        assert [space["name"] for space in spaces.json()][:2] == ["公共知识库", "测试领域知识"]
        space_id = spaces.json()[0]["id"]

        created = client.post(
            "/api/library/knowledge",
            json={
                "space_id": space_id,
                "title": unique("流水线创建错误 50004 处理经验"),
                "type": "experience",
                "summary": "用于验证精确错误码检索",
                "content_md": "## 问题现象\n\n返回 `50004`。\n\n## 处理步骤\n\n1. 检查参数。",
                "tags": ["流水线", "50004"],
            },
        )
        assert created.status_code == 201
        assert created.json()["status"] == "draft"
        knowledge_id = created.json()["id"]

        viewer_list = client.get(
            "/api/library/knowledge",
            params={"keyword": created.json()["title"]},
            headers={"X-Astra-User-Id": "viewer-1", "X-Astra-Role": "viewer"},
        )
        assert viewer_list.status_code == 200
        assert viewer_list.json()["total"] == 0

        forbidden = client.post(
            f"/api/library/knowledge/{knowledge_id}/publish",
            json={"space_id": space_id},
            headers={"X-Astra-User-Id": "viewer-1", "X-Astra-Role": "viewer"},
        )
        assert forbidden.status_code == 403

        published = client.post(
            f"/api/library/knowledge/{knowledge_id}/publish",
            json={"space_id": space_id, "verification_status": "verified"},
            headers={"X-Astra-User-Id": "reviewer-1", "X-Astra-Role": "reviewer"},
        )
        assert published.status_code == 200
        assert published.json()["status"] == "published"
        assert published.json()["published_by"] == "reviewer-1"

        helpful = client.post(
            f"/api/library/knowledge/{knowledge_id}/helpful",
            headers={"X-Astra-User-Id": "viewer-1", "X-Astra-Role": "viewer"},
        )
        repeated = client.post(
            f"/api/library/knowledge/{knowledge_id}/helpful",
            headers={"X-Astra-User-Id": "viewer-1", "X-Astra-Role": "viewer"},
        )
        assert helpful.json() == {"created": True, "helpful_count": 1}
        assert repeated.json() == {"created": False, "helpful_count": 1}

        stats = client.get("/api/library/stats").json()
        assert stats["knowledge_pages"] >= 1
        assert stats["published_experiences"] >= 1

        private_space = client.post(
            "/api/library/spaces",
            json={"name": unique("内部知识空间"), "access_scope": "admin"},
        ).json()
        private_knowledge = client.post(
            "/api/library/knowledge",
            json={
                "space_id": private_space["id"],
                "title": unique("不应对普通访问者可见"),
                "type": "document",
                "summary": "私有空间内容",
                "content_md": "# 私有内容",
            },
        ).json()
        client.post(
            f"/api/library/knowledge/{private_knowledge['id']}/publish",
            json={"space_id": private_space["id"]},
        )
        viewer_headers = {"X-Astra-User-Id": "viewer-1", "X-Astra-Role": "viewer"}
        private_list = client.get(
            "/api/library/knowledge",
            params={"keyword": private_knowledge["title"]},
            headers=viewer_headers,
        )
        private_detail = client.get(
            f"/api/library/knowledge/{private_knowledge['id']}",
            headers=viewer_headers,
        )
        visible_spaces = client.get("/api/library/spaces", headers=viewer_headers).json()
        viewer_stats = client.get("/api/library/stats", headers=viewer_headers).json()
        admin_stats = client.get("/api/library/stats").json()
        assert private_list.json()["total"] == 0
        assert private_detail.status_code == 403
        assert private_space["id"] not in {space["id"] for space in visible_spaces}
        assert admin_stats["knowledge_pages"] == viewer_stats["knowledge_pages"] + 1


def test_candidate_experience_mcp_flow_preserves_provenance_and_review_audit():
    employee_id = unique("employee-library")
    run_id = unique("RUN-LIBRARY")
    with TestClient(app) as client:
        employee = client.post(
            "/api/employees",
            json={
                "id": employee_id,
                "name": "测试知识员工",
                "role": "知识验证员工",
                "category_ids": ["testing-platform"],
                "auto_claim": False,
                "auto_execute": False,
            },
        )
        assert employee.status_code == 201
        task = client.post(
            "/api/tasks",
            json={
                "task_type": "ISSUE",
                "category_id": "testing-platform",
                "title": unique("候选经验来源任务"),
                "description": "验证数字员工提交候选经验",
                "acceptance_criteria": [{"content": "候选经验可审核发布"}],
                "priority": "MEDIUM",
                "completion_policy": "AUTO",
                "employee_id": employee_id,
            },
        )
        assert task.status_code == 201
        task_id = task.json()["id"]

        async def run_flow():
            async with SessionLocal() as session:
                session.add(
                    Run(
                        id=run_id,
                        task_id=task_id,
                        employee_id=employee_id,
                        run_number=1,
                        status="PASSED",
                    )
                )
                await session.commit()
            async with SessionLocal() as session:
                candidate = await KnowledgeService(session).mcp_submit_experience(
                    LibrarySubmitExperienceInput(
                        title=unique("并发任务调度超时处理经验"),
                        summary="并发调度超时后降低批量并验证重试",
                        content_md=(
                            "## 问题现象\n\n调度返回 `SCHED_TIMEOUT`。\n\n## 处理步骤\n\n降低并发后重试。"
                        ),
                        source_employee_id=employee_id,
                        source_task_id=task_id,
                        source_run_id=run_id,
                        evidence=[
                            {
                                "evidence_type": "run_result",
                                "content": "处理后 PASS",
                                "result": "PASS",
                            }
                        ],
                        tags=["SCHED_TIMEOUT", "并发调度"],
                        experience_data={
                            "before_status": "FAILED",
                            "after_status": "PASS",
                            "verification_count": 2,
                            "verification_passed": True,
                            "original_error": "scheduler timeout",
                            "handling": "降低并发批量并重试",
                        },
                    )
                )
                return candidate

        candidate = asyncio.run(run_flow())
        assert candidate.status == "candidate"
        assert candidate.type == "experience"
        assert candidate.source_employee_id == employee_id
        assert candidate.evidence[0].result == "PASS"

        candidate_stats = client.get(
            "/api/library/stats",
            headers={"X-Astra-User-Id": "reviewer-2", "X-Astra-Role": "reviewer"},
        ).json()
        assert candidate_stats["candidate_experiences"] >= 1
        candidate_rows = client.get(
            "/api/library/knowledge",
            params={"type": "experience", "status": "candidate"},
            headers={"X-Astra-User-Id": "reviewer-2", "X-Astra-Role": "reviewer"},
        ).json()
        assert any(item["id"] == candidate.id for item in candidate_rows["items"])

        space_id = client.get("/api/library/spaces").json()[1]["id"]
        published = client.post(
            f"/api/library/knowledge/{candidate.id}/publish",
            json={"space_id": space_id, "verification_status": "verified"},
            headers={"X-Astra-User-Id": "reviewer-2", "X-Astra-Role": "reviewer"},
        )
        assert published.status_code == 200

        async def audit_state():
            async with SessionLocal() as session:
                audits = await session.scalar(select(func.count(KnowledgeAudit.id)).where(
                    KnowledgeAudit.knowledge_id == candidate.id))
                item = await session.get(KnowledgeItem, candidate.id)
                return audits, item

        audit_count, stored = asyncio.run(audit_state())
        assert audit_count >= 2
        assert stored.status == "published"


def test_mcp_server_exposes_only_the_five_v1_library_tools():
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "library_search",
        "library_get",
        "library_related",
        "library_submit_experience",
        "library_feedback",
    }

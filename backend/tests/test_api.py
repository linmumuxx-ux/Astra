import asyncio
import sys

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.domain import TaskStatus
from app.main import app
from app.models import Event, OpenCodeExecutionEnvironment, Task


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


def test_task_workbench_keeps_one_session_for_messages_inquiries_and_follow_up_runs():
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json=task_payload(title="持续任务工作台", priority="MEDIUM"),
        ).json()
        task_id = created["id"]

        initial = client.get(f"/api/tasks/{task_id}/workspace")
        assert initial.status_code == 200
        initial_workspace = initial.json()
        session_id = initial_workspace["session"]["id"]
        assert initial_workspace["messages"][0]["role"] == "user"
        assert initial_workspace["events"][0]["event_type"] == "run.created"
        session_events = client.get(f"/api/sessions/{session_id}/events")
        assert session_events.status_code == 200
        assert session_events.json()[0]["session_id"] == session_id
        assert session_events.json()[0]["event_type"] == "run.created"

        queued = client.post(
            f"/api/tasks/{task_id}/messages",
            json={"content": "增加一个异常测试场景"},
        )
        assert queued.status_code == 200
        assert queued.json()["session"]["id"] == session_id
        assert queued.json()["messages"][-1]["status"] == "QUEUED"

        async def mark_waiting():
            async with SessionLocal() as session:
                row = await session.get(Task, task_id)
                row.status = TaskStatus.WAIT_HUMAN
                row.human_intervention = {
                    "blocking_reason": "存在两个候选方案",
                    "requested_input": "请选择方案 A 或方案 B",
                    "options": [{"label": "方案 A", "value": "A"}, {"label": "方案 B", "value": "B"}],
                }
                await session.commit()

        asyncio.run(mark_waiting())
        waiting = client.get(f"/api/tasks/{task_id}/workspace").json()
        inquiry = waiting["inquiries"][-1]
        assert inquiry["status"] == "OPEN"
        assert inquiry["options"][1]["value"] == "B"

        status_reply = client.post(
            f"/api/tasks/{task_id}/messages",
            json={"content": "/status"},
        )
        assert status_reply.status_code == 200
        assert status_reply.json()["task"]["status"] == "WAIT_HUMAN"
        assert status_reply.json()["inquiries"][-1]["status"] == "OPEN"
        assert status_reply.json()["messages"][-1]["role"] == "agent"
        assert "WAIT_HUMAN" in status_reply.json()["messages"][-1]["content"]

        answered = client.post(
            f"/api/inquiries/{inquiry['id']}/answer",
            json={"answer": "B"},
        )
        assert answered.status_code == 200
        answered_workspace = answered.json()
        assert answered_workspace["session"]["id"] == session_id
        assert answered_workspace["inquiries"][-1]["status"] == "ANSWERED"
        assert answered_workspace["task"]["status"] == "READY"

        async def mark_completed():
            async with SessionLocal() as session:
                row = await session.get(Task, task_id)
                row.status = TaskStatus.COMPLETED
                await session.commit()

        asyncio.run(mark_completed())
        continued = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"content": "继续优化脚本"},
        )
        assert continued.status_code == 200
        assert continued.json()["session"]["id"] == session_id
        assert continued.json()["task"]["status"] == "READY"


def test_workbench_projects_structured_task_tool_into_subagent_session_block():
    with TestClient(app) as client:
        task = client.post(
            "/api/tasks",
            json=task_payload(title="结构化 Subagent 事件", priority="MEDIUM"),
        ).json()

        async def add_runtime_events():
            async with SessionLocal() as session:
                session.add(
                    Event(
                        task_id=task["id"],
                        event_type="TOOL_ACTIVITY",
                        phase="operation",
                        message="Print hello world",
                        detail={
                            "tool": "task",
                            "status": "completed",
                            "title": "Print hello world",
                            "call_id": "call_structured_subagent",
                            "input": {
                                "description": "Print hello world",
                                "prompt": "打印 hello world",
                                "subagent_type": "general",
                            },
                            "output": "<task_result>hello world</task_result>",
                            "metadata": {
                                "parentSessionId": "ses_parent",
                                "sessionId": "ses_child",
                            },
                            "semantic_event_type": "tool.completed",
                        },
                    )
                )
                session.add(
                    Event(
                        task_id=task["id"],
                        event_type="MESSAGE_AGENT",
                        phase="message",
                        message="新的 subagent 返回了 hello world",
                        detail={},
                    )
                )
                await session.commit()

        asyncio.run(add_runtime_events())
        workspace = client.get(f"/api/tasks/{task['id']}/workspace")

        assert workspace.status_code == 200
        payload = workspace.json()
        subagent_events = [
            event for event in payload["events"] if event["event_type"].startswith("subagent.")
        ]
        assert len(subagent_events) == 1
        assert subagent_events[0]["event_type"] == "subagent.completed"
        assert subagent_events[0]["agent_name"] == "general"
        assert subagent_events[0]["payload"]["child_session_id"] == "ses_child"
        assert subagent_events[0]["payload"]["compatibility_projection"] is True
        assert any(
            block["block_type"] == "operation_group" and block["semantic_type"] == "tool.group"
            for block in payload["blocks"]
        )
        assert any(
            block["block_type"] == "event"
            and block["semantic_type"] == "subagent.completed"
            and block["visibility"] == "primary"
            for block in payload["blocks"]
        )


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
                    "model_name": "deepseek/deepseek-v4-flash",
                    "workspace_root": str(tmp_path / "employee-workspace"),
                },
            },
        )
        assert created.status_code == 201
        employee = created.json()
        assert employee["task_types"] == ["ISSUE", "REQUIREMENT"]
        assert employee["category_ids"] == [category_id]
        assert employee["execution_environment"]["workspace_root"].endswith("employee-workspace")
        assert employee["execution_environment"]["model_name"] == "deepseek/deepseek-v4-flash"
        assert "skills" not in employee
        assert "capabilities" not in employee

        checked = client.post("/api/employees/astra-api-v03/environment/test")
        assert checked.status_code == 200
        assert checked.json()["status"] == "AVAILABLE"
        assert all(item["passed"] for item in checked.json()["checks"])


def test_remote_ssh_password_is_never_returned_and_blank_update_keeps_value():
    with TestClient(app) as client:
        category = client.post(
            "/api/task-categories",
            json={"name": "远程环境测试", "description": "验证 SSH 密码边界"},
        )
        assert category.status_code == 201
        created = client.post(
            "/api/employees",
            json={
                "id": "astra-api-remote-password",
                "name": "远程密码员工",
                "role": "远程执行测试",
                "category_ids": [category.json()["id"]],
                "execution_environment": {
                    "mode": "LINUX_REMOTE",
                    "name": "远程 Agent 环境",
                    "host": "example.internal",
                    "port": 22,
                    "username": "nexus",
                    "ssh_password": "database-only-secret",
                    "opencode_server_port": 4196,
                    "opencode_path": "/opt/agent/start-agent.sh",
                    "workspace_root": "/srv/workspace",
                },
            },
        )

        assert created.status_code == 201
        environment = created.json()["execution_environment"]
        assert environment["has_ssh_password"] is True
        assert environment["opencode_server_port"] == 4196
        assert "ssh_password" not in environment

        updated = client.put(
            "/api/employees/astra-api-remote-password/environment",
            json={
                "mode": "LINUX_REMOTE",
                "name": "远程 Agent 环境（已更新）",
                "host": "example.internal",
                "port": 22,
                "username": "nexus",
                "ssh_password": "",
                "opencode_server_port": 4296,
                "opencode_path": "/opt/agent/start-agent.sh",
                "workspace_root": "/srv/workspace",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["has_ssh_password"] is True
        assert updated.json()["opencode_server_port"] == 4296
        assert "ssh_password" not in updated.json()

        async def load_password():
            async with SessionLocal() as session:
                row = await session.get(OpenCodeExecutionEnvironment, environment["id"])
                return row.ssh_password

        assert asyncio.run(load_password()) == "database-only-secret"


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

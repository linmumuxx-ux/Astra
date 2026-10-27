"""AgentWork HITL is answered only via digital-employee relay."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain import EmployeeStatus, EnvironmentStatus, TaskStatus
from app.models import AgentWorker, Base, Event, OpenCodeExecutionEnvironment, RuntimeSession, Task
from app.runtime.environment import environment_snapshot
from app.runtime.hitl_relay import (
    hitl_wake_hint,
    intervention_from_pending,
    is_hitl_waiting,
    merge_intervention,
    normalize_permission_reply,
)
from app.runtime.lifecycle import RuntimeService
from app.runtime.wake_outbox import wake_hint
from app.task_tools import TaskTools, nexus_employee_id


def test_intervention_from_question_and_permission():
    question = intervention_from_pending(
        [{"id": "q1", "sessionID": "ses", "questions": [{"question": "颜色?", "options": [{"label": "蓝"}]}]}],
        [],
        allowed_sessions={"ses"},
    )
    assert question["runtime_kind"] == "question"
    assert question["runtime_request_id"] == "q1"
    assert "颜色" in question["requested_input"]

    permission = intervention_from_pending(
        [],
        [{"id": "p1", "sessionID": "ses", "permission": "bash", "patterns": ["rm"]}],
        allowed_sessions={"ses"},
    )
    assert permission["runtime_kind"] == "permission"
    assert permission["runtime_request_id"] == "p1"
    assert is_hitl_waiting("HITL_PERMISSION")
    assert normalize_permission_reply("拒绝") == "reject"
    assert normalize_permission_reply("始终允许") == "always"


def test_merge_keeps_submitted_response():
    pending = {"runtime_request_id": "q1", "runtime_kind": "question", "requested_input": "x"}
    current = {**pending, "response": "BLUE", "source": "digital-employee"}
    merged = merge_intervention(current, pending)
    assert merged["response"] == "BLUE"
    assert "nexus_task_answer_hitl" in hitl_wake_hint("T1", 9, pending)


def test_wake_hint_uses_hitl_copy_for_waiting_collaboration():
    task = Task(
        id="T1",
        title="t",
        task_type="ISSUE",
        category_id="testing",
        status=TaskStatus.WAITING,
        waiting_reason="HITL_QUESTION",
        human_required_reason="颜色?",
        human_intervention={
            "runtime_kind": "question",
            "requested_input": "颜色?",
            "options": [{"label": "蓝"}],
        },
        current_progress="",
        employee_id="E1",
    )
    event = Event(
        task_id="T1",
        event_type="TASK_WAITING",
        phase="work",
        message="等待",
        created_at=datetime.now(UTC),
    )
    event.id = 3
    hint = wake_hint(task, event, TaskStatus.WAITING)
    assert "nexus_task_answer_hitl" in hint
    assert "颜色" in hint


class Native:
    def __init__(self):
        self.pending = [{"id": "q1", "sessionID": "ses", "questions": [{"question": "marker?"}]}]
        self.pending_permissions = []
        self.question_replies = []
        self.sessions = {"ses": []}
        self.state = "idle"

    async def health(self):
        return {"healthy": True}

    async def session(self, directory, sid):
        return {"id": sid}

    async def status(self, directory, sid):
        return self.state

    async def questions(self, directory):
        return self.pending

    async def permissions(self, directory):
        return self.pending_permissions

    async def children(self, directory, sid):
        return []

    async def messages(self, directory, sid):
        return self.sessions[sid]

    async def messages_page(self, directory, sid, *, limit, before=None):
        return {"messages": self.sessions[sid], "next_before": None}

    async def reply_question(self, directory, request_id, answers):
        self.question_replies.append((request_id, answers))
        self.pending = [item for item in self.pending if item.get("id") != request_id]
        return True

    async def reply_permission(self, directory, request_id, reply):
        self.pending_permissions = [item for item in self.pending_permissions if item.get("id") != request_id]
        return True


@pytest.fixture
async def hitl_runtime(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    native = Native()

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield native

    monkeypatch.setattr("app.runtime.lifecycle.connect", connect)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    async with factory() as session:
        session.add(
            AgentWorker(
                id="E1",
                name="Engineer",
                role="build",
                status=EmployeeStatus.WORKING,
                enabled=True,
                auto_claim=True,
                auto_execute=False,
                task_types=["ISSUE"],
                category_ids=["testing"],
                current_task_count=1,
            )
        )
        environment = OpenCodeExecutionEnvironment(
            employee_id="E1",
            mode="LOCAL",
            name="local",
            workspace_root=str(workspace),
            repository_id=None,
            status=EnvironmentStatus.AVAILABLE,
        )
        session.add(environment)
        await session.flush()
        task = Task(
            id="T1",
            title="hitl",
            task_type="ISSUE",
            category_id="testing",
            status=TaskStatus.WAITING,
            waiting_reason="HITL_QUESTION",
            human_required_reason="marker?",
            responsible_employee_id="emp_1",
            employee_id="E1",
            current_session_id="ses",
            workspace=str(workspace),
            current_progress="marker?",
            execution_environment_snapshot=environment_snapshot(environment),
        )
        session.add(task)
        session.add(
            RuntimeSession(
                id="ses",
                task_id="T1",
                employee_id="E1",
                workspace=str(workspace),
                environment=environment_snapshot(environment),
                status="WAITING",
            )
        )
        await session.commit()
        yield SimpleNamespace(session=session, task=task, native=native, service=RuntimeService(session))
    await engine.dispose()


@pytest.mark.asyncio
async def test_answer_hitl_relays_into_opencode_question(hitl_runtime):
    updated = await hitl_runtime.service.answer_hitl("T1", "BLUE", source="digital-employee")
    assert hitl_runtime.native.question_replies == [("q1", [["BLUE"]])]
    assert updated.human_intervention["response"] == "BLUE"
    assert updated.human_intervention["source"] == "digital-employee"
    assert hitl_runtime.native.pending == []


@pytest.mark.asyncio
async def test_task_tools_answer_hitl_requires_owner(hitl_runtime):
    token = nexus_employee_id.set("emp_1")
    try:
        result = await TaskTools(hitl_runtime.session).answer_hitl("T1", "GREEN")
    finally:
        nexus_employee_id.reset(token)
    assert result["ok"] is True
    assert hitl_runtime.native.question_replies[-1] == ("q1", [["GREEN"]])

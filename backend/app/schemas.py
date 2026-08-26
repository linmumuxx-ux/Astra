from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain import Priority


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EmployeeCreate(BaseModel):
    id: str
    name: str
    role: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    source_scope: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1, ge=1, le=16)


class EmployeePatch(BaseModel):
    name: str | None = None
    role: str | None = None
    description: str | None = None
    capabilities: list[str] | None = None
    source_scope: list[str] | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=16)


class EmployeeRead(ORMModel):
    id: str
    name: str
    role: str
    description: str
    status: str
    capabilities: list[str]
    source_scope: list[str]
    max_concurrency: int
    current_task_count: int
    last_heartbeat: datetime | None
    online_since: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    source: str = "manual"
    external_task_id: str | None = None
    task_type: str
    title: str
    description: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    definition_of_done: list[str] = Field(default_factory=list)
    priority: Priority = Priority.P2
    max_retry_count: int = Field(default=3, ge=0, le=20)


class TaskRead(ORMModel):
    id: str
    source: str
    external_task_id: str | None
    task_type: str
    title: str
    description: str
    input: dict[str, Any]
    definition_of_done: list[str]
    priority: str
    status: str
    employee_id: str | None
    workspace: str | None
    opencode_session_id: str | None
    current_phase: str
    progress: int
    retry_count: int
    max_retry_count: int
    result: dict[str, Any] | None
    failure_reason: str | None
    human_required_reason: str | None
    claimed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskAction(BaseModel):
    reason: str | None = None
    note: str | None = None
    input_patch: dict[str, Any] | None = None


class RunRead(ORMModel):
    id: str
    task_id: str
    employee_id: str
    run_number: int
    status: str
    executor_type: str
    opencode_session_id: str | None
    started_at: datetime
    finished_at: datetime | None
    exit_code: int | None
    result: dict[str, Any] | None
    created_at: datetime


class EventRead(ORMModel):
    id: int
    task_id: str | None
    employee_id: str | None
    run_id: str | None
    event_type: str
    phase: str
    message: str
    detail: dict[str, Any]
    created_at: datetime


class EvidenceRead(ORMModel):
    id: int
    task_id: str
    run_id: str | None
    name: str
    kind: str
    path: str
    size: int
    content_type: str
    metadata_: dict[str, Any]
    created_at: datetime

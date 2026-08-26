from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import EnvironmentStatus, ExecutionMode, Priority


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ExecutionEnvironmentWrite(BaseModel):
    mode: ExecutionMode = ExecutionMode.LOCAL
    name: str = "本地 OpenCode"
    description: str = ""
    host: str | None = None
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = None
    auth_method: str = "SSH_AGENT"
    ssh_key_path: str | None = None
    opencode_path: str = Field(default="opencode", min_length=1)
    workspace_root: str = Field(default="./workspaces", min_length=1)
    labels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_remote(self):
        if self.mode is ExecutionMode.LINUX_REMOTE:
            missing = [
                label
                for label, value in {
                    "环境名称": self.name,
                    "Host": self.host,
                    "Username": self.username,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(f"Linux 远程环境缺少：{', '.join(missing)}")
            if self.auth_method not in {"SSH_AGENT", "SSH_KEY"}:
                raise ValueError("Linux 远程认证仅支持 SSH_AGENT 或 SSH_KEY")
            if self.auth_method == "SSH_KEY" and not self.ssh_key_path:
                raise ValueError("SSH_KEY 认证必须提供 ssh_key_path")
            if not self.workspace_root.startswith("/"):
                raise ValueError("Linux 远程 Workspace 根目录必须使用绝对路径")
        return self


class ExecutionEnvironmentRead(ORMModel):
    id: int
    employee_id: str
    mode: str
    name: str
    description: str
    host: str | None
    port: int
    username: str | None
    auth_method: str
    ssh_key_path: str | None
    opencode_path: str
    workspace_root: str
    status: str
    status_detail: dict[str, Any]
    labels: list[str]
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EnvironmentCheckItem(BaseModel):
    name: str
    passed: bool
    detail: str


class EnvironmentCheckResult(BaseModel):
    status: EnvironmentStatus
    checked_at: datetime
    checks: list[EnvironmentCheckItem]


class UsageSummary(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    total_tokens: int | None = None
    llm_call_count: int | None = None
    tool_call_count: int | None = None
    tool_success_count: int = 0
    tool_failure_count: int = 0
    duration_seconds: int = 0
    completed_tasks: int = 0
    task_count: int = 0


class EmployeeCreate(BaseModel):
    id: str
    name: str
    role: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    source_scope: list[str] = Field(default_factory=list)
    enabled: bool = True
    auto_claim: bool = True
    auto_execute: bool = True
    auto_repair: bool = True
    max_auto_retries: int = Field(default=3, ge=0, le=20)
    max_concurrency: int = Field(default=1, ge=1, le=16)
    execution_environment: ExecutionEnvironmentWrite = Field(default_factory=ExecutionEnvironmentWrite)


class EmployeePatch(BaseModel):
    name: str | None = None
    role: str | None = None
    description: str | None = None
    capabilities: list[str] | None = None
    skills: list[str] | None = None
    source_scope: list[str] | None = None
    enabled: bool | None = None
    auto_claim: bool | None = None
    auto_execute: bool | None = None
    auto_repair: bool | None = None
    max_auto_retries: int | None = Field(default=None, ge=0, le=20)
    max_concurrency: int | None = Field(default=None, ge=1, le=16)


class EmployeeRead(ORMModel):
    id: str
    name: str
    role: str
    description: str
    status: str
    capabilities: list[str]
    skills: list[str]
    source_scope: list[str]
    enabled: bool
    auto_claim: bool
    auto_execute: bool
    auto_repair: bool
    max_auto_retries: int
    max_concurrency: int
    current_task_count: int
    last_heartbeat: datetime | None
    online_since: datetime | None
    created_at: datetime
    updated_at: datetime
    execution_environment: ExecutionEnvironmentRead | None = None
    today_usage: UsageSummary = Field(default_factory=UsageSummary)
    today_completed: int = 0
    success_rate: float | None = None


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
    execution_environment_snapshot: dict[str, Any] | None
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
    execution_environment_snapshot: dict[str, Any]
    model_name: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    total_tokens: int | None
    llm_call_count: int | None
    tool_call_count: int | None
    created_at: datetime


class ToolUsageRead(ORMModel):
    id: int
    run_id: str
    tool_name: str
    call_count: int
    success_count: int
    failure_count: int
    duration_ms: int


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

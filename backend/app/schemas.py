from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import (
    AcceptanceStatus,
    CompletionPolicy,
    EnvironmentStatus,
    ExecutionMode,
    Priority,
    TaskType,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ExecutionEnvironmentWrite(BaseModel):
    mode: ExecutionMode = ExecutionMode.LOCAL
    name: str = "本地 Agent 工作环境"
    description: str = ""
    host: str | None = None
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = None
    ssh_password: str | None = Field(default=None, max_length=1024)
    opencode_server_port: int = Field(default=4096, ge=1, le=65535)
    opencode_path: str = Field(default="opencode", min_length=1)
    model_name: str | None = Field(default=None, max_length=255)
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
    has_ssh_password: bool
    opencode_server_port: int
    opencode_path: str
    model_name: str | None
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


class TaskCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    enabled: bool = True
    sort_order: int = 0


class TaskCategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class TaskCategoryRead(ORMModel):
    id: str
    name: str
    description: str
    enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class EmployeeCreate(BaseModel):
    id: str
    name: str
    role: str
    description: str = ""
    task_types: list[TaskType] = Field(default_factory=lambda: list(TaskType))
    category_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
    auto_claim: bool = True
    auto_execute: bool = True
    max_auto_retries: int = Field(default=3, ge=0, le=20)
    execution_environment: ExecutionEnvironmentWrite = Field(default_factory=ExecutionEnvironmentWrite)


class EmployeePatch(BaseModel):
    name: str | None = None
    role: str | None = None
    description: str | None = None
    task_types: list[TaskType] | None = None
    category_ids: list[str] | None = None
    enabled: bool | None = None
    auto_claim: bool | None = None
    auto_execute: bool | None = None
    max_auto_retries: int | None = Field(default=None, ge=0, le=20)


class EmployeeRead(ORMModel):
    id: str
    name: str
    role: str
    description: str
    status: str
    task_types: list[str]
    category_ids: list[str]
    enabled: bool
    auto_claim: bool
    auto_execute: bool
    max_auto_retries: int
    current_task_count: int
    last_heartbeat: datetime | None
    online_since: datetime | None
    created_at: datetime
    updated_at: datetime
    execution_environment: ExecutionEnvironmentRead | None = None
    today_usage: UsageSummary = Field(default_factory=UsageSummary)
    today_completed: int = 0


class AcceptanceCriterion(BaseModel):
    id: str | None = None
    content: str = Field(min_length=1, max_length=500)


class AcceptanceResult(BaseModel):
    criterion_id: str
    status: AcceptanceStatus
    description: str = ""
    evidence: list[str] = Field(default_factory=list)


class WorkResult(BaseModel):
    summary: str = Field(min_length=1)
    changes: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    commits: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    other: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    source: str = "manual"
    external_task_id: str | None = None
    task_type: TaskType
    category_id: str
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1)
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    employee_id: str | None = None
    priority: Priority = Priority.MEDIUM
    completion_policy: CompletionPolicy | None = None

    @model_validator(mode="after")
    def default_completion_policy(self):
        if self.completion_policy is None:
            self.completion_policy = (
                CompletionPolicy.MANUAL_CONFIRM
                if self.priority in {Priority.VERY_HIGH, Priority.HIGH}
                else CompletionPolicy.AUTO
            )
        return self


class TaskRead(ORMModel):
    id: str
    source: str
    external_task_id: str | None
    task_type: str
    category_id: str | None
    title: str
    description: str
    acceptance_criteria: list[AcceptanceCriterion]
    attachments: list[dict[str, Any]]
    priority: str
    completion_policy: str
    status: str
    employee_id: str | None
    opencode_session_id: str | None
    current_progress: str
    suspension: dict[str, Any] | None
    execution_error: dict[str, Any] | None
    review_history: list[dict[str, Any]]
    inactivity_alert: bool
    inactivity_alert_since: datetime | None
    last_activity_at: datetime | None
    submitted_at: datetime | None
    confirmed_at: datetime | None
    result: dict[str, Any] | None
    failure_reason: str | None
    human_required_reason: str | None
    human_intervention: dict[str, Any] | None
    execution_environment_snapshot: dict[str, Any] | None
    claimed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskAction(BaseModel):
    reason: str | None = None
    note: str | None = None


class TaskProgressUpdate(BaseModel):
    current_progress: str = Field(min_length=1, max_length=500)


class HumanInterventionWrite(BaseModel):
    blocking_reason: str = Field(min_length=1)
    completed_work: str = ""
    current_state: str = ""
    requested_input: str = Field(min_length=1)
    can_suspend: bool = False
    scene_context: str = ""


class TaskSuspendWrite(BaseModel):
    reason: str = Field(min_length=1)
    current_state: str = ""
    scene_context: str = ""
    requested_input: str = ""


class TaskRejectWrite(BaseModel):
    feedback: str = Field(min_length=1, max_length=2000)


class TaskCompletionWrite(BaseModel):
    result: WorkResult
    acceptance_results: list[AcceptanceResult] = Field(min_length=1)


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


class TaskSessionRead(ORMModel):
    id: str
    task_id: str
    status: str
    current_run_id: str | None
    created_at: datetime
    updated_at: datetime


class SessionMessageWrite(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SessionMessageRead(ORMModel):
    id: str
    session_id: str
    run_id: str | None
    role: str
    content: str
    status: str
    created_at: datetime


class InquiryAnswerWrite(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)


class RunInquiryRead(ORMModel):
    id: str
    session_id: str
    run_id: str | None
    agent_name: str | None
    question: str
    description: str
    options: list[dict[str, Any]]
    answer: str | None
    status: str
    created_at: datetime
    answered_at: datetime | None


class RuntimeEventRead(BaseModel):
    id: str
    session_id: str
    run_id: str | None
    sequence: int
    event_type: str
    agent_name: str | None
    timestamp: datetime
    phase: str
    summary: str
    payload: dict[str, Any]


class SessionBlockRead(BaseModel):
    """Stable workbench projection independent of an Agent CLI wire format."""

    id: str
    session_id: str
    run_id: str | None
    sequence: int | None
    block_type: Literal["message", "inquiry", "event", "operation_group"]
    semantic_type: str
    visibility: Literal["primary", "diagnostic"] = "primary"
    actor_name: str | None = None
    status: str | None = None
    timestamp: datetime
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    message: SessionMessageRead | None = None
    inquiry: RunInquiryRead | None = None
    events: list[RuntimeEventRead] = Field(default_factory=list)


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


class TaskWorkbenchRead(BaseModel):
    task: TaskRead
    session: TaskSessionRead
    messages: list[SessionMessageRead]
    events: list[RuntimeEventRead]
    blocks: list[SessionBlockRead]
    inquiries: list[RunInquiryRead]
    artifacts: list[EvidenceRead]
    runs: list[RunRead]
    has_more_events: bool = False

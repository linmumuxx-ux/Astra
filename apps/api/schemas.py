from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TeamInput(Input):
    name: str = Field(min_length=1, max_length=120)


class RoleInput(TeamInput):
    team_id: str
    mandate: str = ""
    permissions: list[str] = Field(default_factory=list)


class EmployeeInput(RoleInput):
    role_id: str
    scope: dict = Field(default_factory=dict)
    daily_token_budget: int = Field(default=100000, ge=0)


class GoalInput(Input):
    team_id: str
    owner_employee_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    metric: str = Field(min_length=1)
    scope: dict = Field(default_factory=dict)
    priority: int = Field(default=3, ge=1, le=5)
    deadline: int | None = None


class TaskInput(Input):
    team_id: str
    owner_employee_id: str
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    goal_id: str | None = None
    constraints: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    asset_scope: dict = Field(default_factory=dict)
    priority: int = Field(default=3, ge=1, le=5)
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"

    @field_validator("acceptance_criteria")
    @classmethod
    def criteria_nonblank(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("验收条件不能为空")
        return value


class ChannelInput(Input):
    team_id: str
    kind: Literal["DM", "GROUP"] = "GROUP"
    name: str = Field(min_length=1, max_length=240)
    member_ids: list[str] = Field(min_length=1)


class MessageInput(Input):
    content: str = Field(min_length=1, max_length=20000)
    mentions: list[str] = Field(default_factory=list)
    attachment_refs: list[str] = Field(default_factory=list)
    reply_to: str | None = None
    causal_root: str | None = Field(default=None, max_length=200)
    source_event_id: str | None = None


class HandoffInput(Input):
    target_employee_id: str
    reason: str = Field(default="工作责任交接", min_length=1)


class HandoffResponse(Input):
    reason: str = Field(min_length=1, max_length=4000)


class OperationInput(Input):
    team_id: str
    action: Literal["task.pause", "task.cancel", "employee.pause", "knowledge.publish"]
    target_id: str
    payload: dict = Field(default_factory=dict)
    expires_in: int = Field(default=3600, ge=60, le=86400)


class RoutineInput(Input):
    employee_id: str
    goal_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    kind: Literal["INTERVAL", "CRON", "EVENT"] = "INTERVAL"
    schedule: str = Field(min_length=1, max_length=120)
    timezone: str = "Asia/Shanghai"
    locked: bool = False


class WorkerInput(Input):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(pattern=r"^https?://[^\s]+$")
    capabilities: list[str] = Field(default_factory=list)
    allowed_projects: list[str] = Field(default_factory=list)
    workspace_roots: list[str] = Field(default_factory=list)
    concurrent_slots: int = Field(default=1, ge=1, le=64)

    @field_validator("base_url")
    @classmethod
    def secret_free_url(cls, value):
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Worker URL 不得包含凭据、查询参数或片段")
        return value.rstrip("/")


class KnowledgeInput(Input):
    team_id: str
    title: str = Field(min_length=1, max_length=240)
    kind: Literal["SOURCE", "WIKI", "EXPERIENCE", "SKILL"] = "SOURCE"
    content: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)


class EventInput(Input):
    team_id: str
    source: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(default=1, ge=1)
    object_ref: str = Field(min_length=1, max_length=200)
    payload_ref: dict = Field(default_factory=dict)
    causal_root: str = Field(min_length=1, max_length=200)
    recipients: list[str] = Field(default_factory=list)


class DecisionInput(Input):
    disposition: Literal["reply", "no_action", "remember", "dispatch", "follow_up", "ask_human", "handoff"]


class DecisionNote(Input):
    reason: str = Field(default="", max_length=4000)


class RevisionPatch(Input):
    revision: int = Field(ge=1)


class GoalPatch(RevisionPatch):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    metric: str | None = Field(default=None, min_length=1)
    scope: dict | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    deadline: int | None = None
    owner_employee_id: str | None = None


class RolePatch(RevisionPatch):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    mandate: str | None = None
    permissions: list[str] | None = None


class EmployeePatch(RevisionPatch):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    scope: dict | None = None
    permissions: list[str] | None = None
    daily_token_budget: int | None = Field(default=None, ge=0)


class RoutinePatch(RevisionPatch):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    kind: Literal["INTERVAL", "CRON", "EVENT"] | None = None
    goal_id: str | None = None
    schedule: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = None
    enabled: bool | None = None
    locked: bool | None = None


class KnowledgePatch(RevisionPatch):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    content: str | None = Field(default=None, min_length=1)
    source_refs: list[str] | None = Field(default=None, min_length=1)


class HumanInput(Input):
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str] = Field(default_factory=list)
    credential_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class MemberInput(Input):
    actor_id: str
    role: Literal["ADMIN", "MEMBER"] = "MEMBER"


class GrantInput(Input):
    team_id: str
    actor_id: str
    project_id: str = Field(min_length=1, max_length=200)
    permissions: list[str] = Field(min_length=1)
    expires_at: int


class GrantPatch(RevisionPatch):
    permissions: list[str] = Field(min_length=1)
    expires_at: int


class HumanPatch(RevisionPatch):
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str]


class CredentialInput(Input):
    credential_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    lifetime_seconds: int = Field(default=86400, ge=300, le=86400)


class SchedulerInput(Input):
    name: str = Field(min_length=1, max_length=120)
    team_ids: list[str] = Field(min_length=1)
    credential_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class DispatchInput(Input):
    worker_id: str


class WorkerCredentialInput(RevisionPatch):
    credential_ref: str = Field(pattern=r"^file:/[^\x00]+$", max_length=240)


class NativeCitation(Input):
    native_session_id: str = Field(pattern=r"^ses[a-zA-Z0-9_-]+$")
    message_id: str = Field(pattern=r"^msg[a-zA-Z0-9_-]+$")
    part_id: str = Field(pattern=r"^prt[a-zA-Z0-9_-]+$")
    excerpt: str = Field(min_length=1, max_length=2000)


class CriterionResult(Input):
    criterion_index: int = Field(ge=0)
    passed: bool
    reason: str = Field(min_length=1, max_length=2000)
    evidence: list[NativeCitation] = Field(default_factory=list, max_length=10)


class TaskReviewInput(Input):
    execution_id: str
    expected_task_revision: int = Field(ge=1)
    outcome: Literal["COMPLETED", "REWORK", "WAIT_HUMAN"]
    criteria_results: list[CriterionResult] = Field(min_length=1, max_length=100)


MemoryNotes = dict[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}\.md$")], str]


class MemoryWriteInput(Input):
    expected_head: str | None = Field(pattern=r"^[a-f0-9]{40}$")
    content: str = Field(max_length=16000)
    notes: MemoryNotes = Field(default_factory=dict, max_length=20, description="文件名不含 notes/ 前缀")
    source_refs: list[str] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=1, max_length=1000)
    expires_at: int | None = None


class PersonaAction(Input):
    admission_id: str


class ReplyAction(PersonaAction):
    type: Literal["reply"]
    content: str = Field(min_length=1, max_length=4000)


class NoAction(PersonaAction):
    type: Literal["no_action"]
    reason: str = Field(min_length=1, max_length=1000)


class RememberAction(PersonaAction):
    type: Literal["remember"]
    content: str = Field(max_length=16000)
    notes: MemoryNotes = Field(default_factory=dict, max_length=20, description="文件名不含 notes/ 前缀")
    reason: str = Field(min_length=1, max_length=1000)
    expires_at: int | None = None


class DispatchAction(PersonaAction):
    type: Literal["dispatch"]
    task: TaskInput
    worker_id: str


class FollowUpAction(PersonaAction):
    type: Literal["follow_up"]
    after_seconds: int = Field(ge=60, le=604800)
    reason: str = Field(min_length=1, max_length=1000)


class AskHumanAction(PersonaAction):
    type: Literal["ask_human"]
    operation: OperationInput


class HandoffAction(PersonaAction):
    type: Literal["handoff"]
    task_id: str
    handoff: HandoffInput


class ReviewAction(PersonaAction):
    type: Literal["review"]
    task_id: str
    review: TaskReviewInput


class RedispatchAction(PersonaAction):
    type: Literal["redispatch"]
    task_id: str
    expected_task_revision: int = Field(ge=1)
    worker_id: str


class PersonaDecision(Input):
    plan: str = Field(max_length=4000)
    actions: list[
        Annotated[
            ReplyAction
            | NoAction
            | RememberAction
            | DispatchAction
            | FollowUpAction
            | AskHumanAction
            | HandoffAction
            | ReviewAction
            | RedispatchAction,
            Field(discriminator="type"),
        ]
    ] = Field(min_length=1, max_length=12)

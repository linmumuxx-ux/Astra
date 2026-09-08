from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.runtime.presentation import RuntimeProjection


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Persist UTC without relying on a database-specific timezone column."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, _dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, _dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class TaskCategory(Base):
    __tablename__ = "task_categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    task_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class DigitalEmployee(RuntimeProjection, Base):
    __tablename__ = "digital_employees"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    default_work_area: Mapped[str] = mapped_column(
        String(32), default="development", server_default="development"
    )
    status: Mapped[str] = mapped_column(String(32), default="OFFLINE", index=True)
    task_types: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["ISSUE", "REQUIREMENT"])
    category_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_claim: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_execute: Mapped[bool] = mapped_column(Boolean, default=True)
    max_auto_retries: Mapped[int] = mapped_column(Integer, default=3)
    current_task_count: Mapped[int] = mapped_column(Integer, default=0)
    active_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(UTCDateTime())
    online_since: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    runtime_run: Mapped["Run | None"] = relationship(
        foreign_keys=[active_run_id], lazy="selectin", viewonly=True,
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="employee")
    execution_environment: Mapped["OpenCodeExecutionEnvironment | None"] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan"
    )


class OpenCodeExecutionEnvironment(Base):
    __tablename__ = "opencode_execution_environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("digital_employees.id"), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(32), default="LOCAL", index=True)
    name: Mapped[str] = mapped_column(String(120), default="本地 Agent 工作环境")
    description: Mapped[str] = mapped_column(Text, default="")
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ssh_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    opencode_server_port: Mapped[int] = mapped_column(Integer, default=4096)
    opencode_path: Mapped[str] = mapped_column(Text, default="opencode")
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_root: Mapped[str] = mapped_column(Text, default="./workspaces")
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    status_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    employee: Mapped[DigitalEmployee] = relationship(back_populates="execution_environment")

    @property
    def has_ssh_password(self) -> bool:
        return bool(self.ssh_password)


class Task(RuntimeProjection, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("source", "external_task_id", name="uq_task_source_external"),
        Index("ix_tasks_dispatch", "status", "priority_weight", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    external_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    task_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    acceptance_criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    priority_weight: Mapped[int] = mapped_column(Integer, default=2)
    completion_policy: Mapped[str] = mapped_column(String(32), default="AUTO")
    status: Mapped[str] = mapped_column(String(32), default="READY", index=True)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("digital_employees.id"), nullable=True)
    active_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )
    current_progress: Mapped[str] = mapped_column(Text, default="等待领取")
    human_intervention: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    suspension: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    inactivity_alert: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    inactivity_alert_since: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    opencode_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_required_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_environment_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    runtime_run: Mapped["Run | None"] = relationship(
        foreign_keys=[active_run_id], lazy="selectin", viewonly=True,
    )

    employee: Mapped[DigitalEmployee | None] = relationship(back_populates="tasks")
    runs: Mapped[list["Run"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="Run.task_id",
    )
    events: Mapped[list["Event"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    work_session: Mapped["TaskSession | None"] = relationship(
        back_populates="task", uselist=False, cascade="all, delete-orphan"
    )


class Run(RuntimeProjection, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("task_id", "run_number", name="uq_task_run_number"),
        UniqueConstraint("execution_token", name="uq_runs_execution_token"),
        Index("ix_runs_task_active", "task_id", "status"),
        Index("ix_runs_employee_active", "employee_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("digital_employees.id"))
    previous_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    run_number: Mapped[int] = mapped_column(Integer)
    trigger_reason: Mapped[str] = mapped_column(String(64), default="INITIAL", server_default="INITIAL")
    retry_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    executor_type: Mapped[str] = mapped_column(String(64), default="opencode_server")
    opencode_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    dispatch_attempt: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    execution_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executor_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    failure_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recovery_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_environment_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="runs", foreign_keys=[task_id])
    events: Mapped[list["Event"]] = relationship(back_populates="run")
    tool_usages: Mapped[list["ToolUsage"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RunDispatchOutbox(Base):
    __tablename__ = "run_dispatch_outbox"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), default="EXECUTE_RUN")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ToolUsage(Base):
    __tablename__ = "tool_usages"
    __table_args__ = (UniqueConstraint("run_id", "tool_name", name="uq_run_tool_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(160), index=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[Run] = relationship(back_populates="tool_usages")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("digital_employees.id"), nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    phase: Mapped[str] = mapped_column(String(80), default="system")
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

    task: Mapped[Task | None] = relationship(back_populates="events")
    run: Mapped[Run | None] = relationship(back_populates="events")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="evidence")


class TaskSession(Base):
    """The durable collaboration space that belongs to one task."""

    __tablename__ = "task_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    current_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    task: Mapped[Task] = relationship(back_populates="work_session")
    messages: Mapped[list["SessionMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    inquiries: Mapped[list["RunInquiry"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("task_sessions.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(24), index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

    session: Mapped[TaskSession] = relationship(back_populates="messages")


class RunInquiry(Base):
    __tablename__ = "run_inquiries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("task_sessions.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    session: Mapped[TaskSession] = relationship(back_populates="inquiries")


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_spaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_spaces.id"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    access_scope: Mapped[str] = mapped_column(String(160), default="public", index=True)
    created_by: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    items: Mapped[list["KnowledgeItem"]] = relationship(back_populates="space")


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (
        Index("ix_knowledge_items_browse", "status", "space_id", "updated_at"),
        Index("ix_knowledge_items_experience", "type", "status", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_spaces.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240), index=True)
    type: Mapped[str] = mapped_column(String(32), default="document", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    content_md: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified", index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("digital_employees.id"), nullable=True, index=True
    )
    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    experience_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(120))
    updated_by: Mapped[str] = mapped_column(String(120))
    published_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reference_count: Mapped[int] = mapped_column(Integer, default=0)
    helpful_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    space: Mapped[KnowledgeSpace | None] = relationship(back_populates="items")
    sources: Mapped[list["KnowledgeSource"]] = relationship(
        back_populates="knowledge", cascade="all, delete-orphan"
    )
    evidence: Mapped[list["ExperienceEvidence"]] = relationship(
        back_populates="knowledge", cascade="all, delete-orphan"
    )


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    knowledge: Mapped[KnowledgeItem] = relationship(back_populates="sources")


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_knowledge_id",
            "target_knowledge_id",
            "relation_type",
            name="uq_knowledge_relation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    target_knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), default="related")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class KnowledgeSync(Base):
    """Durable per-source work; deliberately survives deletion of the original."""

    __tablename__ = "knowledge_sync"

    knowledge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeUsage(Base):
    __tablename__ = "knowledge_usage"
    __table_args__ = (Index("ix_knowledge_usage_summary", "action", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    knowledge_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("digital_employees.id"), nullable=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class KnowledgeFeedback(Base):
    __tablename__ = "knowledge_feedback"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "actor_key", "feedback_type", name="uq_knowledge_feedback_actor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    knowledge_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_key: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("digital_employees.id"), nullable=True, index=True
    )
    feedback_type: Mapped[str] = mapped_column(String(32), index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class KnowledgeFavorite(Base):
    __tablename__ = "knowledge_favorites"
    __table_args__ = (UniqueConstraint("knowledge_id", "user_id", name="uq_knowledge_favorite_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ExperienceEvidence(Base):
    __tablename__ = "experience_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    knowledge: Mapped[KnowledgeItem] = relationship(back_populates="evidence")


class KnowledgeAudit(Base):
    __tablename__ = "knowledge_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(48), index=True)
    actor_id: Mapped[str] = mapped_column(String(120), index=True)
    actor_role: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

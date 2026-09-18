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
    last_heartbeat: Mapped[datetime | None] = mapped_column(UTCDateTime())
    online_since: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

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
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("digital_employees.id"), nullable=True)
    workspace: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    turn_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    pending_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    pending_prompt: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    runtime_connection: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    runtime_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    current_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_required_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_environment_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    employee: Mapped[DigitalEmployee | None] = relationship(back_populates="tasks")
    events: Mapped[list["Event"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    summary: Mapped["TaskSummary | None"] = relationship(
        back_populates="task", uselist=False, cascade="all, delete-orphan"
    )


class RuntimeSession(Base):
    """Binding and result index; OpenCode owns all messages and execution details."""

    __tablename__ = "runtime_sessions"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("digital_employees.id"))
    workspace: Mapped[str] = mapped_column(Text)
    environment: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN", index=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_usage: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    superseded_by: Mapped[str | None] = mapped_column(
        ForeignKey("runtime_sessions.id"), nullable=True, index=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    runtime_context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    runtime_context_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("digital_employees.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    phase: Mapped[str] = mapped_column(String(80), default="system")
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

    task: Mapped[Task | None] = relationship(back_populates="events")


class TaskSummary(Base):
    """One durable summary per Task; Session facts are referenced, never mirrored."""

    __tablename__ = "task_summaries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, index=True
    )
    primary_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("runtime_sessions.id", ondelete="SET NULL"), nullable=True
    )
    referenced_session_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    content_md: Mapped[str] = mapped_column(Text, default="")
    acceptance_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    key_changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    generation: Mapped[int] = mapped_column(Integer, default=0)
    stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    generated_by: Mapped[str] = mapped_column(String(120), default="deterministic")
    source_ref_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    task: Mapped[Task] = relationship(back_populates="summary")


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
        UniqueConstraint("dedupe_key", "fingerprint", name="uq_knowledge_dedupe"),
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
    source_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("runtime_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    origin: Mapped[str] = mapped_column(String(32), default="manual", server_default="manual")
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    experience_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    session_status_at_submission: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_session_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    session_last_message_id_at_verification: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    source_ref_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("runtime_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    source_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("runtime_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    part_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
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

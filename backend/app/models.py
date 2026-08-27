from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TaskCategory(Base):
    __tablename__ = "task_categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DigitalEmployee(Base):
    __tablename__ = "digital_employees"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="OFFLINE", index=True)
    task_types: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["ISSUE", "REQUIREMENT"])
    category_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_claim: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_execute: Mapped[bool] = mapped_column(Boolean, default=True)
    max_auto_retries: Mapped[int] = mapped_column(Integer, default=3)
    current_task_count: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    online_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

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
    auth_method: Mapped[str] = mapped_column(String(32), default="SSH_AGENT")
    ssh_key_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    opencode_path: Mapped[str] = mapped_column(Text, default="opencode")
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_root: Mapped[str] = mapped_column(Text, default="./workspaces")
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    status_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    employee: Mapped[DigitalEmployee] = relationship(back_populates="execution_environment")


class Task(Base):
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
    current_progress: Mapped[str] = mapped_column(Text, default="等待领取")
    human_intervention: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    suspension: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    inactivity_alert: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    inactivity_alert_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opencode_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_required_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_environment_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    employee: Mapped[DigitalEmployee | None] = relationship(back_populates="tasks")
    runs: Mapped[list["Run"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("task_id", "run_number", name="uq_task_run_number"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("digital_employees.id"))
    run_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    executor_type: Mapped[str] = mapped_column(String(64), default="opencode_cli")
    opencode_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="runs")
    events: Mapped[list["Event"]] = relationship(back_populates="run")
    tool_usages: Mapped[list["ToolUsage"]] = relationship(back_populates="run", cascade="all, delete-orphan")


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="evidence")

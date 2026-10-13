from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record, now


class Task(Record, Base):
    __tablename__ = "tasks"
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    owner_employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"))
    created_by_actor: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("goals.id"))
    source_event_id: Mapped[str | None] = mapped_column(ForeignKey("source_events.id"))
    title: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list] = mapped_column(JSON)
    constraints: Mapped[list] = mapped_column(JSON, default=list)
    required_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    asset_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    priority: Mapped[int] = mapped_column(default=3)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    continuity_key: Mapped[str] = mapped_column(String(200))
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    latest_result: Mapped[dict | None] = mapped_column(JSON)
    read_only: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[int | None]
    updated_at: Mapped[int] = mapped_column(default=now, onupdate=now)


class TaskExecution(Record, Base):
    __tablename__ = "task_executions"
    __table_args__ = (UniqueConstraint("task_id", "attempt_no"),)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    native_session_id: Mapped[str | None] = mapped_column(String(120))
    workspace_ref: Mapped[str | None] = mapped_column(Text)
    workspace_base_commit: Mapped[str | None] = mapped_column(String(64))
    preparation_started_at: Mapped[int | None]
    submission_started_at: Mapped[int | None]
    permission_digest: Mapped[str | None] = mapped_column(String(64))
    stop_requested: Mapped[str | None] = mapped_column(String(16))
    abort_started_at: Mapped[int | None]
    attempt_no: Mapped[int]
    lease_id: Mapped[str | None] = mapped_column(ForeignKey("worker_leases.id"))
    lease_fence: Mapped[int | None]
    read_only: Mapped[bool] = mapped_column(default=False)
    grant_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(24), default="BOUND")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    output_ref: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[int | None]
    finished_at: Mapped[int | None]
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("task_executions.id"))


class Handoff(Record, Base):
    __tablename__ = "handoffs"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    source_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    target_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[str] = mapped_column(String(24), default="PROPOSED")
    task_revision: Mapped[int]
    reason: Mapped[str] = mapped_column(Text)


class TaskReview(Record, Base):
    __tablename__ = "task_reviews"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    execution_id: Mapped[str] = mapped_column(ForeignKey("task_executions.id"))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    outcome: Mapped[str] = mapped_column(String(24))
    criteria_results: Mapped[list] = mapped_column(JSON)
    evidence_refs: Mapped[list] = mapped_column(JSON)

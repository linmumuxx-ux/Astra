from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record


class EmployeeState(Record, Base):
    __tablename__ = "employee_state"
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), unique=True)
    plan_digest: Mapped[str] = mapped_column(Text, default="")
    memory_head: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[int] = mapped_column(default=0)
    fence: Mapped[int] = mapped_column(default=0)
    next_review: Mapped[int | None]


class SourceEvent(Record, Base):
    __tablename__ = "source_events"
    __table_args__ = (UniqueConstraint("source", "source_id", "revision"),)
    source: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(String(200))
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    object_ref: Mapped[str] = mapped_column(String(200))
    payload_ref: Mapped[dict] = mapped_column(JSON, default=dict)
    causal_root: Mapped[str] = mapped_column(String(200))
    occurred_at: Mapped[int]


class InboxAdmission(Record, Base):
    __tablename__ = "inbox_admissions"
    __table_args__ = (UniqueConstraint("employee_id", "source_event_id"),)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    source_event_id: Mapped[str] = mapped_column(ForeignKey("source_events.id"))
    reason: Mapped[str] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(default=3)
    wake_policy: Mapped[str] = mapped_column(String(16), default="IMMEDIATE")
    observed_at: Mapped[int | None]
    disposition: Mapped[str | None] = mapped_column(String(24))


class EmployeeTurn(Record, Base):
    __tablename__ = "employee_turns"
    __table_args__ = (UniqueConstraint("employee_id", "fence"),)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    fence: Mapped[int]
    status: Mapped[str] = mapped_column(String(24), default="RUNNING")
    native_session_id: Mapped[str | None] = mapped_column(String(120))
    input_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    submission_started_at: Mapped[int | None]
    budget_reservation: Mapped[int] = mapped_column(default=0)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    finished_at: Mapped[int | None]


class Routine(Record, Base):
    __tablename__ = "routines"
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("goals.id"))
    title: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(16), default="INTERVAL")
    schedule: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    enabled: Mapped[bool] = mapped_column(default=True)
    locked: Mapped[bool] = mapped_column(default=False)
    next_due_at: Mapped[int]

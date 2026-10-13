from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record, now


class Operation(Record, Base):
    __tablename__ = "operations"
    initiator_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(36))
    target_revision: Mapped[int]
    policy_revision: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="WAIT_HUMAN")
    expires_at: Mapped[int]
    decision_note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("actors.id"))
    result: Mapped[dict | None] = mapped_column(JSON)


class Mutation(Record, Base):
    __tablename__ = "mutations"
    __table_args__ = (UniqueConstraint("actor_id", "operation_key"),)
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    operation_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), index=True)
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id"))
    type: Mapped[str] = mapped_column(String(80))
    entity_ref: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int]
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(default=now)


class BudgetUsage(Record, Base):
    __tablename__ = "budget_usage"
    __table_args__ = (UniqueConstraint("actor_id", "purpose", "native_session_id"),)
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    purpose: Mapped[str] = mapped_column(String(16))
    native_session_id: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(120))
    tokens: Mapped[int]
    cost_micros: Mapped[int]


class HistoricalArtifact(Record, Base):
    __tablename__ = "historical_artifacts"
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    content_ref: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    visibility: Mapped[str] = mapped_column(String(16), default="AUDIT")
    owner_actor_id: Mapped[str | None] = mapped_column(ForeignKey("actors.id"))
    read_only: Mapped[bool] = mapped_column(default=True)

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record


class Actor(Record, Base):
    __tablename__ = "actors"
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Credential(Record, Base):
    __tablename__ = "credentials"
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[int]
    revoked: Mapped[bool] = mapped_column(default=False)


class WorkspaceGrant(Record, Base):
    __tablename__ = "workspace_grants"
    __table_args__ = (UniqueConstraint("actor_id", "project_id"),)
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    project_id: Mapped[str] = mapped_column(String(200))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[int]

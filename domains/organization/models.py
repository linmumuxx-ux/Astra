from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record


class Team(Record, Base):
    __tablename__ = "teams"
    name: Mapped[str] = mapped_column(String(120))
    denied_actions: Mapped[list] = mapped_column(JSON, default=list)


class TeamMember(Record, Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "actor_id"),)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")


class Role(Record, Base):
    __tablename__ = "roles"
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    mandate: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    skill_scope: Mapped[list] = mapped_column(JSON, default=list)
    knowledge_scope: Mapped[list] = mapped_column(JSON, default=list)


class Employee(Record, Base):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(ForeignKey("actors.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"))
    manager_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    lifecycle: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    daily_token_budget: Mapped[int] = mapped_column(default=100000)


class Goal(Record, Base):
    __tablename__ = "goals"
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    owner_employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"))
    title: Mapped[str] = mapped_column(String(240))
    metric: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    priority: Mapped[int] = mapped_column(default=3)
    deadline: Mapped[int | None]

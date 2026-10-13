from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record


class KnowledgeItem(Record, Base):
    __tablename__ = "knowledge_items"
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    created_by_actor: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    title: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    source_refs: Mapped[list] = mapped_column(JSON)
    verification: Mapped[str] = mapped_column(String(24), default="UNVERIFIED")
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")


class SkillVersion(Record, Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("knowledge_id", "version"),)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_items.id"))
    version: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    validation_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    published_by: Mapped[str | None] = mapped_column(ForeignKey("actors.id"))
    status: Mapped[str] = mapped_column(String(24), default="PROPOSED")

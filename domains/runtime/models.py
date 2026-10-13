from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record


class Worker(Record, Base):
    __tablename__ = "workers"
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    runtime_version: Mapped[str | None] = mapped_column(String(80))
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    allowed_projects: Mapped[list] = mapped_column(JSON, default=list)
    workspace_roots: Mapped[list] = mapped_column(JSON, default=list)
    credential_ref: Mapped[str | None] = mapped_column(String(240))
    health: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    concurrent_slots: Mapped[int] = mapped_column(default=1)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_seen_at: Mapped[int | None]


class WorkerLease(Record, Base):
    __tablename__ = "worker_leases"
    __table_args__ = (UniqueConstraint("worker_id", "slot"),)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    slot: Mapped[int]
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    fence: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(String(24), default="FREE")


class AssetLock(Record, Base):
    __tablename__ = "asset_locks"
    project_id: Mapped[str] = mapped_column(String(200), unique=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    fence: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int] = mapped_column(default=0)
    scope: Mapped[str] = mapped_column(Text)

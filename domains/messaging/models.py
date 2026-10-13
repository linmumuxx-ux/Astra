from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.core import Base, Record


class Channel(Record, Base):
    __tablename__ = "channels"
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(16))
    read_only: Mapped[bool] = mapped_column(default=False)
    dm_key: Mapped[str | None] = mapped_column(String(80), unique=True)


class ChannelMember(Record, Base):
    __tablename__ = "channel_members"
    __table_args__ = (UniqueConstraint("channel_id", "actor_id"),)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))


class Message(Record, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("channel_id", "seq"),)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), index=True)
    seq: Mapped[int]
    sender_id: Mapped[str] = mapped_column(ForeignKey("actors.id"))
    content: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    attachment_refs: Mapped[list] = mapped_column(JSON, default=list)
    reply_to: Mapped[str | None] = mapped_column(ForeignKey("messages.id"))
    causal_root: Mapped[str] = mapped_column(String(200))
    hops: Mapped[int] = mapped_column(default=0)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)

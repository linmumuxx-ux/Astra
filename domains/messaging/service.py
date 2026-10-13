import hashlib

from sqlalchemy import func, select

from domains.core import DomainError, new_id, now
from domains.governance.service import audit, cas, get_required
from domains.identity.models import Actor
from domains.identity.service import authorize, team_visible
from domains.messaging.models import Channel, ChannelMember, Message
from domains.organization.models import Employee
from domains.personas.models import InboxAdmission, SourceEvent
from domains.personas.service import admit


async def channel_access(session, principal, channel_id):
    channel = await get_required(session, Channel, channel_id)
    member = await session.scalar(
        select(ChannelMember.id).where(
            ChannelMember.channel_id == channel_id, ChannelMember.actor_id == principal.id
        )
    )
    if not member or not await team_visible(session, principal, channel.team_id):
        raise DomainError(403, "不是当前 Channel 成员")
    return channel


async def create_channel(session, principal, data):
    await authorize(session, principal, "channel.send", data.team_id)
    member_ids = sorted(set([principal.id, *data.member_ids]))
    if data.kind == "DM" and len(member_ids) != 2:
        raise DomainError(400, "DM 必须且只能包含两个独立成员")
    for member_id in member_ids:
        actor = await get_required(session, Actor, member_id)
        from domains.identity.service import current_principal

        if not actor.active or not await team_visible(
            session, await current_principal(session, member_id), data.team_id
        ):
            raise DomainError(403, "Channel 成员不在团队内")
    dm_key = ":".join(member_ids) if data.kind == "DM" else None
    if dm_key:
        previous = await session.scalar(select(Channel).where(Channel.dm_key == dm_key))
        if previous:
            await channel_access(session, principal, previous.id)
            if previous.team_id != data.team_id:
                raise DomainError(409, "该长期 DM 已属于另一团队上下文")
            return previous
    channel = Channel(team_id=data.team_id, name=data.name, kind=data.kind, dm_key=dm_key)
    session.add(channel)
    await session.flush()
    for member_id in member_ids:
        session.add(ChannelMember(channel_id=channel.id, actor_id=member_id))
    await audit(
        session, principal, data.team_id, "channel.created", channel, "交流空间已创建", channel_id=channel.id
    )
    return channel


async def send_message(session, principal, channel_id, data):
    channel = await channel_access(session, principal, channel_id)
    await authorize(session, principal, "channel.send", channel.team_id)
    if channel.read_only:
        raise DomainError(409, "历史只读 Channel 不能继续发言")
    if data.attachment_refs:
        raise DomainError(409, "附件需先接入受控上传与可见性校验，不能接受任意文件引用")
    members = set(
        (
            await session.scalars(
                select(ChannelMember.actor_id).where(ChannelMember.channel_id == channel.id)
            )
        ).all()
    )
    if not set(data.mentions) <= members:
        raise DomainError(400, "只能 @ 当前 Channel 成员")
    parent = None
    if data.reply_to:
        parent = await get_required(session, Message, data.reply_to)
        if parent.channel_id != channel.id:
            raise DomainError(403, "不能引用其他私聊的消息")
    source_event = None
    if data.source_event_id:
        source_event = await get_required(session, SourceEvent, data.source_event_id)
        admission = await session.scalar(select(InboxAdmission.id).where(
            InboxAdmission.employee_id == principal.id, InboxAdmission.source_event_id == source_event.id
        ))
        if principal.kind != "EMPLOYEE" or not admission or source_event.team_id != channel.team_id:
            raise DomainError(403, "自动汇报只能引用本人已接收的同团队工作事件")
        if source_event.source == "channel" and not parent:
            raise DomainError(400, "对话事件的自动回复须引用原消息")
    if principal.kind != "HUMAN" and not parent and not source_event:
        raise DomainError(400, "自动消息必须引用可核验的因果来源消息或工作事件")
    root = parent.causal_root if parent else (
        source_event.causal_root if source_event else data.causal_root or new_id()
    )
    hops = parent.hops + 1 if parent else (1 if source_event else 0)
    if principal.kind != "HUMAN" and hops > 6:
        raise DomainError(409, "自动消息往返次数已达到上限")
    fingerprint = hashlib.sha256(f"{channel.id}|{principal.id}|{root}|{data.content}".encode()).hexdigest()
    if principal.kind != "HUMAN":
        duplicate = await session.scalar(select(Message.id).where(Message.fingerprint == fingerprint))
        count = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.causal_root == root)
        )
        if duplicate or count >= 12:
            raise DomainError(409, "重复自动消息或因果链预算已耗尽")
    await cas(session, channel, {})
    message = Message(
        channel_id=channel.id,
        seq=channel.revision - 1,
        sender_id=principal.id,
        content=data.content,
        mentions=data.mentions,
        attachment_refs=[],
        reply_to=data.reply_to,
        causal_root=root,
        hops=hops,
        fingerprint=fingerprint,
    )
    session.add(message)
    await session.flush()
    event = SourceEvent(
        source="channel",
        source_id=message.id,
        actor_id=principal.id,
        team_id=channel.team_id,
        object_ref=f"messages/{message.id}",
        payload_ref={"channel_id": channel.id},
        causal_root=root,
        occurred_at=now(),
    )
    session.add(event)
    await session.flush()
    recipients = set(data.mentions)
    if channel.kind == "DM":
        recipients |= members - {principal.id}
    for recipient in recipients:
        employee = await session.get(Employee, recipient)
        if employee:
            await admit(session, event, recipient, reason="DM 或 @ 提醒")
    from domains.personas.routines import admit_event_routines

    await admit_event_routines(session, event)
    await audit(
        session,
        principal,
        channel.team_id,
        "message.created",
        message,
        "Channel 有新消息",
        channel_id=channel.id,
    )
    return message

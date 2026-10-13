from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domains.core import DomainError, now
from domains.identity.models import Actor, Credential, WorkspaceGrant
from domains.organization.models import Employee, Role, Team, TeamMember


@dataclass(frozen=True)
class Principal:
    id: str
    kind: str
    name: str
    permissions: frozenset[str]
    credential_id: str | None = None

    @property
    def admin(self):
        return self.kind == "HUMAN" and "*" in self.permissions


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_credential(session: AsyncSession, actor: Actor, *, lifetime: int = 86400) -> str:
    token = secrets.token_urlsafe(48)
    session.add(Credential(actor_id=actor.id, digest=digest(token), expires_at=now() + lifetime))
    return token


async def authenticate(session: AsyncSession, token: str) -> Principal:
    credential = await session.scalar(select(Credential).where(Credential.digest == digest(token)))
    if not credential or credential.revoked or credential.expires_at <= now():
        raise DomainError(401, "认证失效，请重新登录")
    actor = await session.get(Actor, credential.actor_id)
    if not actor or not actor.active:
        raise DomainError(401, "身份已停用")
    return Principal(actor.id, actor.kind, actor.name, frozenset(actor.permissions), credential.id)


async def team_visible(session: AsyncSession, principal: Principal, team_id: str) -> bool:
    return principal.admin or bool(
        await session.scalar(
            select(TeamMember.id).where(TeamMember.team_id == team_id, TeamMember.actor_id == principal.id)
        )
    )


async def authorize(
    session: AsyncSession,
    principal: Principal,
    action: str,
    team_id: str,
    *,
    project_id: str | None = None,
    human_only: bool = False,
):
    if human_only and principal.kind != "HUMAN":
        raise DomainError(403, "此操作必须由人类授权人执行")
    team = await session.get(Team, team_id, populate_existing=True, with_for_update=True)
    if not team or not await team_visible(session, principal, team_id):
        raise DomainError(403, "没有团队访问权限")
    if action in team.denied_actions or "*" in team.denied_actions:
        raise DomainError(403, "组织强制规则禁止此操作")
    if not principal.admin and action not in principal.permissions:
        raise DomainError(403, "缺少操作权限")
    if principal.kind == "EMPLOYEE":
        employee = await session.get(Employee, principal.id, populate_existing=True, with_for_update=True)
        if not employee or employee.lifecycle != "ACTIVE" or employee.team_id != team_id:
            raise DomainError(403, "员工不在有效履职范围")
        role = await session.get(Role, employee.role_id, populate_existing=True, with_for_update=True)
        if action not in employee.permissions or not role or action not in role.permissions:
            raise DomainError(403, "操作超出员工或岗位最大授权")
        if project_id and project_id not in employee.scope.get("projects", []):
            raise DomainError(403, "工程不在员工负责范围")
    if project_id:
        grant = await session.scalar(
            select(WorkspaceGrant)
            .where(
                WorkspaceGrant.actor_id == principal.id,
                WorkspaceGrant.team_id == team_id,
                WorkspaceGrant.project_id == project_id,
            )
            .with_for_update()
        )
        if not grant or grant.expires_at <= now() or action not in grant.permissions:
            raise DomainError(403, "缺少当前工程的有效 Workspace Grant")


async def current_principal(session: AsyncSession, actor_id: str) -> Principal:
    actor = await session.get(Actor, actor_id, populate_existing=True, with_for_update=True)
    if not actor or not actor.active:
        raise DomainError(403, "操作发起身份已撤销")
    return Principal(actor.id, actor.kind, actor.name, frozenset(actor.permissions))


async def revalidate_principal(session: AsyncSession, principal: Principal) -> Principal:
    """写入事务入口：与主体/凭据撤销串行，避免沿用请求开始时的授权。"""
    await session.execute(update(Actor).where(Actor.id == principal.id).values(revision=Actor.revision))
    fresh = await current_principal(session, principal.id)
    if principal.credential_id:
        credential = await session.get(
            Credential, principal.credential_id, populate_existing=True, with_for_update=True
        )
        if not credential or credential.revoked or credential.expires_at <= now():
            raise DomainError(401, "原认证凭据已经失效")
    return fresh

"""可信调度入口。凭据从部署文件读取，权限每个短事务重新验证。"""

from pathlib import Path

from sqlalchemy import select

from domains.core import DomainError
from domains.database import Database
from domains.identity.service import authenticate, revalidate_principal
from domains.organization.models import TeamMember
from domains.personas.routines import sweep_due_routines


async def sweep_authenticated(database_url: str, credential_file: str):
    token = Path(credential_file).read_text().strip()
    db = Database(database_url)
    try:
        async with db.sessions() as session:
            principal = await authenticate(session, token)
            if principal.kind != "SYSTEM" or "routine.signal" not in principal.permissions:
                raise DomainError(403, "定时服务必须使用专门签发的可信调度身份")
            team_ids = (
                await session.scalars(select(TeamMember.team_id).where(TeamMember.actor_id == principal.id))
            ).all()
        emitted = []
        for team_id in team_ids:
            async with db.sessions.begin() as session:
                # 撤权或凭据轮换后，后续团队扫描不能继续沿用旧 Principal。
                principal = await revalidate_principal(session, await authenticate(session, token))
                emitted.extend(await sweep_due_routines(session, principal, team_id=team_id))
        return {"teams_checked": len(team_ids), "source_event_ids": emitted}
    finally:
        await db.engine.dispose()

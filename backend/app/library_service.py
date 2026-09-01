from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import String, cast, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.library_schemas import (
    KnowledgeCreate,
    KnowledgeDetail,
    KnowledgeFavoriteResult,
    KnowledgeFeedbackResult,
    KnowledgeFeedbackWrite,
    KnowledgeListItem,
    KnowledgePage,
    KnowledgePatch,
    KnowledgePublishWrite,
    KnowledgeReviewWrite,
    KnowledgeSpaceCreate,
    KnowledgeSpacePatch,
    KnowledgeSpaceRead,
    LibraryFeedbackInput,
    LibrarySearchInput,
    LibrarySearchResult,
    LibraryStats,
    LibrarySubmitExperienceInput,
    LibraryUsageRecent,
    LibraryUsageSummary,
    RelatedTaskRead,
    UsageTopKnowledge,
    UsageTrendPoint,
)
from app.models import (
    DigitalEmployee,
    ExperienceEvidence,
    KnowledgeAudit,
    KnowledgeFavorite,
    KnowledgeFeedback,
    KnowledgeItem,
    KnowledgeRelation,
    KnowledgeSpace,
    KnowledgeUsage,
    Run,
    Task,
    utcnow,
)

KNOWLEDGE_TYPES = {"document", "rule", "guide", "experience", "faq", "tool", "example"}
KNOWLEDGE_STATUSES = {"draft", "candidate", "published", "archived", "rejected"}
FEEDBACK_TYPES = {"helpful", "incorrect", "outdated", "missing", "mismatch"}
ROLE_ALIASES = {
    "viewer": "viewer",
    "browser": "viewer",
    "maintainer": "maintainer",
    "reviewer": "reviewer",
    "admin": "admin",
}


class LibraryError(Exception):
    pass


class LibraryNotFound(LibraryError):
    pass


class LibraryForbidden(LibraryError):
    pass


class LibraryConflict(LibraryError):
    pass


class LibraryValidationError(LibraryError):
    pass


@dataclass(frozen=True, slots=True)
class LibraryPrincipal:
    user_id: str = "admin"
    role: str = "admin"

    @property
    def normalized_role(self) -> str:
        return ROLE_ALIASES.get(self.role.lower(), "viewer")

    @property
    def can_manage(self) -> bool:
        return self.normalized_role in {"maintainer", "admin"}

    @property
    def can_review(self) -> bool:
        return self.normalized_role in {"reviewer", "admin"}

    @property
    def is_admin(self) -> bool:
        return self.normalized_role == "admin"

    @property
    def visible_statuses(self) -> set[str]:
        if self.is_admin:
            return KNOWLEDGE_STATUSES
        if self.normalized_role == "reviewer":
            return {"published", "candidate", "draft", "rejected"}
        if self.normalized_role == "maintainer":
            return {"published", "draft", "archived"}
        return {"published"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20].upper()}"


def _require_manage(principal: LibraryPrincipal) -> None:
    if not principal.can_manage:
        raise LibraryForbidden("需要知识维护权限")


def _require_review(principal: LibraryPrincipal) -> None:
    if not principal.can_review:
        raise LibraryForbidden("需要知识审核权限")


def _scope_allowed(space: KnowledgeSpace | None, principal: LibraryPrincipal) -> bool:
    if space is None or principal.is_admin:
        return True
    scope = (space.access_scope or "public").strip().lower()
    if scope == "public":
        return True
    allowed = {item.strip() for item in scope.split(",") if item.strip()}
    return principal.normalized_role in allowed or f"user:{principal.user_id}" in allowed


def _item_summary(item: KnowledgeItem, space_name: str | None = None) -> KnowledgeListItem:
    return KnowledgeListItem(
        id=item.id,
        space_id=item.space_id,
        space_name=space_name if space_name is not None else item.space.name if item.space else None,
        title=item.title,
        type=item.type,
        summary=item.summary,
        status=item.status,
        verification_status=item.verification_status,
        tags=item.tags or [],
        source_task_id=item.source_task_id,
        reference_count=item.reference_count,
        helpful_count=item.helpful_count,
        updated_at=item.updated_at,
        published_at=item.published_at,
    )


class KnowledgeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _audit(
        self,
        item: KnowledgeItem,
        action: str,
        principal: LibraryPrincipal,
        detail: dict | None = None,
    ) -> None:
        self.session.add(
            KnowledgeAudit(
                knowledge_id=item.id,
                action=action,
                actor_id=principal.user_id,
                actor_role=principal.normalized_role,
                detail=detail or {},
            )
        )

    async def _space(self, space_id: str | None, principal: LibraryPrincipal) -> KnowledgeSpace | None:
        if not space_id:
            return None
        space = await self.session.get(KnowledgeSpace, space_id)
        if not space or space.status != "active":
            raise LibraryNotFound("知识空间不存在或已停用")
        if not _scope_allowed(space, principal):
            raise LibraryForbidden("无权访问该知识空间")
        return space

    async def _visible_space_ids(self, principal: LibraryPrincipal) -> list[str]:
        spaces = (
            await self.session.scalars(
                select(KnowledgeSpace).where(KnowledgeSpace.status == "active")
            )
        ).all()
        return [space.id for space in spaces if _scope_allowed(space, principal)]

    async def _item_scope_condition(self, principal: LibraryPrincipal):
        if principal.is_admin:
            return None
        visible_space_ids = await self._visible_space_ids(principal)
        return or_(
            KnowledgeItem.space_id.is_(None),
            KnowledgeItem.space_id.in_(visible_space_ids),
        )

    async def _item(
        self,
        knowledge_id: str,
        principal: LibraryPrincipal,
        *,
        load_detail: bool = False,
    ) -> KnowledgeItem:
        statement = select(KnowledgeItem).where(KnowledgeItem.id == knowledge_id)
        if load_detail:
            statement = statement.options(
                selectinload(KnowledgeItem.space),
                selectinload(KnowledgeItem.sources),
                selectinload(KnowledgeItem.evidence),
            )
        item = await self.session.scalar(statement)
        if not item or item.status not in principal.visible_statuses:
            raise LibraryNotFound("知识不存在或不可访问")
        if load_detail and not _scope_allowed(item.space, principal):
            raise LibraryForbidden("无权访问该知识空间")
        if not load_detail and item.space_id:
            space = await self.session.get(KnowledgeSpace, item.space_id)
            if not _scope_allowed(space, principal):
                raise LibraryForbidden("无权访问该知识空间")
        return item

    async def stats(self, principal: LibraryPrincipal) -> LibraryStats:
        scope_condition = await self._item_scope_condition(principal)
        published_conditions = [KnowledgeItem.status == "published"]
        if scope_condition is not None:
            published_conditions.append(scope_condition)
        published_count = await self.session.scalar(
            select(func.count(KnowledgeItem.id)).where(*published_conditions)
        )
        if principal.is_admin:
            space_count = await self.session.scalar(
                select(func.count(KnowledgeSpace.id)).where(KnowledgeSpace.status == "active")
            )
        else:
            space_count = len(await self._visible_space_ids(principal))
        since = datetime.now(UTC) - timedelta(days=7)
        reference_conditions = [
            KnowledgeUsage.action == "reference",
            KnowledgeUsage.created_at >= since,
        ]
        if scope_condition is not None:
            reference_conditions.append(scope_condition)
        references = await self.session.scalar(
            select(func.count(KnowledgeUsage.id))
            .join(KnowledgeItem, KnowledgeUsage.knowledge_id == KnowledgeItem.id)
            .where(*reference_conditions)
        )
        experience_conditions = [
            KnowledgeItem.type == "experience",
            KnowledgeItem.status == "published",
        ]
        if scope_condition is not None:
            experience_conditions.append(scope_condition)
        published_experiences = await self.session.scalar(
            select(func.count(KnowledgeItem.id)).where(*experience_conditions)
        )
        candidates = 0
        if principal.can_review:
            candidate_conditions = [
                KnowledgeItem.type == "experience",
                KnowledgeItem.status == "candidate",
            ]
            if scope_condition is not None:
                candidate_conditions.append(scope_condition)
            candidates = (
                await self.session.scalar(
                    select(func.count(KnowledgeItem.id)).where(*candidate_conditions)
                )
                or 0
            )
        return LibraryStats(
            knowledge_pages=published_count or 0,
            knowledge_spaces=space_count or 0,
            weekly_references=references or 0,
            published_experiences=published_experiences or 0,
            candidate_experiences=candidates,
        )

    async def list_spaces(self, principal: LibraryPrincipal) -> list[KnowledgeSpaceRead]:
        count_statuses = principal.visible_statuses
        counts = (
            await self.session.execute(
                select(KnowledgeItem.space_id, func.count(KnowledgeItem.id))
                .where(KnowledgeItem.status.in_(count_statuses))
                .group_by(KnowledgeItem.space_id)
            )
        ).all()
        count_map = {space_id: count for space_id, count in counts}
        spaces = (
            await self.session.scalars(
                select(KnowledgeSpace)
                .where(KnowledgeSpace.status == "active")
                .order_by(KnowledgeSpace.sort_order, KnowledgeSpace.name)
            )
        ).all()
        return [
            KnowledgeSpaceRead.model_validate(space).model_copy(
                update={"knowledge_count": count_map.get(space.id, 0)}
            )
            for space in spaces
            if _scope_allowed(space, principal)
        ]

    async def create_space(
        self, payload: KnowledgeSpaceCreate, principal: LibraryPrincipal
    ) -> KnowledgeSpaceRead:
        _require_manage(principal)
        if await self.session.scalar(select(KnowledgeSpace.id).where(KnowledgeSpace.name == payload.name)):
            raise LibraryConflict("知识空间名称已存在")
        if payload.parent_id:
            await self._space(payload.parent_id, principal)
        space = KnowledgeSpace(
            id=_new_id("SPACE"),
            created_by=principal.user_id,
            **payload.model_dump(),
        )
        self.session.add(space)
        await self.session.commit()
        await self.session.refresh(space)
        return KnowledgeSpaceRead.model_validate(space)

    async def update_space(
        self,
        space_id: str,
        payload: KnowledgeSpacePatch,
        principal: LibraryPrincipal,
    ) -> KnowledgeSpaceRead:
        _require_manage(principal)
        space = await self.session.get(KnowledgeSpace, space_id)
        if not space:
            raise LibraryNotFound("知识空间不存在")
        values = payload.model_dump(exclude_unset=True)
        if values.get("parent_id") == space_id:
            raise LibraryValidationError("知识空间不能以自身作为父目录")
        if values.get("parent_id"):
            await self._space(values["parent_id"], principal)
        for key, value in values.items():
            setattr(space, key, value)
        await self.session.commit()
        await self.session.refresh(space)
        return KnowledgeSpaceRead.model_validate(space)

    async def list_knowledge(
        self,
        principal: LibraryPrincipal,
        *,
        space_id: str | None = None,
        type_: str | None = None,
        status: str | None = None,
        verification_status: str | None = None,
        keyword: str | None = None,
        sort: str = "updated_desc",
        page: int = 1,
        page_size: int = 20,
    ) -> KnowledgePage:
        if status and status not in principal.visible_statuses:
            raise LibraryForbidden("无权查看该知识状态")
        if space_id:
            await self._space(space_id, principal)
        conditions = [KnowledgeItem.status.in_(principal.visible_statuses)]
        scope_condition = await self._item_scope_condition(principal)
        if scope_condition is not None:
            conditions.append(scope_condition)
        if space_id:
            conditions.append(KnowledgeItem.space_id == space_id)
        if type_:
            if type_ not in KNOWLEDGE_TYPES:
                raise LibraryValidationError("未知知识类型")
            conditions.append(KnowledgeItem.type == type_)
        if status:
            conditions.append(KnowledgeItem.status == status)
        if verification_status:
            conditions.append(KnowledgeItem.verification_status == verification_status)
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    KnowledgeItem.title.ilike(pattern),
                    KnowledgeItem.summary.ilike(pattern),
                    KnowledgeItem.content_md.ilike(pattern),
                    KnowledgeItem.source_ref.ilike(pattern),
                    KnowledgeItem.source_task_id.ilike(pattern),
                    cast(KnowledgeItem.tags, String).ilike(pattern),
                )
            )
        base = (
            select(KnowledgeItem, KnowledgeSpace.name)
            .outerjoin(KnowledgeSpace, KnowledgeItem.space_id == KnowledgeSpace.id)
            .where(*conditions)
        )
        order = {
            "updated_asc": KnowledgeItem.updated_at.asc(),
            "references_desc": desc(KnowledgeItem.reference_count),
            "title_asc": KnowledgeItem.title.asc(),
        }.get(sort, desc(KnowledgeItem.updated_at))
        total = await self.session.scalar(select(func.count(KnowledgeItem.id)).where(*conditions))
        rows = (
            await self.session.execute(
                base.order_by(order, KnowledgeItem.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return KnowledgePage(
            items=[_item_summary(item, space_name) for item, space_name in rows],
            total=total or 0,
            page=page,
            page_size=page_size,
            pages=max(1, math.ceil((total or 0) / page_size)),
        )

    async def get_detail(self, knowledge_id: str, principal: LibraryPrincipal) -> KnowledgeDetail:
        item = await self._item(knowledge_id, principal, load_detail=True)
        employee_name = None
        task_title = None
        if item.source_employee_id:
            employee_name = await self.session.scalar(
                select(DigitalEmployee.name).where(DigitalEmployee.id == item.source_employee_id)
            )
        if item.source_task_id:
            task_title = await self.session.scalar(select(Task.title).where(Task.id == item.source_task_id))
        favorite = await self.session.scalar(
            select(KnowledgeFavorite.id).where(
                KnowledgeFavorite.knowledge_id == item.id,
                KnowledgeFavorite.user_id == principal.user_id,
            )
        )
        helpful = await self.session.scalar(
            select(KnowledgeFeedback.id).where(
                KnowledgeFeedback.knowledge_id == item.id,
                KnowledgeFeedback.actor_key == f"user:{principal.user_id}",
                KnowledgeFeedback.feedback_type == "helpful",
            )
        )
        summary = _item_summary(item)
        return KnowledgeDetail(
            **summary.model_dump(),
            content_md=item.content_md,
            source_type=item.source_type,
            source_ref=item.source_ref,
            source_employee_id=item.source_employee_id,
            source_employee_name=employee_name,
            source_task_title=task_title,
            source_run_id=item.source_run_id,
            experience_data=item.experience_data or {},
            review_note=item.review_note,
            created_by=item.created_by,
            updated_by=item.updated_by,
            published_by=item.published_by,
            created_at=item.created_at,
            sources=item.sources,
            evidence=item.evidence,
            is_favorite=bool(favorite),
            user_helpful=bool(helpful),
        )

    async def create_knowledge(
        self, payload: KnowledgeCreate, principal: LibraryPrincipal
    ) -> KnowledgeDetail:
        _require_manage(principal)
        await self._space(payload.space_id, principal)
        item = KnowledgeItem(
            id=_new_id("KNOW"),
            status="draft",
            created_by=principal.user_id,
            updated_by=principal.user_id,
            **payload.model_dump(),
        )
        self.session.add(item)
        await self.session.flush()
        await self._audit(item, "created", principal, {"status": "draft"})
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def update_knowledge(
        self,
        knowledge_id: str,
        payload: KnowledgePatch,
        principal: LibraryPrincipal,
    ) -> KnowledgeDetail:
        _require_manage(principal)
        item = await self._item(knowledge_id, principal)
        values = payload.model_dump(exclude_unset=True)
        if "space_id" in values:
            await self._space(values["space_id"], principal)
        for key, value in values.items():
            setattr(item, key, value)
        item.updated_by = principal.user_id
        await self._audit(item, "updated", principal, {"fields": sorted(values)})
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def publish(
        self,
        knowledge_id: str,
        payload: KnowledgePublishWrite,
        principal: LibraryPrincipal,
    ) -> KnowledgeDetail:
        _require_review(principal)
        item = await self._item(knowledge_id, principal)
        if item.status not in {"candidate", "draft"}:
            raise LibraryConflict("只有候选或草稿知识可以发布")
        await self._space(payload.space_id, principal)
        previous_status = item.status
        values = payload.model_dump(exclude_unset=True)
        for key, value in values.items():
            setattr(item, key, value)
        item.status = "published"
        item.published_by = principal.user_id
        item.published_at = utcnow()
        item.updated_by = principal.user_id
        item.review_note = None
        await self._audit(
            item,
            "published",
            principal,
            {"from_status": previous_status, "space_id": payload.space_id},
        )
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def reject(
        self,
        knowledge_id: str,
        payload: KnowledgeReviewWrite,
        principal: LibraryPrincipal,
    ) -> KnowledgeDetail:
        _require_review(principal)
        item = await self._item(knowledge_id, principal)
        if item.status != "candidate":
            raise LibraryConflict("只有候选经验可以驳回")
        item.status = "rejected"
        item.review_note = payload.reason
        item.updated_by = principal.user_id
        await self._audit(item, "rejected", principal, {"reason": payload.reason})
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def request_supplement(
        self,
        knowledge_id: str,
        payload: KnowledgeReviewWrite,
        principal: LibraryPrincipal,
    ) -> KnowledgeDetail:
        _require_review(principal)
        item = await self._item(knowledge_id, principal)
        if item.status != "candidate":
            raise LibraryConflict("只有候选经验可以要求补充")
        item.review_note = payload.reason
        item.updated_by = principal.user_id
        await self._audit(item, "supplement_requested", principal, {"reason": payload.reason})
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def favorite(self, knowledge_id: str, principal: LibraryPrincipal) -> KnowledgeFavoriteResult:
        await self._item(knowledge_id, principal)
        favorite = await self.session.scalar(
            select(KnowledgeFavorite).where(
                KnowledgeFavorite.knowledge_id == knowledge_id,
                KnowledgeFavorite.user_id == principal.user_id,
            )
        )
        if favorite:
            await self.session.delete(favorite)
            value = False
        else:
            self.session.add(KnowledgeFavorite(knowledge_id=knowledge_id, user_id=principal.user_id))
            value = True
        await self.session.commit()
        return KnowledgeFavoriteResult(favorite=value)

    async def feedback_for_user(
        self,
        knowledge_id: str,
        payload: KnowledgeFeedbackWrite,
        principal: LibraryPrincipal,
    ) -> KnowledgeFeedbackResult:
        item = await self._item(knowledge_id, principal)
        return await self._feedback(
            item,
            feedback_type=payload.feedback_type,
            actor_key=f"user:{principal.user_id}",
            user_id=principal.user_id,
            employee_id=None,
            comment=payload.comment,
            task_id=payload.task_id,
            run_id=None,
        )

    async def _feedback(
        self,
        item: KnowledgeItem,
        *,
        feedback_type: str,
        actor_key: str,
        user_id: str | None,
        employee_id: str | None,
        comment: str | None,
        task_id: str | None,
        run_id: str | None,
    ) -> KnowledgeFeedbackResult:
        if feedback_type not in FEEDBACK_TYPES:
            raise LibraryValidationError("未知反馈类型")
        existing = await self.session.scalar(
            select(KnowledgeFeedback.id).where(
                KnowledgeFeedback.knowledge_id == item.id,
                KnowledgeFeedback.actor_key == actor_key,
                KnowledgeFeedback.feedback_type == feedback_type,
            )
        )
        created = existing is None
        if created:
            self.session.add(
                KnowledgeFeedback(
                    knowledge_id=item.id,
                    actor_key=actor_key,
                    user_id=user_id,
                    employee_id=employee_id,
                    feedback_type=feedback_type,
                    comment=comment,
                    task_id=task_id,
                )
            )
            if feedback_type == "helpful":
                item.helpful_count += 1
        self.session.add(
            KnowledgeUsage(
                knowledge_id=item.id,
                employee_id=employee_id,
                task_id=task_id,
                run_id=run_id,
                tool_name="library_feedback",
                action="feedback",
                result={"feedback_type": feedback_type, "created": created},
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            current_count = await self.session.scalar(
                select(KnowledgeItem.helpful_count).where(KnowledgeItem.id == item.id)
            )
            return KnowledgeFeedbackResult(created=False, helpful_count=current_count or 0)
        return KnowledgeFeedbackResult(created=created, helpful_count=item.helpful_count)

    async def related_tasks(self, knowledge_id: str, principal: LibraryPrincipal) -> list[RelatedTaskRead]:
        item = await self._item(knowledge_id, principal)
        rows: dict[str, RelatedTaskRead] = {}
        if item.source_task_id:
            task = await self.session.get(Task, item.source_task_id)
            if task:
                rows[task.id] = RelatedTaskRead(
                    id=task.id,
                    title=task.title,
                    status=task.status,
                    relation="来源任务",
                )
        used = (
            await self.session.execute(
                select(
                    Task.id,
                    Task.title,
                    Task.status,
                    func.max(KnowledgeUsage.created_at),
                )
                .join(KnowledgeUsage, KnowledgeUsage.task_id == Task.id)
                .where(KnowledgeUsage.knowledge_id == knowledge_id)
                .group_by(Task.id, Task.title, Task.status)
                .order_by(desc(func.max(KnowledgeUsage.created_at)))
                .limit(50)
            )
        ).all()
        for task_id, title, status, last_used_at in used:
            if task_id in rows:
                rows[task_id].last_used_at = last_used_at
                continue
            rows[task_id] = RelatedTaskRead(
                id=task_id,
                title=title,
                status=status,
                relation="引用任务",
                last_used_at=last_used_at,
            )
        return list(rows.values())

    async def usage_summary(self, days: int = 7) -> LibraryUsageSummary:
        since = datetime.now(UTC) - timedelta(days=days - 1)
        conditions = [KnowledgeUsage.action == "reference", KnowledgeUsage.created_at >= since]
        total = await self.session.scalar(select(func.count(KnowledgeUsage.id)).where(*conditions))
        active = await self.session.scalar(
            select(func.count(func.distinct(KnowledgeUsage.employee_id))).where(
                *conditions, KnowledgeUsage.employee_id.is_not(None)
            )
        )
        top_rows = (
            await self.session.execute(
                select(
                    KnowledgeItem.id,
                    KnowledgeItem.title,
                    func.count(KnowledgeUsage.id).label("reference_count"),
                )
                .join(KnowledgeUsage, KnowledgeUsage.knowledge_id == KnowledgeItem.id)
                .where(*conditions)
                .group_by(KnowledgeItem.id, KnowledgeItem.title)
                .order_by(desc("reference_count"))
                .limit(3)
            )
        ).all()
        popular_space = await self.session.scalar(
            select(KnowledgeSpace.name)
            .join(KnowledgeItem, KnowledgeItem.space_id == KnowledgeSpace.id)
            .join(KnowledgeUsage, KnowledgeUsage.knowledge_id == KnowledgeItem.id)
            .where(*conditions)
            .group_by(KnowledgeSpace.id, KnowledgeSpace.name)
            .order_by(desc(func.count(KnowledgeUsage.id)))
            .limit(1)
        )
        trend_rows = (
            await self.session.execute(
                select(func.date(KnowledgeUsage.created_at), func.count(KnowledgeUsage.id))
                .where(*conditions)
                .group_by(func.date(KnowledgeUsage.created_at))
            )
        ).all()
        trend_map = {str(day): count for day, count in trend_rows}
        start = datetime.now(UTC).date() - timedelta(days=days - 1)
        trend = [
            UsageTrendPoint(
                date=(start + timedelta(days=offset)).isoformat(),
                reference_count=trend_map.get((start + timedelta(days=offset)).isoformat(), 0),
            )
            for offset in range(days)
        ]
        return LibraryUsageSummary(
            days=days,
            total_references=total or 0,
            active_employees=active or 0,
            top_knowledge=[
                UsageTopKnowledge(knowledge_id=row[0], title=row[1], reference_count=row[2])
                for row in top_rows
            ],
            popular_space=popular_space,
            trend=trend,
        )

    async def recent_usage(self, limit: int = 20) -> list[LibraryUsageRecent]:
        rows = (
            await self.session.execute(
                select(
                    KnowledgeUsage,
                    DigitalEmployee.name,
                    KnowledgeItem.title,
                )
                .outerjoin(DigitalEmployee, KnowledgeUsage.employee_id == DigitalEmployee.id)
                .outerjoin(KnowledgeItem, KnowledgeUsage.knowledge_id == KnowledgeItem.id)
                .order_by(desc(KnowledgeUsage.created_at))
                .limit(limit)
            )
        ).all()
        return [
            LibraryUsageRecent(
                id=usage.id,
                employee_id=usage.employee_id,
                employee_name=employee_name,
                task_id=usage.task_id,
                knowledge_id=usage.knowledge_id,
                knowledge_title=knowledge_title,
                action=usage.action,
                created_at=usage.created_at,
            )
            for usage, employee_name, knowledge_title in rows
        ]

    async def _validate_mcp_context(
        self,
        employee_id: str | None,
        task_id: str | None,
        run_id: str | None,
        *,
        employee_required: bool = False,
    ) -> tuple[DigitalEmployee | None, Task | None, Run | None]:
        if employee_required and not employee_id:
            raise LibraryValidationError("MCP 请求必须提供 employee_id")
        employee = await self.session.get(DigitalEmployee, employee_id) if employee_id else None
        task = await self.session.get(Task, task_id) if task_id else None
        run = await self.session.get(Run, run_id) if run_id else None
        if employee_id and not employee:
            raise LibraryValidationError("数字员工不存在")
        if task_id and not task:
            raise LibraryValidationError("来源任务不存在")
        if run_id and not run:
            raise LibraryValidationError("来源 Run 不存在")
        if run and task and run.task_id != task.id:
            raise LibraryValidationError("Run 与 Task 不匹配")
        if run and employee and run.employee_id != employee.id:
            raise LibraryValidationError("Run 与 Employee 不匹配")
        if task and employee and task.employee_id != employee.id:
            raise LibraryValidationError("Task 与 Employee 不匹配")
        return employee, task, run

    async def mcp_search(self, payload: LibrarySearchInput) -> list[LibrarySearchResult]:
        started = time.perf_counter()
        await self._validate_mcp_context(
            payload.employee_id, payload.task_id, payload.run_id, employee_required=True
        )
        conditions = [KnowledgeItem.status == "published"]
        principal = LibraryPrincipal(user_id=f"employee:{payload.employee_id}", role="viewer")
        if payload.space_id:
            await self._space(
                payload.space_id,
                principal,
            )
            conditions.append(KnowledgeItem.space_id == payload.space_id)
        else:
            conditions.append(KnowledgeItem.space_id.in_(await self._visible_space_ids(principal)))
        if payload.types:
            conditions.append(KnowledgeItem.type.in_(payload.types))
        rows = (
            await self.session.scalars(
                select(KnowledgeItem).where(*conditions).order_by(desc(KnowledgeItem.updated_at))
            )
        ).all()
        terms = _search_terms(payload.query)
        scored: list[tuple[float, KnowledgeItem]] = []
        for item in rows:
            score = _knowledge_score(item, payload.query, terms)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda value: (value[0], value[1].updated_at), reverse=True)
        results = [
            LibrarySearchResult(
                knowledge_id=item.id,
                title=item.title,
                type=item.type,
                summary=item.summary,
                score=round(score, 3),
                tags=item.tags or [],
                updated_at=item.updated_at,
            )
            for score, item in scored[: payload.limit]
        ]
        self.session.add(
            KnowledgeUsage(
                employee_id=payload.employee_id,
                task_id=payload.task_id,
                run_id=payload.run_id,
                tool_name="library_search",
                action="search",
                query=payload.query,
                result={"knowledge_ids": [result.knowledge_id for result in results]},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        await self.session.commit()
        return results

    async def mcp_get(
        self,
        knowledge_id: str,
        *,
        employee_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> KnowledgeDetail:
        started = time.perf_counter()
        await self._validate_mcp_context(employee_id, task_id, run_id, employee_required=True)
        principal = LibraryPrincipal(user_id=f"employee:{employee_id or 'anonymous'}", role="viewer")
        item = await self._item(knowledge_id, principal, load_detail=True)
        await self.session.execute(
            update(KnowledgeItem)
            .where(KnowledgeItem.id == item.id)
            .values(reference_count=KnowledgeItem.reference_count + 1)
        )
        self.session.add(
            KnowledgeUsage(
                knowledge_id=item.id,
                employee_id=employee_id,
                task_id=task_id,
                run_id=run_id,
                tool_name="library_get",
                action="reference",
                result={"entered_context": True},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def mcp_related(
        self,
        knowledge_id: str,
        *,
        limit: int = 10,
        employee_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> list[LibrarySearchResult]:
        started = time.perf_counter()
        await self._validate_mcp_context(employee_id, task_id, run_id, employee_required=True)
        principal = LibraryPrincipal(user_id=f"employee:{employee_id or 'anonymous'}", role="viewer")
        item = await self._item(knowledge_id, principal)
        visible_space_ids = await self._visible_space_ids(principal)
        relation_rows = (
            await self.session.execute(
                select(KnowledgeRelation.source_knowledge_id, KnowledgeRelation.target_knowledge_id).where(
                    or_(
                        KnowledgeRelation.source_knowledge_id == item.id,
                        KnowledgeRelation.target_knowledge_id == item.id,
                    )
                )
            )
        ).all()
        explicit_ids = {target if source == item.id else source for source, target in relation_rows}
        candidates = (
            await self.session.scalars(
                select(KnowledgeItem)
                .join(KnowledgeSpace, KnowledgeItem.space_id == KnowledgeSpace.id)
                .where(
                    KnowledgeItem.status == "published",
                    KnowledgeItem.id != item.id,
                    KnowledgeItem.space_id.in_(visible_space_ids),
                )
            )
        ).all()
        tags = set(item.tags or [])
        scored = []
        for candidate in candidates:
            score = 20.0 if candidate.id in explicit_ids else 0.0
            score += len(tags.intersection(candidate.tags or [])) * 4.0
            if item.type == candidate.type:
                score += 1.0
            if score > 0:
                scored.append((score, candidate))
        scored.sort(key=lambda value: (value[0], value[1].updated_at), reverse=True)
        results = [
            LibrarySearchResult(
                knowledge_id=candidate.id,
                title=candidate.title,
                type=candidate.type,
                summary=candidate.summary,
                score=score,
                tags=candidate.tags or [],
                updated_at=candidate.updated_at,
            )
            for score, candidate in scored[:limit]
        ]
        self.session.add(
            KnowledgeUsage(
                knowledge_id=item.id,
                employee_id=employee_id,
                task_id=task_id,
                run_id=run_id,
                tool_name="library_related",
                action="search",
                result={"knowledge_ids": [result.knowledge_id for result in results]},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        await self.session.commit()
        return results

    async def mcp_submit_experience(self, payload: LibrarySubmitExperienceInput) -> KnowledgeDetail:
        employee, task, run = await self._validate_mcp_context(
            payload.source_employee_id,
            payload.source_task_id,
            payload.source_run_id,
            employee_required=True,
        )
        experience_data = dict(payload.experience_data)
        experience_data.setdefault("task_executed_at", run.started_at.isoformat() if run else None)
        experience_data.setdefault("run_status", run.status if run else None)
        item = KnowledgeItem(
            id=_new_id("KNOW"),
            space_id=None,
            title=payload.title,
            type="experience",
            summary=payload.summary,
            content_md=payload.content_md,
            status="candidate",
            verification_status=(
                "verified" if run and run.status in {"PASSED", "COMPLETED"} else "unverified"
            ),
            tags=payload.tags,
            source_type="agent_experience",
            source_ref=payload.source_task_id,
            source_employee_id=payload.source_employee_id,
            source_task_id=payload.source_task_id,
            source_run_id=payload.source_run_id,
            experience_data=experience_data,
            created_by=f"employee:{payload.source_employee_id}",
            updated_by=f"employee:{payload.source_employee_id}",
        )
        self.session.add(item)
        await self.session.flush()
        for evidence in payload.evidence:
            self.session.add(
                ExperienceEvidence(
                    knowledge_id=item.id,
                    task_id=evidence.task_id or payload.source_task_id,
                    run_id=evidence.run_id or payload.source_run_id,
                    evidence_type=evidence.evidence_type,
                    content=evidence.content,
                    uri=evidence.uri,
                    result=evidence.result,
                )
            )
        principal = LibraryPrincipal(user_id=f"employee:{payload.source_employee_id}", role="viewer")
        await self._audit(
            item,
            "candidate_submitted",
            principal,
            {
                "employee_id": employee.id if employee else None,
                "task_id": task.id if task else None,
                "run_id": run.id if run else None,
                "evidence_count": len(payload.evidence),
            },
        )
        self.session.add(
            KnowledgeUsage(
                knowledge_id=item.id,
                employee_id=payload.source_employee_id,
                task_id=payload.source_task_id,
                run_id=payload.source_run_id,
                tool_name="library_submit_experience",
                action="feedback",
                result={"status": "candidate"},
            )
        )
        await self.session.commit()
        return await self.get_detail(item.id, LibraryPrincipal(user_id="mcp-review", role="reviewer"))

    async def mcp_feedback(self, payload: LibraryFeedbackInput) -> KnowledgeFeedbackResult:
        await self._validate_mcp_context(payload.employee_id, payload.task_id, payload.run_id)
        principal = LibraryPrincipal(user_id=f"employee:{payload.employee_id}", role="viewer")
        item = await self._item(payload.knowledge_id, principal)
        return await self._feedback(
            item,
            feedback_type=payload.feedback_type,
            actor_key=f"employee:{payload.employee_id}",
            user_id=None,
            employee_id=payload.employee_id,
            comment=payload.comment,
            task_id=payload.task_id,
            run_id=payload.run_id,
        )


def _search_terms(query: str) -> list[str]:
    normalized = query.casefold().strip()
    tokens = re.findall(r"[a-z0-9_./:-]+|[\u3400-\u9fff]+", normalized)
    terms = [normalized, *tokens]
    return list(dict.fromkeys(term for term in terms if term))


def _knowledge_score(item: KnowledgeItem, query: str, terms: list[str]) -> float:
    title = item.title.casefold()
    summary = item.summary.casefold()
    content = item.content_md.casefold()
    tags = " ".join(item.tags or []).casefold()
    source = " ".join(filter(None, (item.source_ref, item.source_task_id))).casefold()
    normalized = query.casefold().strip()
    score = 0.0
    if normalized in title:
        score += 18.0
    if normalized in tags:
        score += 12.0
    for term in terms:
        if term in title:
            score += 7.0
        if term in tags:
            score += 5.0
        if term in summary:
            score += 3.0
        if term in content:
            score += 1.0
        if term in source:
            score += 4.0
    return score

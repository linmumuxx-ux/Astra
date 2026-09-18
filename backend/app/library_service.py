from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import String, cast, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
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
    KnowledgeUsageRead,
    LibraryFeedbackInput,
    LibraryResource,
    LibraryResourceFeedbackResult,
    LibrarySearchInput,
    LibrarySearchResult,
    LibraryServiceStatus,
    LibraryStats,
    LibrarySubmitExperienceInput,
    LibraryUsageRecent,
    LibraryUsageSummary,
    RelatedTaskRead,
    UsageTopKnowledge,
    UsageTrendPoint,
)
from app.library_sync import mark_for_sync
from app.llm_wiki import LlmWikiClient, LlmWikiError, wiki_resource_path
from app.models import (
    DigitalEmployee,
    ExperienceEvidence,
    KnowledgeAudit,
    KnowledgeFavorite,
    KnowledgeFeedback,
    KnowledgeItem,
    KnowledgeSpace,
    KnowledgeSync,
    KnowledgeUsage,
    Run,
    Task,
    utcnow,
)
from app.runtime.runtime_context import RuntimeContext
from app.runtime.runtime_context import resolve_runtime_context as _resolve_runtime_context
from app.usage import day_bounds

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


def _tree_scope_allowed(
    space: KnowledgeSpace,
    spaces_by_id: dict[str, KnowledgeSpace],
    principal: LibraryPrincipal,
) -> bool:
    """A directory can never be more visible than its ancestor knowledge space."""

    current: KnowledgeSpace | None = space
    visited: set[str] = set()
    while current is not None:
        if current.id in visited or current.status != "active" or not _scope_allowed(current, principal):
            return False
        visited.add(current.id)
        if current.parent_id is None:
            return True
        current = spaces_by_id.get(current.parent_id)
    return False


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
        source_type=item.source_type,
        source_task_id=item.source_task_id,
        reference_count=item.reference_count,
        helpful_count=item.helpful_count,
        updated_at=item.updated_at,
        published_at=item.published_at,
    )


async def _space_descendant_ids(session: AsyncSession, space_id: str) -> list[str]:
    ids = [space_id]
    queue = [space_id]
    visited = {space_id}
    while queue:
        current = queue.pop()
        rows = (
            await session.scalars(select(KnowledgeSpace.id).where(KnowledgeSpace.parent_id == current))
        ).all()
        for row in rows:
            if row in visited:
                continue
            visited.add(row)
            ids.append(row)
            queue.append(row)
    return ids


async def _space_root_id(session: AsyncSession, space_id: str) -> str:
    current = space_id
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        space = await session.get(KnowledgeSpace, current)
        if not space or not space.parent_id:
            return current
        current = space.parent_id
    return current


def _build_space_tree(
    nodes: list[KnowledgeSpace],
    count_map: dict[str, int],
) -> list[KnowledgeSpaceRead]:
    by_parent: dict[str | None, list[KnowledgeSpace]] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)
    memo: dict[str, int] = {}

    def subtree_count(node: KnowledgeSpace) -> int:
        if node.id in memo:
            return memo[node.id]
        total = count_map.get(node.id, 0) + sum(subtree_count(child) for child in by_parent.get(node.id, []))
        memo[node.id] = total
        return total

    def build(node: KnowledgeSpace) -> KnowledgeSpaceRead:
        return KnowledgeSpaceRead.model_validate(node).model_copy(
            update={
                "knowledge_count": count_map.get(node.id, 0),
                "subtree_knowledge_count": subtree_count(node),
                "children": [build(child) for child in by_parent.get(node.id, [])],
            }
        )

    return [build(node) for node in nodes if node.parent_id is None]


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
        if action in {"published", "updated", "moved", "archived"}:
            await self._queue_sync(item)
        self.session.add(
            KnowledgeAudit(
                knowledge_id=item.id,
                action=action,
                actor_id=principal.user_id,
                actor_role=principal.normalized_role,
                detail=detail or {},
            )
        )

    async def _queue_sync(self, item: KnowledgeItem) -> None:
        if item.status == "published" or await self.session.get(KnowledgeSync, item.id):
            await mark_for_sync(self.session, item.id)

    async def _space(self, space_id: str | None, principal: LibraryPrincipal) -> KnowledgeSpace | None:
        if not space_id:
            return None
        space = await self.session.get(KnowledgeSpace, space_id)
        if not space or space.status != "active":
            raise LibraryNotFound("知识空间不存在或已停用")
        if not await self._space_scope_allowed(space, principal):
            raise LibraryForbidden("无权访问该知识空间")
        return space

    async def _space_scope_allowed(self, space: KnowledgeSpace, principal: LibraryPrincipal) -> bool:
        spaces_by_id = {space.id: space}
        current = space
        visited: set[str] = set()
        while current.parent_id is not None:
            if current.id in visited:
                return False
            visited.add(current.id)
            parent = await self.session.get(KnowledgeSpace, current.parent_id)
            if parent is None:
                return False
            spaces_by_id[parent.id] = parent
            current = parent
        return _tree_scope_allowed(space, spaces_by_id, principal)

    async def _visible_space_ids(self, principal: LibraryPrincipal) -> list[str]:
        spaces = (await self.session.scalars(select(KnowledgeSpace))).all()
        spaces_by_id = {space.id: space for space in spaces}
        return [space.id for space in spaces if _tree_scope_allowed(space, spaces_by_id, principal)]

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
        if item.space_id:
            await self._space(item.space_id, principal)
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
            KnowledgeUsage.action == "read",
            KnowledgeUsage.created_at >= since,
        ]
        references = await self.session.scalar(
            select(func.count(KnowledgeUsage.id)).where(*reference_conditions)
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
                await self.session.scalar(select(func.count(KnowledgeItem.id)).where(*candidate_conditions))
                or 0
            )
        return LibraryStats(
            knowledge_pages=published_count or 0,
            knowledge_spaces=space_count or 0,
            weekly_references=references or 0,
            published_experiences=published_experiences or 0,
            candidate_experiences=candidates,
        )

    async def dashboard_summary(self, principal: LibraryPrincipal) -> dict[str, object]:
        """Return permission-aware counters for the lightweight dashboard card."""

        scope_condition = await self._item_scope_condition(principal)
        start, end = day_bounds()
        today_conditions = [
            KnowledgeItem.status.in_(principal.visible_statuses),
            KnowledgeItem.created_at >= start,
            KnowledgeItem.created_at < end,
        ]
        if scope_condition is not None:
            today_conditions.append(scope_condition)
        today_added = await self.session.scalar(select(func.count(KnowledgeItem.id)).where(*today_conditions))

        total_conditions = [KnowledgeItem.status.in_(principal.visible_statuses)]
        if scope_condition is not None:
            total_conditions.append(scope_condition)
        total = await self.session.scalar(select(func.count(KnowledgeItem.id)).where(*total_conditions))
        recent_items = (
            await self.session.scalars(
                select(KnowledgeItem)
                .where(*total_conditions)
                .order_by(KnowledgeItem.updated_at.desc())
                .limit(3)
            )
        ).all()

        candidates = 0
        if principal.can_review:
            candidate_conditions = [
                KnowledgeItem.type == "experience",
                KnowledgeItem.status == "candidate",
            ]
            if scope_condition is not None:
                candidate_conditions.append(scope_condition)
            candidates = (
                await self.session.scalar(select(func.count(KnowledgeItem.id)).where(*candidate_conditions))
                or 0
            )
        return {
            "today_added": today_added or 0,
            "candidate_experiences": candidates,
            "total": total or 0,
            "recent": [{"id": item.id, "title": item.title} for item in recent_items],
        }

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
                select(KnowledgeSpace).order_by(KnowledgeSpace.sort_order, KnowledgeSpace.name)
            )
        ).all()
        spaces_by_id = {space.id: space for space in spaces}
        visible = [space for space in spaces if _tree_scope_allowed(space, spaces_by_id, principal)]
        return _build_space_tree(visible, count_map)

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
        if "parent_id" in values and values["parent_id"] != space.parent_id:
            await self._validate_space_move(space, values["parent_id"], principal)
        for key, value in values.items():
            setattr(space, key, value)
        if {"access_scope", "status", "parent_id"}.intersection(values):
            descendant_ids = {space.id, *(await _space_descendant_ids(self.session, space.id))}
            items = (await self.session.scalars(select(KnowledgeItem).where(
                KnowledgeItem.space_id.in_(descendant_ids)))).all()
            for item in items:
                await self._queue_sync(item)
        await self.session.commit()
        await self.session.refresh(space)
        return KnowledgeSpaceRead.model_validate(space)

    async def _validate_space_move(self, space: KnowledgeSpace, target_parent_id, principal) -> None:
        if target_parent_id == space.id:
            raise LibraryValidationError("目录不能移动到自身")
        if space.parent_id is None:
            if target_parent_id is not None:
                raise LibraryValidationError("知识空间不能移动，仅目录可以移动")
            return
        if target_parent_id is None:
            raise LibraryValidationError("目录必须归属于某个知识空间")
        await self._space(target_parent_id, principal)
        if await _space_root_id(self.session, space.id) != await _space_root_id(
            self.session, target_parent_id
        ):
            raise LibraryValidationError("目录不能移出当前知识空间")
        if target_parent_id in await _space_descendant_ids(self.session, space.id):
            raise LibraryValidationError("不能移动到自身或自己的子目录之下")

    async def move_space(
        self,
        space_id: str,
        target_parent_id: str | None,
        principal: LibraryPrincipal,
    ) -> KnowledgeSpaceRead:
        _require_manage(principal)
        await self._space(space_id, principal)
        return await self.update_space(space_id, KnowledgeSpacePatch(parent_id=target_parent_id), principal)

    async def delete_space(self, space_id: str, principal: LibraryPrincipal) -> dict[str, object]:
        _require_manage(principal)
        space = await self._space(space_id, principal)
        child_count = await self.session.scalar(
            select(func.count(KnowledgeSpace.id)).where(KnowledgeSpace.parent_id == space_id)
        )
        if child_count:
            raise LibraryConflict("该目录下存在子目录，请先移动或删除子目录。")
        knowledge_count = await self.session.scalar(
            select(func.count(KnowledgeItem.id)).where(KnowledgeItem.space_id == space_id)
        )
        if knowledge_count:
            raise LibraryConflict("该目录下存在知识，请先将知识移动到其他目录。")
        await self.session.delete(space)
        await self.session.commit()
        return {"deleted": space_id}

    async def list_knowledge(
        self,
        principal: LibraryPrincipal,
        *,
        space_id: str | None = None,
        type_: str | None = None,
        status: str | None = None,
        verification_status: str | None = None,
        source: str | None = None,
        tag: str | None = None,
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
            conditions.append(KnowledgeItem.space_id.in_(await _space_descendant_ids(self.session, space_id)))
        if type_:
            if type_ not in KNOWLEDGE_TYPES:
                raise LibraryValidationError("未知知识类型")
            conditions.append(KnowledgeItem.type == type_)
        if status:
            conditions.append(KnowledgeItem.status == status)
        if verification_status:
            conditions.append(KnowledgeItem.verification_status == verification_status)
        if source == "manual":
            conditions.append(or_(KnowledgeItem.source_type == "manual", KnowledgeItem.source_type.is_(None)))
        elif source:
            conditions.append(KnowledgeItem.source_type == source)
        if tag and tag.strip():
            conditions.append(cast(KnowledgeItem.tags, String).ilike(f'%"{tag.strip()}"%'))
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

    async def move_knowledge(
        self, knowledge_id: str, space_id: str, principal: LibraryPrincipal
    ) -> KnowledgeDetail:
        _require_manage(principal)
        await self._space(space_id, principal)
        item = await self._item(knowledge_id, principal)
        previous = item.space_id
        item.space_id = space_id
        item.updated_by = principal.user_id
        await self._audit(item, "moved", principal, {"from_space_id": previous, "to_space_id": space_id})
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def batch_move(
        self, knowledge_ids: list[str], space_id: str, principal: LibraryPrincipal
    ) -> dict[str, int]:
        _require_manage(principal)
        await self._space(space_id, principal)
        moved = 0
        for knowledge_id in knowledge_ids:
            item = await self._item(knowledge_id, principal)
            previous = item.space_id
            item.space_id = space_id
            item.updated_by = principal.user_id
            await self._audit(item, "moved", principal, {"from_space_id": previous, "to_space_id": space_id})
            moved += 1
        await self.session.commit()
        return {"moved": moved}

    async def archive(self, knowledge_id: str, principal: LibraryPrincipal) -> KnowledgeDetail:
        _require_manage(principal)
        item = await self._item(knowledge_id, principal)
        if item.status == "archived":
            raise LibraryConflict("知识已是归档状态")
        item.status = "archived"
        item.updated_by = principal.user_id
        await self._audit(item, "archived", principal)
        await self.session.commit()
        return await self.get_detail(item.id, principal)

    async def batch_archive(self, knowledge_ids: list[str], principal: LibraryPrincipal) -> dict[str, int]:
        _require_manage(principal)
        archived = 0
        for knowledge_id in knowledge_ids:
            item = await self._item(knowledge_id, principal)
            if item.status == "archived":
                continue
            item.status = "archived"
            item.updated_by = principal.user_id
            await self._audit(item, "archived", principal)
            archived += 1
        await self.session.commit()
        return {"archived": archived}

    async def batch_publish(
        self,
        knowledge_ids: list[str],
        space_id: str,
        verification_status: str,
        principal: LibraryPrincipal,
    ) -> dict[str, int]:
        _require_review(principal)
        await self._space(space_id, principal)
        published = 0
        for knowledge_id in knowledge_ids:
            item = await self._item(knowledge_id, principal)
            if item.status not in {"candidate", "draft"}:
                raise LibraryConflict("只有候选或草稿知识可以发布")
            previous_status = item.status
            item.space_id = space_id
            item.status = "published"
            item.verification_status = verification_status
            item.published_by = principal.user_id
            item.published_at = utcnow()
            item.updated_by = principal.user_id
            await self._audit(item, "published", principal, {"from_status": previous_status})
            published += 1
        await self.session.commit()
        return {"published": published}

    async def delete_knowledge(self, knowledge_id: str, principal: LibraryPrincipal) -> dict[str, str]:
        _require_manage(principal)
        item = await self._item(knowledge_id, principal)
        await self._queue_sync(item)
        await self.session.execute(update(KnowledgeUsage).where(
            KnowledgeUsage.knowledge_id == knowledge_id).values(knowledge_id=None))
        await self.session.execute(update(KnowledgeFeedback).where(
            KnowledgeFeedback.knowledge_id == knowledge_id).values(knowledge_id=None))
        for model in (KnowledgeFavorite, KnowledgeAudit):
            rows = await self.session.scalars(select(model).where(model.knowledge_id == knowledge_id))
            for row in rows.all():
                await self.session.delete(row)
        await self.session.delete(item)
        await self.session.commit()
        return {"deleted": knowledge_id}

    async def knowledge_usages(
        self, knowledge_id: str, principal: LibraryPrincipal, limit: int = 20
    ) -> list[KnowledgeUsageRead]:
        await self._item(knowledge_id, principal)
        rows = (
            await self.session.execute(
                select(KnowledgeUsage, DigitalEmployee.name, Task.title)
                .outerjoin(DigitalEmployee, KnowledgeUsage.employee_id == DigitalEmployee.id)
                .outerjoin(Task, KnowledgeUsage.task_id == Task.id)
                .where(
                    KnowledgeUsage.knowledge_id == knowledge_id,
                    KnowledgeUsage.action == "read",
                )
                .order_by(desc(KnowledgeUsage.created_at))
                .limit(limit)
            )
        ).all()
        return [
            KnowledgeUsageRead(
                id=usage.id,
                employee_id=usage.employee_id,
                employee_name=employee_name,
                task_id=usage.task_id,
                task_title=task_title,
                action=usage.action,
                used_at=usage.created_at,
            )
            for usage, employee_name, task_title in rows
        ]

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
                    resource_id=f"astra:{item.id}",
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
                resource_id=f"astra:{item.id}",
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
        conditions = [KnowledgeUsage.action == "read", KnowledgeUsage.created_at >= since]
        total = await self.session.scalar(select(func.count(KnowledgeUsage.id)).where(*conditions))
        used_resources = await self.session.scalar(
            select(func.count(func.distinct(KnowledgeUsage.resource_id))).where(*conditions)
        )
        feedback_count = await self.session.scalar(
            select(func.count(KnowledgeFeedback.id)).where(KnowledgeFeedback.created_at >= since)
        )
        top_rows = (
            await self.session.execute(
                select(
                    KnowledgeUsage.resource_id,
                    func.count(KnowledgeUsage.id).label("reference_count"),
                )
                .where(*conditions, KnowledgeUsage.resource_id.is_not(None))
                .group_by(KnowledgeUsage.resource_id)
                .order_by(desc("reference_count"))
                .limit(3)
            )
        ).all()
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
        top_knowledge = []
        for resource_id, reference_count in top_rows:
            latest_hit = await self.session.scalar(
                select(KnowledgeUsage.result)
                .where(
                    KnowledgeUsage.resource_id == resource_id,
                    KnowledgeUsage.action == "search_hit",
                )
                .order_by(KnowledgeUsage.id.desc())
                .limit(1)
            )
            top_knowledge.append(
                UsageTopKnowledge(
                    resource_id=resource_id,
                    title=(latest_hit or {}).get("title") or resource_id,
                    reference_count=reference_count,
                )
            )
        return LibraryUsageSummary(
            days=days,
            total_references=total or 0,
            used_resources=used_resources or 0,
            feedback_count=feedback_count or 0,
            top_knowledge=top_knowledge,
            trend=trend,
        )

    async def recent_usage(self, limit: int = 20) -> list[LibraryUsageRecent]:
        rows = (
            await self.session.scalars(
                select(KnowledgeUsage).order_by(desc(KnowledgeUsage.created_at)).limit(limit)
            )
        ).all()
        return [
            LibraryUsageRecent(
                id=usage.id,
                resource_id=usage.resource_id,
                query=usage.query,
                action=usage.action,
                created_at=usage.created_at,
            )
            for usage in rows
        ]

    async def _validate_mcp_context(
        self,
        employee_id: str | None,
        task_id: str | None,
        run_id: str | None,
    ) -> tuple[DigitalEmployee | None, Task | None, Run | None]:
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
        results = await LlmWikiClient().search(payload.query, payload.limit)
        for result in results:
            self.session.add(
                KnowledgeUsage(
                    resource_id=result.resource_id,
                    tool_name="library_search",
                    action="search_hit",
                    query=payload.query,
                    result={"title": result.title, "score": result.score},
                )
            )
        await self.session.commit()
        return results

    async def mcp_get(self, resource_id: str) -> LibraryResource:
        resource = await LlmWikiClient().read(resource_id)
        self.session.add(
            KnowledgeUsage(
                resource_id=resource.resource_id,
                tool_name="library_get",
                action="read",
            )
        )
        await self.session.commit()
        return resource

    async def mcp_related(self, resource_id: str) -> dict:
        wiki_resource_path(resource_id)
        return {
            "status": "unsupported",
            "resource_id": resource_id,
            "results": [],
            "message": "当前 Graph API 不提供可靠的按页面查询邻居能力，相关知识暂不可用",
        }

    async def resolve_runtime_context(self, token: str | None) -> RuntimeContext:
        """Shared runtime MCP capability used by every runtime tool."""
        return await _resolve_runtime_context(self.session, token)

    async def mcp_submit_experience(
        self,
        payload: LibrarySubmitExperienceInput,
        *,
        runtime_context: str | None = None,
    ) -> KnowledgeDetail:
        source_session_id: str | None = None
        if runtime_context:
            context = await _resolve_runtime_context(self.session, runtime_context)
            # Runtime identity is never taken from Agent-supplied arguments.
            payload = payload.model_copy(
                update={
                    "source_employee_id": context.employee_id,
                    "source_task_id": context.task_id,
                    "source_run_id": None,
                }
            )
            source_session_id = context.session_id
        employee, task, run = await self._validate_mcp_context(
            payload.source_employee_id,
            payload.source_task_id,
            payload.source_run_id,
        )
        experience_data = dict(payload.experience_data)
        experience_data.setdefault(
            "task_executed_at",
            run.started_at.isoformat() if run and run.started_at else None,
        )
        experience_data.setdefault("run_status", run.status if run else None)
        item = KnowledgeItem(
            id=_new_id("KNOW"),
            space_id=None,
            title=payload.title,
            type="experience",
            summary=payload.summary,
            content_md=payload.content_md,
            status="candidate",
            verification_status=("verified" if run and run.status in {"COMPLETED"} else "unverified"),
            tags=payload.tags,
            source_type="agent_experience",
            source_ref=payload.source_task_id,
            source_employee_id=payload.source_employee_id,
            source_task_id=payload.source_task_id,
            source_run_id=payload.source_run_id,
            source_session_id=source_session_id,
            experience_data=experience_data,
            created_by=f"employee:{payload.source_employee_id}" if payload.source_employee_id else "mcp",
            updated_by=f"employee:{payload.source_employee_id}" if payload.source_employee_id else "mcp",
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
        principal = LibraryPrincipal(user_id=item.created_by, role="viewer")
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
                resource_id=f"astra:{item.id}",
                knowledge_id=item.id,
                employee_id=payload.source_employee_id,
                task_id=payload.source_task_id,
                run_id=payload.source_run_id,
                tool_name="library_submit_experience",
                action="experience_submitted",
                result={"status": "candidate"},
            )
        )
        await self.session.commit()
        return await self.get_detail(item.id, LibraryPrincipal(user_id="mcp-review", role="reviewer"))

    async def mcp_feedback(self, payload: LibraryFeedbackInput) -> LibraryResourceFeedbackResult:
        resource_id = wiki_resource_path(payload.resource_id)
        feedback = KnowledgeFeedback(
            resource_id=resource_id,
            actor_key="mcp",
            feedback_type=payload.feedback_type,
            comment=payload.comment,
        )
        self.session.add(feedback)
        self.session.add(
            KnowledgeUsage(
                resource_id=resource_id,
                tool_name="library_feedback",
                action="feedback",
                result={"feedback_type": payload.feedback_type},
            )
        )
        await self.session.commit()
        return LibraryResourceFeedbackResult(
            id=feedback.id,
            resource_id=resource_id,
            feedback_type=payload.feedback_type,
        )

    async def service_status(self) -> LibraryServiceStatus:
        settings = get_settings()
        counts = dict(
            (
                await self.session.execute(
                    select(KnowledgeSync.status, func.count()).group_by(KnowledgeSync.status)
                )
            ).all()
        )
        last_synced = await self.session.scalar(select(func.max(KnowledgeSync.synced_at)))
        healthy = False
        try:
            await LlmWikiClient(settings).verify_project()
            healthy = True
            message = "源文件扫描已接受不代表知识加工完成"
        except LlmWikiError as exc:
            message = str(exc)
        if counts.get("failed", 0):
            healthy = False
            error = await self.session.scalar(
                select(KnowledgeSync.error)
                .where(KnowledgeSync.status == "failed")
                .order_by(KnowledgeSync.requested_at.desc())
                .limit(1)
            )
            message = error or message
        return LibraryServiceStatus(
            enabled=settings.llm_wiki_enabled,
            healthy=healthy,
            message=message,
            last_synced_at=last_synced,
            pending_count=counts.get("pending", 0),
            failed_count=counts.get("failed", 0),
        )

    async def resync(self, principal: LibraryPrincipal) -> dict[str, int]:
        _require_manage(principal)
        # Re-export the current published set and retry all retained deletion records.
        ids = set(
            (
                await self.session.scalars(
                    select(KnowledgeItem.id).where(KnowledgeItem.status == "published")
                )
            ).all()
        )
        ids.update((await self.session.scalars(select(KnowledgeSync.knowledge_id))).all())
        for knowledge_id in ids:
            await mark_for_sync(self.session, knowledge_id)
        await self.session.commit()
        return {"pending_count": len(ids)}

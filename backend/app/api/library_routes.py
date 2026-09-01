from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.library_schemas import (
    KnowledgeCreate,
    KnowledgeDetail,
    KnowledgeFavoriteResult,
    KnowledgeFeedbackResult,
    KnowledgeFeedbackWrite,
    KnowledgePage,
    KnowledgePatch,
    KnowledgePublishWrite,
    KnowledgeReviewWrite,
    KnowledgeSpaceCreate,
    KnowledgeSpacePatch,
    KnowledgeSpaceRead,
    LibraryStats,
    LibraryUsageRecent,
    LibraryUsageSummary,
    RelatedTaskRead,
)
from app.library_service import (
    KnowledgeService,
    LibraryConflict,
    LibraryError,
    LibraryForbidden,
    LibraryNotFound,
    LibraryPrincipal,
    LibraryValidationError,
)

router = APIRouter(prefix="/api/library", tags=["digital-library"])


def library_principal(
    user_id: Annotated[str, Header(alias="X-Astra-User-Id")] = "admin",
    role: Annotated[str, Header(alias="X-Astra-Role")] = "admin",
) -> LibraryPrincipal:
    """Identity is supplied by the trusted upstream gateway; local mode remains admin-compatible."""

    return LibraryPrincipal(user_id=user_id.strip() or "anonymous", role=role.strip() or "viewer")


async def library_error_handler(_request: Request, exc: LibraryError) -> JSONResponse:
    code = status.HTTP_400_BAD_REQUEST
    if isinstance(exc, LibraryNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, LibraryForbidden):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, LibraryConflict):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, LibraryValidationError):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return JSONResponse(status_code=code, content={"detail": str(exc)})


@router.get("/permissions")
async def permissions(principal: LibraryPrincipal = Depends(library_principal)) -> dict:
    return {
        "user_id": principal.user_id,
        "role": principal.normalized_role,
        "can_manage": principal.can_manage,
        "can_review": principal.can_review,
    }


@router.get("/stats", response_model=LibraryStats)
async def stats(
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).stats(principal)


@router.get("/spaces", response_model=list[KnowledgeSpaceRead])
async def spaces(
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).list_spaces(principal)


@router.post("/spaces", response_model=KnowledgeSpaceRead, status_code=status.HTTP_201_CREATED)
async def create_space(
    payload: KnowledgeSpaceCreate,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).create_space(payload, principal)


@router.put("/spaces/{space_id}", response_model=KnowledgeSpaceRead)
async def update_space(
    space_id: str,
    payload: KnowledgeSpacePatch,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).update_space(space_id, payload, principal)


@router.get("/knowledge", response_model=KnowledgePage)
async def knowledge_list(
    space_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
    verification_status: str | None = None,
    keyword: str | None = None,
    sort: str = "updated_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).list_knowledge(
        principal,
        space_id=space_id,
        type_=type,
        status=status,
        verification_status=verification_status,
        keyword=keyword,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/knowledge/{knowledge_id}", response_model=KnowledgeDetail)
async def knowledge_detail(
    knowledge_id: str,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).get_detail(knowledge_id, principal)


@router.post("/knowledge", response_model=KnowledgeDetail, status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    payload: KnowledgeCreate,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).create_knowledge(payload, principal)


@router.put("/knowledge/{knowledge_id}", response_model=KnowledgeDetail)
async def update_knowledge(
    knowledge_id: str,
    payload: KnowledgePatch,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).update_knowledge(knowledge_id, payload, principal)


@router.post("/knowledge/{knowledge_id}/publish", response_model=KnowledgeDetail)
async def publish_knowledge(
    knowledge_id: str,
    payload: KnowledgePublishWrite,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).publish(knowledge_id, payload, principal)


@router.post("/knowledge/{knowledge_id}/reject", response_model=KnowledgeDetail)
async def reject_knowledge(
    knowledge_id: str,
    payload: KnowledgeReviewWrite,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).reject(knowledge_id, payload, principal)


@router.post("/knowledge/{knowledge_id}/request-supplement", response_model=KnowledgeDetail)
async def request_supplement(
    knowledge_id: str,
    payload: KnowledgeReviewWrite,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).request_supplement(knowledge_id, payload, principal)


@router.post("/knowledge/{knowledge_id}/helpful", response_model=KnowledgeFeedbackResult)
async def helpful(
    knowledge_id: str,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).feedback_for_user(
        knowledge_id,
        KnowledgeFeedbackWrite(feedback_type="helpful"),
        principal,
    )


@router.post("/knowledge/{knowledge_id}/feedback", response_model=KnowledgeFeedbackResult)
async def feedback(
    knowledge_id: str,
    payload: KnowledgeFeedbackWrite,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).feedback_for_user(knowledge_id, payload, principal)


@router.post("/knowledge/{knowledge_id}/favorite", response_model=KnowledgeFavoriteResult)
async def favorite(
    knowledge_id: str,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).favorite(knowledge_id, principal)


@router.get("/knowledge/{knowledge_id}/related-tasks", response_model=list[RelatedTaskRead])
async def related_tasks(
    knowledge_id: str,
    session: AsyncSession = Depends(get_session),
    principal: LibraryPrincipal = Depends(library_principal),
):
    return await KnowledgeService(session).related_tasks(knowledge_id, principal)


@router.get("/usage/summary", response_model=LibraryUsageSummary)
async def usage_summary(
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    session: AsyncSession = Depends(get_session),
):
    return await KnowledgeService(session).usage_summary(days)


@router.get("/usage/recent", response_model=list[LibraryUsageRecent])
async def usage_recent(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: AsyncSession = Depends(get_session),
):
    return await KnowledgeService(session).recent_usage(limit)

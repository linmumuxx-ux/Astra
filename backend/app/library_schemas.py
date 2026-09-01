from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KnowledgeType = Literal["document", "rule", "guide", "experience", "faq", "tool", "example"]
KnowledgeStatus = Literal["draft", "candidate", "published", "archived", "rejected"]
VerificationStatus = Literal["unverified", "verified", "failed"]
FeedbackType = Literal["helpful", "incorrect", "outdated", "missing", "mismatch"]


class LibraryORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KnowledgeSpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    parent_id: str | None = None
    sort_order: int = 0
    access_scope: str = Field(default="public", max_length=160)


class KnowledgeSpacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: str | None = None
    sort_order: int | None = None
    status: Literal["active", "inactive"] | None = None
    access_scope: str | None = Field(default=None, max_length=160)


class KnowledgeSpaceRead(LibraryORMModel):
    id: str
    name: str
    description: str
    parent_id: str | None
    sort_order: int
    status: str
    access_scope: str
    knowledge_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeSourceRead(LibraryORMModel):
    id: int
    source_type: str
    source_id: str | None
    source_name: str | None
    source_uri: str | None
    version: str | None
    created_at: datetime


class ExperienceEvidenceWrite(BaseModel):
    evidence_type: str = Field(min_length=1, max_length=64)
    content: str | None = None
    uri: str | None = None
    result: str | None = Field(default=None, max_length=64)
    task_id: str | None = None
    run_id: str | None = None


class ExperienceEvidenceRead(LibraryORMModel):
    id: int
    task_id: str | None
    run_id: str | None
    evidence_type: str
    content: str | None
    uri: str | None
    result: str | None
    created_at: datetime


class KnowledgeCreate(BaseModel):
    space_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    type: KnowledgeType = "document"
    summary: str = Field(default="", max_length=4000)
    content_md: str = Field(min_length=1)
    verification_status: VerificationStatus = "unverified"
    tags: list[str] = Field(default_factory=list, max_length=50)
    source_type: str | None = Field(default=None, max_length=64)
    source_ref: str | None = Field(default=None, max_length=240)
    source_task_id: str | None = None
    source_run_id: str | None = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class KnowledgePatch(BaseModel):
    space_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    type: KnowledgeType | None = None
    summary: str | None = Field(default=None, max_length=4000)
    content_md: str | None = Field(default=None, min_length=1)
    verification_status: VerificationStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    source_type: str | None = Field(default=None, max_length=64)
    source_ref: str | None = Field(default=None, max_length=240)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str] | None) -> list[str] | None:
        if tags is None:
            return None
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class KnowledgePublishWrite(BaseModel):
    space_id: str
    title: str | None = Field(default=None, min_length=1, max_length=240)
    summary: str | None = Field(default=None, max_length=4000)
    content_md: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = Field(default=None, max_length=50)
    verification_status: VerificationStatus | None = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str] | None) -> list[str] | None:
        if tags is None:
            return None
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class KnowledgeReviewWrite(BaseModel):
    reason: str = Field(min_length=2, max_length=4000)


class KnowledgeListItem(LibraryORMModel):
    id: str
    space_id: str | None
    space_name: str | None = None
    title: str
    type: KnowledgeType
    summary: str
    status: KnowledgeStatus
    verification_status: VerificationStatus
    tags: list[str]
    source_task_id: str | None
    reference_count: int
    helpful_count: int
    updated_at: datetime
    published_at: datetime | None


class KnowledgeDetail(KnowledgeListItem):
    content_md: str
    source_type: str | None
    source_ref: str | None
    source_employee_id: str | None
    source_employee_name: str | None = None
    source_task_title: str | None = None
    source_run_id: str | None
    experience_data: dict[str, Any]
    review_note: str | None
    created_by: str
    updated_by: str
    published_by: str | None
    created_at: datetime
    sources: list[KnowledgeSourceRead] = Field(default_factory=list)
    evidence: list[ExperienceEvidenceRead] = Field(default_factory=list)
    is_favorite: bool = False
    user_helpful: bool = False


class KnowledgePage(BaseModel):
    items: list[KnowledgeListItem]
    total: int
    page: int
    page_size: int
    pages: int


class LibraryStats(BaseModel):
    knowledge_pages: int
    knowledge_spaces: int
    weekly_references: int
    published_experiences: int
    candidate_experiences: int


class KnowledgeFeedbackWrite(BaseModel):
    feedback_type: FeedbackType
    comment: str | None = Field(default=None, max_length=4000)
    task_id: str | None = None


class KnowledgeFeedbackResult(BaseModel):
    created: bool
    helpful_count: int


class KnowledgeFavoriteResult(BaseModel):
    favorite: bool


class RelatedTaskRead(BaseModel):
    id: str
    title: str
    status: str
    relation: str
    last_used_at: datetime | None = None


class UsageTopKnowledge(BaseModel):
    knowledge_id: str
    title: str
    reference_count: int


class UsageTrendPoint(BaseModel):
    date: str
    reference_count: int


class LibraryUsageSummary(BaseModel):
    days: int
    total_references: int
    active_employees: int
    top_knowledge: list[UsageTopKnowledge]
    popular_space: str | None
    trend: list[UsageTrendPoint]


class LibraryUsageRecent(BaseModel):
    id: int
    employee_id: str | None
    employee_name: str | None
    task_id: str | None
    knowledge_id: str | None
    knowledge_title: str | None
    action: str
    created_at: datetime


class LibrarySearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    space_id: str | None = None
    types: list[KnowledgeType] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)
    employee_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None


class LibrarySearchResult(BaseModel):
    knowledge_id: str
    title: str
    type: KnowledgeType
    summary: str
    score: float
    tags: list[str]
    updated_at: datetime


class LibraryGetInput(BaseModel):
    knowledge_id: str
    employee_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None


class LibraryRelatedInput(LibraryGetInput):
    limit: int = Field(default=10, ge=1, le=50)


class LibrarySubmitExperienceInput(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    content_md: str = Field(min_length=1)
    source_employee_id: str
    source_task_id: str
    source_run_id: str
    evidence: list[ExperienceEvidenceWrite] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)
    experience_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class LibraryFeedbackInput(BaseModel):
    knowledge_id: str
    feedback_type: FeedbackType
    comment: str | None = Field(default=None, max_length=4000)
    employee_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None

    @model_validator(mode="after")
    def require_actor(self):
        if not self.employee_id:
            raise ValueError("数字员工反馈必须提供 employee_id")
        return self

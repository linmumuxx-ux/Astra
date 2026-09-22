"""Assistant-authored reviews and candidate submission, never Task lifecycle decisions."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select, update

from app.assistant.client import AssistantOpenCodeClient
from app.config.settings import get_settings
from app.database import SessionLocal
from app.executors.errors import OpenCodeSessionNotFound
from app.library_schemas import ExperienceEvidenceWrite, LibrarySubmitExperienceInput
from app.library_service import KnowledgeService
from app.models import RuntimeSession, Task, TaskReview, TaskSummary
from app.runtime.session_connection import connect, resolve_runtime_session_environment, session_tree

logger = logging.getLogger(__name__)
TERMINAL_TASKS = ("SUCCEEDED", "FAILED", "CANCELED")
TERMINAL_SESSIONS = ("SUCCEEDED", "FAILED", "INTERRUPTED")
REVIEW_TIMEOUT = timedelta(minutes=30)


class ReviewExperience(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    content_md: str = Field(min_length=1)
    evidence: list[ExperienceEvidenceWrite] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)


def review_id(task: Task, binding: RuntimeSession) -> str:
    facts = [task.id, binding.id, task.last_message_id, binding.last_message_id, task.status]
    return hashlib.sha256(json.dumps(facts).encode()).hexdigest()


async def session_messages(
    session,
    session_id: str,
    *,
    before: str | None = None,
    limit: int = 20,
    native_session_id: str | None = None,
) -> dict:
    """Read native messages without truncating human input or question answers.

    OpenCode pages backwards; callers must exhaust before cursors, then review
    chronologically. Descendants share the RuntimeSession's immutable binding.
    """
    if not 1 <= limit <= 50:
        raise ValueError("limit 必须在 1～50 之间")
    binding = await session.get(RuntimeSession, session_id)
    if binding is None:
        raise ValueError("执行会话不存在")
    task = await session.get(Task, binding.task_id)
    environment = await resolve_runtime_session_environment(session, binding)
    directory = Path(binding.workspace)
    async with connect(environment) as client:
        descendants = await session_tree(client, directory, binding.id)
        native_id = native_session_id or binding.id
        if native_id not in descendants:
            raise ValueError("子会话不属于该执行会话")
        page = await client.messages_page(directory, native_id, limit=limit, before=before)
    # Preserve native info.id, parts[].id and full tool input/output, including
    # question metadata.answers. No summary/compaction/last-turn filtering here.
    return {
        "session_id": binding.id,
        "native_session_id": native_id,
        "child_session_ids": sorted(descendants - {binding.id}),
        "task_id": binding.task_id,
        "review_id": review_id(task, binding),
        "session_status": binding.status,
        "task_status": task.status,
        "messages": page["messages"],
        "next_before": page["next_before"],
        "page_order": "newest_pages_first; exhaust next_before to reach early human corrections",
    }


async def submit_review(
    session,
    *,
    task_id: str,
    source_session_id: str,
    expected_review_id: str,
    task_summary: str,
    experiences: list[ReviewExperience],
) -> dict:
    task_summary = task_summary.strip()
    if not task_summary:
        raise ValueError("任务总结不能为空")
    task = await session.scalar(
        select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True)
    )
    binding = await session.get(RuntimeSession, source_session_id, populate_existing=True)
    if not task or not binding or binding.task_id != task_id or task.current_session_id != binding.id:
        raise ValueError("Task 与当前 Session 不匹配，旧 Session 不能覆盖新结果")
    if (
        task.status not in TERMINAL_TASKS
        or binding.status not in TERMINAL_SESSIONS
        or task.pending_message_id
    ):
        raise ValueError("任务及 Session 尚未结束")
    if expected_review_id != review_id(task, binding):
        raise ValueError("执行轮次已变化，请重新读取完整会话")
    job = await session.get(TaskReview, expected_review_id)
    if job and job.status == "completed":
        return job.result
    if job is None:
        job = TaskReview(
            id=expected_review_id,
            task_id=task.id,
            source_session_id=binding.id,
            source_status=task.status,
            turn_anchor_id=task.last_message_id,
            final_message_id=binding.last_message_id,
        )
        session.add(job)
    summary = await session.scalar(select(TaskSummary).where(TaskSummary.task_id == task.id))
    if summary is None:
        summary = TaskSummary(id=f"TS-{uuid4().hex[:12]}", task_id=task.id, generation=0)
        session.add(summary)
    summary.generation += 1
    summary.summary = task_summary
    summary.content_md = task_summary
    summary.source_status = task.status
    summary.primary_session_id = binding.id
    summary.referenced_session_ids = [binding.id]
    summary.generated_by = "nexus-task-experience-review"
    summary.stale = False
    summary.key_changes = {}
    summary.acceptance_results = []
    summary.source_ref_snapshot = {
        "task_id": task.id,
        "task_title": task.title,
        "turn_anchor_id": task.last_message_id,
        "final_message_id": binding.last_message_id,
        "review_id": job.id,
    }
    summary.generated_at = summary.updated_at = datetime.now(UTC)
    await session.flush()
    candidates = []
    library = KnowledgeService(session)
    for experience in experiences:
        if any(e.task_id not in (None, task.id) for e in experience.evidence):
            raise ValueError("经验证据不属于当前任务")
        payload = LibrarySubmitExperienceInput(**experience.model_dump())
        item = await library.mcp_submit_experience(
            payload, review_session=binding, review_key=job.id, commit=False
        )
        candidates.append(item.id)
    job.status = "completed"
    job.error = None
    job.result = {
        "task_id": task.id,
        "source_session_id": binding.id,
        "summary_id": summary.id,
        "candidate_ids": list(dict.fromkeys(candidates)),
    }
    await session.commit()
    return job.result


async def reconcile_task_reviews(limit: int = 100) -> list[str]:
    """Discover completed rounds and retry assistant dispatch with a durable lease.

    No natural-language response is parsed. Only submit_review completes a job.
    A crash before/after sending expires the lease and safely retries the same
    idempotent review. Errors never flow back to execution state.
    """
    if not get_settings().assistant_enabled:
        return []
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        ids = (
            await session.scalars(
                select(Task.id)
                .join(RuntimeSession, RuntimeSession.id == Task.current_session_id)
                .outerjoin(
                    TaskReview,
                    and_(
                        TaskReview.task_id == Task.id,
                        TaskReview.source_session_id == RuntimeSession.id,
                        TaskReview.source_status == Task.status,
                        TaskReview.turn_anchor_id.is_not_distinct_from(Task.last_message_id),
                        TaskReview.final_message_id.is_not_distinct_from(RuntimeSession.last_message_id),
                    ),
                )
                .where(
                    Task.status.in_(TERMINAL_TASKS),
                    RuntimeSession.status.in_(TERMINAL_SESSIONS),
                    Task.pending_message_id.is_(None),
                    or_(
                        TaskReview.id.is_(None),
                        and_(TaskReview.status != "completed", TaskReview.retry_at <= now),
                    ),
                )
                .order_by(Task.updated_at)
                .limit(limit)
            )
        ).all()
    dispatched = []
    client = AssistantOpenCodeClient()
    for task_id in ids:
        job_id = None
        claimed = False
        try:
            async with SessionLocal() as session:
                task = await session.scalar(select(Task).where(Task.id == task_id).with_for_update())
                if not task or task.status not in TERMINAL_TASKS or task.pending_message_id:
                    continue
                binding = await session.get(RuntimeSession, task.current_session_id)
                if not binding or binding.status not in TERMINAL_SESSIONS:
                    continue
                job_id = review_id(task, binding)
                job = await session.get(TaskReview, job_id)
                if job and (job.status == "completed" or job.retry_at > now):
                    continue
                if job is None:
                    job = TaskReview(
                        id=job_id,
                        task_id=task.id,
                        source_session_id=binding.id,
                        source_status=task.status,
                        turn_anchor_id=task.last_message_id,
                        final_message_id=binding.last_message_id,
                        attempts=0,
                        retry_at=now,
                    )
                    session.add(job)
                previous_session = job.assistant_session_id
                await session.flush()
                claim = await session.execute(
                    update(TaskReview)
                    .where(
                        TaskReview.id == job_id, TaskReview.status != "completed", TaskReview.retry_at <= now
                    )
                    .values(
                        status="running",
                        attempts=TaskReview.attempts + 1,
                        retry_at=now + REVIEW_TIMEOUT,
                        error=None,
                    )
                )
                if not claim.rowcount:
                    await session.rollback()
                    continue
                source_session_id = binding.id
                await session.commit()
                claimed = True
            if previous_session:
                try:
                    await client.abort(previous_session)
                except OpenCodeSessionNotFound:
                    pass  # The prior review session is already gone; a new attempt is required.
            assistant_id = await client.create_session(title=f"任务经验沉淀 {task_id}")
            async with SessionLocal() as session:
                job = await session.get(TaskReview, job_id)
                if job is None or job.status == "completed":
                    continue
                job.assistant_session_id = assistant_id
                await session.commit()
            await client.prompt_async(
                assistant_id,
                text=(
                    "使用 nexus-task-experience-review Skill 完成任务经验沉淀。"
                    f"输入 session_id={source_session_id}，review_id={job_id}。"
                    "查询任务事实，分页读完主会话和子会话，再结构化提交。"
                    "以当前架构事实为准：历史会话中的旧协议（如 ASTRA_RESULT_JSON）只作为当时事实，"
                    "不得写成当前规则或经验。"
                    "此 review_id 固定代表本次执行轮次，若读取结果不同则停止，不得改用新轮次。"
                ),
            )
            dispatched.append(task_id)
        except Exception as exc:
            logger.exception("Assistant review dispatch failed for %s", task_id)
            if claimed:
                async with SessionLocal() as session:
                    job = await session.get(TaskReview, job_id)
                    if job and job.status != "completed":
                        job.status = "failed"
                        job.error = str(exc)
                        job.retry_at = datetime.now(UTC) + timedelta(
                            seconds=min(3600, 30 * 2 ** min(job.attempts, 7))
                        )
                        await session.commit()
    return dispatched

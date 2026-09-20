"""Conservative automatic experience extraction after a Task reaches a terminal state.

The service creates candidates only when the Task result contains reusable facts.
It does not create a second Agent and it never copies the OpenCode transcript.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.library_service import experience_fingerprint
from app.models import (
    ExperienceEvidence,
    KnowledgeAudit,
    KnowledgeItem,
    KnowledgeUsage,
    RuntimeSession,
    Task,
    TaskSummary,
)


_REUSABLE_HINTS = re.compile(
    r"根因|原因|定位|修复|解决|规避|配置|环境|命令|工具|步骤|方法|规则|约束|"
    r"验证|测试|兼容|依赖|超时|权限|接口|git|pytest|bun|npm|mypy",
    re.IGNORECASE,
)


def _experience_type(text: str) -> str:
    lower = text.casefold()
    if re.search(r"根因|原因|定位|root cause", text, re.IGNORECASE):
        return "root_cause"
    if re.search(r"环境|配置|依赖|权限|environment|config", text, re.IGNORECASE):
        return "environment"
    if re.search(r"工具|命令|git|pytest|bun|npm|mypy|tool", lower, re.IGNORECASE):
        return "tool_usage"
    if re.search(r"规则|约束|验收|测试方法|test rule", text, re.IGNORECASE):
        return "test_rule"
    return "fix"


def _is_reusable(task: Task, summary: TaskSummary) -> bool:
    text = " ".join(
        value
        for value in (
            summary.summary,
            task.failure_reason or "",
            summary.content_md,
        )
        if value
    ).strip()
    if task.status == "SUCCEEDED":
        changes = summary.key_changes or {}
        return bool(changes.get("changed_files")) and (
            len(summary.summary.strip()) >= 60 or bool(_REUSABLE_HINTS.search(text))
        )
    if task.status == "FAILED":
        # A plain timeout/no-reply marker is an execution fact, not reusable
        # experience. Failure candidates require additional diagnostic content.
        diagnostic = (summary.summary or "").strip()
        return len(diagnostic) >= 60 and bool(_REUSABLE_HINTS.search(text))
    return False


def _candidate_content(task: Task, summary: TaskSummary) -> str:
    parts = [
        f"## 适用场景\n{task.title}",
        f"## 处理结论\n{summary.summary.strip()}",
    ]
    changes = summary.key_changes or {}
    files = changes.get("files") or []
    commits = changes.get("commits") or []
    facts = []
    if files:
        facts.append("涉及文件：" + "、".join(str(item) for item in files))
    if commits:
        facts.append("相关提交：" + "、".join(str(item)[:12] for item in commits))
    if task.failure_reason:
        facts.append("失败原因：" + task.failure_reason)
    if facts:
        parts.append("## 可确认事实\n" + "\n".join(f"- {item}" for item in facts))
    return "\n\n".join(parts)


class ExperienceExtractionService:
    """Extract 0..N reusable candidates from stable Task facts."""

    def __init__(self, session):
        self.session = session

    async def extract(self, task_id: str) -> list[KnowledgeItem]:
        task = await self.session.get(Task, task_id)
        if not task or task.status not in {"SUCCEEDED", "FAILED"}:
            return []
        summary = await self.session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == task.id)
        )
        if not summary or summary.stale or not _is_reusable(task, summary):
            return []

        runtime_session = (
            await self.session.get(RuntimeSession, summary.primary_session_id)
            if summary.primary_session_id
            else None
        )
        content = _candidate_content(task, summary)
        experience_type = _experience_type(content)
        fingerprint = experience_fingerprint(
            experience_type=experience_type,
            title=task.title,
            content_md=content,
        )
        verification = "verified" if task.status == "SUCCEEDED" else "unverified"
        now = datetime.now(UTC)

        existing = await self.session.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.type == "experience",
                KnowledgeItem.origin == "auto",
                KnowledgeItem.source_task_id == task.id,
                KnowledgeItem.source_session_id == summary.primary_session_id,
            )
        )

        if (
            existing
            and existing.status == "candidate"
            and existing.fingerprint == fingerprint
            and existing.verification_status == verification
            and (existing.experience_data or {}).get("summary_generation") == summary.generation
        ):
            return []

        knowledge_ids = (
            await self.session.scalars(
                select(KnowledgeUsage.knowledge_id)
                .where(
                    KnowledgeUsage.task_id == task.id,
                    KnowledgeUsage.knowledge_id.is_not(None),
                )
                .distinct()
            )
        ).all()
        experience_data = {
            "source": "auto_extraction",
            "source_status": task.status,
            "summary_generation": summary.generation,
            "key_changes": summary.key_changes or {},
            "referenced_knowledge_ids": list(knowledge_ids),
        }
        snapshot = {
            "task_id": task.id,
            "task_title": task.title,
            "task_status": task.status,
            "session_id": summary.primary_session_id,
            "summary_id": summary.id,
            "summary_generation": summary.generation,
        }

        if existing:
            if existing.status != "candidate":
                return []
            existing.title = task.title
            existing.summary = summary.summary
            existing.content_md = content
            existing.experience_type = experience_type
            existing.fingerprint = fingerprint
            existing.verification_status = verification
            existing.source_ref_snapshot = snapshot
            existing.experience_data = experience_data
            existing.updated_by = "system:experience-extraction"
            existing.updated_at = now
            item = existing
        else:
            item = KnowledgeItem(
                id=f"KNOW_{uuid4().hex[:20].upper()}",
                space_id=None,
                title=task.title,
                type="experience",
                summary=summary.summary,
                content_md=content,
                status="candidate",
                verification_status=verification,
                tags=[],
                source_type="auto_extracted_experience",
                source_ref=task.id,
                source_employee_id=task.employee_id,
                source_task_id=task.id,
                source_session_id=summary.primary_session_id,
                origin="auto",
                dedupe_key=f"auto:{task.id}:{summary.primary_session_id or 'none'}",
                fingerprint=fingerprint,
                experience_type=experience_type,
                scope={},
                source_ref_snapshot=snapshot,
                experience_data=experience_data,
                created_by="system:experience-extraction",
                updated_by="system:experience-extraction",
            )
            self.session.add(item)
            await self.session.flush()
            self.session.add(
                ExperienceEvidence(
                    knowledge_id=item.id,
                    task_id=task.id,
                    source_session_id=summary.primary_session_id,
                    evidence_type="task_summary",
                    result=summary.source_status,
                    captured_at=now,
                )
            )
            self.session.add(
                KnowledgeAudit(
                    knowledge_id=item.id,
                    action="candidate_extracted",
                    actor_id="system:experience-extraction",
                    actor_role="admin",
                    detail={
                        "task_id": task.id,
                        "session_id": summary.primary_session_id,
                        "summary_generation": summary.generation,
                    },
                )
            )

        if runtime_session:
            item.session_status_at_submission = runtime_session.status
            if verification == "verified":
                item.verification_session_status = runtime_session.status
                item.verification_message_id = runtime_session.last_message_id
                item.session_last_message_id_at_verification = runtime_session.last_message_id
                item.verified_at = item.verified_at or now

        self.session.add(
            KnowledgeUsage(
                resource_id=f"astra:{item.id}",
                knowledge_id=item.id,
                employee_id=task.employee_id,
                task_id=task.id,
                session_id=summary.primary_session_id,
                tool_name="experience_extraction",
                action="experience_extracted",
                result={
                    "status": "candidate",
                    "verification_status": verification,
                    "summary_generation": summary.generation,
                },
            )
        )
        await self.session.commit()
        return [item]

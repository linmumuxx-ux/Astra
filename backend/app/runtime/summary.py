"""Deterministic Task summary: one durable record per Task.

The summary is composed from Task facts plus the completing OpenCode Session's
final assistant reply. It never mirrors messages, never depends on
ASTRA_RESULT_JSON, and never forges business acceptance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.domain import AcceptanceStatus
from app.models import RuntimeSession, Task, TaskSummary


def extract_final_assistant_text(messages: list[dict]) -> tuple[str, str | None]:
    """Visible final assistant text from native messages, ignoring synthetic parts."""
    for message in reversed(messages):
        info = message.get("info") if isinstance(message.get("info"), dict) else {}
        if info.get("role") != "assistant":
            continue
        texts = [
            part.get("text", "")
            for part in message.get("parts", [])
            if isinstance(part, dict)
            and part.get("type") == "text"
            and not part.get("synthetic")
            and not part.get("ignored")
        ]
        content = "\n".join(text for text in texts if text).strip()
        if content:
            return content, info.get("id")
    return "", None


def derive_acceptance_results(criteria: list[dict]) -> list[dict]:
    """Acceptance stays UNCONFIRMED unless a human or structured flow states otherwise."""
    return [
        {
            "criterion_id": str(item.get("id")),
            "status": AcceptanceStatus.UNCONFIRMED.value,
            "description": "未提供结构化验收结论，请人工核对处理结果",
            "evidence": [],
        }
        for item in criteria
    ]


def _snapshot(task: Task) -> dict:
    return {
        "task_id": task.id,
        "title": task.title,
        "task_type": task.task_type,
        "employee_id": task.employee_id,
        "source": task.source,
    }


class TaskSummaryService:
    def __init__(self, session):
        self.session = session

    async def mark_stale(self, task: Task, *, commit: bool = True) -> None:
        existing = await self.session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == task.id)
        )
        if existing and not existing.stale:
            existing.stale = True
            existing.updated_at = datetime.now(UTC)
        if commit:
            await self.session.commit()

    async def upsert(
        self,
        task: Task,
        *,
        source_status: str,
        primary_session_id: str | None,
        summary_text: str,
        generated_by: str = "deterministic",
    ) -> TaskSummary:
        referenced = (
            await self.session.scalars(
                select(RuntimeSession.id).where(RuntimeSession.task_id == task.id)
            )
        ).all()
        now = datetime.now(UTC)
        acceptance = derive_acceptance_results(task.acceptance_criteria or [])
        content_md = "\n\n".join(
            part
            for part in (
                f"# {task.title}",
                f"- 任务：{task.id}",
                f"- 结果：{source_status}",
                f"- 完成 Session：{primary_session_id or '-'}",
                f"- 执行员工：{task.employee_id or '-'}",
                "## 结果摘要",
                (summary_text or task.current_progress or "无可见最终回复").strip(),
                "## 验收标准",
                "\n".join(
                    f"- {item['criterion_id']}：{item['status']}"
                    for item in acceptance
                ),
            )
            if part
        )
        existing = await self.session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == task.id)
        )
        if existing:
            existing.generation += 1
            existing.stale = False
            existing.summary = (summary_text or task.current_progress or "").strip()
            existing.content_md = content_md
            existing.acceptance_results = acceptance
            existing.key_changes = {}
            existing.source_status = source_status
            existing.primary_session_id = primary_session_id
            existing.referenced_session_ids = list(referenced)
            existing.generated_by = generated_by
            existing.source_ref_snapshot = _snapshot(task)
            existing.updated_at = now
            summary = existing
        else:
            summary = TaskSummary(
                id=f"TS-{uuid4().hex[:12]}",
                task_id=task.id,
                primary_session_id=primary_session_id,
                referenced_session_ids=list(referenced),
                summary=(summary_text or task.current_progress or "").strip(),
                content_md=content_md,
                acceptance_results=acceptance,
                key_changes={},
                source_status=source_status,
                generation=1,
                stale=False,
                generated_by=generated_by,
                source_ref_snapshot=_snapshot(task),
                generated_at=now,
                updated_at=now,
            )
            self.session.add(summary)
        await self.session.commit()
        return summary
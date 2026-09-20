"""Deterministic Task summary: one durable record per Task.

The summary is composed from Task facts plus the completing OpenCode Session's
final assistant reply and stable Workspace/Git facts. It never mirrors messages,
never depends on ASTRA_RESULT_JSON, and never forges business acceptance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.models import RuntimeSession, Task, TaskSummary
from app.runtime.workspace_changes import collect_workspace_changes


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


def _snapshot(task: Task) -> dict:
    return {
        "task_id": task.id,
        "title": task.title,
        "task_type": task.task_type,
        "employee_id": task.employee_id,
        "source": task.source,
    }


def _criteria_markdown(criteria: list[dict]) -> str:
    rows = []
    for index, item in enumerate(criteria, start=1):
        criterion_id = item.get("id") or f"AC-{index:02d}"
        content = str(item.get("content") or "").strip()
        if content:
            rows.append(f"- {criterion_id}：{content}")
    return "\n".join(rows)


def _changes_markdown(changes: dict) -> str:
    if not changes:
        return ""
    rows = [
        f"- 变更文件：{changes.get('changed_files', 0)}",
        f"- 新增文件：{changes.get('added_files', 0)}",
        f"- 删除文件：{changes.get('deleted_files', 0)}",
    ]
    files = changes.get("files") or []
    commits = changes.get("commits") or []
    if files:
        rows.append("- 文件：" + "、".join(str(item) for item in files))
    if commits:
        rows.append("- 提交：" + "、".join(str(item)[:12] for item in commits))
    return "\n".join(rows)


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
        key_changes = await collect_workspace_changes(self.session, task)
        result_text = (
            summary_text
            or task.failure_reason
            or task.current_progress
            or "无可见最终回复"
        ).strip()
        criteria_md = _criteria_markdown(task.acceptance_criteria or [])
        changes_md = _changes_markdown(key_changes)
        content_md = "\n\n".join(
            part
            for part in (
                f"# {task.title}",
                f"- 任务：{task.id}",
                f"- 结果：{source_status}",
                f"- 完成 Session：{primary_session_id or '-'}",
                f"- 执行员工：{task.employee_id or '-'}",
                "## 结果摘要",
                result_text,
                "## 关键变更" if changes_md else "",
                changes_md,
                "## 原始验收标准" if criteria_md else "",
                criteria_md,
            )
            if part
        )
        existing = await self.session.scalar(
            select(TaskSummary).where(TaskSummary.task_id == task.id)
        )
        if (
            existing
            and not existing.stale
            and existing.summary == result_text
            and existing.content_md == content_md
            and existing.key_changes == key_changes
            and existing.source_status == source_status
            and existing.primary_session_id == primary_session_id
            and existing.referenced_session_ids == list(referenced)
        ):
            return existing
        if existing:
            existing.generation += 1
            existing.stale = False
            existing.summary = result_text
            existing.content_md = content_md
            # No reliable structured acceptance source exists. Keep the field
            # for API compatibility, but never manufacture UNCONFIRMED rows.
            existing.acceptance_results = []
            existing.key_changes = key_changes
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
                summary=result_text,
                content_md=content_md,
                acceptance_results=[],
                key_changes=key_changes,
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

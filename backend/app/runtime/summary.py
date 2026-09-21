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


def extract_final_assistant_text(
    messages: list[dict], *, turn_anchor_id: str | None = None
) -> tuple[str, str | None]:
    """Visible assistant result from the current turn only.

    Task status derivation and TaskSummary must use the same turn boundary; an
    old successful reply must never become the result of a later failed turn.
    """

    turn = messages
    if turn_anchor_id:
        positions = [
            index
            for index, message in enumerate(messages)
            if isinstance(message.get("info"), dict)
            and message["info"].get("id") == turn_anchor_id
        ]
        turn = messages[positions[-1] :] if positions else []

    for message in reversed(turn):
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


def summary_is_complete(summary: TaskSummary | None, task: Task) -> bool:
    """A summary only counts as the completed result when it is current."""

    return bool(summary and not summary.stale and summary.source_status == task.status)


def _snapshot(task: Task, *, final_message_id: str | None = None) -> dict:
    return {
        "task_id": task.id,
        "title": task.title,
        "task_type": task.task_type,
        "employee_id": task.employee_id,
        "source": task.source,
        "final_message_id": final_message_id,
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
                select(RuntimeSession.id)
                .where(RuntimeSession.task_id == task.id)
                .order_by(RuntimeSession.created_at, RuntimeSession.id)
            )
        ).all()
        now = datetime.now(UTC)
        primary_session = (
            await self.session.get(RuntimeSession, primary_session_id)
            if primary_session_id
            else None
        )
        final_message_id = primary_session.last_message_id if primary_session else None
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
            existing.source_ref_snapshot = _snapshot(task, final_message_id=final_message_id)
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
                source_ref_snapshot=_snapshot(task, final_message_id=final_message_id),
                generated_at=now,
                updated_at=now,
            )
            self.session.add(summary)
        await self.session.commit()
        return summary

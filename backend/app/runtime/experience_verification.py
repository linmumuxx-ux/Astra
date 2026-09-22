"""Verify source execution facts; library approval/publication remains separate."""

from app.models import KnowledgeItem, RuntimeSession, Task, TaskSummary
from app.runtime.summary import summary_is_complete


def experience_item_is_verified(
    item: KnowledgeItem,
    task: Task | None,
    summary: TaskSummary | None,
    runtime_session: RuntimeSession | None,
) -> bool:
    """Only the accepted current execution round can verify its own candidates."""
    return bool(
        task
        and runtime_session
        and task.status == "SUCCEEDED"
        and summary_is_complete(summary, task)
        and item.source_task_id == task.id
        and item.source_session_id == task.current_session_id == runtime_session.id
        and runtime_session.status == "SUCCEEDED"
        and item.source_ref_snapshot.get("turn_anchor_id") is not None
        and item.source_ref_snapshot["turn_anchor_id"] == task.last_message_id
    )

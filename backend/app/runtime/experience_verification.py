"""Single source of truth for Experience verification.

An experience is verified only when it is bound to the Task's current, accepted
execution round:

* a concrete source Task and Session;
* a current TaskSummary for the Task (not stale, matching status and Session);
* the source Session is the Session that produced the accepted result;
* that Session reached SUCCEEDED;
* the round the experience was submitted in is still the accepted round.

This forbids verifying an unconfirmed MANUAL_CONFIRM result, verifying an earlier
round's candidate with a later round's success, or batch-verifying every
historical candidate because the Session happened to succeed.
"""

from __future__ import annotations

from app.models import KnowledgeItem, RuntimeSession, Task, TaskSummary
from app.runtime.summary import summary_is_complete


def experience_item_round(item: KnowledgeItem):
    """The execution round the experience was submitted in."""

    if item.origin == "auto":
        return (item.experience_data or {}).get("summary_generation")
    return (item.source_ref_snapshot or {}).get("turn_anchor_id")


def experience_verification_is_current(
    *,
    origin: str,
    source_task_id: str | None,
    source_session_id: str | None,
    round_marker,
    task: Task | None,
    summary: TaskSummary | None,
    runtime_session: RuntimeSession | None,
) -> bool:
    """Whether an experience belongs to the Task's current accepted round."""

    if task is None or summary is None or runtime_session is None:
        return False
    if task.status != "SUCCEEDED":
        # MANUAL_CONFIRM awaiting sign-off is not an accepted business result.
        return False
    if not summary_is_complete(summary, task):
        return False
    if source_task_id != task.id:
        return False
    if source_session_id != summary.primary_session_id:
        return False
    if runtime_session.status != "SUCCEEDED":
        return False
    if origin == "auto":
        return round_marker == summary.generation
    # Runtime-submitted experience is bound to the turn anchor of its round.
    return round_marker is not None and round_marker == task.last_message_id


def experience_item_is_verified(
    item: KnowledgeItem,
    task: Task | None,
    summary: TaskSummary | None,
    runtime_session: RuntimeSession | None,
) -> bool:
    return experience_verification_is_current(
        origin=item.origin,
        source_task_id=item.source_task_id,
        source_session_id=item.source_session_id,
        round_marker=experience_item_round(item),
        task=task,
        summary=summary,
        runtime_session=runtime_session,
    )
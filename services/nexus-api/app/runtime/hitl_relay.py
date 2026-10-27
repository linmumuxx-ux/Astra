"""AgentWork/OpenCode HITL → digital-employee relay helpers.

Humans must not answer question/permission requests on AgentWork itself.
The responsible digital employee decides (auto-answer) or asks the bound human
in /chat, then relays the answer back into the OpenCode session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


_HITL_WAITING = {"HITL_QUESTION", "HITL_PERMISSION"}


def is_hitl_waiting(waiting_reason: str | None) -> bool:
    return (waiting_reason or "") in _HITL_WAITING


def intervention_from_pending(
    questions: list[dict[str, Any]],
    permissions: list[dict[str, Any]],
    *,
    allowed_sessions: set[str] | None = None,
) -> dict[str, Any] | None:
    """Build a durable human_intervention payload from native pending requests."""

    scoped_q = [
        item
        for item in questions
        if isinstance(item, dict)
        and (allowed_sessions is None or item.get("sessionID") in allowed_sessions)
    ]
    scoped_p = [
        item
        for item in permissions
        if isinstance(item, dict)
        and (allowed_sessions is None or item.get("sessionID") in allowed_sessions)
    ]
    if scoped_q:
        request = scoped_q[0]
        items = request.get("questions") if isinstance(request.get("questions"), list) else []
        if not items and request.get("question"):
            items = [{"question": request.get("question"), "options": request.get("options") or []}]
        summaries = [
            str(item.get("question") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("question") or "").strip()
        ]
        options = items[0].get("options") if items and isinstance(items[0], dict) else []
        return {
            "blocking_reason": "执行需要回答后继续",
            "completed_work": "已保留当前 Session",
            "current_state": "等待回答",
            "requested_input": "\n".join(summaries) or "需要回答后继续",
            "options": options if isinstance(options, list) else [],
            "runtime_kind": "question",
            "runtime_request_id": request.get("id"),
            "runtime_session_id": request.get("sessionID"),
            "runtime_questions": items,
        }
    if scoped_p:
        request = scoped_p[0]
        permission = str(request.get("permission") or request.get("type") or "操作")
        patterns = request.get("patterns") or request.get("pattern") or []
        return {
            "blocking_reason": f"执行需要授权：{permission}",
            "completed_work": "已保留当前 Session",
            "current_state": "等待授权",
            "requested_input": f"是否允许执行 {permission}？{patterns}",
            "options": [
                {"label": "允许一次", "value": "once"},
                {"label": "始终允许", "value": "always"},
                {"label": "拒绝", "value": "reject"},
            ],
            "runtime_kind": "permission",
            "runtime_request_id": request.get("id"),
            "runtime_session_id": request.get("sessionID"),
            "runtime_questions": [],
        }
    return None


def merge_intervention(
    current: dict[str, Any] | None,
    pending: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep an already-submitted response; otherwise replace with latest pending."""

    if pending is None:
        return current
    if current and str(current.get("response") or "").strip():
        if current.get("runtime_request_id") == pending.get("runtime_request_id"):
            return {**pending, "response": current.get("response"), "source": current.get("source")}
    return pending


def normalize_permission_reply(answer: str) -> str:
    normalized = answer.strip().lower()
    if any(value in normalized for value in ("reject", "deny", "拒绝", "不允许")):
        return "reject"
    if any(value in normalized for value in ("always", "始终允许", "永久允许")):
        return "always"
    if any(value in normalized for value in ("once", "允许一次", "允许", "同意", "yes", "ok")):
        return "once"
    return "once"


def hitl_wake_hint(task_id: str, event_id: int, intervention: dict[str, Any] | None) -> str:
    requested = str((intervention or {}).get("requested_input") or "").strip()
    kind = str((intervention or {}).get("runtime_kind") or "question")
    options = (intervention or {}).get("options") or []
    option_text = ""
    if isinstance(options, list) and options:
        labels = []
        for item in options:
            if isinstance(item, dict):
                labels.append(str(item.get("label") or item.get("value") or "").strip())
            else:
                labels.append(str(item).strip())
        labels = [item for item in labels if item]
        if labels:
            option_text = "可选：" + " / ".join(labels) + "。"
    detail = f"请求（{kind}）：{requested}。" if requested else ""
    return (
        f"任务 {task_id} 需要协作输入（事件 {event_id}）。{detail}{option_text}"
        "先调用 nexus_task_get 查看详情。"
        "能直接回答时调用 nexus_task_answer_hitl 写回执行会话；"
        "不能回答时在当前数字员工对话中向绑定人类确认，收到人类回复后再调用 nexus_task_answer_hitl。"
        "不要根据这条提示直接改任务状态。"
    )


def stamped_response(intervention: dict[str, Any], answer: str, *, source: str) -> dict[str, Any]:
    return {
        **intervention,
        "response": answer.strip(),
        "source": source,
        "runtime_replied_at": datetime.now(UTC).isoformat(),
    }

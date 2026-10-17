"""员工绑定的 desired/applied。放在员工 JSON 里，不新建表。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .agentscope import AgentScopeClient, AgentScopeError


def binding_revision(names: list[str]) -> str:
    payload = json.dumps(sorted({name for name in names if name}), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _names(items: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("name") or item.get("id") or "") for item in items if isinstance(item, dict)}


def missing_bindings(
    expected: list[str],
    catalog: set[str],
    workspace: set[str],
    toolkit: set[str],
) -> list[str]:
    return [name for name in expected if name not in catalog or name not in workspace or name not in toolkit]


def settle(
    current: dict[str, Any] | None,
    *,
    desired: str,
    missing: list[str],
    error: str,
    checked_at: str,
) -> dict[str, Any]:
    record = dict(current or {})
    previous = str(record.get("applied_revision") or "")
    record["desired_revision"] = desired
    record["checked_at"] = checked_at
    if error:
        record["runtime_status"] = "error"
        record["error"] = error
        record["applied_revision"] = previous
        return record
    if missing:
        record["runtime_status"] = "error"
        record["error"] = "未发现：" + "、".join(missing)
        record["applied_revision"] = previous
        return record
    record["applied_revision"] = desired
    record["runtime_status"] = "applied"
    record["error"] = ""
    return record


async def inspect_employee(
    client: AgentScopeClient,
    employee: dict[str, Any],
    checked_at: str,
) -> dict[str, Any]:
    expected = [name for name in [*employee.get("skills", []), *employee.get("tools", [])] if name]
    desired = binding_revision(expected)
    current = employee.get("capability") if isinstance(employee.get("capability"), dict) else {}
    if not expected:
        return settle(current, desired=desired, missing=[], error="", checked_at=checked_at)
    agent_id = employee.get("agentscope_agent_id") or ""
    session_id = employee.get("mailbox_session_id") or ""
    if not client.configured or not agent_id or not session_id:
        return settle(current, desired=desired, missing=[], error="绑定尚未核对", checked_at=checked_at)
    try:
        catalog = _names(await client.list_skills()) | _names(await client.list_user_mcp())
        workspace_skills = _names(await client.list_workspace_skills(agent_id, session_id))
        workspace_mcp = await client.list_workspace_mcp(agent_id, session_id)
    except AgentScopeError as exc:
        return settle(current, desired=desired, missing=[], error=exc.detail, checked_at=checked_at)
    mcp_names = _names(workspace_mcp)
    tool_names: set[str] = set()
    for item in workspace_mcp:
        tools = item.get("tools") if isinstance(item, dict) else None
        if isinstance(tools, list):
            tool_names.update(_names(tools))
    workspace = workspace_skills | mcp_names
    toolkit = workspace | tool_names
    return settle(
        current,
        desired=desired,
        missing=missing_bindings(expected, catalog, workspace, toolkit),
        error="",
        checked_at=checked_at,
    )

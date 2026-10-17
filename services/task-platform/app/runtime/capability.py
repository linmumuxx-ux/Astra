"""能力绑定的 desired/applied。不新建表，也不改正在运行的任务。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def binding_revision(names: list[str]) -> str:
    payload = json.dumps(sorted({name for name in names if name}), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def loads_jsonc(text: str) -> dict[str, Any]:
    lines = [line for line in text.splitlines() if not line.strip().startswith("//")]
    if not lines:
        return {}
    data = json.loads("\n".join(lines))
    return data if isinstance(data, dict) else {}


def skill_names_in(root: Path) -> set[str]:
    """OpenCode 1.18.35 在给定目录下找 `<name>/SKILL.md`。不扫描仓库里的 `.opencode/`。"""

    if not root.is_dir():
        return set()
    return {path.parent.name for path in root.glob("*/SKILL.md") if path.is_file()}


def mcp_names_in(config: dict[str, Any]) -> set[str]:
    raw = config.get("mcp")
    if not isinstance(raw, dict):
        return set()
    return {str(name) for name in raw if name}


def discover_worker(skill_roots: list[Path], config_text: str) -> set[str]:
    found: set[str] = set()
    for root in skill_roots:
        found.update(skill_names_in(root))
    found.update(mcp_names_in(loads_jsonc(config_text)))
    return found


def observe_bindings(
    current: dict[str, Any] | None,
    *,
    desired: str,
    found: set[str],
    expected: list[str],
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
    missing = [name for name in expected if name not in found]
    if missing:
        record["runtime_status"] = "error"
        record["error"] = "未发现：" + "、".join(missing)
        record["applied_revision"] = previous
        return record
    record["applied_revision"] = desired
    record["runtime_status"] = "applied"
    record["error"] = ""
    return record


def write_capability(status_detail: dict[str, Any] | None, record: dict[str, Any]) -> dict[str, Any]:
    detail = dict(status_detail or {})
    detail["capability"] = record
    return detail


def dispatch_allowed(status_detail: dict[str, Any] | None) -> bool:
    if not isinstance(status_detail, dict):
        return True
    record = status_detail.get("capability")
    if not isinstance(record, dict):
        return True
    desired = str(record.get("desired_revision") or "")
    if not desired:
        return True
    return record.get("applied_revision") == desired and record.get("runtime_status") != "error"

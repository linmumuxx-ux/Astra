"""Deterministically turn an employee's final reply into Astra's work result."""

from __future__ import annotations

import json
import re
from typing import Any

from app.domain import AcceptanceStatus

RESULT_MARKER = "ASTRA_RESULT_JSON:"
_FENCED_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _structured_result(raw_text: str) -> dict[str, Any] | None:
    marker_index = raw_text.rfind(RESULT_MARKER)
    candidates: list[str] = []
    if marker_index >= 0:
        candidates.append(raw_text[marker_index + len(RESULT_MARKER) :].strip())
    candidates.extend(match.group(1).strip() for match in _FENCED_BLOCK.finditer(raw_text))
    for candidate in candidates:
        try:
            payload, _ = json.JSONDecoder().raw_decode(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        nested = payload.get("astra_result")
        return nested if isinstance(nested, dict) else payload
    return None


def human_readable_result(raw_text: str) -> str:
    """Remove Astra's machine-readable suffix from text shown to managers."""
    marker_index = raw_text.rfind(RESULT_MARKER)
    visible = raw_text[:marker_index] if marker_index >= 0 else raw_text

    def remove_result_block(match: re.Match[str]) -> str:
        block = match.group(1)
        return "" if "acceptance_results" in block or "astra_result" in block else match.group(0)

    visible = _FENCED_BLOCK.sub(remove_result_block, visible).strip()
    if visible:
        return visible
    structured = _structured_result(raw_text)
    summary = structured.get("summary") if structured else None
    return str(summary).strip() if summary else ""


def _status(value: Any) -> AcceptanceStatus | None:
    text = str(value or "").strip()
    upper = text.upper()
    if upper in AcceptanceStatus._value2member_map_:
        return AcceptanceStatus(upper)
    if any(token in text for token in ("未满足", "不满足", "未通过", "不通过", "❌", "失败")):
        return AcceptanceStatus.UNSATISFIED
    if any(token in text for token in ("无法确认", "待确认", "未确认", "不确定")):
        return AcceptanceStatus.UNCONFIRMED
    if any(token in text for token in ("满足", "通过", "✅", "已完成")):
        return AcceptanceStatus.SATISFIED
    return None


def _markdown_result(raw_text: str, criterion_id: str) -> dict[str, Any] | None:
    pattern = re.compile(rf"(?<![\w-]){re.escape(criterion_id)}(?![\w-])", re.IGNORECASE)
    for line in human_readable_result(raw_text).splitlines():
        if not pattern.search(line):
            continue
        status = _status(line)
        if not status:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        evidence = cells[2] if len(cells) >= 3 and cells[2] else ""
        description = evidence or next(
            (cell for cell in cells[1:] if _status(cell)),
            "员工已明确提交该项结论",
        )
        return {
            "criterion_id": criterion_id,
            "status": status,
            "description": description,
            "evidence": [evidence] if evidence else [],
        }
    return None


def build_work_result(
    raw_text: str,
    acceptance_criteria: list[dict[str, Any]],
    evidence_path: str,
) -> dict[str, Any]:
    """Build one complete work result, preferring explicit JSON over Markdown."""
    structured = _structured_result(raw_text) or {}
    submitted_results = structured.get("acceptance_results")
    by_id = (
        {
            str(item.get("criterion_id")): item
            for item in submitted_results
            if isinstance(item, dict) and item.get("criterion_id")
        }
        if isinstance(submitted_results, list)
        else {}
    )

    acceptance_results: list[dict[str, Any]] = []
    for criterion in acceptance_criteria:
        criterion_id = str(criterion["id"])
        submitted = by_id.get(criterion_id)
        parsed_status = _status(submitted.get("status")) if submitted else None
        parsed = None
        if submitted and parsed_status:
            parsed = {
                "criterion_id": criterion_id,
                "status": parsed_status,
                "description": str(submitted.get("description") or "员工已提交该项结论"),
                "evidence": [str(item) for item in submitted.get("evidence", []) if str(item).strip()],
            }
        parsed = parsed or _markdown_result(raw_text, criterion_id)
        if not parsed:
            parsed = {
                "criterion_id": criterion_id,
                "status": AcceptanceStatus.UNCONFIRMED,
                "description": "员工未提交可识别的逐项验收结论，请人工核对处理结果",
                "evidence": [],
            }
        if evidence_path not in parsed["evidence"]:
            parsed["evidence"].append(evidence_path)
        acceptance_results.append(parsed)

    def string_list(field: str) -> list[str]:
        value = structured.get(field, [])
        return [str(item) for item in value] if isinstance(value, list) else []

    return {
        "summary": str(structured.get("summary") or human_readable_result(raw_text)).strip(),
        "changes": string_list("changes"),
        "files": string_list("files"),
        "commits": string_list("commits"),
        "logs": string_list("logs"),
        "attachments": string_list("attachments"),
        "other": structured.get("other") if isinstance(structured.get("other"), dict) else {},
        "acceptance_results": acceptance_results,
    }

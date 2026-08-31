from collections import defaultdict
from typing import Any

from app.executors.base import TokenUsage, ToolUsageResult


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return None


def _token_values(payload: dict[str, Any]) -> tuple[int | None, int | None, int | None, int | None]:
    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    input_tokens = _integer(payload.get("input_tokens", payload.get("input")))
    output_tokens = _integer(payload.get("output_tokens", payload.get("output")))
    cache_read = _integer(payload.get("cache_read_tokens", payload.get("cacheRead", cache.get("read"))))
    cache_write = _integer(payload.get("cache_write_tokens", payload.get("cacheWrite", cache.get("write"))))
    return input_tokens, output_tokens, cache_read, cache_write


def _find_tokens(event: dict[str, Any]) -> tuple[int | None, int | None, int | None, int | None]:
    candidates: list[dict[str, Any]] = []
    info = event.get("info")
    if isinstance(info, dict):
        for key in ("tokens", "usage"):
            if isinstance(info.get(key), dict):
                candidates.append(info[key])
    part = event.get("part")
    if isinstance(part, dict):
        for key in ("tokens", "usage"):
            if isinstance(part.get(key), dict):
                candidates.append(part[key])
        candidates.append(part)
    for key in ("tokens", "usage"):
        if isinstance(event.get(key), dict):
            candidates.append(event[key])
    candidates.append(event)
    for candidate in candidates:
        values = _token_values(candidate)
        if any(value is not None for value in values):
            return values
    return None, None, None, None


def _deep_value(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return str(value[key])
        for child in value.values():
            found = _deep_value(child, keys)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _deep_value(child, keys)
            if found:
                return found
    return None


def parse_opencode_usage(
    events: list[dict[str, Any]],
) -> tuple[TokenUsage, list[ToolUsageResult], str | None]:
    token_totals: list[int | None] = [None, None, None, None]
    llm_calls = 0
    model_name: str | None = None
    tool_calls: dict[str, dict[str, Any]] = {}

    for index, event in enumerate(events):
        values = _find_tokens(event)
        if any(value is not None for value in values):
            llm_calls += 1
            for position, value in enumerate(values):
                if value is not None:
                    token_totals[position] = (token_totals[position] or 0) + value
        model_name = model_name or _deep_value(
            event, ("modelID", "model_id", "modelName", "model_name", "model")
        )

        part = event.get("part") if isinstance(event.get("part"), dict) else event
        event_type = str(event.get("type", "")).lower()
        part_type = str(part.get("type", "")).lower() if isinstance(part, dict) else ""
        if "tool" not in event_type and part_type not in {"tool", "tool_use", "tool-call"}:
            continue
        name = _deep_value(part, ("tool", "toolName", "tool_name", "name")) or "其他"
        call_id = _deep_value(part, ("callID", "call_id", "toolCallID", "tool_call_id", "id"))
        key = call_id or f"event-{index}"
        state = part.get("state") if isinstance(part, dict) and isinstance(part.get("state"), dict) else {}
        status = str(state.get("status", part.get("status", event.get("status", "unknown")))).lower()
        timing = state.get("time") if isinstance(state.get("time"), dict) else {}
        start = _integer(timing.get("start"))
        end = _integer(timing.get("end"))
        duration = max(0, end - start) if start is not None and end is not None else 0
        tool_calls[key] = {"name": name, "status": status, "duration_ms": duration}

    grouped: dict[str, dict[str, int]] = defaultdict(
        lambda: {"call_count": 0, "success_count": 0, "failure_count": 0, "duration_ms": 0}
    )
    for call in tool_calls.values():
        item = grouped[call["name"]]
        item["call_count"] += 1
        item["duration_ms"] += call["duration_ms"]
        if call["status"] in {"completed", "success", "succeeded", "done"}:
            item["success_count"] += 1
        elif call["status"] in {"error", "failed", "failure"}:
            item["failure_count"] += 1

    total_tokens = (
        sum(value or 0 for value in token_totals)
        if any(value is not None for value in token_totals)
        else None
    )
    token_usage = TokenUsage(
        input_tokens=token_totals[0],
        output_tokens=token_totals[1],
        cache_read_tokens=token_totals[2],
        cache_write_tokens=token_totals[3],
        total_tokens=total_tokens,
        llm_call_count=llm_calls if llm_calls else None,
    )
    tools = [ToolUsageResult(name=name, **values) for name, values in sorted(grouped.items())]
    return token_usage, tools, model_name

"""提取并强化旧 assistant/review.py 原生引用校验，不复制旧领域或 Transcript。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from urllib.parse import quote

from domains.core import DomainError


async def native_messages(client, binding, native_session_id=None):
    messages, cursor, seen = [], None, set()
    while True:
        page = await client.messages_in_tree(
            binding, native_session_id or binding.native_session_id, limit=100, before=cursor
        )
        messages.extend(page["messages"])
        cursor = page["next_before"]
        if not cursor:
            break
        if cursor in seen or len(messages) > 10000:
            raise DomainError(409, "原生分页无法完整核验，保留执行等待对账")
        seen.add(cursor)
    return messages


async def native_tree(client, binding):
    ids = await client.session_tree(binding)
    if len(ids) > 1000:
        raise DomainError(409, "原生子树超过核验上限，保留执行等待对账")
    return {sid: await native_messages(client, binding, sid) for sid in sorted(ids)}


def native_ref(session_id, message_id, part_id=None, *, digest=None):
    return (
        f"opencode://{quote(session_id, safe='')}/{quote(message_id, safe='')}"
        + (f"/{quote(part_id, safe='')}" if part_id else "")
        + (f"?sha256={digest}" if digest else "")
    )


def part_digest(part):
    return hashlib.sha256(
        json.dumps(part, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def final_message(messages, prompt_id):
    finals = [
        message
        for message in messages
        if (
            message.get("info", {}).get("role") == "assistant"
            and message["info"].get("parentID") == prompt_id
            and message["info"].get("time", {}).get("completed")
            and message["info"].get("finish") in {"stop", "end_turn"}
            and not message["info"].get("error")
        )
    ]
    return max(finals, key=lambda message: message["info"]["time"]["completed"]) if finals else None


def usage_facts(messages):
    infos = [item["info"] for item in messages if item.get("info", {}).get("role") == "assistant"]
    if not infos or any(not isinstance(info.get("tokens"), dict) or "cost" not in info for info in infos):
        raise DomainError(409, "原生执行缺少真实用量事实，不能猜测零消耗")
    count, cost = 0, Decimal(0)
    for info in infos:
        tokens = info["tokens"]
        values = (
            [tokens["total"]]
            if tokens.get("total") is not None
            else [
                *(tokens.get(key, 0) for key in ["input", "output", "reasoning"]),
                *tokens.get("cache", {}).values(),
            ]
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise DomainError(409, "原生用量格式不可信")
        count += sum(values)
        amount = Decimal(str(info["cost"]))
        if not amount.is_finite() or amount < 0:
            raise DomainError(409, "原生成本格式不可信")
        cost += amount
    return {
        "model": f"{infos[-1]['providerID']}/{infos[-1]['modelID']}",
        "tokens": count,
        "cost_micros": round(cost * 1000000),
    }


def evidence_index(messages, session_id):
    return [
        native_ref(session_id, message["info"]["id"], part["id"], digest=part_digest(part))
        for message in messages
        for part in message.get("parts", [])
        if part.get("type") == "tool"
        and part.get("state", {}).get("status") == "completed"
        and not part.get("synthetic")
        and not part.get("ignored")
    ]


def verify_citation(tree, citation, session_id, *, require_success=True):
    if session_id not in tree or citation.native_session_id not in tree:
        raise DomainError(409, "验收证据不能引用其他任务 Session")
    messages = tree[citation.native_session_id]
    message = next((item for item in messages if item.get("info", {}).get("id") == citation.message_id), None)
    part = next((p for p in (message or {}).get("parts", []) if p.get("id") == citation.part_id), None)
    if not part or part.get("type") != "tool" or part.get("synthetic") or part.get("ignored"):
        raise DomainError(409, "验收必须引用真实工具结果，不能使用模型自述或合成内容")
    state = part.get("state", {})
    output = state.get("output")
    if state.get("status") != "completed" or not isinstance(output, str) or not output.strip():
        raise DomainError(409, "工具结果未完成或缺少可核验输出")
    if citation.excerpt not in output:
        raise DomainError(409, "验收摘录与原生工具输出不符")
    # 旧校验以缺省 exit=0 判成功；新协议不把缺失的退出码猜成成功。
    exit_code = state.get("metadata", {}).get("exit")
    if part.get("tool") == "bash" and (type(exit_code) is not int or (require_success and exit_code != 0)):
        raise DomainError(409, "命令缺少明确成功退出码，不可作为通过依据")
    return native_ref(
        citation.native_session_id, citation.message_id, citation.part_id, digest=part_digest(part)
    )

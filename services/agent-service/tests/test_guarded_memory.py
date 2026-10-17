"""记忆 hook 只在下游还没开始时降级。handler 开始之后的错误直接抛出。"""

import asyncio

from agent_service import GuardedMemory, _memory_state, memory_status


class _Before:
    async def on_reply(self, _agent, _input_kwargs, _next_handler):
        raise RuntimeError("记忆坏了")
        yield  # pragma: no cover


class _After:
    async def on_reply(self, _agent, input_kwargs, next_handler):
        async for item in next_handler(**input_kwargs):
            yield item
        raise RuntimeError("模型 429")


def _handler(calls):
    async def handler(**_kwargs):
        calls["n"] += 1
        yield "ok"

    return handler


def test_memory_degrades_only_before_the_handler_starts():
    _memory_state.clear()
    calls = {"n": 0}

    async def degraded():
        items = []
        async for item in GuardedMemory(_Before(), "agent-a").on_reply(None, {}, _handler(calls)):
            items.append(item)
        return items

    assert asyncio.run(degraded()) == ["ok"]
    assert calls["n"] == 1
    assert memory_status("agent-a")["status"] == "degraded"

    calls["n"] = 0

    async def downstream():
        async for _item in GuardedMemory(_After(), "agent-b").on_reply(None, {}, _handler(calls)):
            pass

    try:
        asyncio.run(downstream())
    except RuntimeError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("下游错误应该抛出")
    assert calls["n"] == 1
    assert memory_status("agent-b")["status"] == "ok"

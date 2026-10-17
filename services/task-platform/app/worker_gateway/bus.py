"""连接所有者与指令路由。

在线状态和 epoch 以数据库为准。这里只回答「哪个进程持有当前 epoch 的套接字」、
如何把已落库的指令送到那个进程，以及如何把结果交回等待中的调用方。
内存实现与 Redis 实现使用同一组方法。Redis 列表长度加上已取出未送达的数量
才是队列深度，容量检查和入队在同一段 Lua 里完成。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

SINGLE_PROCESS_WARNING = "仅单进程可用"

_PUSH_LUA = """
local limit = tonumber(ARGV[1])
local held = tonumber(redis.call('GET', KEYS[2]) or '0')
if held + redis.call('LLEN', KEYS[1]) >= limit then
  return 0
end
redis.call('RPUSH', KEYS[1], ARGV[2])
return 1
"""

_PULL_LUA = """
local item = redis.call('LPOP', KEYS[1])
if not item then
  return 0
end
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[1])
return item
"""

_RESTORE_LUA = """
redis.call('LPUSH', KEYS[1], ARGV[1])
local held = tonumber(redis.call('GET', KEYS[2]) or '0')
if held > 0 then
  redis.call('DECR', KEYS[2])
end
return 1
"""

_RELEASE_LUA = """
local n = tonumber(ARGV[1])
local held = tonumber(redis.call('GET', KEYS[1]) or '0')
if held <= 0 or n <= 0 then
  return 0
end
if n >= held then
  redis.call('DEL', KEYS[1])
  return held
end
redis.call('DECRBY', KEYS[1], n)
return n
"""

_CLEAR_LUA = """
local current = redis.call('GET', KEYS[1])
if not current then
  return 0
end
local owner, epoch = string.match(current, '^(.-)|(%d+)$')
if epoch ~= ARGV[1] then
  return 0
end
if ARGV[2] ~= '' and owner ~= ARGV[2] then
  return 0
end
redis.call('DEL', KEYS[1])
return 1
"""

_TOUCH_LUA = """
local current = redis.call('GET', KEYS[1])
if not current then
  return 0
end
local owner, epoch = string.match(current, '^(.-)|(%d+)$')
if owner ~= ARGV[1] or epoch ~= ARGV[2] then
  return 0
end
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

_RESULT_LUA = """
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


def resolve_worker_gateway_bus(requested: str, redis_url: str) -> tuple[str, str | None]:
    """auto 在 Redis URL 非空时用 redis，否则用 memory。memory / redis 显式覆盖。"""

    choice = (requested or "auto").strip().lower()
    if choice not in {"auto", "memory", "redis"}:
        choice = "auto"
    if choice == "redis":
        return "redis", None
    if choice == "memory" or not (redis_url or "").strip():
        return "memory", SINGLE_PROCESS_WARNING
    return "redis", None


def _ttl_seconds(seconds: float) -> int:
    return max(1, int(seconds))


class ConnectionQueues:
    """控制帧优先于事件帧。事件队列满时丢弃事件并计数，不阻塞控制帧。"""

    def __init__(
        self,
        control_limit: int,
        event_limit: int,
        on_delivered=None,
    ) -> None:
        self.control: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=control_limit)
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=event_limit)
        self.dropped_events = 0
        self._signal = asyncio.Event()
        self._lock = asyncio.Lock()
        self._on_delivered = on_delivered

    async def put_control(self, frame: dict[str, Any]) -> bool:
        async with self._lock:
            if self.control.full():
                return False
            self.control.put_nowait(frame)
            self._signal.set()
            return True

    async def put_event(self, frame: dict[str, Any]) -> bool:
        async with self._lock:
            if self.events.full():
                self.dropped_events += 1
                return False
            self.events.put_nowait(frame)
            self._signal.set()
            return True

    def _pop_locked(self) -> tuple[str, dict[str, Any]] | None:
        if not self.control.empty():
            return "control", self.control.get_nowait()
        if not self.events.empty():
            return "event", self.events.get_nowait()
        return None

    async def wait_frame(self) -> dict[str, Any]:
        while True:
            async with self._lock:
                popped = self._pop_locked()
                if popped is not None:
                    if self.control.empty() and self.events.empty():
                        self._signal.clear()
                    kind, frame = popped
                else:
                    kind, frame = None, None
                    self._signal.clear()
            if kind is not None and frame is not None:
                if self._on_delivered is not None:
                    await self._on_delivered(kind)
                return frame
            await self._signal.wait()


class MemoryRouteBus:
    mode = "memory"

    def __init__(
        self,
        *,
        control_limit: int = 64,
        event_limit: int = 64,
        owner_ttl_seconds: float = 60,
        result_ttl_seconds: float = 60,
    ) -> None:
        self.control_limit = control_limit
        self.event_limit = event_limit
        self.owner_ttl_seconds = owner_ttl_seconds
        self.result_ttl_seconds = result_ttl_seconds
        self.owners: dict[str, tuple[str, int, float]] = {}
        self.bound: dict[str, ConnectionQueues] = {}
        self._results: dict[str, tuple[float, dict[str, Any]]] = {}
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}

    def _remember_owner(self, worker_instance_id: str, owner_id: str, epoch: int) -> None:
        self.owners[worker_instance_id] = (
            owner_id,
            epoch,
            time.monotonic() + self.owner_ttl_seconds,
        )

    def _live_owner(self, worker_instance_id: str) -> tuple[str, int, float] | None:
        current = self.owners.get(worker_instance_id)
        if current is None:
            return None
        if current[2] <= time.monotonic():
            del self.owners[worker_instance_id]
            return None
        return current

    async def set_owner(self, worker_instance_id: str, owner_id: str, epoch: int) -> None:
        if "|" in owner_id:
            raise ValueError("owner_id 不能包含 |")
        self._remember_owner(worker_instance_id, owner_id, epoch)

    async def get_owner(self, worker_instance_id: str) -> tuple[str, int] | None:
        current = self._live_owner(worker_instance_id)
        if current is None:
            return None
        return current[0], current[1]

    async def touch_owner(self, worker_instance_id: str, owner_id: str, epoch: int) -> bool:
        current = self._live_owner(worker_instance_id)
        if current is None or current[0] != owner_id or current[1] != epoch:
            return False
        self._remember_owner(worker_instance_id, owner_id, epoch)
        return True

    async def clear_owner(
        self, worker_instance_id: str, epoch: int, owner_id: str | None
    ) -> bool:
        current = self._live_owner(worker_instance_id)
        if current is None or current[1] != epoch:
            return False
        if owner_id is not None and current[0] != owner_id:
            return False
        del self.owners[worker_instance_id]
        return True

    def bind(self, worker_instance_id: str) -> ConnectionQueues:
        queues = ConnectionQueues(self.control_limit, self.event_limit)
        self.bound[worker_instance_id] = queues
        return queues

    async def unbind(self, worker_instance_id: str, queues: ConnectionQueues) -> None:
        if self.bound.get(worker_instance_id) is queues:
            del self.bound[worker_instance_id]

    async def publish_command(self, worker_instance_id: str, frame: dict[str, Any]) -> bool:
        queues = self.bound.get(worker_instance_id)
        if queues is None:
            return False
        return await queues.put_control(frame)

    async def publish_event(self, worker_instance_id: str, frame: dict[str, Any]) -> bool:
        queues = self.bound.get(worker_instance_id)
        if queues is None:
            return False
        return await queues.put_event(frame)

    async def publish_response(self, request_id: str, frame: dict[str, Any]) -> None:
        waiter = self._waiters.pop(request_id, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(frame)
            return
        self._results[request_id] = (time.monotonic() + self.result_ttl_seconds, frame)

    async def wait_response(self, request_id: str, timeout: float) -> dict[str, Any] | None:
        self._drop_expired_results()
        stored = self._results.pop(request_id, None)
        if stored is not None:
            return stored[1]
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiters[request_id] = future
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            self._waiters.pop(request_id, None)
            return None

    def _drop_expired_results(self) -> None:
        now = time.monotonic()
        expired = [key for key, (deadline, _) in self._results.items() if deadline <= now]
        for key in expired:
            del self._results[key]

    async def aclose(self) -> None:
        return None


class RedisRouteBus:
    """跨进程路由。租约、有界队列和响应都在 Redis，调用方不另存一份在线表。"""

    mode = "redis"

    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "astra:worker-gateway",
        control_limit: int = 64,
        event_limit: int = 64,
        owner_ttl_seconds: float = 60,
        result_ttl_seconds: float = 60,
    ) -> None:
        self.redis_url = redis_url
        self.prefix = prefix
        self.control_limit = control_limit
        self.event_limit = event_limit
        self.owner_ttl_seconds = owner_ttl_seconds
        self.result_ttl_seconds = result_ttl_seconds
        self._client: Any | None = None
        self.bound: dict[str, ConnectionQueues] = {}
        self._pulls: dict[int, tuple[asyncio.Event, asyncio.Task[None]]] = {}
        self._last_touch: dict[str, float] = {}

    def _connection(self) -> Any:
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def _owner_key(self, worker_instance_id: str) -> str:
        return f"{self.prefix}:owner:{worker_instance_id}"

    def _control_key(self, worker_instance_id: str) -> str:
        return f"{self.prefix}:control:{worker_instance_id}"

    def _event_key(self, worker_instance_id: str) -> str:
        return f"{self.prefix}:events:{worker_instance_id}"

    def _held_key(self, worker_instance_id: str, kind: str) -> str:
        return f"{self.prefix}:{kind}-held:{worker_instance_id}"

    def _result_key(self, request_id: str) -> str:
        return f"{self.prefix}:result:{request_id}"

    async def set_owner(self, worker_instance_id: str, owner_id: str, epoch: int) -> None:
        if "|" in owner_id:
            raise ValueError("owner_id 不能包含 |")
        await self._connection().set(
            self._owner_key(worker_instance_id),
            f"{owner_id}|{epoch}",
            ex=_ttl_seconds(self.owner_ttl_seconds),
        )

    async def get_owner(self, worker_instance_id: str) -> tuple[str, int] | None:
        raw = await self._connection().get(self._owner_key(worker_instance_id))
        if not raw:
            return None
        owner, _, epoch = raw.rpartition("|")
        return owner, int(epoch)

    async def touch_owner(self, worker_instance_id: str, owner_id: str, epoch: int) -> bool:
        result = await self._connection().eval(
            _TOUCH_LUA,
            1,
            self._owner_key(worker_instance_id),
            owner_id,
            str(epoch),
            str(_ttl_seconds(self.owner_ttl_seconds)),
        )
        return int(result) == 1

    async def clear_owner(
        self, worker_instance_id: str, epoch: int, owner_id: str | None
    ) -> bool:
        result = await self._connection().eval(
            _CLEAR_LUA,
            1,
            self._owner_key(worker_instance_id),
            str(epoch),
            owner_id or "",
        )
        return int(result) == 1

    def bind(self, worker_instance_id: str) -> ConnectionQueues:
        queues = ConnectionQueues(
            self.control_limit,
            self.event_limit,
            on_delivered=lambda kind: self._release(worker_instance_id, kind, 1),
        )
        self.bound[worker_instance_id] = queues
        stop = asyncio.Event()
        task = asyncio.create_task(self._pull(worker_instance_id, queues, stop))
        self._pulls[id(queues)] = (stop, task)
        return queues

    async def unbind(self, worker_instance_id: str, queues: ConnectionQueues) -> None:
        if self.bound.get(worker_instance_id) is queues:
            del self.bound[worker_instance_id]
        pull = self._pulls.pop(id(queues), None)
        if pull is not None:
            pull[0].set()
            pull[1].cancel()
            await asyncio.gather(pull[1], return_exceptions=True)
        await self._release(worker_instance_id, "control", queues.control.qsize())
        await self._release(worker_instance_id, "event", queues.events.qsize())

    async def publish_command(self, worker_instance_id: str, frame: dict[str, Any]) -> bool:
        return await self._push(
            self._control_key(worker_instance_id),
            self._held_key(worker_instance_id, "control"),
            frame,
            self.control_limit,
        )

    async def publish_event(self, worker_instance_id: str, frame: dict[str, Any]) -> bool:
        return await self._push(
            self._event_key(worker_instance_id),
            self._held_key(worker_instance_id, "event"),
            frame,
            self.event_limit,
        )

    async def publish_response(self, request_id: str, frame: dict[str, Any]) -> None:
        await self._connection().eval(
            _RESULT_LUA,
            1,
            self._result_key(request_id),
            json.dumps(frame),
            str(_ttl_seconds(self.result_ttl_seconds)),
        )

    async def wait_response(self, request_id: str, timeout: float) -> dict[str, Any] | None:
        client = self._connection()
        key = self._result_key(request_id)
        item = await client.lpop(key)
        if item:
            return json.loads(item)
        if timeout <= 0:
            return None
        popped = await client.blpop(key, timeout=timeout)
        if not popped:
            return None
        return json.loads(popped[1])

    async def _push(self, list_key: str, held_key: str, frame: dict[str, Any], limit: int) -> bool:
        result = await self._connection().eval(
            _PUSH_LUA, 2, list_key, held_key, str(limit), json.dumps(frame)
        )
        return int(result) == 1

    async def _release(self, worker_instance_id: str, kind: str, count: int) -> None:
        if count <= 0:
            return
        await self._connection().eval(
            _RELEASE_LUA, 1, self._held_key(worker_instance_id, kind), str(count)
        )

    async def _pull(
        self, worker_instance_id: str, queues: ConnectionQueues, stop: asyncio.Event
    ) -> None:
        client = self._connection()
        control_key = self._control_key(worker_instance_id)
        event_key = self._event_key(worker_instance_id)
        control_held = self._held_key(worker_instance_id, "control")
        event_held = self._held_key(worker_instance_id, "event")
        ttl = str(_ttl_seconds(self.owner_ttl_seconds))
        while not stop.is_set():
            await self._maybe_touch(worker_instance_id)
            moved = await self._transfer(client, queues, control_key, control_held, ttl, "control")
            if queues.control.qsize() == 0:
                moved = await self._transfer(
                    client, queues, event_key, event_held, ttl, "event"
                ) or moved
            if queues.control.qsize():
                await client.expire(control_held, int(ttl))
            if queues.events.qsize():
                await client.expire(event_held, int(ttl))
            if not moved:
                await asyncio.sleep(0.05)

    async def _transfer(
        self,
        client,
        queues: ConnectionQueues,
        list_key: str,
        held_key: str,
        ttl: str,
        kind: str,
    ) -> bool:
        if kind == "control" and queues.control.full():
            return False
        if kind == "event" and queues.events.full():
            return False
        item = await client.eval(_PULL_LUA, 2, list_key, held_key, ttl)
        if not item:
            return False
        payload = json.loads(item)
        accepted = await (
            queues.put_control(payload) if kind == "control" else queues.put_event(payload)
        )
        if accepted:
            return True
        if kind == "control":
            await client.eval(_RESTORE_LUA, 2, list_key, held_key, item)
        else:
            await self._release_key(held_key, 1)
        return False

    async def _release_key(self, held_key: str, count: int) -> None:
        await self._connection().eval(_RELEASE_LUA, 1, held_key, str(count))

    async def _maybe_touch(self, worker_instance_id: str) -> None:
        now = time.monotonic()
        if now - self._last_touch.get(worker_instance_id, 0) < self.owner_ttl_seconds / 3:
            return
        self._last_touch[worker_instance_id] = now
        client = self._connection()
        key = self._owner_key(worker_instance_id)
        if await client.exists(key):
            await client.expire(key, _ttl_seconds(self.owner_ttl_seconds))

    async def delete_prefix(self) -> None:
        client = self._connection()
        keys = [key async for key in client.scan_iter(match=f"{self.prefix}:*")]
        if keys:
            await client.delete(*keys)

    async def aclose(self) -> None:
        pulls = list(self._pulls.values())
        self._pulls.clear()
        for stop, task in pulls:
            stop.set()
            task.cancel()
        if pulls:
            await asyncio.gather(*(task for _, task in pulls), return_exceptions=True)
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def build_route_bus(
    requested: str,
    redis_url: str,
    *,
    control_limit: int,
    event_limit: int,
) -> tuple[MemoryRouteBus | RedisRouteBus, str, str | None]:
    mode, warning = resolve_worker_gateway_bus(requested, redis_url)
    if mode == "redis":
        return RedisRouteBus(
            redis_url, control_limit=control_limit, event_limit=event_limit
        ), mode, warning
    return MemoryRouteBus(control_limit=control_limit, event_limit=event_limit), mode, warning

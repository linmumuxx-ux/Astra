"""连接所有者与指令路由。

在线状态和 epoch 以数据库为准。这里只回答「哪个进程持有当前 epoch 的套接字」
以及如何把已落库的指令送到那个进程。内存实现与 Redis 实现使用同一组方法；
多进程部署必须使用 Redis，进程内字典不能当作共享在线表。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

_PUSH_LUA = """
local limit = tonumber(ARGV[1])
if redis.call('LLEN', KEYS[1]) >= limit then
  return 0
end
redis.call('RPUSH', KEYS[1], ARGV[2])
return 1
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


class ConnectionQueues:
    """控制帧优先于事件帧。事件队列满时丢弃事件并计数，不阻塞控制帧。"""

    def __init__(self, control_limit: int, event_limit: int) -> None:
        self.control: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=control_limit)
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=event_limit)
        self.dropped_events = 0
        self._signal = asyncio.Event()
        self._lock = asyncio.Lock()

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

    def _pop_locked(self) -> dict[str, Any] | None:
        if not self.control.empty():
            return self.control.get_nowait()
        if not self.events.empty():
            return self.events.get_nowait()
        return None

    async def wait_frame(self) -> dict[str, Any]:
        while True:
            async with self._lock:
                frame = self._pop_locked()
                if frame is not None:
                    if self.control.empty() and self.events.empty():
                        self._signal.clear()
                    return frame
                self._signal.clear()
            await self._signal.wait()


class MemoryRouteBus:
    def __init__(self, *, control_limit: int = 64, event_limit: int = 64) -> None:
        self.control_limit = control_limit
        self.event_limit = event_limit
        self.owners: dict[str, tuple[str, int]] = {}
        self.bound: dict[str, ConnectionQueues] = {}

    async def set_owner(self, worker_instance_id: str, owner_id: str, epoch: int) -> None:
        self.owners[worker_instance_id] = (owner_id, epoch)

    async def get_owner(self, worker_instance_id: str) -> tuple[str, int] | None:
        return self.owners.get(worker_instance_id)

    async def clear_owner(
        self, worker_instance_id: str, epoch: int, owner_id: str | None
    ) -> bool:
        current = self.owners.get(worker_instance_id)
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

    async def aclose(self) -> None:
        return None


class RedisRouteBus:
    """跨进程路由。所有者租约和有界列表都在 Redis，调用方不保存另一份在线表。"""

    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "astra:worker-gateway",
        control_limit: int = 64,
        event_limit: int = 64,
    ) -> None:
        self.redis_url = redis_url
        self.prefix = prefix
        self.control_limit = control_limit
        self.event_limit = event_limit
        self._client: Any | None = None
        self.bound: dict[str, ConnectionQueues] = {}
        self._pulls: dict[int, tuple[asyncio.Event, asyncio.Task[None]]] = {}

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

    async def set_owner(self, worker_instance_id: str, owner_id: str, epoch: int) -> None:
        if "|" in owner_id:
            raise ValueError("owner_id 不能包含 |")
        await self._connection().set(self._owner_key(worker_instance_id), f"{owner_id}|{epoch}")

    async def get_owner(self, worker_instance_id: str) -> tuple[str, int] | None:
        raw = await self._connection().get(self._owner_key(worker_instance_id))
        if not raw:
            return None
        owner, _, epoch = raw.rpartition("|")
        return owner, int(epoch)

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
        queues = ConnectionQueues(self.control_limit, self.event_limit)
        self.bound[worker_instance_id] = queues
        stop = asyncio.Event()
        task = asyncio.create_task(self._pull(worker_instance_id, queues, stop))
        self._pulls[id(queues)] = (stop, task)
        return queues

    async def unbind(self, worker_instance_id: str, queues: ConnectionQueues) -> None:
        if self.bound.get(worker_instance_id) is queues:
            del self.bound[worker_instance_id]
        pull = self._pulls.pop(id(queues), None)
        if pull is None:
            return
        pull[0].set()
        pull[1].cancel()
        await asyncio.gather(pull[1], return_exceptions=True)

    async def publish_command(self, worker_instance_id: str, frame: dict[str, Any]) -> bool:
        return await self._push(self._control_key(worker_instance_id), frame, self.control_limit)

    async def publish_event(self, worker_instance_id: str, frame: dict[str, Any]) -> bool:
        return await self._push(self._event_key(worker_instance_id), frame, self.event_limit)

    async def _push(self, key: str, frame: dict[str, Any], limit: int) -> bool:
        result = await self._connection().eval(_PUSH_LUA, 1, key, str(limit), json.dumps(frame))
        return int(result) == 1

    async def _pull(self, worker_instance_id: str, queues: ConnectionQueues, stop: asyncio.Event) -> None:
        client = self._connection()
        control_key = self._control_key(worker_instance_id)
        event_key = self._event_key(worker_instance_id)
        while not stop.is_set():
            moved = False
            if not queues.control.full():
                item = await client.lpop(control_key)
                if item:
                    accepted = await queues.put_control(json.loads(item))
                    if not accepted:
                        await client.lpush(control_key, item)
                    moved = accepted
            if not queues.events.full():
                item = await client.lpop(event_key)
                if item:
                    await queues.put_event(json.loads(item))
                    moved = True
            if not moved:
                await asyncio.sleep(0.05)

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


def build_route_bus(bus: str, redis_url: str, *, control_limit: int, event_limit: int):
    if bus == "redis":
        return RedisRouteBus(redis_url, control_limit=control_limit, event_limit=event_limit)
    return MemoryRouteBus(control_limit=control_limit, event_limit=event_limit)

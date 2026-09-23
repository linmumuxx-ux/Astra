"""已发布配置的运行态通知。

生产环境使用 Redis 保存当前版本并发布变更通知，Gateway 实例据此原子替换
内存配置。发布失败或结果未知不得让旧版本失效，因此通知异常向上抛出，由控制面
保留不可变版本并交由对账收敛，而不是回滚删除版本。

注意：节点活跃并发不再从这里读取。控制面与数据面必须使用同一事实来源——
``RuntimeStore.active``（按 lease 的 ZSET）。旧键 ``...:node:{id}:active`` 已废弃。
"""

from __future__ import annotations

import json
from typing import Any, Protocol

CURRENT_VERSION_KEY = "astra:gateway:config:current"


class ConfigNotifier(Protocol):
    async def publish(self, version: int, snapshot: dict[str, Any]) -> None: ...

    async def current_version(self) -> int | None: ...


class GatewayNotificationError(Exception):
    """Redis 不可达或通知失败。"""


class RedisConfigNotifier:
    def __init__(self, redis_url: str, channel: str = "astra:gateway:config") -> None:
        self._redis_url = redis_url
        self._channel = channel

    async def publish(self, version: int, snapshot: dict[str, Any]) -> None:
        from redis.asyncio import Redis

        client = Redis.from_url(
            self._redis_url,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
        )
        try:
            payload = json.dumps({"version": version})
            pipe = client.pipeline()
            pipe.set(CURRENT_VERSION_KEY, str(version))
            pipe.publish(self._channel, payload)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001 - 统一转换为结构化运行态错误
            raise GatewayNotificationError(f"配置通知失败: {exc}") from exc
        finally:
            await client.aclose()

    async def current_version(self) -> int | None:
        from redis.asyncio import Redis

        client = Redis.from_url(self._redis_url, socket_connect_timeout=3, socket_timeout=3)
        try:
            value = await client.get(CURRENT_VERSION_KEY)
        except Exception as exc:  # noqa: BLE001
            raise GatewayNotificationError(f"读取当前配置版本失败: {exc}") from exc
        finally:
            await client.aclose()
        if value is None:
            return None
        return int(value)


class InMemoryConfigNotifier:
    """测试与嵌入式场景的进程内通知器。"""

    def __init__(self) -> None:
        self.current: int | None = None
        self.published: list[int] = []

    async def publish(self, version: int, snapshot: dict[str, Any]) -> None:
        self.current = version
        self.published.append(version)

    async def current_version(self) -> int | None:
        return self.current
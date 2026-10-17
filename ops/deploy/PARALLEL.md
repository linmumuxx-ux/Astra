# 与 v0.9 同机部署

Nexus 与 v0.9 可以装在同一台机器上，各自使用下面这组名字。部署前在仓库根目录执行：

```bash
python ops/deploy/check_parallel.py
```

脚本只读取本仓库的默认值，不启动 v0.9。有重叠时退出码为 1。

| 项 | v0.9 | Nexus |
|---|---|---|
| 数据库名 / 用户 | `astra` / `astra` | `nexus` / `nexus` |
| SQLite 文件 | `astra.db` | `nexus.db` |
| Redis | 库 `0`，前缀 `astra:` | 库 `1`，前缀 `nexus:` |
| Celery 队列 | `control`（任务名 `astra.*`） | `nexus-control`（任务名 `nexus.*`） |
| systemd | `astra-opencode-{id}.service`、`astra-worker-{id}.service` | `nexus-opencode-{id}.service`、`nexus-worker-{id}.service` |
| 路径 | `/opt/astra`、`/etc/astra` | `/opt/nexus`、`/etc/nexus` |
| 锁目录 | `/tmp/astra-employee-serve` | `/tmp/nexus-employee-serve` |
| 端口 | 8000、8100、8110、8120、8201、8202、5174、4096、4097 | 18000、18100、18110、18120、18201、18202、15174、14096、14097 |

Redis 进程仍监听 6379。`ASTRA_REDIS_URL` 使用库 1。`ASTRA_*` 变量名保持不变。

Celery 的 `agent` 队列名，以及 worker 主机名 `astra-control`、`astra-agent`，沿用原名。它们和 v0.9 不在同一个 Redis 库里。

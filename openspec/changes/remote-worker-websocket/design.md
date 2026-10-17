## Context

当前链路是 Task → Run → Employee → Worker → OpenCode Session。远程 Worker 的数据面仍是 SSH：

| 位置 | 现在的职责 | 目标阶段 |
| --- | --- | --- |
| `app/runtime/ssh_client.py` | Paramiko 会话、本地转发 `open_tunnel`、反向转发 `open_reverse_tunnel` | 保留，只给部署和故障维护 |
| `app/executors/opencode_remote_server.py` | 每次连接打开 SSH 和本地隧道；进程内字典维持 MCP/Gateway 反向隧道 | 阶段 2 抽出传输；阶段 4 去掉业务反向隧道 |
| `app/runtime/session_connection.py` | 远程 `connect()` 走 `RemoteOpenCodeServerConnection` 或 `open_tunnel` | 阶段 2 改为 Worker Transport |
| `app/runtime/environment.py` | `ExecutionEnvironmentRuntime` 提供 `run_remote` / `open_session` | 阶段 2–3 不再被日常控制使用 |
| `app/runtime/remote_provisioning.py` | 安装 OpenCode 时使用 SSH 和本地隧道 | 阶段 4 安装 Worker Agent 并写入内网地址 |
| `app/runtime/workspace_files.py`、`workspace_changes.py` | 文件和 Git diff 走 SSH | 阶段 3 改到 Worker 本地 |
| `app/api/workspace_routes.py` | 浏览器接口里的远程命令走 `run_remote` | 阶段 3 仍对浏览器暴露 HTTP/SSE，内部改走 Worker |
| `app/executors/opencode_remote.py` | CLI fallback | 保持不动 |
| `app/main.py` | 关闭进程内 MCP 反向隧道 | 阶段 4 之前保留 |

API 和 Celery 是两个进程，反向隧道字典不能跨进程共享。执行环境与数字员工是一对一，`opencode_server_port` 默认 4096。OpenCode 公司版本仍是 1.18.35。

## Goals / Non-Goals

- 阶段 1 提供可认证的 Worker 通道、单一 epoch、持久化指令和共享路由。
- Worker Agent 用独立 `worker_instance_id` 绑定执行环境，不使用数字员工 ID，也不执行业务状态机。
- WebSocket 短帧有大小限制。大文件不走 JSON/Base64。
- 不在本阶段切换 Session、Workspace、Gateway 或 MCP 的现有调用。
- 不改 `RuntimeService.apply_session_state()` 的投影含义。

## Decisions

1. 通道与现有 SSH 并行。阶段 1 不修改 `session_connection`、`lifecycle`、`recovery`、workspace 和 provisioning 的调用路径。
2. 新路由是 `/api/worker-gateway`。`/api/workers` 继续是数字员工的只读别名。
3. 一个执行环境对应一个 Worker 实例。再次登记旋转 token、递增 epoch，不新建第二身份。库里只存 token 摘要。
4. 认证成功时用 `epoch` 条件更新加一。旧连接行标记 superseded。断开和心跳只在 epoch 仍是当前值时改在线状态。
5. 指令先 `commit`，再发布。相同 `request_id` 返回原行，不第二次投递。离线时把该行记为 `failed/offline`，避免换 epoch 后补投。队列满则保持 `pending`。
6. 响应的 epoch 取套接字注册时的值，不取消息里自报的值。`command.epoch`、套接字 epoch 和实例当前 epoch 三者一致才写入结果。ACK 只能把 `pending` 变成 `accepted`，不能把终态改回去。
7. 在线事实在 `worker_instances`。RouteBus 只保存「哪个进程持有哪个 epoch 的套接字」以及有界控制/事件队列。控制帧优先，事件队列满则丢弃并计数。
8. `MemoryRouteBus` 与 `RedisRouteBus` 使用同一组方法。默认 `ASTRA_WORKER_GATEWAY_BUS=memory`，供单进程开发和测试。API 与 Celery 分进程部署必须设为 `redis`，前缀 `astra:worker-gateway:`，避免和 API 中转的 Redis 键混用。清除租约时必须同时匹配 epoch；指定 owner 时还要匹配 owner。
9. 心跳默认 20 秒，超时 10 秒，连续 2 次失败关闭套接字。重连退避 1–30 秒再加不超过 1 秒的抖动，结果不超过 30 秒。超过 `ping + ping_timeout` 没有心跳的在线实例由 sweep 标为离线。
10. Worker Agent 的 `on_connection_lost()` 不调用 `on_process_exit()`。阶段 1 不启动 OpenCode。Agent 只处理 `ping`、`echo`、`status`。
11. OpenCode 监听端口仍以环境上的 `opencode_server_port`（默认 4096）为准。需求文本中的 4296 不在阶段 1 改列默认值。

## Risks / Trade-offs

- 阶段 1 之后，任务执行、文件、Git、Gateway 和 MCP 仍依赖 SSH。这是先建通道、后切换调用方的顺序，不是遗漏切换。
- 默认内存总线时，另一个进程看不到套接字所有者。分进程部署必须打开 Redis 总线。阶段 1 还没有 Celery 任务去投递指令。
- 非所有者进程轮换 token 后，旧套接字要到下一次心跳或响应才因 epoch 不符而关闭。迟到响应在关闭前已经被 epoch 检查拒绝。
- 连接行会随重连增长。阶段 1 不裁剪历史连接。
- 指令超时只到期 `pending/accepted`。阶段 2 的 Session 指令需要调用方传入更长的 `timeout_seconds`。

## Migration Plan

- 迁移 `0039_worker_gateway` 新增三张表，`down_revision` 为 `0038_gateway_request_lifecycle`。downgrade 删除这三张表。
- 不回填历史执行环境。没有登记的环境继续走 SSH。
- 不修改 `fix-session-task-state` 的数据或语义。

## Open Questions

- 阶段 4 是否把新安装的 Worker 本机 OpenCode 改到 127.0.0.1:4296，还是继续使用环境上的 4096。阶段 1 不改。
- 生产环境何时把 `ASTRA_WORKER_GATEWAY_BUS` 设为 `redis`。代码和跳过条件已经准备好，本机测试没有默认 Redis。

## 后续阶段

### 阶段 2

`OpenCodeServerClient` 的远程传输改为经 Worker Gateway 下发。`session_connection.connect()` 在 Worker 在线时走新传输。`recovery.py` 复用现有对账，并订阅 Worker 事件。断线只把通信标为不可用，投影仍走 `apply_session_state()`。不自动新建 Session，不自动重发最后一条 Prompt。ACK 丢失时用现有 `pending_message_id` / `pending_prompt`（含 `in_flight`）和原生消息核对。

### 阶段 3

目录、Git worktree、上传、路径校验和 diff 改到 Worker 本地。浏览器仍调用现有 Workspace HTTP/SSE。上传先落在 Nexus，由 Worker 拉取。路径必须落在该 Task/Session/Workspace 内。

### 阶段 4

执行期间不再依赖到 8110/8201 的反向隧道。部署时写入可达的 Nexus 内网地址，保留 Gateway Key 和 MCP Token。LLM Wiki 的独立连接不变。SSH 只在安装 Worker Agent、基础环境和故障维护时使用。Worker 在线时，日常 OpenCode 重启和健康检查由 Agent 本地执行。

### 阶段 5

调用方都已切换后，再清理业务反向隧道和不再使用的转发。补完整回归：重连、重复指令、进程重启、网络超时、状态一致。不改 CLI fallback。

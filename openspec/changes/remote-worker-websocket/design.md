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
4. 认证成功时用 `epoch` 条件更新加一。旧连接行标记 superseded。断开、心跳、响应和 sweep 都用条件更新：`UPDATE ... WHERE epoch=:e AND status IN (...)`。SQLite 与 MySQL 使用同一条 SQLAlchemy 语句，后提交的旧状态匹配不到行。
5. 指令先 `commit`，再由投递循环发布。相同 `request_id` 且 Worker、指令名、payload 一致时返回原行，不第二次插入。不一致返回 409。并发插入撞上唯一约束时回滚并读取原行，按同样规则比较。离线时把该行记为 `failed/offline`。队列满则保持 `pending`，租约到期后由 owner 再投。
6. 响应的 epoch 取套接字注册时的值，不取消息里自报的值。结果更新同时要求实例当前 epoch、命令 epoch 和状态仍是 `pending` 或 `accepted`。ACK 只能把 `pending` 变成 `accepted`。
7. 在线事实在 `worker_instances`。RouteBus 只保存「哪个进程持有哪个 epoch 的套接字」以及有界控制/事件队列。控制帧优先，事件队列满则丢弃并计数。
8. `MemoryRouteBus` 与 `RedisRouteBus` 使用同一组方法：owner/epoch/`clear_owner`、`touch_owner`、有界控制/事件队列、响应路由和过期。`set_owner` 只接受更高 epoch，或同一 epoch 的同一 owner；较旧 epoch 和同 epoch 的另一个 owner 都被拒绝。Redis 用 Lua 完成比较和写入。本地套接字表使用同一规则。队列键和帧都带目标 epoch。发布前核对当前 owner epoch，消费前核对 owner 与 epoch，失去所有权立即停止拉取。发送前再核对 epoch 和 `expires_at`。默认 `ASTRA_WORKER_GATEWAY_BUS=auto`。`ASTRA_REDIS_URL` 非空时用 Redis；URL 为空时用 memory，启动日志和健康接口提示「仅单进程可用」。`memory` 与 `redis` 可显式覆盖。键前缀 `astra:worker-gateway:`。清除租约时必须同时匹配 epoch；指定 owner 时还要匹配 owner。租约和未取走的响应会过期。Redis 队列深度是列表长度加上已取出未送达的数量，容量检查和入队在同一段 Lua 中完成。
9. 心跳默认 20 秒，超时 10 秒，连续 2 次失败关闭套接字。Gateway 和 Agent 都记录自己发出的 ping，并在 `ping_timeout_seconds` 内等待对应 pong。认证回复同样有超时。心跳任务异常会结束本次会话并进入重连。重连退避 1–30 秒再加不超过 1 秒的抖动，结果不超过 30 秒。超过 `ping + ping_timeout` 没有心跳的在线实例由一条批量条件更新标为离线。协议违规无论是否已经认证，都用明确关闭码关闭：超大帧 1009，其他违规 1008。
10. Worker Agent 的 `on_connection_lost()` 不调用 `on_process_exit()`。阶段 1 不启动 OpenCode。Agent 只处理 `ping`、`echo`、`status`。传输边界把关闭、拒绝连接、超时归一成 `WorkerTransportError`，Agent 进程不因 `ConnectionClosedError` 退出。执行过的 `request_id` 保留有界且会过期的记录；重复帧返回上次结果，仍在执行则返回 `already_executing`。执行前核对帧上的 epoch 和有效期。
11. OpenCode 监听端口仍以环境上的 `opencode_server_port`（默认 4096）为准。需求文本中的 4296 不在阶段 1 改列默认值。
12. 管理接口使用内部服务密钥 `ASTRA_WORKER_GATEWAY_ADMIN_KEY`，请求头 `X-Astra-Worker-Gateway-Key`。任务平台没有统一登录：图书馆身份来自受信任的上游头，MCP 密钥只保护 MCP。因此只给 Worker Gateway 的登记、查询和下发加这把密钥，不新做账号体系。密钥为空时，服务启动生成 `wgk_` 并写入 `ops/env/.env`。WebSocket 仍用 Worker token。`/health` 不要求这把密钥。

## 投递语义

至少一次投递，执行端去重。`worker_commands` 记录 `delivery_attempts`、`last_dispatched_at`、`dispatched_epoch`。认领是条件更新，只有当前 epoch 的 owner 进程跑补投循环，避免两个进程同时发布。发布失败会退回这次认领，队列满或发布异常不会把命令留在不可推进的状态。LPOP 之后消费者崩溃，租约到期后幂等指令会再投一次；Agent 按 `request_id` 去重。

`prompt` 这类有副作用的指令，一旦发布成功而结果仍未知，就停止盲重发。阶段 2 在允许再次发送之前，先用已有的 `pending_message_id` / `pending_prompt`（含 `in_flight`）和原生 Session 消息核对。没有原生证据表明 OpenCode 未接受时，不重发。

## Risks / Trade-offs

- 阶段 1 之后，任务执行、文件、Git、Gateway 和 MCP 仍依赖 SSH。这是先建通道、后切换调用方的顺序，不是遗漏切换。
- `ASTRA_REDIS_URL` 为空或显式 `ASTRA_WORKER_GATEWAY_BUS=memory` 时，另一个进程看不到套接字所有者。健康接口会提示仅单进程可用。阶段 1 还没有 Celery 任务去投递指令。
- 非所有者进程轮换 token 后，旧套接字要到下一次心跳或响应才因 epoch 不符而关闭。迟到响应在关闭前已经被 epoch 检查拒绝。
- 连接行会随重连增长。阶段 1 不裁剪历史连接。
- 指令超时只到期 `pending/accepted`。阶段 2 的 Session 指令需要调用方传入更长的 `timeout_seconds`。
- `prompt` 在结果未知时不会自动重发。阶段 2 补上原生消息核对之前，这类命令停在待对账，直到超时。

## Migration Plan

- 迁移 `0039_worker_gateway` 新增三张表，`down_revision` 为 `0038_gateway_request_lifecycle`。downgrade 删除这三张表。
- 迁移 `0040_worker_command_delivery` 为已有指令补上投递次数字段，默认 0。downgrade 删除这三列。
- 不回填历史执行环境。没有登记的环境继续走 SSH。
- 不修改 `fix-session-task-state` 的数据或语义。

## Open Questions

- 阶段 4 是否把新安装的 Worker 本机 OpenCode 改到 127.0.0.1:4296，还是继续使用环境上的 4096。阶段 1 不改。

## 后续阶段

### 阶段 2

`OpenCodeServerClient` 的远程传输改为经 Worker Gateway 下发。`session_connection.connect()` 在 Worker 在线时走新传输。`recovery.py` 复用现有对账，并订阅 Worker 事件。断线只把通信标为不可用，投影仍走 `apply_session_state()`。不自动新建 Session，不自动重发最后一条 Prompt。

传输按环境显式选择。已经迁移到 Worker 通道的环境，断线进入通信恢复，不自动退回 SSH，也不运行会杀掉旧 OpenCode 进程的启动脚本。

事件缓冲需要消费出口、事件序号、丢失通知和重新对账。阶段 1 只在套接字上丢弃超出上限的事件并计数，还没有把事件交给 Session 恢复。这是阶段 2 接通 SSE 之前要补上的契约。

HTTP 数据通道承载主控对 OpenCode 的普通请求、响应体、流式输出和大响应。WebSocket 只传控制帧和短事件。契约包括：请求如何关联到 `request_id`、沿用 Worker token 还是一次性调用凭证、流控、取消、以及单次响应和分块的大小边界。大响应不进 WebSocket JSON。

ACK 丢失的核对：`pending_message_id` 在 OpenCode 接受消息后立刻持久化，`pending_prompt.in_flight` 覆盖“请求已发出、原生消息尚未出现”的窗口。Agent 崩溃后，Nexus 用这两个字段向原生 Session 查消息。查到消息就视为已接受，禁止重发；查清没有这条消息，才允许重发。要覆盖“OpenCode 已接受、Agent 还没回结果就退出”。

Worker 占用在阶段 2 收成一个入口，同时替换 `lifecycle.py` 里的占用查询和 `remote_provisioning.reserve_operation` 里的占用条件。语义以 `dfc5eab` 为准：Task 处于 RUNNING 或 WAITING 时占用 Worker；Session SUCCEEDED、FAILED、INTERRUPTED、UNKNOWN 都不释放；Task SUCCEEDED 释放；Task CANCELED 只有在执行确认停止后才释放。部署脚本不能再用另一套 Session 状态或 `current_task_count` 判断。

### 阶段 3

目录、Git worktree、上传、路径校验和 diff 改到 Worker 本地。浏览器仍调用现有 Workspace HTTP/SSE。上传先落在 Nexus，由 Worker 拉取。路径必须落在该 Task/Session/Workspace 内。

文件安全在 Worker 端校验真实路径：解析符号链接后仍须留在工作区边界内，并用打开后的文件描述符做校验，避免检查和使用之间的替换。上传带校验和。暂存文件在成功、失败和进程退出时都要清理。

### 阶段 4

执行期间不再依赖到 8110/8201 的反向隧道。部署时写入可达的 Nexus 内网地址，保留 Gateway Key 和 MCP Token。LLM Wiki 的独立连接不变。SSH 只在安装 Worker Agent、基础环境和故障维护时使用。Worker 在线时，日常 OpenCode 重启和健康检查由 Agent 本地执行。

替换维护通道之前，`remote_provisioning` 仍要求远程 IP、用户名和 SSH 密码。阶段 4 要先证明 Gateway 与 MCP 地址从 Worker 网络可以连上，再去掉执行期对 SSH 的依赖。

### 阶段 5

调用方都已切换后，再清理业务反向隧道和不再使用的转发。epoch 乱序、双 owner、发布后崩溃、消费者崩溃和 ACK 丢失已在阶段 1/2 覆盖；本阶段只回归剩余的进程重启、网络超时和 Task/Session 一致性。不改 CLI fallback。

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
8. `MemoryRouteBus` 与 `RedisRouteBus` 使用同一组方法：owner/epoch/`clear_owner`、`touch_owner`、有界控制/事件队列、响应路由和过期。`set_owner` 只接受不低于已见过最高 epoch 的注册，或同一 epoch 的同一 owner；较旧 epoch 和同 epoch 的另一个 owner 都被拒绝。这个最高 epoch 写在单独的高水位里，清除租约或租约过期都不删除它，所以旧 epoch 不能在租约消失后复活。Redis 用 Lua 完成比较和写入。本地套接字表使用同一规则。`_handoff` 和 `serve_socket` 在 `set_owner` 之后还要核对数据库里的 `WorkerInstance.epoch`。队列键和帧都带目标 epoch。发布前核对当前 owner epoch，消费前核对 owner 与 epoch，失去所有权立即停止拉取。发送前再核对 epoch 和 `expires_at`。默认 `ASTRA_WORKER_GATEWAY_BUS=auto`。`ASTRA_REDIS_URL` 非空时用 Redis；URL 为空时用 memory，启动日志和健康接口提示「仅单进程可用」。`memory` 与 `redis` 可显式覆盖。键前缀 `astra:worker-gateway:`。清除租约时必须同时匹配 epoch；指定 owner 时还要匹配 owner。租约和未取走的响应会过期。Redis 队列深度是列表长度加上已从 Redis 取出、尚未送达的数量；本地心跳不占这个计数，取出本地帧也不释放它。容量检查和入队在同一段 Lua 中完成。队列键带 TTL，解绑时删除该 epoch 的列表。Gateway 的接收、发送、心跳和补投任一任务退出，就结束会话并关闭套接字。sweep 把实例标为离线时，同时关闭本进程套接字并释放该 epoch 的 owner；心跳不再把已离线实例改回在线。
9. 心跳默认 20 秒，超时 10 秒，连续 2 次失败关闭套接字。Gateway 和 Agent 都记录自己发出的 ping，并在 `ping_timeout_seconds` 内等待对应 pong。认证回复同样有超时。心跳任务异常会结束本次会话并进入重连。重连退避 1–30 秒再加不超过 1 秒的抖动，结果不超过 30 秒。超过 `ping + ping_timeout` 没有心跳的在线实例由一条批量条件更新标为离线。协议违规无论是否已经认证，都用明确关闭码关闭：超大帧 1009，其他违规 1008。
10. Worker Agent 的 `on_connection_lost()` 不调用 `on_process_exit()`。阶段 1 不启动 OpenCode。Agent 只处理 `ping`、`echo`、`status`。传输边界把关闭、拒绝连接、超时归一成 `WorkerTransportError`，Agent 进程不因 `ConnectionClosedError` 退出。执行过的 `request_id` 保留有界且会过期的记录；重复帧返回上次结果，仍在执行则返回 `already_executing`。执行前核对帧上的 epoch 和有效期。
11. OpenCode 监听端口仍以环境上的 `opencode_server_port`（默认 4096）为准。需求文本中的 4296 不在阶段 1 改列默认值。
12. 管理接口使用内部服务密钥 `ASTRA_WORKER_GATEWAY_ADMIN_KEY`，请求头 `X-Astra-Worker-Gateway-Key`。任务平台没有统一登录：图书馆身份来自受信任的上游头，MCP 密钥只保护 MCP。因此只给 Worker Gateway 的登记、查询和下发加这把密钥，不新做账号体系。密钥由 `ops/dev/astra_service.py` 在拉起 API 之前生成一次：文件锁、临时文件加 `rename`、写后重读、权限 `0600`。API 进程发现密钥为空时只记录「管理密钥未配置，拒绝管理调用」并返回 401，不各自生成，也不因目录不可写而退出。WebSocket 仍用 Worker token。`/health` 不要求这把密钥。

## 投递语义

阶段 1 不跨 epoch 接管。进程崩溃后重连得到新 epoch，旧 epoch 上还没完成的指令不会被新连接补投，由 sweep 在 `deadline_at` 到期时记为 `expired`。同一 epoch 内，owner 只补投仍是 `pending` 的幂等指令；已经 `accepted` 的指令不再重发。

`worker_commands.delivery_state` 把发布结果拆开，不再用 `delivery_attempts` 同时表示「没发出去」「也许发出去了」和「已经发出去」：

- `unpublished`：确定没有进队列。队列满或 owner 拒绝时退回这一态，并撤销这次认领，之后可以再投。
- `uncertain`：已经认领，发布结果未知。进程在调用总线前崩溃，或总线执行了写入但回复丢失，都留在这一态，不减回尝试次数。
- `published`：总线接受了这一帧。

`prompt` 离开 `unpublished` 之后不再发布，一直等到超时。幂等指令在 `uncertain` 或 `published` 且仍是 `pending` 时，租约到期后可以由当前 epoch 的 owner 再投一次。Agent 按 `request_id` 去重，并且只在 ACK 发送成功之后才记下「执行中」，避免 ACK 失败留下假记录。

同一进程、同一 epoch 里，LPOP 之后消费者崩溃，租约到期后幂等指令可以再投。新 epoch 不读取旧队列。

阶段 2 在允许再次发送 `prompt` 之前，先用已有的 `pending_message_id` / `pending_prompt`（含 `in_flight`）和原生 Session 消息核对。没有原生证据表明 OpenCode 未接受时，不重发。重连本身不新建 Session，也不重发最后一条 Prompt。显式 `retry_submission` 只有在原生消息查询成功、该 `messageID` 不存在、且 `in_flight` 已过期时才允许用同一个 ID 再发一次。查询失败不是「未接受」。详见「阶段 2 契约」。

## Risks / Trade-offs

- 阶段 1 之后，任务执行、文件、Git、Gateway 和 MCP 仍依赖 SSH。这是先建通道、后切换调用方的顺序，不是遗漏切换。
- `ASTRA_REDIS_URL` 为空或显式 `ASTRA_WORKER_GATEWAY_BUS=memory` 时，另一个进程看不到套接字所有者。健康接口会提示仅单进程可用。阶段 1 还没有 Celery 任务去投递指令。
- 非所有者进程轮换 token 后，旧套接字要到下一次心跳或响应才因 epoch 不符而关闭。迟到响应在关闭前已经被 epoch 检查拒绝。
- 连接行会随重连增长。阶段 1 不裁剪历史连接。
- 指令超时只到期 `pending/accepted`。阶段 2 的 Session 指令需要调用方传入更长的 `timeout_seconds`。
- `prompt` 在 `uncertain` 或 `published` 时不会自动重发。阶段 2 补上原生消息核对之前，这类命令停在待对账，直到超时。跨 epoch 同样不接管。

## Migration Plan

- 迁移 `0039_worker_gateway` 创建三张表，`down_revision` 为 `0038_gateway_request_lifecycle`。`worker_commands` 直接包含 `delivery_attempts`（默认 0）、`delivery_state`（默认 `unpublished`）、`last_dispatched_at` 和 `dispatched_epoch`。downgrade 删除这三张表。
- 不回填历史执行环境。没有登记的环境继续走 SSH。
- 不修改 `fix-session-task-state` 的数据或语义。

## Open Questions

- 阶段 4 是否把新安装的 Worker 本机 OpenCode 改到 127.0.0.1:4296，还是继续使用环境上的 4096。阶段 1 不改。

## 后续阶段

### 阶段 2 契约

本节是阶段 2 的实现约定。本轮只写契约，不写传输代码。实现时以本节为准，不再把下面的选择留作开放问题。

产品尚未发布：不保留旧帧、旧字段、SSH 回退别名或双路径兼容。OpenCode 仍只支持 1.18.35，不干预它自己的模型重试。不改 AgentScope 和 LLM Wiki 的连接。Task 完成仍须人工确认。不新增第二套 Task/Session 状态机，不改 `RuntimeService.apply_session_state()` 的投影含义。

阶段 1 已经落地的投递规则继续有效：不跨 epoch 接管；`prompt` 以及下面定义为有副作用的 `http` 离开 `unpublished` 后不再由 dispatcher 发布；幂等指令只在同一 epoch、仍是 `pending`、租约到期后可再投。

#### 2.1 远程 OpenCode 传输抽象与切换顺序

`OpenCodeServerClient` 的 `request`、`events`、`health` 下面增加一种传输。本地环境继续用 httpx 访问 `127.0.0.1:{opencode_server_port}`。远程环境的选择只看有没有 `worker_instances` 行：

| 环境 | 传输 |
| --- | --- |
| `LOCAL` | 现有本机 httpx |
| `LINUX_REMOTE` 且没有 Worker 实例 | 现有 SSH 本地转发。阶段 2 不删这条路径 |
| `LINUX_REMOTE` 且已有 Worker 实例 | Worker 数据通道。Worker 离线就失败，不打开 SSH，不调用 `RemoteOpenCodeServerConnection._start_server` |

已登记就是已迁移。不另加「传输模式」列，也不在 Worker 离线时退回 SSH。

切换顺序：

1. 先加传输和数据通道，调用方仍走旧路径。这一步要能单独测试请求关联、认证、流控和事件序号。
2. 再改 `session_connection.connect()`。`lifecycle` 的 start、send、refresh、stop，以及 `recovery.watch_session`，都从这里进入新传输。
3. `workspace_routes.native_events` 和 Workspace 里已经通过 `connect()` 转发的 OpenCode HTTP，随第 2 步切换。浏览器 URL 和 SSE 的 `data:` 行格式不变。
4. `RemoteOpenCodeServerConnection.__aenter__` 在已有 Worker 实例时改为返回同一客户端，不再打开 SSH 隧道，也不再跑会 `kill` 旧 pid 的启动脚本。没有 Worker 实例时保持现状。
5. 文件、Git、上传仍留在 `workspace_files.py`、`workspace_changes.py` 的 SSH，阶段 3 再切。`remote_provisioning` 的安装、反向隧道和部署脚本留到阶段 4。`opencode_remote.py` CLI fallback、`ssh_client.py` 不改。

`connect(..., start=True)` 在已迁移环境上只表示「经 Worker 确认本机 OpenCode 健康」。健康失败把这次调用标为 OpenCode 不可用，不在连接路径上启动或杀掉进程。日常重启留给阶段 4 的显式维护命令。

#### 2.7 HTTP 数据通道

云端不对 Worker 开入站端口。OpenCode 只听 `127.0.0.1`。所有字节都在 Worker 主动拨出的连接上。

两条平面：

- **WebSocket** 只携带控制帧：`http` / `subscribe_events` / `cancel`、ACK、心跳，以及很短的完成通知。完成通知只有 `request_id`、HTTP 状态和字节数，不带响应体。
- **数据通道** 承载响应体、超过帧限制的响应，以及 OpenCode SSE。Worker 把本地 OpenCode 的响应主动上传到 Nexus。

普通调用：

1. 调用方经传输提交一条 `http` 指令。payload 含 `method`、`path`、`query`，以及可选的 JSON `body`。`body` 编码后超过 32 KiB，或整帧超过 `worker_gateway_max_frame_bytes`（默认 256 KiB），提交时直接拒绝，错误码 `body_too_large`，不发布。阶段 2 的 OpenCode 控制调用都落在这个上限内。更大的上传是阶段 3 的文件通道，不在这里做。
2. 指令先落库再发布，沿用阶段 1 的 epoch fencing。
3. Agent 用已有登记 token 校验帧上的 epoch。然后只访问 `http://127.0.0.1:{opencode_server_port}{path}`。
4. Agent 把响应 `PUT` 到 `/api/worker-gateway/data/{request_id}`。请求头是 `Authorization: Bearer <登记 token>` 和 `X-Astra-Worker-Epoch: <epoch>`。不使用管理密钥，也不发一次性调用凭证。
5. Nexus 校验 token 摘要、该 `request_id` 属于这个 Worker、指令 epoch 与当前 `WorkerInstance.epoch` 一致，且指令名是 `http` 或 `subscribe_events`。旧 epoch 返回 409 `epoch_stale`，不保存正文。
6. WebSocket 上的完成帧只唤醒等待者。正文放在路由总线的独立键 `astra:worker-gateway:body:{request_id}`，TTL 沿用现有结果 TTL（60 秒）。`worker_commands.result` 只存 `{http_status, size, sha256}`。等待者取走正文后删除该键。

同一 `request_id` 的第二次 PUT：摘要相同则返回 200 且不再次完成等待者；摘要不同返回 409。

大响应：PUT 分块，每块不超过 256 KiB。非流式响应累计超过 8 MiB 时，Agent 中止本地读取，数据通道以 `response_too_large` 失败，命令记失败。调用方改用已经存在的分页接口 `messages_page`。禁止把响应用 Base64 放进 WebSocket。

SSE 不使用这条「一次 PUT 一个完整正文」的路径，见下一节。`events()` 在新传输上打开 `subscribe_events`，而不是把 `/event` 当成普通 `http`。

流控：每个 Worker 同时最多 8 个未完成 `http` 和 1 个 `subscribe_events`。超出的指令保持 `pending`，直到有空位或到达 `deadline_at`。Nexus 侧未消费的 SSE 记录超过 64 条时停止读取上传，靠 TCP 反压让 Agent 停止读取本地 SSE。这条反压不经过控制队列，不能堵住 ping、ACK 和取消。

取消：调用方或截止时间到了，就发一条幂等的 WebSocket 指令 `cancel`，`request_id` 与原指令相同。Agent 中止本地 httpx 并结束上传。其后的字节丢弃。epoch 变化使旧 epoch 的上传全部 409。`cancel` 是幂等控制指令，可以在同一 epoch 的租约到期后重发。

有副作用的 `http`：方法不是 `GET` 或 `HEAD` 的 `http`，与 `prompt` 一样，离开 `unpublished` 后 dispatcher 不再发布。`GET` / `HEAD` 仍是幂等指令。

#### 2.2 / 2.6 事件

OpenCode 的 `/event` 由 Agent 在 Worker 本机订阅，再按序号上传。Nexus 把它写成浏览器已经在读的 `text/event-stream`。阶段 1 的 `_SocketLease.inbound_events` 只是套接字进程里的丢弃缓冲，阶段 2 不把它当作 Session 或浏览器的消费出口。

订阅：Nexus 发 `subscribe_events`，payload 是 `directory`。同一 epoch、同一 directory 只保留一个 `subscription_id`。重复订阅返回现有 id，不第二路读取本地 SSE。新 epoch 不延续旧序号；重连后的第一件事是对账，而不是补旧序号。

上传体是 NDJSON，每行一个对象，单行 UTF-8 不超过 256 KiB：

```json
{"seq": 41, "subscription_id": "sub_…", "event": {"type": "session.status", "properties": {}}}
```

`seq` 从 1 开始，按 `(worker_instance_id, epoch, subscription_id)` 单调递增，由 Agent 在读到一条 SSE 时分配。超过 256 KiB 的事件不上传正文，改为这一条：

```json
{"seq": 41, "subscription_id": "sub_…", "dropped": true, "reason": "event_too_large", "event_type": "session.diff"}
```

持有上传的进程把接受的行写到共享日志 `astra:worker-gateway:eventlog:{worker}:{epoch}:{subscription_id}`，并只保留最近 64 条。memory 总线在进程内保存同一份日志；多进程要能对上事件，必须使用已经配置的 Redis。memory 的健康提示仍是「仅单进程可用」。

消费方是 `recovery.watch_session` 和 `native_events`。它们读这份日志，不读套接字 deque。浏览器输出保持现在的形状：普通事件是 `data: {OpenCode 事件}\n\n`，全局流仍是 `data: {"directory","payload"}\n\n`。

丢失：收到的 `seq` 大于已确认序号加 1，或收到 `dropped: true`，就记一个缺口，并向浏览器写一条：

```text
data: {"type":"astra.event_gap","subscription_id":"sub_…","from":12,"to":15}
```

不补造缺失事件，也不为了补洞新建 Session。`recovery` 看到缺口或订阅断开后，走现有的有界 `refresh`：重新读取原生 Session、消息、问题和权限。事件只用来缩短等待，原生读取才是事实。对账结果进入 `apply_session_state()`。

过期 epoch：上传的 epoch 与 `WorkerInstance.epoch` 不一致时整次上传 409，不追加日志，不推进序号。旧连接上迟到的行不能推进新 epoch 的游标。

#### 2.3 / 2.9 / 2.12 重连与 ACK 丢失

选择：**用原生消息核对，不在 Agent 上落盘去重账本。** 阶段 1 的内存 `request_id` 记录只挡住同一进程里的重复帧。进程重启后它消失，不能当作「已经执行」或「可以重发」的证据。有副作用的指令不新增 Worker 本地数据库或文件账本。

`pending_message_id` 的写入时机不变：在 OpenCode 的 POST 离开 Nexus 之前，与 `pending_prompt` 同一事务提交。`pending_prompt.in_flight` 与 `in_flight_since` 覆盖「请求已发出、原生消息列表里还看不到这条 `messageID`」的窗口。不改到 Agent ACK 之后，也不改到 OpenCode 响应之后。Agent 的 ACK 只表示指令帧被接受，不表示 OpenCode 接受了 Prompt。

重连时 Nexus 用新 epoch 的数据通道读取已绑定的 Session，不创建 Session。然后读取：

- `GET /session/{id}`
- `GET /session/{id}/message`
- `GET /question` 与 `GET /permission`
- 现有的 `session_tree`

对照规则：

| 证据 | 动作 |
| --- | --- |
| 原生消息里能看到 `pending_message_id` | 视为 OpenCode 已接受。清除 `in_flight`。不重发。把这次读取交给 `refresh` / `apply_session_state()` |
| 查询成功，消息不存在，且 `in_flight` 已超过 `opencode_control_timeout_seconds` | 只有现有的显式 `retry_submission` 可以用同一个 `messageID` 再发一次。重连路径不发 |
| 查询失败、超时、Worker 离线、epoch 过期 | 不重发。通信按 2.4 记为不可用 |
| OpenCode 已接受，Agent 在 PUT 结果之前退出 | 与第一行相同。`pending_message_id` 还在，重连后的消息列表就是证据 |
| 只丢失了 WebSocket ACK，原生消息尚未出现，`in_flight` 未过期 | 保持预约。不重发，也不把命令当成失败 |

「OpenCode 已接受、Agent 未回结果即退出」因此由 Task 上的 `pending_message_id` 和随后的原生消息列表收口，不依赖 Agent 内存。跨 epoch 仍不接管旧的 `http` 指令；旧指令到期后，上面的核对决定要不要走显式 retry，而不是由新连接把旧帧再送一遍。

#### 2.4 / 2.8 故障分类与恢复

三类故障分开落在已有字段上，不新增状态列：

| 种类 | 记录 | Task 业务状态 |
| --- | --- | --- |
| 通信中断：套接字断开、Worker 离线、数据通道超时、epoch 失效 | `runtime_connection=UNAVAILABLE`，`runtime_error`，事件 `RUNTIME_DISCONNECTED`。非终态 Session 记 `UNKNOWN` / `TRANSPORT_UNKNOWN`。不写 `execution_error` | 不变。走现有 `RuntimeService.disconnected()` |
| 执行超时：这一轮达到现有时间上限 | 现有 `SessionTerminalReason.TIMEOUT`，经 `apply_session_state()` 投影 | 按现有规则进入 WAITING，理由用 `_RECOVERY_REASON` |
| OpenCode 异常：`session.error`、原生会话错误 | 现有 `execution_error` 与 `SessionTerminalReason.ASSISTANT_ERROR` 等 | 只经 `apply_session_state()` 投影。不把 Task 写成 FAILED |

Worker Gateway、Agent 和传输层不赋值 `Task.status`。Session 观察要变成任务状态时，只调用 `RuntimeService.apply_session_state()`。`recovery.py` 继续做对账和订阅，断线调用 `disconnected()`。

已迁移环境断线后停留在通信恢复：标记不可用、等待 Worker 重连、重连后按 2.3 核对。不打开 SSH 隧道，不执行 `opencode_remote_server.py` 里那段先 `kill` 同端口旧进程再 `nohup` 的 `_start_server`。Worker Agent 的 `on_connection_lost()` 继续不调用 `on_process_exit()`，也不因为 WebSocket 断开去启动或重启仍然健康的 OpenCode。

#### 2.5 / 2.10 占用

`lifecycle.py` 里 start/send 的占用查询，和 `remote_provisioning.reserve_operation` 里的占用条件，收成一个函数，两边都调用它。`current_task_count` 只由这个结果写出（占用为 1，否则为 0），不再当作判断输入。`reserve_operation` 去掉单独的 `RuntimeSession.status in (RUNNING, WAITING, UNKNOWN)` 条件和 `current_task_count == 0` 条件。

员工被占用，当且仅当他有一条 Task 满足下面任一条件：

- `status` 是 `RUNNING` 或 `WAITING`
- `pending_message_id` 不为空
- `status` 是 `PENDING` 且 `claimed_at` 不为空
- `status` 是 `CANCELED`，并且执行还没确认停止。确认停止指 `pending_message_id` 与 `pending_prompt` 都已清空，且绑定的 RuntimeSession 不是 `RUNNING`、`WAITING` 或 `UNKNOWN`

释放只发生在两种情况：Task 是 `SUCCEEDED`，或 Task 是 `CANCELED` 且上面的停止确认已经成立。Session 的 `SUCCEEDED`、`FAILED`、`INTERRUPTED` 不单独释放。套接字在线与否、Session `idle`、单条 Worker 指令结束，都不改变占用。`UNKNOWN` 不释放；通信恢复后的 `refresh` 若证明执行已停，再由取消完成路径释放。占用函数自身不新增超时。

#### 2.11 幂等身份包含 session_id

相同 `request_id` 只有在 `worker_instance_id`、指令名、`payload` 和 `session_id` 都相同的时候才返回原行。任一项不同，包括一边是 `NULL`、另一边不是，都返回 409。

理由：阶段 2 的指令作用在原生 Session 上。`request_id` 全局唯一，现在的比较不看 `session_id` 列，调用方只要保持 payload 不变就能把另一条 Session 的重放当成原指令。列和 payload 必须一起看。产品未发布，直接收紧比较，不加旧请求的例外。

#### 阶段 2 故障测试

实现阶段要新增或补齐下面六项。阶段 1 已有的通道测试继续留着，不把它们当成这六项的替代。

1. **epoch 乱序。** 旧 epoch 的事件行和数据 PUT 得到 409，事件序号不前进，`Task.status` 不变。
2. **双 owner。** 同一 epoch 的另一个 owner 不能注册，也不能发布；只有持有套接字的进程收到 `http` 指令。
3. **发布后崩溃。** 指令已经是 `published` 或 `uncertain` 时投递进程退出。有副作用的 `http` / `prompt` 不被新循环再次发布；幂等 `GET` 只在同一 epoch 的租约到期后可以再投。
4. **消费者崩溃。** 帧已从 Redis 取出、尚未上传完成时消费者退出。同一 epoch 的幂等指令在租约到期后可以再投；新 epoch 不读取旧列表。容量不永久占用。
5. **ACK 丢失。** OpenCode 消息列表里已经有 `pending_message_id`，Agent 在结果 PUT 之前退出。重连后看到该消息，不重发 Prompt，不新建 Session，`in_flight` 被清掉，随后的状态变化只来自 `apply_session_state()`。
6. **事件丢失对账。** 序号出现缺口或 `event_too_large`。消费方收到 `astra.event_gap`，`refresh` 重读 Session、消息、问题和权限。不新建 Session。Task 业务状态只有投影函数可以改。

### 阶段 3

目录、Git worktree、上传、路径校验和 diff 改到 Worker 本地。浏览器仍调用现有 Workspace HTTP/SSE。上传先落在 Nexus，由 Worker 拉取。路径必须落在该 Task/Session/Workspace 内。

文件安全在 Worker 端校验真实路径：解析符号链接后仍须留在工作区边界内，并用打开后的文件描述符做校验，避免检查和使用之间的替换。上传带校验和。暂存文件在成功、失败和进程退出时都要清理。

### 阶段 4

执行期间不再依赖到 8110/8201 的反向隧道。部署时写入可达的 Nexus 内网地址，保留 Gateway Key 和 MCP Token。LLM Wiki 的独立连接不变。SSH 只在安装 Worker Agent、基础环境和故障维护时使用。Worker 在线时，日常 OpenCode 重启和健康检查由 Agent 本地执行。

替换维护通道之前，`remote_provisioning` 仍要求远程 IP、用户名和 SSH 密码。阶段 4 要先证明 Gateway 与 MCP 地址从 Worker 网络可以连上，再去掉执行期对 SSH 的依赖。

### 阶段 5

调用方都已切换后，再清理业务反向隧道和不再使用的转发。epoch 乱序、双 owner、发布后崩溃、消费者崩溃和 ACK 丢失已在阶段 1/2 覆盖；本阶段只回归剩余的进程重启、网络超时和 Task/Session 一致性。不改 CLI fallback。

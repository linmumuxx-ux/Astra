## Context

当前链路是 Task → Run → Employee → Worker → OpenCode Session。下面这张表和 Migration Plan 里「未标成 `worker` 的环境继续走 SSH」都是阶段 1 之前的历史，不是阶段 4 的契约。阶段 4 之后，未标记的远程环境直接失败，不走 SSH。`main.py` 关闭隧道的调用只是进程退出时的清理钩子，不是创建隧道的地方。

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

阶段 2 在允许再次发送 `prompt` 之前，先核对原生 Session 的完整分页消息，以及这次 attempt 的请求体有没有被 Agent 拉取过。消息还不可见，只说明 OpenCode 还没落库，不能当成未发送。重连、恢复、调度、心跳和超时都不发送 Prompt，也不新建 Session。只有人工显式重试可以再发，而且必须满足「阶段 2 契约」里的拉取证据、本地上限和再次确认。OpenCode 1.18.35 不会把相同 `messageID` 当成一次无操作。

## Risks / Trade-offs

- 阶段 1 之后，任务执行、文件、Git、Gateway 和 MCP 仍依赖 SSH。这是先建通道、后切换调用方的顺序，不是遗漏切换。
- `ASTRA_REDIS_URL` 为空或显式 `ASTRA_WORKER_GATEWAY_BUS=memory` 时，另一个进程看不到套接字所有者。健康接口会提示仅单进程可用。阶段 1 还没有 Celery 任务去投递指令。
- 非所有者进程轮换 token 后，旧套接字要到下一次心跳或响应才因 epoch 不符而关闭。迟到响应在关闭前已经被 epoch 检查拒绝。
- 连接行会随重连增长。阶段 1 不裁剪历史连接。
- 指令超时只到期 `pending/accepted`。阶段 2 的 Session 指令需要调用方传入更长的 `timeout_seconds`。
- `prompt` 在 `uncertain` 或 `published` 时不会自动重发。阶段 2 补上原生消息核对之前，这类命令停在待对账，直到超时。跨 epoch 同样不接管。

## Migration Plan

- 迁移 `0039_worker_gateway` 创建三张表，`down_revision` 为 `0038_gateway_request_lifecycle`。`worker_commands` 直接包含 `delivery_attempts`（默认 0）、`delivery_state`（默认 `unpublished`）、`last_dispatched_at` 和 `dispatched_epoch`。downgrade 删除这三张表。
- 不回填历史执行环境。上一条「未标成 `worker` 的环境继续走 SSH」是阶段 1 的历史。阶段 4 之后该环境直接失败，不走 SSH。已迁移仍是环境上的显式标记，不是「有 `worker_instances` 行」。
- 不修改 `fix-session-task-state` 的数据或语义。

## Open Questions

- 无。通道已拍板为 A，密码已拍板为选项 2。OpenCode 继续使用环境上的 `opencode_server_port`（默认 4096）。

## 后续阶段

### 阶段 2 契约

本节是阶段 2 的实现约定。本轮只写契约，不写传输代码。实现时以本节为准。

产品尚未发布：不保留旧帧、旧字段、SSH 回退别名或双路径兼容。OpenCode 仍只支持 1.18.35，不干预它自己的模型重试。不改 AgentScope 和 LLM Wiki 的连接。Task 完成仍须人工确认。不新增第二套 Task/Session 状态机，不改 `RuntimeService.apply_session_state()` 的投影含义。重连不新建 Session，不重发最后一条 Prompt。通信故障不改 Task 业务状态。OpenCode 只听 `127.0.0.1`。

阶段 1 的投递规则继续有效：不跨 epoch 接管；有副作用的指令离开 `unpublished` 后不再由 dispatcher 发布；幂等指令只在同一 epoch、仍是 `pending`、租约到期后可再投。

#### 2.1 传输抽象、调用方与切换顺序

凡是发到 OpenCode 的 HTTP，都走同一个传输，包括 `OpenCodeServerClient.request`、`events`、`health`，以及 `workspace_routes.py` 里现在用 httpx 直连 `client.base_url` 的那段（约 440–442 行）。迁移后的 Workspace 代理不再自己拨 `base_url`。本地环境继续用 httpx 访问 `127.0.0.1:{opencode_server_port}`。

远程环境看显式标记 `opencode_execution_environments.worker_channel`，取值 `ssh` 或 `worker`，默认 `ssh`。有 `worker_instances` 行但标记仍是 `ssh` 的，数据面继续走现有 SSH。标记写成 `worker` 之后，Worker 离线就失败，不打开 SSH，不调用 `_start_server`。

`environment_snapshot`（`environment.py` 约 27–40 行）不写入 `worker_channel`。`environment_from_snapshot`（约 44–60 行）和 `session_connection.py` 的两个 resolver（约 34–53 行）也不能从快照得到它。所有 `connect()` 入口按 `environment_id` 重新读取环境行上的 `worker_channel`。快照里即使出现这个字段也忽略。

切换 `worker_channel` 是一次维护操作，不是普通连接的副作用。它受占用谓词和维护前的 Session 检查约束；员工被占用时拒绝。探测只访问配置里的 Gateway 与 MCP 地址（现为 8110 和 8201），不接受指令 payload 里传来的 URL。写入配置后做一次受控重载：只在无人占用时重启本机 `127.0.0.1` 上的 OpenCode，然后读取运行中的生效配置。项目级 `opencode.json` 可以覆盖全局配置，所以核对的是生效地址，不是刚写下去的那个文件。生效地址与配置的内网地址一致，才把标记改成 `worker`。

标记改成 `worker` 的前置条件，全部满足才做条件更新：

1. 该环境已有 Worker 实例，并且当前 epoch 在线。员工当时不被占用。
2. Worker 从自己的网络对配置中的内网 Gateway 和图书馆 MCP 做 HTTP 探测并成功。探测失败则标记保持 `ssh`。
3. 写到 Worker 上的 OpenCode 配置使用这两个内网直连地址，保留 Gateway Key 和 MCP Token。不再写入反向隧道产生的回环地址。受控重载后，生效配置里的地址与此一致。
4. OpenCode 监听地址仍是 `127.0.0.1`，端口仍是环境上的 `opencode_server_port`。

这是阶段 2 的迁移门，不是阶段 4 才做的检查。LLM Wiki 的独立连接不改。

切换顺序：

1. 先加传输、数据通道和事件序号，调用方仍走旧路径。
2. 再改 `session_connection.connect()`。`lifecycle` 的首次发送、refresh、stop，以及 `recovery.watch_session`，都从这里进入。人工重试单独走下面的重试函数，不走首次发送。
3. `native_events` 和 Workspace 代理，包括现在直连 `client.base_url` 的请求，随第 2 步改走传输。浏览器 URL 和 SSE 的 `data:` 行格式不变。响应头至少带回 `x-next-cursor`、`link`、`x-has-more`。
4. 已标记 `worker` 的 `RemoteOpenCodeServerConnection.__aenter__` 返回同一客户端。不再为这次连接打开 SSH，不再调用 `ensure_remote_gateway_tunnel` / `ensure_remote_mcp_tunnel`，也不再跑 `_start_server`。
5. 已迁移环境的目录、worktree 和复制 `opencode.json` 改成 Agent 指令，见下表。文件与 Git 浏览仍走 SSH，阶段 3 再切。隧道代码在仍有 `ssh` 环境时保留，阶段 4 再删。`opencode_remote.py` CLI fallback 和 `ssh_client.py` 不改。

`connect(..., start=True)` 在已迁移环境上只表示「经 Worker 确认本机 OpenCode 健康」。健康失败把这次调用标为不可用。连接路径不启动、不杀掉 OpenCode。日常重启留给阶段 4 的显式维护命令。

Workspace 启动里的 SSH，阶段 2 按环境拆开：

| 步骤 | 未迁移（`ssh`） | 已迁移（`worker`） | 之后 |
| --- | --- | --- | --- |
| `session_connection._ensure_remote_workspace`（约 168–211 行）：目录、worktree、复制 `opencode.json` | 保留 SSH | 阶段 2 改为 Agent 指令 `prepare_workspace`，不再走 SSH | 已在阶段 2 完成 |
| `workspace_files` / `workspace_changes` / 任务仓库的 `git` 浏览和 diff | 保留 | 契约见下方阶段 3。代码落地前这些调用仍走 SSH | 阶段 3 |
| `RemoteOpenCodeServerConnection` 的 SSH 会话、到 OpenCode 端口的本地转发、每次连接维持的 Gateway/MCP 反向隧道（`opencode_remote_server.py` 约 146–162 行） | 保留 | 阶段 2 去掉 | 阶段 4 删除实现 |
| `remote_provisioning` 把隧道地址写进 OpenCode 配置（约 286–303 行） | 保留 | 阶段 2 改为写入内网 8110/8201，并先由 Worker 探测 | 阶段 4 不再准备隧道 |
| `_start_server` 里先 `kill` 旧 pid 再 `nohup` | 保留 | 阶段 2 不跑 | 阶段 4 的显式重启也不得杀掉健康进程 |
| 安装 Worker Agent、基础环境、故障维护用的 SSH | 保留 | 保留 | 阶段 4 仍保留到替换完成 |

#### 2.7 HTTP 数据通道与 WebSocket 分工

云端不对 Worker 开入站端口。OpenCode 只听 `127.0.0.1`。Worker 主动连接。

分工：

- **WebSocket** 只承载控制与事件。控制帧是短的「请求就绪」通知，字段只有 `request_id`、`epoch`、`expires_at`，以及方法、路径这类不含正文的元数据。事件帧见下一节。心跳、pong、取消也在这条连接上。
- **HTTP** 承载服务调用和大文件。Worker 用 `GET /api/worker-gateway/data/{request_id}/request` 拉取请求体，用 `PUT /api/worker-gateway/data/{request_id}/response` 上传响应。响应正文不进 WebSocket。阶段 3 的大文件走同一对端点，另加阶段 3 的校验和与路径规则。

调用步骤：

1. 调用方提交 `http` 指令。请求体先存到路由总线的 `astra:worker-gateway:body-request:{request_id}`，不放进 WebSocket 帧。阶段 2 的服务调用正文上限 8 MiB，超过则 `body_too_large`，不发布。这个键的过期时间不早于该指令的 `deadline_at` 再加上 `worker_gateway_dispatch_lease_seconds`。
2. 指令先落库再发布。发布出去的帧只有就绪通知。有副作用的 Prompt 在同一事务里把 `(pending_message_id, pending_attempt)` 映射到这条 `request_id`。
3. Agent 在独立任务里处理这条通知，见 2.6 的并发规则。它用登记 token 和 epoch 调用 GET。Nexus 核对 token 摘要、指令属于这个 Worker、指令 epoch 等于当前 `WorkerInstance.epoch`，并且指令仍是 `pending` 或 `accepted`。旧 epoch 返回 409，不返回正文。GET 成功时记下 `body_fetched_at`；这是「请求体已被拉取」的记录。
4. Agent 只访问 `http://127.0.0.1:{opencode_server_port}{path}`。本地调用的硬上限是 `opencode_control_timeout_seconds`。所属 epoch 已经结束时，还没发出的本地 POST 不得再发。已经发出的调用仍受这个上限约束，到点中止。
5. Agent PUT 响应。每次上传使用独立暂存键 `astra:worker-gateway:body-response:{request_id}:{upload_id}`。请求头仍是 `Authorization: Bearer <登记 token>` 和 `X-Astra-Worker-Epoch: <epoch>`。不用管理密钥，也不发一次性调用凭证。PUT 带 HTTP 状态、`content-type`，以及 `x-next-cursor`、`link`、`x-has-more`。正文分块，每块不超过 256 KiB。非流式响应累计超过 8 MiB 则 `response_too_large`。
6. 等待者只由最终 CAS 成功的那次上传唤醒。`worker_commands.result` 只存 `{http_status, size, sha256, headers, upload_id}`。CAS 失败只删除自己的 `upload_id` 键，不删除另一个上传的正文。WebSocket 上不再为响应体发完成帧。

同一 `request_id` 再 PUT 一次：若 CAS 已经成功且摘要相同，返回 200，不再次唤醒。摘要不同，或 CAS 没有赢，返回 409，并只清理这次 `upload_id`。

每个 Worker 同时最多 8 个未完成的 `http`。超出的指令保持 `pending`，直到有空位或到达 `deadline_at`。这 8 路和事件订阅都不占用 WebSocket 读循环，因此心跳不会被大请求堵住。

有副作用的 `http`：方法不是 `GET` 或 `HEAD` 的，与 `prompt` 一样，离开 `unpublished` 后 dispatcher 不再发布。`GET` / `HEAD` 仍可在同一 epoch 的租约到期后重投。

取消见 2.11 后面的专门一节。取消只结束这次 HTTP 等待，不代替 OpenCode abort。

#### 2.2 / 2.6 事件、缓冲与并发

选择：**OpenCode SSE 用带 `seq` 的 WebSocket 事件帧上报。** 单帧超过 `worker_gateway_max_frame_bytes`（默认 256 KiB）时，不改走 HTTP，也不上传该事件正文。Agent 改发一条缺口帧，Nexus 写成 `astra.event_gap` 并触发 `refresh`。另一条「超限事件改存 HTTP 引用」的做法不采用，避免事件同时存在两条通道。

帧：

```json
{"type":"event","request_id":"evt_…","worker_instance_id":"wrk_…","environment_id":1,"session_id":"ses_…","epoch":4,"payload":{"seq":41,"directory":"/workspace","event":{"type":"session.status","properties":{}}}}
```

超限时 payload 是 `{"seq":41,"directory":"/workspace","dropped":true,"reason":"event_too_large","event_type":"session.diff"}`，没有 `event` 正文。

`seq` 从 1 起，按 `(worker_instance_id, epoch, directory)` 单调递增。新 epoch 不延续旧序号。重连后先对账，不补旧序号。

订阅粒度是 **每个 Worker、每个 epoch、每个 directory 一路**。同一个三元组重复订阅时返回现有读取任务，不第二路连接本地 `/event`。一个 Worker 可以同时有多个 directory。之前「每个 Worker 只准 1 路订阅」和「每个 directory 1 路」的冲突，按后者解决。HTTP 的 8 路上限不限制 directory 数量。

共享日志键是 `astra:worker-gateway:eventlog:{worker}:{epoch}:{directory}`，只保留最近 N 条，N 就是 `worker_gateway_event_queue_size`（默认 64）。memory 总线在进程内保存同一份；多进程对账必须用已配置的 Redis。健康提示仍是「仅单进程可用」。阶段 1 的 `_SocketLease.inbound_events` 不是消费出口。

消费者和各自的游标。游标带租约，默认 30 秒。浏览器流在响应仍被读取时续期；`recovery` 每个监督周期续期。租约到期的游标不再是活跃消费者，死标签页不能一直当最慢的一个。

| 消费者 | 游标键 |
| --- | --- |
| `recovery.watch_session` | `eventcursor:{worker}:{epoch}:{directory}:recovery:{task_id}` |
| 每一条浏览器 `native_events` | `eventcursor:{worker}:{epoch}:{directory}:browser:{stream_id}` |

两条规则共用这一个 N：

- 日志只留最近 N 条。游标已经落到保留窗口之外，就算缺口，发 `astra.event_gap`，不回放被裁掉的历史。
- 某个订阅上，最慢的未过期消费者未读条数达到 N 时，Nexus 发控制帧 `pause_events`（带 directory）。Agent 暂停读取该 directory 的本地 SSE，而不是再丢一条还能放进帧的事件。落后收回去之后发 `resume_events`。没有任何未过期消费者时发 `stop_events`，结束本地订阅并删掉这路日志。暂停和停止只影响这一路 SSE，不影响其他 directory，也不影响 pong 和取消。

同一个 Task 上，缺口触发的 `refresh` 正在进行时，后续缺口合并进这一次，不另起一趟对账。

浏览器输出保持 `data: {OpenCode 事件}\n\n`；全局流仍是 `data: {"directory","payload"}\n\n`。缺口是：

```text
data: {"type":"astra.event_gap","directory":"/workspace","from":12,"to":15}
```

不补造缺失事件，也不为了补洞新建 Session。`recovery` 见到缺口或订阅断开后做现有的有界 `refresh`：重读 Session、完整分页消息、问题和权限。事件只缩短等待，原生读取才是事实。对账结果只进 `apply_session_state()`。

旧 epoch 的事件帧直接丢弃，不写日志，不推进游标。

Agent 现在在 `worker_agent/connection.py` 的读循环里串行执行命令（约 206–219 行）。阶段 2 改成：读循环只处理心跳、pong、取消和「把 http / 事件订阅交给独立任务」。`http` 的 GET、本地 OpenCode 调用和 PUT，以及每个 directory 的 SSE 读取，都在独立任务里并发执行。读循环不被这些任务挡住，因此 pong 和取消不排队等大响应。

#### 2.3 / 2.9 / 2.12 首次发送、人工重试与 ACK 丢失

选择：**用原生消息核对，不在 Agent 上落盘去重账本。** 内存里的 `request_id` 记录只挡住同一进程的重复帧。它消失之后不能当作已执行或可重发的证据。

OpenCode 1.18.35（标签 `v1.18.35`）**不按 `messageID` 去重**。`packages/opencode/src/session/prompt.ts` 的 `createUserMessage` 到 `prompt`（约 635–1071 行）使用调用方给出的 `messageID`，没有就自己生成。它不先查询这个 id。用户消息要等 part 解析和插件 hook 之后才 `updateMessage`。`packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts` 的 `promptAsync`（约 311–329 行）把这次调用放进后台并立刻返回 204。因此 204 和「消息列表里还没有这条 id」都不能证明 POST 没发出去；列表里已经能看到这条 id，才证明已经落库。第二次 POST 同一个 `messageID` 会再次进入 `loop()`，不是一次无操作。Astra 在消息可见时绝不 POST。

`pending_message_id` 仍在调用离开 Nexus 之前，与 `pending_prompt` 同一事务提交。`in_flight` 与 `in_flight_since` 只表示 Nexus 已把这次 attempt 交出去。Agent 的 ACK 只表示帧被接受。新增 `pending_attempt`，以及这次 attempt 到 Worker `request_id` 的映射和 `body_fetched_at`。首次发送把 attempt 写成 1。

把现在的 `retry_submission` 拆成两个函数。`start()` 在约 715 行调用的是首次发送：那时 Session 刚创建，`start()` 已经拒绝已有 Session 或已有 pending 的任务。`send()` 也是首次发送。人工重试只由 `POST /tasks/{id}/retry-submission`（`workspace_routes.py` 约 514 行）调用。恢复、重连、调度、心跳、超时路径都不调用人工重试。

数据库里的 `expired` 只是 sweep 改了指令行。新 epoch 不会停掉旧 Agent 上已经开始的本地 POST。所以指令过期或 epoch 变化都不是「未发送」的证据。

人工重试的顺序：

1. 任务未结束；`pending_message_id`、`pending_prompt` 和到 `request_id` 的映射都在。
2. 先看 `in_flight_since`。未超过 `opencode_control_timeout_seconds` 就拒绝，此时不重置 `in_flight_since`。
3. 用映射找到 Worker 指令。没有映射就拒绝，因为无法证明这次 attempt 的下落。映射在、请求体从未被 GET：这是唯一可以视为未发送的证据。指令行即使还在 `pending`，只要正文没被拉取，就还没进本地 POST。
4. 请求体已经被拉取：结果未知。必须再等到 `body_fetched_at` 加上本地硬上限，再加一段落库余量。余量取 `opencode_control_timeout_seconds`。在这之前拒绝。时间到了之后，仍要由这一次人工请求显式确认，才进入下一步。到点不会自动 POST。
5. CAS 认领：`UPDATE ... SET pending_attempt = pending_attempt + 1, pending_prompt = :armed WHERE id = :task AND pending_message_id = :id AND pending_attempt = :expected`。`rowcount` 不是 1 就放弃。这一步提交后才放出行锁，并清掉旧的 `execution_stop_confirmed_at`。并发的两个人工重试只有一个能继续。
6. 用 `messages_page` 沿 `x-next-cursor` 读完整个消息列表。读失败、超时、Worker 离线或 epoch 失效：保持这次认领后的 `in_flight`，抛错，不调用 `_without_in_flight`。
7. 列表里有这个 `messageID`：只清 `in_flight`，不 POST，再交给 `refresh`。
8. 列表里没有，并且第 3 步或第 4 步的证据成立：用同一个 `messageID` POST 一次。这是唯一允许重发 Prompt 的路径。

首次发送不把「未拉取」当成重试条件。它在 POST 前用同一种 CAS 认领自己的 `pending_attempt`，写好 `request_id` 映射，避免并发双发。

重连只读取已绑定的 Session：`GET /session/{id}`、分页消息、`GET /question`、`GET /permission` 和现有 `session_tree`。不创建 Session，不调用人工重试。

| 证据 | 动作 |
| --- | --- |
| 完整分页里能看到 `pending_message_id` | 已落库。清 `in_flight`。不重发。交给 `refresh` / `apply_session_state()` |
| 指令已存，请求体从未被 GET，分页确认没有该 id，并且是人工重试的 CAS 赢家 | 视为未发送。用同一个 `messageID` POST 一次 |
| 请求体已被 GET，分页里仍没有该 id | 结果未知。先等本地上限加落库余量，再由人显式确认后才可 POST |
| 查询失败、超时、Worker 离线、epoch 过期 | 不重发，不清 `in_flight`。通信按 2.4 记为不可用 |
| OpenCode 已落库，Agent 在响应 PUT 之前退出 | 与第一行相同 |
| 只丢失 WebSocket 就绪通知，请求体还没被 GET | 保持预约。不重发 |

#### 2.4 / 2.8 故障分类、已迁移与恢复

| 种类 | 记录 | Task 业务状态 |
| --- | --- | --- |
| 通信中断：套接字断开、Worker 离线、数据通道超时、epoch 失效 | `runtime_connection=UNAVAILABLE`，`runtime_error`，事件 `RUNTIME_DISCONNECTED`。非终态 Session 记 `UNKNOWN` / `TRANSPORT_UNKNOWN`。不写 `execution_error` | 不变。走现有 `disconnected()` |
| 执行超时 | 现有 `SessionTerminalReason.TIMEOUT`，经 `apply_session_state()` | 按现有规则进入 WAITING |
| OpenCode 异常 | 现有 `execution_error` 与相应的 Session 终态理由 | 只经 `apply_session_state()`。不把 Task 写成 FAILED |

Gateway、Agent 和传输层不赋值 `Task.status`。`recovery.py` 断线调用 `disconnected()`。

已迁移环境断线后停留在通信恢复：标记不可用，等 Worker 重连，再按 2.3 核对。不打开 SSH 隧道，不跑 `_start_server`。`on_connection_lost()` 不调用 `on_process_exit()`，也不因为 WebSocket 断开重启健康的 OpenCode。

#### 2.5 / 2.10 占用

现有实现会提前释放：`project()` 按 RUNNING、WAITING 和 `pending_message_id` 重算 `current_task_count`（`lifecycle.py` 约 252–264 行），心跳在没有这条查询结果时把 `current_task_count` 写成 0（约 1655 行），调度按 `current_task_count < 1` 派单（`dispatcher.py` 约 51–55 行）。未确认停止的 `CANCELED` 因此会空出来。阶段 2 实现时先修这个 bug，再切传输。

占用只有一个谓词。投影、心跳、调度、`start`、`send`、维护和取消完成都调用它。`current_task_count` 只由这个谓词写出，心跳不得另写 0。调度用这个谓词选员工，不再单独用 `current_task_count < 1` 判断。

谓词只看已经认领或已经绑定的 Task：`claimed_at` 不为空、已有 Session、`pending_message_id` 不为空，或状态不是未认领的 `PENDING`。未认领的 `PENDING` 不占用员工，因此不会挡住 `dispatcher.py` 约 42–58 行去派这些任务。

一条已认领或已绑定的 Task 占用员工，除非下面之一成立：

- `status` 是 `SUCCEEDED`
- `status` 是 `CANCELED` 或取消正在进行，并且这次人工释放仍然对得上当前 Session 和 `pending_attempt`

`RUNNING` 和 `WAITING` 即使写着 `execution_stop_confirmed_at` 也继续占用。`FAILED`、绑定异常、`pending_message_id` 仍在，以及还没被有效人工释放确认的 `CANCELED`，都占用。套接字是否在线、Session 是否 `idle`、单条指令是否结束，都不释放。

`disconnected()`（`lifecycle.py` 约 1598–1614 行）会因为通信故障把非终态 Session 写成 `UNKNOWN`。这个状态不证明执行已经停止。

维护前保留第二道防线：该员工仍有 RuntimeSession 处于 `RUNNING`、`WAITING` 或 `UNKNOWN`，而且对应 Task 没有一份仍然有效的人工释放时，`reserve_operation` 拒绝。这道检查不代替谓词。

人工释放是单独入口，只由人调用。只接受 `CANCELED` 或取消正在进行的 Task。它记录操作人和原因，并绑定当时的 Session id 与 `pending_attempt`。不把 Task 改成 `SUCCEEDED`，不调用 `apply_session_state()`，也不发送 Prompt 或 abort。恢复、重连、调度、心跳和超时都不调用它。新的 attempt、显式重启或新 Session 都会清掉这份确认。确认被清掉或对不上当前 Session / attempt 时，任务继续占用。

#### 2.11 幂等身份与取消

相同 `request_id` 只有在 `worker_instance_id`、指令名、`payload` 和 `session_id` 都相同的时候才返回原行。任一项不同，包括一边是 `NULL`，都返回 409。

取消使用自己的 `request_id`。payload 里带 `target_request_id`，指向要取消的那次 `http`。取消指令的幂等比较包含这个 payload，所以同一个取消 `request_id` 重放返回原行；对同一目标再取消一次必须用新的 `request_id`。这样不会和「相同 request_id 不同 payload 即 409」冲突，也不会把取消误当成原来的 `http`。

取消的 HTTP 等待：Agent 中止本地 httpx，结束 PUT，其后的字节丢弃。旧 epoch 的 GET/PUT 返回 409。这次取消不调用 OpenCode 的 abort。Task 取消仍走现有的原生 `POST /session/{id}/abort`，那是另一条 `http` 指令。

#### 跨数据库与 Redis 的生效点

| 动作 | 以谁为准 |
| --- | --- |
| 授权执行 | 数据库。`WorkerInstance.epoch` 和 `worker_commands` 的状态、epoch 决定能不能 GET 正文和执行。Redis owner 只决定哪个进程可以发布就绪通知，不能单独授权。 |
| epoch 切换 | 数据库。认证时对 `WorkerInstance.epoch` 的条件更新是切换点。`set_owner` 的高水位只拒绝更旧的注册，不能把数据库 epoch 改回去。Redis owner 在这次提交成功之后写入。Redis 写入失败就结束会话，不以 Redis 里旧的 owner 继续发令。 |
| 提交上传 | 数据库上的两次检查。PUT 开始时核对指令 epoch 等于当前 `WorkerInstance.epoch`。最终 CAS 与 `apply_response`（`service.py` 约 508–518 行）一样，带上当前实例的 epoch 子查询：`UPDATE worker_commands SET status='succeeded' ... WHERE id=:id AND epoch=:epoch AND status IN ('pending','accepted') AND worker_instance_id = (SELECT id FROM worker_instances WHERE id=:worker AND epoch=:epoch)`。`rowcount` 为 1 才把这次 `upload_id` 的正文交给等待者。Redis 只暂存正文。CAS 失败只删除这次 `upload_id` 的键，不唤醒。 |

认领之后 epoch 变了：旧指令不再授权执行，Agent 不得开始那次本地 POST，新 epoch 不补投这条有副作用的指令。上传写到一半时 epoch 变了：后续块和带 epoch 子查询的最终 CAS 失败，只作废这次 `upload_id` 的正文，等待者看不到它，`Task.status` 不变。

#### 阶段 2 故障测试

实现时先覆盖占用被提前释放的回归，再覆盖下面十项。阶段 1 已有的通道测试不代替这些项。未认领的 `PENDING` 不占用员工，也要有一条回归，避免调度被自己的候选任务挡住。

1. **epoch 乱序。** 旧 epoch 的事件帧被丢弃，序号不前进。旧 epoch 的请求 GET 和响应 PUT 得到 409。`Task.status` 不变。
2. **双 owner。** 同一 epoch 的另一个 owner 不能注册，也不能发布。只有持有套接字的进程发出就绪通知。
3. **发布后崩溃。** 指令已经是 `published` 或 `uncertain` 时投递进程退出。有副作用的 `http` / `prompt` 不被再次发布。幂等 `GET` 只在同一 epoch 的租约到期后可以再投。
4. **消费者崩溃。** 帧已从 Redis 取出、响应尚未 PUT 完成时消费者退出。同一 epoch 的幂等指令在租约到期后可以再投。新 epoch 不读取旧列表。容量不永久占用。
5. **ACK 丢失。** 完整分页里已经有 `pending_message_id`，Agent 在响应 PUT 之前退出。重连看到该消息，不重发 Prompt，不新建 Session，`in_flight` 被清掉。之后的业务状态只来自 `apply_session_state()`。
6. **事件丢失对账。** 序号缺口或 `event_too_large`。消费方收到 `astra.event_gap`，`refresh` 重读 Session、完整分页消息、问题和权限。不新建 Session。
7. **认领后 epoch 切换。** 指令认领之后 `WorkerInstance.epoch` 增加。旧 GET/PUT 被拒绝，新 epoch 不补投这条有副作用的指令。
8. **上传中途 epoch 切换。** PUT 已经开始写正文，随后 epoch 变化。带子查询的最终 CAS 失败，等待者收不到这份正文，`Task.status` 不变。同时进行的另一次上传若已经 CAS 成功，失败的一方不得删掉它的正文。
9. **请求体拉取证据。** 指令已落库但从未 GET：人工重试可以视为未发送。已经 GET 而消息仍不可见：在本地上限加落库余量之前，以及没有新的人工确认时，不重发。
10. **过期事件游标。** 浏览器流断开后，它的游标过期，不再把该 directory 的 SSE 停在暂停。

### 阶段 3

本阶段只定契约，不改运行代码。`worker_channel=worker` 的日常文件浏览、Git 只读和上传在落地后不再打开 SSH，也不再读取 `ssh_password`。`worker_channel=ssh` 的现有 SFTP / `run_remote` 分支留到阶段 4，本阶段不删除。目录、worktree 和复制 `opencode.json` 已是阶段 2 的 `prepare_workspace`，这里不重做。

不新增第三种传输。WebSocket 仍是控制与事件；请求体和响应体仍是阶段 2 的 `GET /api/worker-gateway/data/{request_id}/request` 与 `PUT /api/worker-gateway/data/{request_id}/response`。不新增迁移，指令名是 `worker_commands.name` 上的新字符串。Worker Agent 只做本地文件系统和只读 Git，不识别 Task、Session 或业务状态。

行号对应当前树（阶段 2 验收 `3c14623`）。

#### 仍走 SSH 的调用点

已迁移环境在日常执行期还会因为下面这些点需要 SSH 密码。落地时只给 `worker_channel=worker` 换通道。

| 位置 | 现在 | 改法 |
| --- | --- | --- |
| `workspace_files.py:90-102` `validate_path` 的远程分支 | `open_session` 后 `sftp.normalize` | 发 `validate_path`。`ssh` 保留 SFTP |
| `workspace_files.py:72-78` `check_request_path` | `native_path` 属于 `_FILE_API`（`/file`、`/file/content`、`/file/status`、`/find/file`）时落入上面的 SSH | 这四个路径发同一条 `validate_path`。其余路径保持现有词法 `relative_path`，本来就不打开 SSH |
| `workspace_files.py:149-168` `upload` 的远程分支 | SFTP `mkdir` + `open(..., "wx")` | 发 `upload_file`。字节走数据通道 |
| `workspace_files.py:174-207` `materialize_task_attachments` | 调用 `upload` | 随 `upload` 的分支，不另做一条路径。调用方是 `lifecycle.py:608-618` |
| `workspace_changes.py:33-36` `_git` | `run_remote(shlex.join(["git","-C",workspace,*args]))` | 发 `git_readonly`。Agent 不接受 shell 字符串 |
| `workspace_changes.py:39-45` `workspace_head_commit` | 经 `_git` | 随 `git_readonly`。失败仍返回 `None`。调用方是 `lifecycle.py:600` |
| `workspace_changes.py:68-122` `collect_workspace_changes` | 经 `_git` | 随 `git_readonly`。异常仍返回 `{}` |
| `workspace_changes.py:149-165` `_working_text` 的远程分支 | SFTP `stat` + `read` | 发 `read_file` |
| `workspace_changes.py:180-222` `workspace_diff` | `validate_path` + `_git` + `_working_text` | Nexus 继续组装现有列表，三次调用分别换成上面的指令 |
| `workspace_routes.py:286` `POST /files/{filename}` | `upload` | 随 `upload_file` |
| `workspace_routes.py:348-353` 提示词里的 `data:` 附件 | `upload` | 随 `upload_file` |
| `workspace_routes.py:366-367` 提示词里的 `file:` 附件 | 已迁移环境只做词法 `relative_path`，不查符号链接 | 改为 `validate_path`，补上 SSH 路径已经有的真实路径约束 |
| `workspace_routes.py:412` diff 的目录覆盖 | `validate_path` | 随指令 |
| `workspace_routes.py:417-430` `GET /vcs/diff` 与 `/vcs/diff/raw` | `workspace_diff` | 随指令 |
| `workspace_routes.py:455-457` 代理前的路径检查 | 文件类路径因此打开 SSH，通过后才 `client.exchange` | 文件类改为指令。通过之后仍走阶段 2 的 OpenCode `http`，不在 Agent 里重写 `/file` |
| `workspace_routes.py:594` 与 `608-612` `GET /repo` | `validate_path(".")`，然后 `run_remote` 五次 git | 改为 `validate_path` 加 `git_readonly` |
| `workspace_routes.py:390` | 把库里的 `ssh_password` 抄到临时环境，供上面的 SSH 使用 | 已迁移环境的文件、Git、上传不再读这个字段。`ssh` 环境仍抄 |
| `session_connection.py:44` `resolve_environment` | 不分通道把 `stored.ssh_password` 抄到环境对象 | 已迁移环境的文件、Git、上传不读这个字段 |
| `session_connection.py:55` `resolve_runtime_session_environment` | 同上 | 同上 |

下面这些仍然使用 SSH，但不属于本阶段的日常文件 / Git / 上传。`ssh` 环境和阶段 4 的安装、探测、故障维护继续用它们：

| 位置 | 用途 | 阶段 |
| --- | --- | --- |
| `session_connection.py:84` | `ssh` 环境的 OpenCode 隧道。`worker` 的 `connect()` 已经不走这里 | 保持到阶段 4 |
| `session_connection.py:226` `_ensure_remote_workspace` | `ssh` 环境的目录准备。`worker` 已是 `prepare_workspace` | 保持到阶段 4 |
| `environment.py:67-100` `open_session` / `run_remote` | SSH 会话本身 | 被上面的旧分支继续使用 |
| `environment.py:199-244` | 远程环境测试和二进制版本 | 阶段 4 的健康检查 |
| `remote_provisioning.py:467` | 部署 SSH | 阶段 4 |
| `opencode_remote_server.py:90,160,344` | 隧道与远程 Serve | 阶段 4 |
| `opencode_remote.py:34` | CLI fallback | 不改 |
| `ssh_client.py` | Paramiko 实现 | 不改 |

落地之后，已迁移环境在任务启动、附件落盘、文件浏览、diff、仓库摘要和上传这些路径上不再调用 `open_session` 或 `run_remote`。

#### 指令

四条指令。payload 放在现有指令帧的 `data` 里，不含文件字节和 Git 标准输出。它们不进 `_handle_command` 的读循环（`connection.py:446-453`），也不占用阶段 2 的 8 路 OpenCode `http` 名额，也不新增数据库槽。Agent 用单独的任务表执行，信号量上限 4。套接字关闭时，这张表按 `http_tasks`（`connection.py:280-286`）同样取消。

WebSocket 指令结果只放结构化字段，编码后必须小于 `worker_gateway_max_frame_bytes`（默认 262144，即 256 KiB）。文件字节和 Git 标准输出一律走数据通道，结果里不内联。空的 Git 标准输出不发起 PUT，结果里 `size` 为 0。

这样定的理由：porcelain、`git show` 和 diff 没有可靠的「一定小于一帧」上界，20 MB 的上传也放不进帧。按大小再分一叉，Agent 上就会出现第三条隐式路径。256 KiB 是帧上限，用来约束结果对象，不用来决定正文走哪条通道。

`http` 的单次组装上限仍是 8 MiB（`data_channel.py` 的 `MAX_BODY_BYTES`）。`upload_file` 的请求体、`read_file` 和 `git_readonly` 的响应仍走同一对 GET/PUT，分块仍是 256 KiB（`MAX_CHUNK_BYTES`）。不提高 `http` 的 8 MiB，也不把浏览器已经公开的 20 MB 收成 8 MB，也不新增端点。

`read_file` 和 `git_readonly` 的正文是原始字节的 base64，写进现有的 UTF-8 文本块（`data_channel.py:143` 与 `161-179`）。`size`、`sha256` 和 20 MiB 上限都按编码前（即解码后）的原始字节计算。文本块的组装上限只放到这份 base64 的长度（20 MiB 原始字节约为 27 MiB），不按 utf-8 替换解码后的字符串计。Nexus 先做 base64 解码，再按 utf-8 `errors=replace` 得到文本，与 `ssh_client.py:302` 和 `workspace_changes.py:168` 一致。这样二进制 `git show` 的校验和就是原始字节，Nexus 也能自己重算。

`upload_file` 的 GET 按已落库的指令名返回原始字节：`Content-Type: application/octet-stream`，并带 `X-Astra-Sha256`。URL 仍是 `GET /api/worker-gateway/data/{request_id}/request`。`http` 的 JSON 正文不变。

| 指令 | WebSocket `data` | WebSocket 结果 | 数据通道 | 副作用 |
| --- | --- | --- | --- | --- |
| `validate_path` | `workspace`、`path` | `{relative}`。最后一级缺失也返回 | 无 | 幂等，同一 epoch 可在租约到期后重投；新 epoch 可以再执行 |
| `git_readonly` | `workspace`、`operation`，以及该操作需要的 `revision` / `path` / `baseline` / `file` | `{code, size, sha256}` | 非空 stdout 的原始字节以 base64 放入现有文本块。20 MiB、`size`、`sha256` 都按原始字节 | 只读。到达指令截止时间则杀掉 git，`code=124`，空输出 |
| `read_file` | `workspace`、`path` | `{size, sha256, missing}` | 文件存在时把原始字节的 base64 放入现有文本块。20 MiB、`size`、`sha256` 都按原始字节 | 同上，只读 |
| `upload_file` | `workspace`、`filename`、`size`、`sha256` | `{path}` | GET 原始请求体，上限 20 MiB | 有副作用。离开 `unpublished` 后不重投，不自动重发。套接字关闭时取消 |

错误码写在指令行的 `error_code` 上。Nexus 把它转回现在这些中文异常，浏览器仍走现有 `error_response`：

| `error_code` | 对应现在的异常 |
| --- | --- |
| `path_forbidden` | `PermissionError("不允许访问此路径")` |
| `path_outside` | `PermissionError("路径不属于此任务 Workspace")` |
| `symlink_escape` | `PermissionError("符号链接指向任务 Workspace 之外")` 或 `PermissionError("上传目录越界")` |
| `invalid_name` | `ValueError("文件名无效")` |
| `too_large` | `ValueError("文件不能超过 20 MB")` 或 `ValueError("Diff 文件不能超过 20 MB")` |
| `checksum_mismatch` | `ValueError("上传校验和不匹配")` |
| `invalid_revision` | `ValueError("Git 修订无效")` |
| `unsupported_operation` | `ValueError("不支持的 Git 操作")` |
| `io` | 打开或写入失败，以及 `openat2` 的 `ENOSYS` 或 seccomp 造成的 `EPERM` |
| `timeout` | `git_readonly` 在指令截止时间杀掉 git，返回 `code=124` 和空 stdout |
| `offline` / `epoch_conflict` | 沿用阶段 1/2，不新解释 |

`read_file` 找不到文件时不报错：`missing=true`、`size=0`，Nexus 得到空字符串。这是 `workspace_changes.py:157-158` 现在的 SFTP 行为。

`git_readonly` 的 `operation` 是闭集。Agent 按表自己拼 argv，每条前面固定加 `-c core.fsmonitor=false`，不接受调用方传入的 `-c`。工作目录是用允许根的 fd 打开的 workspace，环境使用 `child_environ()`。git 自己会再次解析路径，这和现在的 SSH 是同一窗口。Nexus 等待的是 `worker_gateway_command_timeout_seconds`（`settings.py:63`，默认 30 秒，上限 600 秒），请求暂存大约在截止时间加派发租约后过期。Agent 在该指令的截止时间杀掉 git，返回 `code=124` 和空输出，不用 `opencode_timeout_seconds`。`revision` 只能是字面量 `HEAD` 或 4–64 位十六进制。`baseline` 只能是同样的十六进制，拼进 `{baseline}..HEAD` 这一个参数。路径参数先过与 `validate_path` 相同的词法规则。不接受 `add`、`commit`、`push`、`reset`、`checkout`、`clean` 或写 `config`。

| `operation` | argv | 现在的调用 |
| --- | --- | --- |
| `head` | `rev-parse HEAD` | `workspace_head_commit`，`GET /repo` |
| `inside_work_tree` | `rev-parse --is-inside-work-tree` | `collect_workspace_changes`，`workspace_diff` |
| `git_common_dir` | `rev-parse --path-format=absolute --git-common-dir` | `GET /repo`，只用于显示名 |
| `branch` | `branch --show-current` | `GET /repo` |
| `status_porcelain` | `status --porcelain=v1 -z --no-renames --untracked-files=all` | 变更摘要，`GET /repo` |
| `origin_url` | `config --get remote.origin.url` | `GET /repo` |
| `rev_list` | `rev-list --reverse --max-count=200 {baseline}..HEAD` | `collect_workspace_changes` |
| `diff_name_status_range` | `diff --name-status --no-renames -z {baseline}..HEAD` | `collect_workspace_changes` |
| `diff_numstat` | `diff --no-ext-diff --no-textconv --no-renames --numstat -z {revision} -- {path}` | `workspace_diff` |
| `ls_files_others` | `ls-files --others --exclude-standard -z -- {path}` | `workspace_diff` |
| `show_file` | `show {revision}:{file}` | `workspace_diff` 的 before。读的是对象库，不是工作区符号链接 |
| `diff_patch` | `diff --no-ext-diff --no-textconv --no-color --no-renames {revision} -- {file}` | `workspace_diff` |
| `diff_name_status_file` | `diff --no-renames --name-status -z {revision} -- {file}` | `workspace_diff` 的状态 |

`/file`、`/file/content`、`/file/status`、`/find/file` 在 `validate_path` 通过之后，仍由本机 OpenCode 经阶段 2 的 `http` 返回。OpenCode 会自己再解析一次路径，和现在 SSH 检查之后再读文件是同一窗口，这里没有放宽。浏览器看到的仍是现有过滤后的 OpenCode 正文。不在 Agent 里重做这些接口。`/find` 和 `/find/symbol` 保持现在的词法检查。

同一 `request_id` 的重放返回已存储的指令，`upload_file` 不写第二个文件。payload 任一字段不同则 409。一次新的上传使用新的 `request_id` 和新的 12 位十六进制文件名，不覆盖已有文件。

#### 安全边界

workspace 本身从允许根（`ASTRA_WORKER_WORKSPACE_ROOT`，或该根父目录下的 `.astra-tasks`）的目录 fd 用 `openat2` 打开，标志为 `RESOLVE_BENEATH | RESOLVE_NO_MAGICLINKS`。不用 `realpath` 得到字符串再单独 `open`。允许范围与 `worker_agent/workspace.py` 的 `_require_allowed` 相同。`openat2` 返回 `ENOSYS`，或 seccomp 造成的 `EPERM`，指令失败为 `io`，不用字符串路径打开。

`validate_path` 先从 workspace 的 fd 用 `openat2(O_PATH, RESOLVE_BENEATH|RESOLVE_NO_MAGICLINKS)` 打开完整相对路径。这样最后一级若是指向外部的符号链接（例如 `link → /etc/passwd`），会得到 `EXDEV` 或 `ELOOP`，返回 `symlink_escape`，不会放行。`/file*` 只靠这次检查，必须在这里封住 SSH `sftp.normalize` 已经封住的逃逸。只有完整路径返回 `ENOENT` 时，才用同样的 `openat2` 打开父目录；父目录能打开就返回 `{relative}`。`workspace_changes.py:207` 会对已删除的文件调用它，SSH 的 `sftp.normalize` 和本地 `resolve(strict=False)` 都接受缺失的最后一级。`ENOSYS` 或 seccomp 造成的 `EPERM` 是 `io`。

`read_file` 和 `upload_file` 的打开本身用 `openat2`，这一次打开是原子的。写最终分量时再加 `O_CREAT | O_EXCL | O_NOFOLLOW`，模式 `0o600`。`uploads` 目录用 `O_DIRECTORY | O_NOFOLLOW` 打开；尚不存在时从 workspace 的 dirfd 创建。把 partial 换成目标名时使用 `renameat2(RENAME_NOREPLACE)`。`/file*` 由 OpenCode 再解析，Git 由 git 再解析，这两处和 SSH 现状是同一窗口。

词法拒绝在打开之前做一次，规则与远程 `relative_path`（`workspace_files.py:35-66`）相同：NUL、反斜杠、`..`、路径分量恰好为 `.git`（区分大小写，不用本地的 `casefold`）。Nexus 侧保留现在的检查，Worker 再做一次，不信任调用方。

对照现在的 SSH 实现。Worker 列不得比 SSH 列更宽。标成更严的两项是既有选择，不是放宽。

| 限制 | SSH / 当前远程实现 | Worker |
| --- | --- | --- |
| NUL、反斜杠 | `relative_path` 拒绝 | 同样拒绝 |
| `..` 与分量 `.git` | 远程分支区分大小写 | 同样。不改用本地 `casefold` |
| 绝对路径 | `PurePosixPath.relative_to(workspace)` | 同样，并且 workspace 从允许根的 fd 用 `openat2` 打开 |
| 相对符号链接留在 workspace 内 | `sftp.normalize` 之后必须等于根，或以 `根/` 开头 | `RESOLVE_BENEATH` 仍可读取 |
| 指向 workspace 内的绝对符号链接 | `sftp.normalize` 接受，只要目标仍在根下 | `RESOLVE_BENEATH` 拒绝。这比 SSH 更严 |
| 符号链接逃出 workspace | normalize 后不在根下则拒绝 | `EXDEV` / `ELOOP` 为 `symlink_escape` |
| 已删除文件的最后一级 | normalize 与 `resolve(strict=False)` 接受缺失 | 先打开完整路径；只有 `ENOENT` 时再打开父目录，父目录能打开才返回 `{relative}` |
| 最后一级符号链接指向外部 | normalize 后不在根下则拒绝 | 打开完整路径得到 `EXDEV` / `ELOOP`，为 `symlink_escape`。不能只打开父目录就放行 |
| 上传文件名 | 必须等于 `PurePosixPath(filename).name`，无反斜杠和 NUL | 同样 |
| 上传大小 | `MAX_UPLOAD` = 20 MiB；路由在 413 处先拒绝 | Nexus 与 Worker 都按原始字节 20 MiB 拒绝 |
| 上传目录 | `uploads/{12 hex}-{name}`；`normalize(folder)==folder`；`sftp.open(..., "wx")` | 同样的相对路径。目录本身不能是符号链接。`O_EXCL` 且 `RENAME_NOREPLACE`，不覆盖 |
| 上传模式 | SSH 不 `chmod`，随 umask。本地 Unix 是 `0o600` | Linux Worker 写 `0o600`。这比 SSH 更严 |
| 返回路径 | 远程是 `{workspace}/{relative}` 的 posix 字符串（`workspace_files.py:171`） | 同样的字符串 |
| diff 单文件 | `stat` 与读入都不得超过 20 MiB；多读 1 字节再判断 | `read_file` 按原始字节同样封顶。正文是这些字节的 base64；Nexus 解码后再 utf-8 `replace` |
| 缺失文件的内容 | 返回空字节 | `read_file` 为 `missing=true`，Nexus 使用空字符串 |
| Git 参数 | 固定 argv，但是整串 shell 交给 SSH | 只允许上表，并固定加 `-c core.fsmonitor=false`。`--no-ext-diff`、`--no-textconv`、`--no-renames`、porcelain v1 `-z`、`--untracked-files=all`、`rev-list --max-count=200` 都保留 |
| Git 环境 | SSH 远端的登录环境 | `child_environ()`，继续去掉 `ASTRA_`、token、key |
| Git stdout | 无字节上限，超时随 `opencode_timeout_seconds` | 原始字节上限 20 MiB。超过则 `too_large`。到达指令截止时间杀掉进程并返回 `code=124`、空输出。这比 SSH 更严 |
| 校验和 | 上传路径没有 | `sha256` 按原始字节。上传比对 GET 到的字节，不一致则不打开文件。文件和 Git 响应的 `sha256` 也是原始字节，Nexus 对 base64 解码结果重算 |
| 浏览器写入面 | `POST /files/{filename}` 和提示词 `data:` 附件 | 不增加删除、改名、chmod |
| 暂存 | SSH 直接写最终名 | 见下一节。Redis 暂存沿用阶段 2：失败只删除本次 `upload_id` |

暂存有两处。

Redis 上的请求体和响应体沿用阶段 2：失败、epoch 冲突和重复成功都只删除这一次的键。`http` 的 8 MiB 与槽位规则不改。Gateway 仍只在最终更新的 `rowcount` 为 1 时唤醒等待者。Agent 发出结果后没有确认帧（`connection.py:453`，`service.py:596-630`），所以 Gateway 的 CAS 失败不能再通知 Agent 去删文件。

Worker 本地的暂存名是 `uploads/.partial-{request_id}`。每个连接有一个 `threading.Event`（`closed`）。`run_session` 的 `finally` 里把它 `set`；断开清理不改 `self.epoch`（`connection.py:279-286`），所以不能只看 epoch。顺序是：GET 并按原始字节核对 `size` 与 `sha256`；在阻塞函数里、创建 partial 之前同时检查 `closed` 和 `self.epoch`；在 `uploads` 的 dirfd 上以 `O_EXCL|O_NOFOLLOW|0o600` 创建 partial；写完并 `fsync`；rename 之前再同时检查 `closed` 和 `self.epoch`；然后 `renameat2(RENAME_NOREPLACE)` 到最终名。`to_thread` 里的阻塞函数取消不了，所以这两次检查做在函数内部。任一次 `closed` 已置位或 epoch 已经变化，就不创建或不改名，并删掉已经存在的 partial。套接字关闭时取消这条上传任务。rename 之前的失败删除 partial。

rename 已经完成后，文件留在 `uploads/`，模式 `0o600`，名字是随机的。CAS 失败、等待者没被唤醒、或者进程在 rename 之后退出，都留下这个孤儿文件，不自动重发，也不再删它。人可以再次上传，那是新的 `request_id` 和新文件名。

残留 partial 的扫描在 Agent 启动时执行，只覆盖 `{允许根}/*/uploads/.partial-*` 和 `{允许根父目录}/.astra-tasks/*/uploads/.partial-*`。扫描不跟随符号链接。指令 `finally` 只删除本次尚未改名的 partial。

#### 浏览器契约

URL、方法和响应形状保持不变：

| 接口 | 响应 |
| --- | --- |
| `GET /api/tasks/{id}/workspace` | 现有 workspace JSON |
| `POST /api/tasks/{id}/files/{filename}` | `{"path": path}`。超过 20 MB 仍是 413 |
| `GET/POST/PATCH/DELETE /api/tasks/{id}/opencode/{session_id}/{path}` | 现有过滤规则。`/vcs/diff` 仍是 `{file, patch, before, after, additions, deletions, status}` 的列表。`/vcs/diff/raw` 仍是 `text/x-diff` |
| `GET .../global/event` 与 `.../event` | `text/event-stream`，`Cache-Control: no-cache`，`X-Accel-Buffering: no`。`data:` 行格式不变 |
| `GET /api/tasks/{id}/repo` | `{name, branch, commit, dirty, changes, task_changes}`。git 非零仍变成空字符串。`status_porcelain` 得到 `too_large` 时 `dirty` 为 true，不能把这次失败当成空字符串而得到 `dirty=false` |
| 提示词附件 | `data:` 仍改写成 file URI；`file:` 仍必须落在任务 workspace |

`/file*` 的正文仍是 OpenCode 的正文，只是路径检查不再经过 SSH。

#### 离线、重连和 Task 状态

只读指令（`validate_path`、`git_readonly`、`read_file`）没有本地副作用。同一 epoch 的派发租约到期后可以重投。新 epoch 可以重新执行，因为它们不修改工作区。旧 epoch 的迟到结果仍不能覆盖新行。

`upload_file` 有副作用。离开 `unpublished` 之后不重投，不自动重发。套接字关闭时取消这条任务，并在该连接的 `closed` 事件上 `set`。阻塞函数内部在创建 partial 之前和 rename 之前同时检查 `closed` 和 `self.epoch`；任一不满足就不再创建或改名。rename 完成后的 `0o600` 随机名文件可以留下。Gateway 只在 `rowcount` 为 1 时唤醒等待者，CAS 失败不要求 Agent 删除该文件。人再次上传才会产生新文件。

这些失败都不写 `Task.status`，也不调用 `apply_session_state()`。Gateway 和 Agent 不认识 Task。调用方保持现在的异常政策：`workspace_head_commit` 失败得到 `None`，`collect_workspace_changes` 得到 `{}`，diff、上传和路径错误变成现有 HTTP 错误。`start()` 里的基线提交和附件落盘发生在创建 Session 之前；通信失败仍走 `lifecycle.py:730` 之后的现有处理，不把这种失败归类成 `OpenCodeExecutionError`，因此不会由此把 Task 投影成 `WAITING`。已迁移环境在这些调用失败时不打开 SSH 隧道。

重连仍不新建 Session，也不重发 Prompt。本阶段的指令不是 Prompt。

#### 模型映射（已取消）

公司网关已由用户验证可用。阶段 3 不给 `opencode/*` 增加 `direct_model` 路径，也不改 `LINUX_REMOTE` 的模型映射或 Gateway 的路由、密钥和供应商配置。部署保持现有动作：把网关 provider 写入 `opencode.jsonc`（`remote_provisioning.py` 与通道切换里的 `astra-gateway` 配置）。免费模型的验证由用户在本机完成。

#### 实现时要覆盖的测试

落地时再写，本设计不附带代码。至少包括：已迁移环境的 `validate_path`、`upload`、`_git`、`_working_text` 和 `GET /repo` 不调用 `open_session`，也不读 `session_connection.py:44` 与 `:55` 抄来的密码；`ssh` 环境仍调用；删除文件的 diff 在完整路径 `ENOENT` 且父目录能打开时仍返回该变更；最后一级符号链接指向外部时 `validate_path` 是 `symlink_escape`；相对符号链接留在 workspace 内仍可读取；指向 workspace 内的绝对符号链接被拒绝；逃出 workspace 的符号链接是 `symlink_escape`；`ENOSYS` 与 seccomp `EPERM` 是 `io`；校验和不匹配时不创建文件；`O_EXCL` / `RENAME_NOREPLACE` 不覆盖；Agent 启动时 partial 只扫 `{根或 .astra-tasks}/*/uploads/.partial-*` 且不跟随符号链接；rename 之后的 `0o600` 孤儿在 CAS 失败时保留，等待者只在 `rowcount` 为 1 时被唤醒；创建 partial 前和 rename 前同时检查 `closed` 与 epoch，套接字关闭而 epoch 未变时不创建文件；同一 `request_id` 不写两次；枚举之外的 Git 操作被拒绝；git argv 固定带 `-c core.fsmonitor=false`，调用方传入的 `-c` 被拒；git 在指令截止时间被杀掉并返回 `code=124` 与空输出；`/repo` 的 `status_porcelain` 超限时 `dirty=true`；文件和 Git 响应的 base64 按编码前的原始字节计算 `size` 与 `sha256`，Nexus 再做 utf-8 `replace`；上述浏览器响应字段不变；指令失败不修改 `Task.status`；只读指令可在租约到期后重投，`upload_file` 不重投；这四条指令使用独立任务表和上限 4 的信号量，套接字关闭时取消，不占 8 路 `http` 槽，也不写数据库槽。

### 阶段 4

本节是阶段 4 的实现约定。本轮只写设计，不写运行代码。产品尚未发布，不保留 `worker_channel=ssh` 这条执行路径，也不保留反向隧道。`ssh_password` 按已拍板的选项 2 继续留在环境行上，安装成功后不清空。空库 `alembic upgrade head` 仍须能跑到当前 head。不新增迁移。

硬约束不变：云端机器不开入站业务端口；OpenCode 只听 `127.0.0.1`；重连不新建 Session、不重发；通信失败不改 `Task.status`，`apply_session_state()` 仍是唯一投影点；Worker Agent 没有业务状态机；不改 Gateway 的路由、密钥、供应商和模型映射；不改 AgentScope 与 LLM Wiki 的业务设计。

阶段 2 已经让标记为 `worker` 的环境不再打开到 8110/8201 的反向隧道，并在打标记前写入内网地址、由 Worker 探测。阶段 3 已经让该标记上的文件、Git 和上传离开 SSH。阶段 4 删掉剩下的执行期 SSH，包括反向隧道本身。Migration Plan 里「未标成 `worker` 的环境继续走 SSH」到本阶段为止：未标记的远程环境直接失败，不打开 SSH。通道按已拍板的选项 A，密码按已拍板的选项 2。端口继续用环境上的 `opencode_server_port`（默认 4096）。

#### 已拍板

**通道 A。** 去掉 `worker_channel=ssh` 这条执行路径。远程执行只留 `worker`。反向隧道、`connect()` 的 SSH 分支、文件 / Git / 上传的 SSH 分支、健康失败后的 `_start_server`，都在本阶段删除。`worker_channel` 列保留，不迁移：`worker` 表示可以远程执行；`ssh` 或任何其他值只表示还没安装完成，`connect()` 直接失败，不打开 SSH。切换接口收成单向标记：安装成功后做阶段 2 那次探测、无占用受控重载、核对生效配置，然后写成 `worker`。失败保持未标记，不因此打开 SSH。LOCAL 不经过这条通道。保留两条远程执行路径的选项不采用。

选项 A 对三处现有代码的影响：

- `opencode_remote.py` 的 `RemoteOpenCodeExecutor`（`:34` `open_session`）是 CLI fallback。运行时代码没有 import 它；任务启动走 `session_connection.connect()`。本阶段不改这个模块，也不得让 `connect()` 或 `start()` 调用它。阶段 5 可以再删确认无调用方的死代码。
- LOCAL 仍走 `session_connection.py:68-72` 的 `LocalOpenCodeServerExecutor` 和本地文件 / Git。删除远程 SSH 不改变本地环境。
- 部署不再把 SSH 当成执行通道。一次管理员触发的 SSH 只负责安装；装完并标记 `worker` 之后，日常执行不读 SSH 密码。库里还标着 `ssh` 的开发数据不能再执行，要先走安装。产品未发布，接受这一点。

**SSH 密码，选项 2。** `ssh_password` 继续存在环境行上，安装成功后不清空，不新增迁移。环境写入接口保持现在的行为：非空密码写入该列，空白更新保留原值（`routes.py:328-329`），响应里仍然只有 `has_ssh_password`。日志继续打码。

日常路径不读这列。`session_connection.py:44`、`:55` 和 `workspace_routes.py:386` 不再把 `ssh_password` 抄到环境对象。`connect()`、任务启动、健康检查、文件、Git、上传、目录准备和环境测试不调用 `open_session`。

`open_session` 必须由调用方传入维护锁的 `operation_id`。它先核对这个操作仍属于该环境且 `state` 仍是 `RUNNING`，通过之后才读取 `ssh_password`。核对失败就拒绝，并且不读这列。漏掉的调用方因此安全失败。`run_remote` 走同一个参数。维护请求体不另带密码。`routes.py:328-329` 的空白更新保留旧密码，`remote_provisioning.py:111` 仍要求环境行上已经有密码，`bootstrap.py:116` 的种子仍可写入该列。

`POST /api/employees/{id}/environment/{action}`（`environment_routes.py:15`，`main.py:90` 注册）除了数据库会话，还要使用与 Worker Gateway 相同的 `require_admin`（`worker_gateway/routes.py:52`）。没有管理密钥的请求返回 401，不打开 SSH。

**OpenCode 端口。建议维持 4096，此项不再另做选项。** 各端口现在的用途：

| 端口 | 现在的用途 |
| --- | --- |
| 4096 | 环境列 `opencode_server_port` 的默认值（`models.py:95`），也是平台设置 `settings.py:106` 和 Agent 本机 OpenCode 的默认监听。控制机上的平台 Serve 用它 |
| 4097 | 控制机助手 OpenCode（`settings.py:171` `assistant_opencode_port`）。本地员工环境不得占用 4096 或 4097 |
| 4296 | 不是代码默认值，也不是第二个监听。部署指南把远端环境列写成 4296；`test_api.py` 只验证这一列可以存下 4296 |
| 8110 | Astra Gateway。Worker 出站访问。阶段 2 的迁移门探测这个配置地址 |
| 8201 | 图书馆 MCP。Worker 出站访问。同一道迁移门 |
| 8202 | Task MCP，给 AgentScope 工具用。不进 OpenCode 配置 |
| 19828 | LLM Wiki。`settings.py:142` 默认 `http://127.0.0.1:19828/api/v1`，由独立客户端访问。与 OpenCode 无关 |

4096 与 4296 在两台机器上各自绑 `127.0.0.1`，端口号不会撞。部署指南里的 4296 是反向隧道时期避免和主控机端口表混淆的写法。直连内网之后不需要第二个默认端口。新安装继续用该环境的 `opencode_server_port`，默认 4096。管理员仍可在这一列里改成别的端口，Agent 和 OpenCode 跟着这一列走，仍然只绑 `127.0.0.1`。不把 4296 写成新的默认值。

#### 执行期 SSH 调用点

目标：SSH 只用于安装 Worker Agent、基础环境和故障维护。Worker 在线时，日常健康检查和显式重启都在 Agent 本地执行。

| 位置 | 现在 | 本阶段 |
| --- | --- | --- |
| `opencode_remote_server.py:48-70` `ensure_remote_mcp_tunnel` / `ensure_remote_gateway_tunnel` | 为 8201 / 8110 准备反向隧道，或在设置了 public URL 时直接返回该地址 | 删 |
| `:73-109` `_ensure_service_tunnel` | 进程内字典 `_mcp_tunnels`，`open_reverse_tunnel` | 删。API 与 Celery 本来就不能共享这份字典 |
| `:112-122` `close_remote_mcp_tunnels`；`main.py:67-71` | 进程退出时的清理钩子，不创建隧道 | 删函数和这处调用 |
| `:155-159` | `worker` 只做 `WorkerOpenCodeClient.health()` | 保留。这里不启动、不杀掉 OpenCode |
| `:160-180` | `ssh`：`open_session`、到 OpenCode 端口的 `open_tunnel`、两条反向隧道；健康失败则 `_require_workspace_config` + `_start_server` | 删 |
| `:203-253` `_require_workspace_config`、`_start_server` | SSH 上检查配置，cwd 匹配就 `kill` 再 `nohup` | 删。显式重启不得复用这段脚本 |
| `:335-359` `test_remote_server` | SSH 本地转发后做健康检查；Serve 不在也算通过 | 删 |
| `ssh_client.py:98` `SSHTunnel`、`:153` `SSHReverseTunnel`、`:222-277` `open_tunnel` / `open_reverse_tunnel` | 本地转发和反向转发 | 删。LLM Wiki 的隧道是 `install_nexus.sh` 里的 `ssh -L`，不依赖这两个类 |
| `ssh_client.py:200-220`、`:279-299` `connect` / `open_exec` / `run_command` | Paramiko 会话和远程命令 | 保留，只给安装和故障维护 |
| `session_connection.py:44`、`:55` | 两个 resolver 无条件抄 `stored.ssh_password` | 删这两次拷贝 |
| `:68-78` | LOCAL 启动；`worker` 的 `connect()` 在 `start=True` 时只做健康检查 | 保留 |
| `:79-92` | `ssh` 的 `connect()`：`start=True` 走上面的 SSH 连接，否则 `open_session` + `open_tunnel` | 删。`LINUX_REMOTE` 不是 `worker` 时直接失败，不打开 SSH |
| `:226` `_ensure_remote_workspace`，以及 `:264-267`、`:287-288` 的调用 | `ssh` 环境用 `run_remote` 准备目录 | 删这些调用。`worker` 已走 `:260-263`、`:285-286` 的 `prepare_workspace` |
| `environment.py:67-80` `open_session` | 用环境行上的密码打开 SSH | 改：必须传入 `operation_id`，核对仍是 `RUNNING` 之后才读密码 |
| `:82-102` `run_remote` | 任意调用方都能打开 SSH | 改：日常调用方删除后，只留维护入口 |
| `:104-107`、`:131-196` | LOCAL 的 `test()` | 保留 |
| `:198-256` `_test_remote` | `POST /api/employees/{id}/environment/test`（`routes.py:356`）用 SSH 测连接、二进制和 `test_remote_server` | 改：`worker` 在线时由 Agent 做本机健康检查和版本；离线时报告离线。这条接口不打开 SSH |
| `workspace_files.py:95-107`、`:159` | `ssh` 的 SFTP 校验和上传。`worker` 已提前返回 | 删远程分支。LOCAL 保留 |
| `workspace_changes.py:37-39`、`:159-174` | `ssh` 的 `run_remote` git 和 SFTP 读文件 | 删远程分支。LOCAL 保留 |
| `workspace_routes.py:386-387` | 原生代理把 `ssh_password` 和 `worker_channel` 抄到临时环境 | 删密码拷贝。通道仍以环境行为准 |
| `workspace_routes.py:618-621` | `GET /repo` 在非 worker 时 `run_remote` | 删这段远程分支。LOCAL 与 `worker` 保留 |
| `remote_provisioning.py:111` | 部署要求库里已有 host、用户名、密码 | 保留这三项都在环境行上。只有这次维护在锁内读取密码。安装成功后不清空 |
| `:171` | 日志打码列表含密码 | 保留打码 |
| `:208-224` `_native_idle` | SSH `open_tunnel` 看 OpenCode 是否忙 | 改：在线时用 Agent 本机检查；离线安装时在远程 shell 里看 `127.0.0.1` 端口，不建隧道 |
| `:286-307`、`:345-354` | 写 `~/.config/opencode/opencode.json`；`ssh` 时地址来自反向隧道 | 改：始终写配置里的内网 Gateway 与 MCP。已有 `opencode.jsonc` 时仍拒绝覆盖（`:288-289`，`channel_switch.py:65-67`），由人合并。不另换一种配置格式 |
| `:356-413` `_restart` | `worker` 只做健康检查；`ssh` 打开隧道并 `_start_server` | 改：见下面的重启规则 |
| `:467` `run()` | 部署用 `open_session` | 保留为安装和故障维护的唯一 SSH 入口 |
| `worker_channel.py:26-33` | 缺行或非法值当成 `ssh` 传输 | 改：只有 `worker` 是执行通道；其他值是未安装 |
| `:35-131` `mark_worker_channel` | 无占用、探测、受控重载、核对生效配置，然后写成 `worker` | 保留，作为安装完成时的单向标记 |
| `:198` `_release` | 失败时写回 `worker_channel=ssh` | 改：可以仍写这个字符串，但它只表示未安装。写回它不得打开 SSH。不新增第三种取值 |
| `worker_gateway/routes.py:136-145` 与 `python -m app.runtime.worker_channel` | 管理员标记通道 | 保留为这一次单向标记的入口，不再表示切回 SSH |
| `worker_gateway/routes.py:167-170` | 普通指令接口拒绝 `switch_channel`，403 `maintenance_command` | 保留。显式重启指令同样只能从维护入口下发 |
| `channel_switch.py:50-59`、`:143-188`、`:237-255` | Worker 探测配置地址；`systemctl restart` 或核对命令行后 SIGTERM | 保留给无占用的显式维护。WebSocket 断开不得调用 |
| `supervisor.py:12-13`、`connection.py:218` | `on_connection_lost()` 是空操作 | 保留 |
| `lifecycle.py:636-639` | `LINUX_REMOTE` 一律 `gateway_model`，得到 `astra-gateway/<末段>` | 保留，不改 |
| `models.py:94`、`:100`；`routes.py:328-329` | `ssh_password` 可空；空白更新保留原值；`worker_channel` 默认 `ssh` | 保留列、写入行为和默认值。安装成功后不清空密码。`ssh` 默认值表示未安装，不是传输。不新增迁移 |
| `bootstrap.py:116` | 种子数据可以写入密码 | 保留。日常路径不读它 |
| `opencode_remote.py:34` | CLI fallback 的 `open_session` | 保留模块。执行路径不调用 |
| `app/llm_wiki.py`、`settings.py:141-145` | LLM Wiki 独立 HTTP 客户端 | 保留，不改 |
| `settings.py:136` | 未设置 MCP 公网地址时改走反向隧道 | 改：没有隧道回退。地址用已配置的内网 MCP |

`RemoteOpenCodeServerExecutor`（`opencode_remote_server.py:278`）不在任务启动链上，只有测试构造它。删掉连接对象的 SSH 分支之后，它不能再打开隧道。

#### Gateway 与图书馆 MCP

不改 Gateway 的业务设计，也不改模型映射。公司网关已验证可用。部署写进 OpenCode 全局配置的仍是现有 `astra-gateway` provider：`baseURL` 为 `settings.remote_gateway_local_url`，MCP 为 `settings.mcp_resource_server_url`。阶段 2 的切换已经对 `worker` 使用这两个地址（`remote_provisioning.py:350-351`，核对在 `worker_channel.py:174-177`）。阶段 4 让安装路径和这个标记用同一对地址，不再写 `http://127.0.0.1:8110` 或 `http://127.0.0.1:8201` 这种隧道回环。

`remote_gateway_public_url` 和 `mcp_public_url` 只为跳过反向隧道而存在。隧道删除之后，安装和标记不再读这两个字段，地址只取上面这一对。

`settings.py:127` 的 `remote_gateway_local_url` 和 `:139` 的 `mcp_resource_server_url` 默认是 `127.0.0.1`。控制机上的图书馆 MCP 仍只听回环（`install_nexus.sh` 写入 `ASTRA_MCP_HOST=127.0.0.1`）。部署拒绝这两个配置地址里的回环主机名。Worker 要访问的是管理员配置的内网地址。Agent 的 systemd 单元写入 `ASTRA_REMOTE_GATEWAY_URL`、`ASTRA_MCP_RESOURCE_URL`，以及与该环境 `opencode_server_port` 一致的 `ASTRA_WORKER_OPENCODE_URL`（`http://127.0.0.1:<端口>`）。不改 Gateway 的路由、密钥、供应商和模型映射。

可达探测仍是阶段 2 的那一组检查：只探测配置地址，无占用时受控重载，生效配置一致才写成 `worker`。这次检查在 deploy 自己已经写下的 `RUNNING` 操作里完成。`mark_worker_channel` 会再调用 `require_no_operation` 并另拿一把锁（`worker_channel.py:55`），所以 deploy 不调用它，也不先释放自己的锁再重取。探测失败或生效配置不一致则保持未标记，远程执行直接失败，不打开 SSH。

安装仍在远端 SSH shell 里用 Node 探测 Gateway 的模型和 Key，不建隧道。Worker 上线后，经 Agent 核对 OpenCode 的 `/mcp` 里 `nexus-library` 为 `connected`。这两项原来在即将删除的 SSH 分支（`remote_provisioning.py:385-411`）。

云端不对 Worker 开入站业务端口。OpenCode 只听 `127.0.0.1`。Worker 主动连接主控的 Worker Gateway；OpenCode 再从 Worker 所在网络出站访问 8110 和 8201。

#### 离线、重启与故障维护

日常路径没有 SSH 回退。`connect()`、任务 `start()`、健康检查、文件、Git、上传、目录准备、`POST .../environment/test` 在 Worker 离线或通道未标记时直接失败，不打开 SSH。这些失败不调用 `open_session`，不改 `Task.status`，不调用 `apply_session_state()`。重连仍不新建 Session，不重发 Prompt。

WebSocket 断开只走现有的 `on_connection_lost()` 空操作。Agent 退避重连。它不因此执行 `systemctl restart`，也不对健康的 OpenCode 发 SIGTERM。

重启 OpenCode 只发生在员工无占用、并且管理员明确发起维护的时候。两道门一起用，缺一不可：

1. 与 `reserve_operation` / `mark_worker_channel` 相同的维护锁：没有进行中的环境操作，占用谓词为假，也没有仍占住的 Session。
2. 管理员这次操作本身就是安装或重启。任务启动失败、健康检查失败、套接字断开，都不是这道操作。

`RemoteProvisioner.run()` 今天总是先 `open_session`（`remote_provisioning.py:467`）。Worker 在线时，restart 改为下发给 Agent，不打开 SSH。只有 Worker 离线时，安装和重启才走 SSH，并用上面的 `operation_id` 读取密码。

Worker 在线时的重启是 Agent 本地指令，走与 `switch_channel` 相同的维护入口，普通指令接口返回 403 `maintenance_command`。有 `ASTRA_WORKER_OPENCODE_UNIT` 时用 `systemctl restart` 该单元；否则先确认监听进程的命令行含 `opencode` 和 `serve`，再 SIGTERM。不按进程名扫杀，不使用 `_start_server`。

deploy 在员工无占用时重载 OpenCode。迁移门里的受控重载（`channel_switch.py` 的 reload）会重启本机 OpenCode，所以 deploy 不承诺「只修 Agent、不动 OpenCode」。离线本身不构成日常执行去打开 SSH 的理由。

这道维护不发送 Prompt，不创建 Session，不调用 `apply_session_state()`，不改 `Task.status`。代码里不存在「Worker 调用失败之后改调 `open_session`」的分支。

#### 部署

一次管理员触发的 SSH 会话完成安装。密码留在环境行上，供以后的故障维护在锁内使用。日常执行不读这列：

1. 环境行上已有 host、用户名、`ssh_password`、`workspace_root` 和 `opencode_server_port`。安装读取已保存的密码，不从请求体取密码，成功后也不清空。
2. 拒绝回环的 Gateway 与 MCP 配置。在远端安装 OpenCode 1.18.35，systemd 单元执行 `opencode serve --hostname 127.0.0.1 --port <opencode_server_port>`。单元名写入 Agent 的 `ASTRA_WORKER_OPENCODE_UNIT`。
3. 写入全局 `opencode.json` 的 `astra-gateway` provider 和图书馆 MCP，地址是上一节的内网配置。保留 Gateway Key 和 MCP Token。不写隧道回环地址。SSH shell 里用 Node 探测 Gateway 的 Key 和模型。
4. 用现有登记取得该环境自己的 `worker_instance_id` 和 token。再次登记仍是旋转 token、递增 epoch，不新建第二个身份。token 写到远端仅 root 可读的文件，不进日志。
5. 安装 Worker Agent 的 systemd 单元。单元写入 `ASTRA_REMOTE_GATEWAY_URL`、`ASTRA_MCP_RESOURCE_URL` 和 `ASTRA_WORKER_OPENCODE_URL=http://127.0.0.1:<opencode_server_port>`。单元出站连接主控，不在云端机器上监听业务端口。脚本默认端口改为 4096：`install_nexus.sh` 的 `REMOTE_WORKER_OPENCODE_PORT`、`ops/env/.env.example`，以及 `DEPLOYMENT_GUIDE.md`、`docs/deploy/REMOTE_EMPLOYEES.md` 里的反向隧道和 4296 描述。
6. 启动单元。仍在同一次 `RUNNING` 操作里做探测、重载、生效配置核对，通过才把 `worker_channel` 写成 `worker`，并经 Agent 核对 `/mcp` 已连接。`ssh_password` 保持原值。未通过则环境保持不可执行，不打开另一条 SSH 执行路径，也不释放锁之后再调用 `mark_worker_channel`。

基础环境（系统包、Node、目录）仍由这次安装 SSH 负责。装完之后，健康检查和显式重启不再使用这次会话。

#### 实现时要覆盖的测试

落地时再写，本设计不附带代码。至少包括：`ensure_remote_mcp_tunnel`、`ensure_remote_gateway_tunnel`、`_ensure_service_tunnel`、`open_reverse_tunnel`、`open_tunnel`、`SSHTunnel`、`SSHReverseTunnel`、`close_remote_mcp_tunnels` 没有调用方；`app` 与 `ops` 的运行时代码不 import `opencode_remote.py`；`LINUX_REMOTE` 在通道不是 `worker` 时 `connect()` 失败且不调用 `open_session`；LOCAL 的启动、文件和 Git 仍不使用 SSH；没有管理密钥时维护接口返回 401；`open_session` 缺少 `operation_id` 或操作不是 `RUNNING` 时拒绝且不读 `ssh_password`；日常路径不读该列；部署的回环 Gateway 或 MCP 地址被拒绝；在线 restart 不调用 `open_session`，离线才走 SSH；deploy 在自己的操作里完成标记，不嵌套 `mark_worker_channel`；安装写出的地址不是回环隧道地址，Agent 单元带上两个内网变量和与环境端口一致的 `ASTRA_WORKER_OPENCODE_URL`；探测失败不写成 `worker`；`lifecycle.py:636-639` 仍把 `LINUX_REMOTE` 映射为 `gateway_model`；OpenCode 仍只绑 `127.0.0.1`；部署成功后 `ssh_password` 仍是原值；WebSocket 断开不重启 OpenCode；通信失败不改 `Task.status`；重连不新建 Session、不重发。另有一条安装到文件与上传的端到端测试：安装、登记、Worker 在线、迁移门、文件与上传。

### 阶段 5

阶段 4 按选项 A 删除反向隧道和 ssh 执行分支之后，再确认没有残留调用方。epoch 乱序、双 owner、发布后崩溃、消费者崩溃、ACK 丢失，以及认领后和上传中的 epoch 切换，已在阶段 2 覆盖。本阶段只回归剩余的进程重启、网络超时和 Task/Session 一致性。不改 `opencode_remote.py` 这个 CLI fallback 模块；确认无调用方之后可以再删死代码。

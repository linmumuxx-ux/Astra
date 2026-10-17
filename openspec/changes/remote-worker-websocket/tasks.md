## 1. Worker Gateway、Worker Agent、连接认证与路由

- [x] 1.1 审查 SSH、本地转发和反向隧道调用方，并记录与新架构的冲突
- [x] 1.2 增加 Worker 实例、连接纪元、指令表和 `0039_worker_gateway`
- [x] 1.3 实现注册、token 摘要、epoch、心跳、指令持久化、ACK/结果和过期
- [x] 1.4 实现内存路由与 Redis 路由；控制优先于事件；旧 epoch 不能清除新租约
- [x] 1.5 挂载 `/api/worker-gateway`，Worker Agent 能认证、退避重连，且断线不重启 OpenCode
- [x] 1.6 补齐通道测试。不切换现有 SSH 调用，不改 Task/Session 投影
- [x] 1.7 传输异常归一化，并用真实 WebSocket 覆盖断线、拒绝连接、认证超时和协议关闭码
- [x] 1.8 owner 注册按 epoch 原子比较；发布、消费、发送都做 fencing
- [x] 1.9 断开、响应和 sweep 改为条件更新
- [x] 1.10 相同 request_id 冲突回读原记录，不一致返回 409
- [x] 1.11 持久化投递状态和 owner dispatcher；Agent 按 request_id 去重；prompt 不盲重发
- [x] 1.12 管理接口使用内部服务密钥；启动脚本生成一次，API 进程不各自生成
- [x] 1.13 epoch 高水位不随租约删除；投递状态拆成 unpublished / uncertain / published；已 ACK 的指令不再重发

## 2. OpenCode API、SSE 与 Session 恢复

实现以 design.md「阶段 2 契约」为准。切换维护会写入内网直连地址、在无占用时受控重载并核对生效配置。`prepare_workspace` 在 Worker 上创建 git worktree。重连对账沿 `x-next-cursor` 翻页，并在有限页数后停止。

- [x] 2.1 抽出远程 OpenCode 传输。已标记 `worker` 的环境走 Gateway；`workspace_routes` 直连 `client.base_url` 的请求纳入同一传输
- [x] 2.2 OpenCode SSE 用带 seq 的 WebSocket 帧上报，Nexus 转成现有浏览器事件流。超过帧上限只发 `astra.event_gap` 并 refresh
- [x] 2.3 断线重连后核对原生 Session、完整分页消息、问题和权限；不新建 Session，不重发最后一条 Prompt
- [x] 2.4 通信中断、执行超时和 OpenCode 异常分开记录；投影仍只走 `apply_session_state()`
- [x] 2.5 保留 `pending_message_id` / `pending_prompt`（含 `in_flight`）和 `pending_attempt`
- [x] 2.6 事件日志保留最近 N 条。消费者游标有租约。未读达到 N 时发 pause_events，收回后 resume_events，没有消费者时 stop_events。缺口 refresh 按 Task 合并。http 与 SSE 在独立任务中执行
- [x] 2.7 HTTP 承载请求体和响应体：WebSocket 只发就绪通知，Worker GET 请求、PUT 响应。请求体 TTL 盖过 deadline。每次上传用独立 upload_id。完成记录带上 `x-next-cursor` 等响应头。取消使用独立 request_id。最终 CAS 带 WorkerInstance.epoch 子查询
- [x] 2.8 显式 `worker_channel`，连接时按 environment_id 读环境行，不读快照。切换是受占用约束的维护操作：只探测配置地址，受控重载后核对生效配置。已迁移环境的 workspace 准备改成 Agent 指令。文件和 Git 浏览在阶段 3 前仍走 SSH
- [x] 2.9 拆开首次发送和人工重试。保存 attempt 到 request_id 的映射和 body_fetched_at。只有从未拉取请求体才证明未发送；拉取后视为结果未知，等本地上限加落库余量，再由人确认才可重发。epoch 结束后不得开始本地 POST。恢复、重连、调度、心跳、超时永不调用人工重试
- [x] 2.10 先修占用被提前释放的 bug。谓词只作用于已认领或已绑定的 Task。人工释放只用于 CANCELED 或取消进行中，记录操作人、原因、Session 和 attempt；新 attempt、重启或新 Session 时清除。RUNNING/WAITING 不因该时间戳释放
- [x] 2.11 幂等身份包含 session_id。相同 request_id 在 Worker、指令名、payload、session_id 不一致时返回 409
- [x] 2.12 有副作用的指令用原生消息核对决定能否重发。OpenCode 1.18.35 不按 messageID 去重。不新增 Agent 落盘去重账本
- [x] 2.13 按 design.md「阶段 2 故障测试」覆盖十项，包括认领后和上传中途的 epoch 切换、拉取证据和过期事件游标

## 3. Workspace、文件与 Git

- [x] 3.1 文件浏览、Git diff 和上传改由 Worker 本地执行。目录和 worktree 准备已在阶段 2 完成。测试：已迁移环境这些调用不打开 SSH，也不读 `session_connection.py` 里抄来的密码；删除文件的 diff 在最后一级 ENOENT 时仍返回该变更；最后一级符号链接指向外部时 `validate_path` 返回 `symlink_escape`；指向 workspace 内的绝对符号链接被拒绝；git argv 固定带 `-c core.fsmonitor=false`，调用方传入的 `-c` 被拒；git 在指令截止时间被杀掉并返回 code=124；`/repo` 的 `status_porcelain` 超限时 `dirty=true`
- [x] 3.2 浏览器继续使用现有 Workspace HTTP/SSE。测试：URL 和响应字段不变；`/file*` 在 `validate_path` 之后仍由 OpenCode 返回，OpenCode 再次解析路径的窗口与 SSH 现状相同
- [x] 3.3 上传经阶段 2 的 HTTP 拉取/上传端点传输；保留大小、权限、路径和校验和边界。测试：`read_file` 与 Git 原始字节以 base64 写入现有文本块，`size`、`sha256` 和 20 MiB 都按原始字节，Nexus 再按 utf-8 `errors=replace` 解码；不新增端点；Agent 用独立任务表和上限 4 的信号量，套接字关闭时取消，不占 8 路 http 槽，也不加数据库槽
- [x] 3.4 Worker 端校验真实路径、符号链接和 TOCTOU，校验上传校验和并清理暂存。测试：`validate_path` 先用 `openat2(O_PATH, RESOLVE_BENEATH|RESOLVE_NO_MAGICLINKS)` 打开完整相对路径，只有 ENOENT 才同样打开父目录并返回 `{relative}`，最后一级指向外部的符号链接是 `symlink_escape`，EXDEV/ELOOP 为 `symlink_escape`，ENOSYS 或 seccomp EPERM 为 `io`；workspace 从允许根的 fd 用 openat2 打开；openat2 的原子打开只覆盖 `read_file` 和 `upload_file`；残留 partial 在 Agent 启动时只扫 `{根或 .astra-tasks}/*/uploads/.partial-*` 且不跟随符号链接；rename 后的 0600 孤儿在 CAS 失败时保留，等待者只在 rowcount 为 1 时被唤醒；阻塞函数在创建 partial 前和 rename 前同时检查连接的 `closed` 事件和 epoch，套接字关闭而 epoch 未变时也不创建文件

## 4. Gateway、MCP 与部署

实现以 design.md「阶段 4」为准。已拍板：通道选项 A，密码选项 2。远程执行只留 `worker`。`ssh_password` 继续留在环境行上，安装成功后不清空；日常路径不读它，只有维护锁内且员工无占用时 `open_session` 才读。OpenCode 继续用环境上的 `opencode_server_port`（默认 4096）。不新增迁移。

- [ ] 4.1 删除反向隧道和 `ssh` 执行分支。测试：`ensure_remote_mcp_tunnel`、`ensure_remote_gateway_tunnel`、`_ensure_service_tunnel`、`open_reverse_tunnel`、`close_remote_mcp_tunnels` 无调用方；`LINUX_REMOTE` 在通道不是 `worker` 时 `connect()` 失败且不调用 `open_session`；LOCAL 的启动、文件和 Git 仍不使用 SSH
- [ ] 4.2 安装写入内网 Gateway 与图书馆 MCP，探测复用阶段 2 的迁移门。测试：写出的地址是 `remote_gateway_local_url` 与 `mcp_resource_server_url`，不是 `127.0.0.1:8110` 或 `127.0.0.1:8201`；探测失败不写成 `worker`；`lifecycle.py` 的 `LINUX_REMOTE` 模型映射仍是 `gateway_model`
- [ ] 4.3 SSH 只用于安装 Worker Agent、基础环境和故障维护。测试：`connect`、任务启动、健康检查、文件、Git、上传、环境测试不调用 `open_session`；Worker 调用失败不会落到 SSH
- [ ] 4.4 Worker 在线时，显式重启和健康检查在 Agent 本地执行。测试：WebSocket 断开不增加重启计数、不调用 `systemctl`；员工被占用时拒绝维护重启；普通指令接口对维护重启返回 403 `maintenance_command`；显式重启不使用 `_start_server` 的 kill 脚本；健康的 OpenCode 不因套接字断开被重启
- [ ] 4.5 LLM Wiki 仍使用现有独立连接；OpenCode 继续听 `127.0.0.1` 和环境上的 `opencode_server_port`（默认 4096），不把 4296 写成新的默认值。测试：LLM Wiki 客户端仍使用 `llm_wiki_api_base_url`
- [ ] 4.6 `ssh_password` 继续留在环境行上，安装成功后不清空。测试：部署成功后该列仍是原值；空白更新仍保留原值，响应仍只有 `has_ssh_password`；`connect`、启动、健康检查、文件、Git、上传、环境测试不读取该列；`open_session` 在没有维护锁或员工被占用时拒绝且不读密码；有锁且无占用的安装或故障维护才读取环境行上的密码。部署在 Worker 在线且迁移门通过之前，不把环境标成可执行

## 5. 回归与清理

- [ ] 5.1 确认阶段 4 已删除的反向隧道和 ssh 执行分支没有残留调用方。不改 CLI fallback 模块
- [ ] 5.2 回归进程重启、网络超时和 Task/Session 一致性。epoch 乱序、双 owner、发布后崩溃、消费者崩溃和 ACK 丢失放在阶段 1/2
- [ ] 5.3 确认 CLI fallback、AgentScope 和状态机语义未被改写

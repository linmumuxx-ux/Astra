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

实现以 design.md「阶段 2 契约」为准。2.8 的受控重载和生效配置核对仍未做。重连对账仍走现有 `refresh()` 的单次消息读取；沿 `x-next-cursor` 翻完整页只在人工重试。

- [x] 2.1 抽出远程 OpenCode 传输。已标记 `worker` 的环境走 Gateway；`workspace_routes` 直连 `client.base_url` 的请求纳入同一传输
- [x] 2.2 OpenCode SSE 用带 seq 的 WebSocket 帧上报，Nexus 转成现有浏览器事件流。超过帧上限只发 `astra.event_gap` 并 refresh
- [x] 2.3 断线重连后核对原生 Session、完整分页消息、问题和权限；不新建 Session，不重发最后一条 Prompt
- [x] 2.4 通信中断、执行超时和 OpenCode 异常分开记录；投影仍只走 `apply_session_state()`
- [x] 2.5 保留 `pending_message_id` / `pending_prompt`（含 `in_flight`）和 `pending_attempt`
- [x] 2.6 事件日志保留最近 N 条。消费者游标有租约。未读达到 N 时发 pause_events，收回后 resume_events，没有消费者时 stop_events。缺口 refresh 按 Task 合并。http 与 SSE 在独立任务中执行
- [x] 2.7 HTTP 承载请求体和响应体：WebSocket 只发就绪通知，Worker GET 请求、PUT 响应。请求体 TTL 盖过 deadline。每次上传用独立 upload_id。完成记录带上 `x-next-cursor` 等响应头。取消使用独立 request_id。最终 CAS 带 WorkerInstance.epoch 子查询
- [ ] 2.8 显式 `worker_channel`，连接时按 environment_id 读环境行，不读快照。切换是受占用约束的维护操作：只探测配置地址，受控重载后核对生效配置。已迁移环境的 workspace 准备改成 Agent 指令。文件和 Git 浏览在阶段 3 前仍走 SSH
- [x] 2.9 拆开首次发送和人工重试。保存 attempt 到 request_id 的映射和 body_fetched_at。只有从未拉取请求体才证明未发送；拉取后视为结果未知，等本地上限加落库余量，再由人确认才可重发。epoch 结束后不得开始本地 POST。恢复、重连、调度、心跳、超时永不调用人工重试
- [x] 2.10 先修占用被提前释放的 bug。谓词只作用于已认领或已绑定的 Task。人工释放只用于 CANCELED 或取消进行中，记录操作人、原因、Session 和 attempt；新 attempt、重启或新 Session 时清除。RUNNING/WAITING 不因该时间戳释放
- [x] 2.11 幂等身份包含 session_id。相同 request_id 在 Worker、指令名、payload、session_id 不一致时返回 409
- [x] 2.12 有副作用的指令用原生消息核对决定能否重发。OpenCode 1.18.35 不按 messageID 去重。不新增 Agent 落盘去重账本
- [x] 2.13 按 design.md「阶段 2 故障测试」覆盖十项，包括认领后和上传中途的 epoch 切换、拉取证据和过期事件游标

## 3. Workspace、文件与 Git

- [ ] 3.1 文件浏览、Git diff 和上传改由 Worker 本地执行。目录和 worktree 准备已在阶段 2 完成
- [ ] 3.2 浏览器继续使用现有 Workspace HTTP/SSE
- [ ] 3.3 上传经阶段 2 的 HTTP 拉取/上传端点传输；保留大小、权限、路径和校验和边界
- [ ] 3.4 Worker 端校验真实路径、符号链接和 TOCTOU，校验上传校验和并清理暂存

## 4. Gateway、MCP 与部署

- [ ] 4.1 删除反向隧道实现。阶段 2 已让 `worker_channel=worker` 的环境不再打开到 8110/8201 的隧道；此处只在没有 `ssh` 环境后删除代码
- [ ] 4.2 内网 8110/8201 直连地址和 Worker 可达探测已是阶段 2 的迁移门。此处确认未迁移环境不再依赖隧道地址
- [ ] 4.3 SSH 仅用于安装 Worker Agent、基础环境和故障维护
- [ ] 4.4 Worker 在线时，日常 OpenCode 重启和健康检查在 Agent 本地执行
- [ ] 4.5 确认 LLM Wiki 仍使用现有独立连接；处理 4096 与 4296 的端口选择
- [ ] 4.6 在去掉执行期 SSH 之前，验证 Gateway 与 MCP 地址从 Worker 可达；部署仍要求 SSH 地址和密码直到替换完成

## 5. 回归与清理

- [ ] 5.1 调用方切换完成后再删除不再使用的业务隧道
- [ ] 5.2 回归进程重启、网络超时和 Task/Session 一致性。epoch 乱序、双 owner、发布后崩溃、消费者崩溃和 ACK 丢失放在阶段 1/2
- [ ] 5.3 确认 CLI fallback、AgentScope 和状态机语义未被改写

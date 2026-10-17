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

实现以 design.md「阶段 2 契约」为准。本轮只锁定契约，下列项仍未实现。

- [ ] 2.1 抽出远程 OpenCode 传输，在线 Worker 走 Gateway 指令，而不是每调用一次 SSH
- [ ] 2.2 SSE 事件经 Worker 上报后，由 Nexus 转成现有浏览器事件流
- [ ] 2.3 断线重连后核对原生 Session、消息、问题和权限；不新建 Session，不重发最后一条 Prompt
- [ ] 2.4 通信中断、执行超时和 OpenCode 异常分开记录；投影仍只走 `apply_session_state()`
- [ ] 2.5 保留 `pending_message_id` / `pending_prompt`（含 `in_flight`）和 Worker 占用规则
- [ ] 2.6 事件缓冲的消费出口、序号、丢失通知和重新对账
- [ ] 2.7 HTTP 数据通道：请求关联、认证、流控、取消和大小边界
- [ ] 2.8 已迁移环境断线进入通信恢复，不回退 SSH，不运行会杀旧进程的启动脚本
- [ ] 2.9 ACK 丢失时用持久化的原生消息 ID 决定能否重发
- [ ] 2.10 把 lifecycle 与 remote_provisioning 的占用判断收成一个入口，沿用 dfc5eab
- [ ] 2.11 幂等身份包含 session_id。相同 request_id 在 Worker、指令名、payload、session_id 不一致时返回 409
- [ ] 2.12 有副作用的指令用原生消息核对决定能否重发，不新增 Agent 落盘去重账本。内存去重只挡同一进程的重复帧
- [ ] 2.13 按 design.md「阶段 2 故障测试」覆盖 epoch 乱序、双 owner、发布后崩溃、消费者崩溃、ACK 丢失和事件丢失对账

## 3. Workspace、文件与 Git

- [ ] 3.1 目录准备、worktree、diff、浏览和上传改由 Worker 本地执行
- [ ] 3.2 浏览器继续使用现有 Workspace HTTP/SSE
- [ ] 3.3 上传经 Nexus 暂存，Worker 拉取；保留大小、权限和路径边界
- [ ] 3.4 Worker 端校验真实路径、符号链接和 TOCTOU，校验上传校验和并清理暂存

## 4. Gateway、MCP 与部署

- [ ] 4.1 执行期不再打开到 8110/8201 的反向隧道
- [ ] 4.2 部署写入可达的 Nexus 内网地址，保留 Gateway Key 与 MCP Token
- [ ] 4.3 SSH 仅用于安装 Worker Agent、基础环境和故障维护
- [ ] 4.4 Worker 在线时，日常 OpenCode 重启和健康检查在 Agent 本地执行
- [ ] 4.5 确认 LLM Wiki 仍使用现有独立连接；处理 4096 与 4296 的端口选择
- [ ] 4.6 在去掉执行期 SSH 之前，验证 Gateway 与 MCP 地址从 Worker 可达；部署仍要求 SSH 地址和密码直到替换完成

## 5. 回归与清理

- [ ] 5.1 调用方切换完成后再删除不再使用的业务隧道
- [ ] 5.2 回归进程重启、网络超时和 Task/Session 一致性。epoch 乱序、双 owner、发布后崩溃、消费者崩溃和 ACK 丢失放在阶段 1/2
- [ ] 5.3 确认 CLI fallback、AgentScope 和状态机语义未被改写

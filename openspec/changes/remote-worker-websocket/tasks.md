## 1. Worker Gateway、Worker Agent、连接认证与路由

- [x] 1.1 审查 SSH、本地转发和反向隧道调用方，并记录与新架构的冲突
- [x] 1.2 增加 Worker 实例、连接纪元、指令表和 `0039_worker_gateway`
- [x] 1.3 实现注册、token 摘要、epoch、心跳、指令持久化、ACK/结果和过期
- [x] 1.4 实现内存路由与 Redis 路由；控制优先于事件；旧 epoch 不能清除新租约
- [x] 1.5 挂载 `/api/worker-gateway`，Worker Agent 能认证、退避重连，且断线不重启 OpenCode
- [x] 1.6 补齐通道测试。不切换现有 SSH 调用，不改 Task/Session 投影

## 2. OpenCode API、SSE 与 Session 恢复

- [ ] 2.1 抽出远程 OpenCode 传输，在线 Worker 走 Gateway 指令，而不是每调用一次 SSH
- [ ] 2.2 SSE 事件经 Worker 上报后，由 Nexus 转成现有浏览器事件流
- [ ] 2.3 断线重连后核对原生 Session、消息、问题和权限；不新建 Session，不重发最后一条 Prompt
- [ ] 2.4 通信中断、执行超时和 OpenCode 异常分开记录；投影仍只走 `apply_session_state()`
- [ ] 2.5 保留 `pending_message_id` / `pending_prompt`（含 `in_flight`）和 Worker 占用规则

## 3. Workspace、文件与 Git

- [ ] 3.1 目录准备、worktree、diff、浏览和上传改由 Worker 本地执行
- [ ] 3.2 浏览器继续使用现有 Workspace HTTP/SSE
- [ ] 3.3 上传经 Nexus 暂存，Worker 拉取；保留大小、权限和路径边界

## 4. Gateway、MCP 与部署

- [ ] 4.1 执行期不再打开到 8110/8201 的反向隧道
- [ ] 4.2 部署写入可达的 Nexus 内网地址，保留 Gateway Key 与 MCP Token
- [ ] 4.3 SSH 仅用于安装 Worker Agent、基础环境和故障维护
- [ ] 4.4 Worker 在线时，日常 OpenCode 重启和健康检查在 Agent 本地执行
- [ ] 4.5 确认 LLM Wiki 仍使用现有独立连接；处理 4096 与 4296 的端口选择

## 5. 回归与清理

- [ ] 5.1 调用方切换完成后再删除不再使用的业务隧道
- [ ] 5.2 回归重连、重复指令、进程重启、网络超时和 Task/Session 一致性
- [ ] 5.3 确认 CLI fallback、AgentScope 和状态机语义未被改写

# NEXUS 平台助手真实验收报告（2026-09-04，2026-09-05 复核）

验收对象：按《平台助手方案设计》（`docs/archive/design/PLATFORM_ASSISTANT.md`，原 `docs/product/design/PLATFORM_ASSISTANT.md`）落地的第一版平台助手。

验收环境：

- OpenCode 初验 1.18.25、复核 1.18.29（`opencode serve` 独立实例，
  `127.0.0.1:4097`；初验使用当时的工作区 `nexus-assistant/`，已改为以 Astra 项目根目录加载，无独立工作区）；
- 模型：`deepseek/deepseek-v4-flash-vision-exp`（本机 OpenCode 全局配置）；
- 后端：FastAPI + SQLite（隔离实例），前端：Vite Dev + Chromium（Playwright）。

## 后端测试

- `services/task-platform/tests/` 全量 **89 项通过**（含 18 项助手测试），`ruff check` 无告警；
- 覆盖：事件映射、卡片协议、prepare → confirm 生命周期（创建/取消/重试/恢复/重分配）、
  幂等确认、过期拦截、操作归属、重分配资格与状态复验、消息限流、状态冲突收敛、
  同会话并发拦截、跨进程卡片序号恢复、
  Tool Gateway、REST API（Fake OpenCode Client）、OpenCode 不可用时的降级行为。

## 迁移与部署

- `alembic upgrade head` 从 0001 至 0013 全链路通过，新建 6 张助手表；
- 0012 本地库已被 `create_all` 预建完整助手表时，0013 可校验结构后接管并保留现有会话；
- `astra-assistant-mcp` 入口注册成功；跨平台生命周期启动器会把当前虚拟环境
  可执行目录注入 `PATH`，`opencode mcp list` 实测为 `connected`。MCP Server 构建出
  18 个 `nexus_*` 工具，
  不含任何确认类工具（确认只走 REST）。
- macOS/Linux `runtime.sh`、Windows `process_manager.py` 与 Linux systemd 均管理独立助手
  Server；实测 `python -m app.assistant.server` 可在 4097 启动 OpenCode 1.18.29，且助手
  启动异常不会阻断平台核心进程。

## 真实 OpenCode 验收

1. **健康检查**：`GET /api/assistant/health` 在 OpenCode 启动前返回 `degraded`，
   启动后返回 `available: true, version: 1.18.29`；
2. **流式问答**：自然语言提问“平台现在有哪些数字员工”，Agent 调用
   `nexus_employee_search` 后返回隔离库中的真实员工与状态（3 名），
   工具调用写入 `assistant_tool_calls` 审计；
3. **推理隔离**：`reasoning` 片段不进入用户可见内容；
4. **查询卡片**：`nexus_task_get` 结果自动渲染为 `TASK_CARD`；
5. **prepare → confirm 全链路**：
   - 初验完成运行中任务取消；复核以自然语言创建“助手真实闭环验收”任务，
     Agent 调用 `nexus_task_prepare_create`；
   - 平台落库 `assistant_operations`（L2、WAITING_CONFIRM），会话出现 `CONFIRM_CARD`；
   - `POST /api/assistant/operations/{id}/confirm` → 真实创建来源为 `assistant` 的 Task，
     操作 `SUCCESS`；重复确认返回同一 Task ID，未重复创建；
   - 刷新页面后确认卡按操作真实状态（SUCCESS）渲染，不误导重复确认；
6. **浏览器端（Playwright 真实交互）**：
   - 2 项 Chromium 用例通过：入口降级显示、真实新建会话发送消息与流式回复；
   - 页面刷新后会话历史完整恢复；
   - 已修复“点击新建后立即输入可能发往旧会话”的竞态；
7. **降级隔离**：OpenCode 停止时助手入口保留并显示服务异常；
   消息发送返回 503 且不残留脏消息；`/api/health`、`/api/system/metrics`
   等平台核心接口完全正常。

## 可靠性复核

- SSE 断线后按事件序号回放，并在重连前从数据库恢复消息，避免丢事件窗口；
- OpenCode 事件流重连时只恢复最新 Assistant Message，不把整段历史重复写入当前回复；
- Agent 回合超时会 Abort 对应 Session 并落为失败；停止生成不触碰业务 Task；
- Operation 执行前后均校验用户归属，业务对象状态变化导致执行冲突时会从
  `EXECUTING` 收敛到 `FAILED`，不会形成永久卡死的确认卡；
- 助手 OpenCode 指向非 loopback 地址时强制要求密码。

## 已知边界

- 重分配（reassign）已按 L2 风险纳入 prepare → confirm，仅允许待领取或已挂起
  任务；运行中任务需先挂起，以保证不会与旧 Run 并发；
- Astra 当前管理台仍是单控制台身份；正式多用户 RBAC 依赖企业认证网关注入真实用户，
  本版已确保 Conversation 与 Operation 不可跨配置身份访问；
- 模型消息入口默认按用户限制为每分钟 30 次（可配置）；当前单 Uvicorn 进程
  部署使用进程内滑动窗口，未来扩展多 Backend Worker 时需替换为 Redis 共享计数；
- 前端 `MessageInput` 附件按方案要求留待后续版本。

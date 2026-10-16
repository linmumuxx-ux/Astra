# 持续任务工作台设计与实现

## 定位

任务详情页不再只是任务状态和 Run 结果的只读页面，而是一个可持续工作的任务会话。一个 Task 对应一个长期 TaskSession；用户、数字员工、Run、询问、事件与产物都归属这项任务的工作现场。任务成功或失败后，会话仍然存在，用户可以补充要求并在同一 Session 下启动新的 Run。

现有 Task、Run、Executor、Celery 和 Evidence 模型继续承担原有职责：Task 保存业务事实，Run 保存单次执行，Executor 执行具体工作，TaskSession 只负责把多轮运行组织成连续会话。

## 页面结构

任务工作台采用借鉴 OpenCode CLI 信息布局、但使用 NEXUS 原生浅色主题的双栏持续会话。OpenCode 只作为阅读结构和交互形式参考，不作为颜色、字体或终端皮肤规范：

- 左侧是连续 Session，只展示原始任务、有效用户/Agent 消息、结构化 Inquiry、真实 Subagent、失败提示和简洁最终结果。Tool、Run 生命周期、Token 与 Session 元数据不进入主阅读流。
- 右侧是轻量 Context，只保留任务状态、完成策略、数字员工、真实 Subagent、产物、验收标准、实际消耗和默认折叠的运行信息。
- 底部输入区在任务运行、等待、失败或完成后都保持可用。运行中输入会先进入 Pending Instruction，安全边界后再进入下一轮执行。
- 已回答 Inquiry 将问题和答案合并展示；重复的用户回答消息、询问复述和终态长回复不重复出现，终态使用 Task Result 摘要作为面向用户的输出。

Tool Event、完整 Run 和原始 Runtime payload 继续在后端留存，可从折叠运行信息或专门的 Run 页面查看。页面不伪造 Agent 或 Subagent，也不展示模型隐藏推理。

## 持久化模型

迁移 `0007_task_workbench` 新增三张表；`0008_semantic_workbench` 负责补齐历史任务会话、过滤旧 usage 噪声并统一交互状态；`0009_runtime_event_adapter` 从历史结构化 Task Tool 记录回填真实 Subagent 事件：

### `task_sessions`

- 每项任务唯一一个 Session。
- `current_run_id` 指向当前或最近一次 Run。
- Session 状态由任务状态投影为 `ACTIVE`、`WAITING_INPUT`、`PAUSED`、`FAILED` 或 `COMPLETED`。

### `session_messages`

- 保存用户和数字员工在任务会话中的消息。
- `PENDING` 表示运行中的新指令等待安全边界；`QUEUED` 表示已排入下一轮；`APPLIED` / `ANSWERED` 表示已进入执行上下文或已回答询问。
- 可选 `run_id` 用于追踪消息最终应用到哪一次 Run。

### `run_inquiries`

- 保存结构化确认问题、描述、选项、回答及其状态；新问题使用 `OPEN`，回答后为 `ANSWERED`，取消后为 `CANCELLED`。
- Inquiry 既可以通过选项回答，也可以通过底部输入框使用自然语言回答。
- 回答后复用原任务的恢复能力，并保留在同一 TaskSession 中。

既有 `events` 表继续作为 Runtime Event 的持久化来源，既有 `evidence` 表继续作为产物来源，避免复制 Task / Run 数据。

## API

聚合读取：

- `GET /api/tasks/{task_id}/workspace`
- `GET /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/events`

写入与人工介入：

- `POST /api/tasks/{task_id}/messages`
- `POST /api/sessions/{session_id}/messages`
- `POST /api/inquiries/{inquiry_id}/answer`

实时事件：

- `GET /api/tasks/{task_id}/workspace/stream`
- `GET /api/sessions/{session_id}/events/stream`

聚合接口一次返回 Task、TaskSession、Message、Runtime Event、Inquiry、Artifact 和 Run，避免页面初始化阶段发起大量相互竞争的请求。事件读取支持 `before_sequence` 游标；SSE 支持 `after_sequence`，仅推送新事件。

## Runtime Event 适配

后端 Semantic Event Adapter 先把 OpenCode Server Event 归一为稳定语义，再决定是否进入主会话流：

- 一条原始 Runtime Event 可以产生多个 Semantic Event。例如 OpenCode 的 `tool_use` + `part.tool=task` 同时产生 `tool.completed/failed` 和 `subagent.completed/failed`。
- Subagent 判定只使用 `subagent_type`、Task Tool 状态、父子 Session 元数据和 call ID 等结构化字段；禁止从 Agent 最终自然语言中猜测。
- `reasoning` 只生成不含原文的诊断事件；未知事件归一为 `runtime.unknown`，不静默丢失，也不进入主会话。
- API 把 Message、Inquiry、Semantic Event 和按 Run 聚合的 Tool Event 投影为稳定 `SessionBlock`；前端消费 SessionBlock，不再重新解释 OpenCode 原始格式。

- Run：`run.created`、`run.started`、`run.resumed`、`run.paused`、`run.completed`、`run.failed`
- Agent：`agent.started`、`agent.progress`、`agent.completed`、`agent.failed`
- Tool：`tool.started`、`tool.completed`、`tool.failed`
- Message：`message.user`、`message.agent`
- Inquiry：`inquiry.created`、`inquiry.answered`
- Artifact：`artifact.created`、`artifact.updated`
- Runtime Metadata：`runtime.session`、`runtime.metadata`，只保留用于诊断和消耗统计，前端主会话流不展示

每条事件包含 Session、Run、顺序号、时间、阶段、摘要和原始 payload。适配层保留来源事件类型，前端不依赖 OpenCode 的 Event 细节。

| 原始 Agent / 平台事件 | 稳定语义 | 主会话流 |
| --- | --- | --- |
| assistant / text message | `message.agent` | 是，作为数字员工消息 |
| tool lifecycle | `tool.started/completed/failed` | 否，保留在后端和 Run 诊断页 |
| question / permission ask | Inquiry + `run.waiting_input` | 是 |
| subagent lifecycle | `subagent.started/progress/completed/failed` | 是，仅真实事件 |
| result / artifact | `run.completed` / `artifact.created` | 结果摘要进入主会话，产物进入 Context / Files |
| step、token、usage、heartbeat、session metadata | `runtime.metadata` | 否 |

历史 `WORK_PROGRESS` 只回填有意义的 Agent 文本；“模型用量已更新”等旧运行噪声不会被迁移为 Message。

## 连续执行语义

- READY：用户指令加入会话，等待员工领取。
- RUNNING：用户指令标记为 Pending；当前不可中断操作结束后，协调器在同一 Session 创建后续 Run。
- WAIT_HUMAN：对应 Session `WAITING_INPUT`、Run `WAITING_INPUT`、Inquiry `OPEN`、Employee `WAIT_HUMAN`。用户从任务详情回答后，Inquiry 变为 `ANSWERED`，原 Run 恢复为 `RUNNING`，不创建第二个 Run。
- SUSPENDED：用户补充要求后恢复任务。
- PENDING_CONFIRMATION：补充意见按退回继续处理。
- COMPLETED / FAILED：保存上一次结果到审阅历史，重新打开任务并创建新 Run；Session ID 不变。
- EXECUTION_ERROR：`/retry` 或“恢复执行”沿用既有恢复路径。

运行中的普通新指令在安全边界生效；用户显式暂停、挂起或终止时调用 OpenCode Session Abort，并保留 `MessageAbortedError` 与 Tool output 作为事实。

## 验证

自动化覆盖以下关键路径：

- 创建任务时自动建立 Session 与首条用户消息。
- Session 事件读取、消息排队、结构化 Inquiry 与自然语言回答。
- 任务完成后在同一 Session 继续输入并重新进入执行队列。
- 真实隔离 Redis、Celery、Backend、Frontend 与可控 Agent 的询问—回答—恢复—完成链路。
- P0 任务“先向使用者询问要打印的答案，收到回答后打印该答案。”在等待和恢复后保持同一 Task、TaskSession、OpenCode Session 与 Run。
- 普通任务不会出现伪 Inquiry；已完成任务的后续要求保持同一 TaskSession 并创建新 Run。
- Task、Run、Employee、Inquiry、Session 在等待、恢复、完成状态下保持一致。
- 已完成、失败、验收、工作消耗和原有 Task / Run 页面兼容性。

当前门禁结果：67 个后端测试、前端类型检查、生产构建与 10 个 Chromium 系统 E2E 全部通过。OpenCode 1.18.25 + GLM5.1 真实 Server 验收覆盖结构化 Task Tool → Child Session → Subagent 内部 Tool、Question/Resume、Abort 和并发隔离；Linux 远程使用 SSH Tunnel 接入同一结构化 Runtime。

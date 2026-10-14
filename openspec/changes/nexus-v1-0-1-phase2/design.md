## Context

Phase 1 产品在 `nexus/`：Vue 3 + Element Plus 三页（员工管理、私聊、团队交流），FastAPI 使用 `nexus/api/data` 下的 SQLite，Agent 与 Session 只存在于 AgentScope 2.0.10。对等联系走 `nexus/deploy/agent_service.py` 的 `contact_employee`，经 `deliver_to_inbox` 写入目标 Session 的 inbox，并在没有消费者时 `enqueue_run_trigger(kind="wake")`。官方 `TaskCreate`、`TaskGet`、`TaskList`、`TaskUpdate`、`ToolStop`、定时任务和 Agent Team 在组装后被卸掉。

历史复用基线是 `origin/codex/astra-updates-20261010`，提交 `05dd73142b294a9cb6b2b14a0750b707422aeec3`。`https://github.com/linxuyiyi/Astra` 用当前凭证返回 404，因此以本仓库该远程分支为准。它是 Phase 1 的祖先。`backend/` 与 `frontend/` 相对该提交没有差异。`domains/` 是此后 `9d96dd48` 起另写的一套模型，历史分支上不存在。

Phase 1 实测（AgentScope 2.0.10 + `deepseek-flash`）里，三跳同事联系、SSE 收尾和团队 `@` 已通过。同事回复落在各自邮箱 Session，不会自动出现在用户的私聊记录里。`HintBlock` 与答复写在同一条 assistant 消息中。邮箱和团队 Session 使用 `dont_ask`，自定义工具需要显式 `ALLOW`，否则会停在权限询问。

## Goals / Non-Goals

**Goals:**

- 把历史 Task Service、OpenCode 执行、环境运维、API 网关和数字图书馆接到 Phase 1 员工上。
- 责任员工与执行 Worker 分开。员工通过 Task Skill / Task MCP 管理任务。任务状态用 AgentScope 已有 inbox 与 wakeup 唤醒员工。
- OpenCode 执行模型默认 `deepseek-flash`，上游 `https://api.deepseek.com`，仍可配置。

**Non-Goals:**

- 本变更不迁移业务代码。D1–D10 确认前不开始实现。
- 不把第三阶段的多员工职责协作当作前置条件。
- 不修改 `openspec/specs/` 里的 Astra 历史契约，也不改写 Phase 1 change。

## 差异分析

| | Phase 1（`nexus/`） | 历史分支（`backend/` + `frontend/`） | 同分支上的 `domains/` |
| --- | --- | --- | --- |
| 员工 | 一位员工一个 AgentScope Agent。SQLite 表 `employees` 存目录、技能/工具/知识 id、`agentscope_agent_id`、`mailbox_session_id` | `DigitalEmployee` 是执行槽：状态、心跳、`current_task_count < 1`、`auto_claim`、`auto_execute`，并一对一挂 `OpenCodeExecutionEnvironment` | `employees` 与 `workers` 已分开，另有 lease、fence、handoff |
| 会话 | 一条私聊或频道成员一条 AgentScope Session | `RuntimeSession` 是某次 OpenCode 执行的绑定和用量索引，消息在 OpenCode | `TaskExecution.native_session_id` |
| 任务 | 无 | `Task`：`PENDING/RUNNING/WAITING/SUCCEEDED/FAILED/CANCELED`，`TaskService` + `TaskStateMachine` | 状态从 `QUEUED` 起，含 team、goal、actor |
| 调度 | 无 | Celery：`astra.dispatch`、心跳、scout、复盘 | `domains/runtime/service.py` 里的租约 |
| 唤醒 | Redis inbox + wakeup | 进程内 `event_bus`，队列满则丢弃；前端看 `/api/events/stream` | `InboxAdmission`，不是 AgentScope inbox |
| 模型 | 对话：`OPENAI_MODEL=deepseek-flash`，`OPENAI_BASE_URL=https://api.deepseek.com` | OpenCode：`ASTRA_OPENCODE_MODEL` 或环境 `model_name`；远程部署走 `astra-gateway/<路由模型>` | 直播报告里用过 `deepseek/deepseek-flash` |

两边叫「员工」的不是同一条记录。Phase 1 员工负责对话和任务决策。历史员工记录里的执行环境、心跳和单槽占用要变成 Agent Worker。`domains/` 的拆分关系与这个方向一致，但它没有任务中心、`remote_provisioning`、网关控制面、图书馆和对应前端，不能替换 `backend/app`。

## 复用清单

路径均相对历史树，也就是当前分支上未改过的 `backend/` 与 `frontend/`。

### Task Service、Task API、任务状态机

- 直接复用：`backend/app/state_machine.py`，`backend/app/domain.py` 的 `TaskStatus`、`Priority`、`TaskType`、`CompletionPolicy`，`backend/app/services.py` 的 `TaskService`，`backend/app/runtime/presentation.py` 与 `task_status.json`，`backend/app/api/routes.py` 的任务列表、创建、详情、确认、删除、事件，`backend/app/api/workspace_routes.py` 的 `start`、`restart`、`stop`、`reconnect`、`retry-submission`，`backend/tests/test_state_machine.py`、`test_api.py`、`test_runtime.py`。
- 小范围适配：`Task.employee_id` 今天指向历史执行员工。迁到 `worker_id`，并增加责任员工和来源会话字段。`Dispatcher.claim_once`（`backend/app/runtime/dispatcher.py`）改为挑选空闲 Worker。MCP 的暂停、恢复、终止、重试做成上述生命周期方法的别名，不新增状态机。
- 需要重新实现：面向 AgentScope 的 Task MCP 进程。历史 `backend/app/assistant/mcp_server.py` 是平台助手的 prepare/确认卡，不是员工直接调用的任务服务。
- 不再需要：`domains/work/service.py` 的第二套任务状态；AgentScope 内置 `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate`（Phase 1 已卸掉，继续卸）。

### Task / Session / Workspace 数据模型及执行链路

- 直接复用：`backend/app/models.py` 的 `Task`、`RuntimeSession`、`Event`、`TaskCategory`，`backend/app/runtime/lifecycle.py` 的 `RuntimeService`，`session_connection.py`，`session_state.py`，`workspace_changes.py`，`workspace_files.py`，`runtime_context.py`，Alembic `backend/alembic/versions/0001` 至 `0028` 中与这些表对应的修订。
- 小范围适配：见下方数据关系。`RuntimeSession.employee_id` 改为 Worker。工作区隔离和 OpenCode 消息归属保持原样。
- 需要重新实现：任务与 Phase 1 来源会话的关联。历史任务没有 AgentScope `session_id`。
- 不再需要：`domains/work/models.py` 的 `Task`、`TaskExecution`、`Handoff` 作为运行中的第二份任务表。

### OpenCode 执行、远程连接、运行恢复

- 直接复用：`backend/app/executors/opencode_server.py`、`opencode_local_server.py`、`opencode_remote.py`、`opencode_remote_server.py`、`opencode_cli.py`、`opencode_prompt.py`，`backend/app/runtime/opencode_server.py`，`opencode_workspace.py`，`semantic_events.py`，`recovery.py`，`failure.py`，`ssh_client.py`，`backend/tests/test_opencode_server.py`、`test_recovery_supervisor.py`、`test_session_state.py`、`test_semantic_events.py`。
- 小范围适配：模型默认值。`split_model` 要求 `provider/model`。全局后备现为 `deepseek/deepseek-flash`。直接创建 Session 时 `providerID=deepseek`、`id=deepseek-flash`。远程部署仍走网关时，OpenCode 侧为 `astra-gateway/deepseek-flash`，网关上游基址 `https://api.deepseek.com`，上游模型 id `deepseek-flash`。
- 需要重新实现：无。CLI 执行器保留为历史注释中的隔离测试入口，不作为正式路径。
- 不再需要：在 Nexus 进程内再写一个 OpenCode 客户端。

### 数字员工执行环境及 Worker

- 直接复用：`OpenCodeExecutionEnvironment` 的字段（`backend/app/models.py`），`backend/app/runtime/environment.py` 的检查与快照，`backend/app/api/routes.py` 里环境的保存、测试、启停，`frontend/src/views/EmployeeListView.vue` 的表格，`EmployeeDetailView.vue`，`frontend/src/views/settings/EmployeeConfig.vue` 的抽屉。
- 小范围适配：这些页面和 `/api/employees/.../environment` 改挂到 Worker。表格列从「员工 / 职责」改为 Worker 名称、环境、当前任务、责任员工。`DigitalEmployee` 上的 `status`、`current_task_count`、`last_heartbeat`、`enabled`、`auto_execute` 随环境一起迁到 Worker。Phase 1 的 `nexus/web/src/views/EmployeesView.vue` 继续只管理 AgentScope 员工。
- 需要重新实现：Worker 与责任员工的关联展示。历史没有这层。
- 不再需要：把 Worker 注册成 AgentScope Agent 或 SubAgent。`character_id`、`default_work_area` 和三维工位不进入 Worker。

### 远程环境部署、重启、检测与日志

- 直接复用：`backend/app/runtime/remote_provisioning.py` 的 `RemoteProvisioner`、`reserve_operation`、`managed_config`，`backend/app/api/environment_routes.py` 的 deploy/restart 流，`frontend/e2e/remote-provisioning.spec.ts`，`backend/tests/test_remote_provisioning.py`。
- 小范围适配：部署锁和占用判断从历史员工 id 改为 Worker id。默认写入的模型路由为 `deepseek-flash`。SSH 密码仍只存环境记录，页面留空表示不改。
- 需要重新实现：无。
- 不再需要：`domains/runtime/ssh.py` 作为另一套 SSH 实现。

### API 网关

- 直接复用：`backend/app/gateway/`（`service.py`、`server.py`、`proxy.py`、`models.py`、`security.py`、`observability.py`、`scheduler.py`、`config.py`），`backend/app/api/gateway_routes.py`，`frontend/src/views/gateway/`，`frontend/e2e/gateway-*.spec.ts`，Alembic `0031`–`0034`。
- 小范围适配：导航进 Nexus。OpenCode 与 AgentScope 对话都使用模型 id `deepseek-flash`。网关路由的上游基址使用 `https://api.deepseek.com`。密钥仍不进仓库，继续用 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`。
- 需要重新实现：无。
- 不再需要：在 Nexus 页面增加模型供应商配置。Phase 1 员工页继续不出现密钥字段。

### 数字图书馆、知识检索及 MCP

- 直接复用：`backend/app/library_service.py`，`library_schemas.py`，`llm_wiki.py`，`backend/app/mcp_server.py`（`library_search`、`library_get`、`library_related`、`library_feedback`），`backend/app/api/library_routes.py`，`backend/app/models.py` 的 `Knowledge*`，`frontend/src/views/DigitalLibraryView.vue` 与 `frontend/src/views/library/`，`frontend/e2e/library-*.spec.ts`，`backend/tests/test_library.py`、`test_library_tree.py`、`test_llm_wiki.py`。
- 小范围适配：图书馆 MCP 按 AgentScope `HttpMCPConfig` 挂到配置了该能力的员工 Session。它与 Task MCP 分开，避免把检索和任务状态机放进同一个工具面。Phase 1 的 AgentScope 知识库保持关闭条件不变：没有 `knowledge_base_manager` 和可用嵌入时，员工档案仍不能手写知识库 id。
- 需要重新实现：员工管理里对图书馆 MCP 的选用，以及把它装进对应 Agent 的 workspace。
- 不再需要：用 AgentScope Knowledge Base 重写图书馆。

### 任务总结、候选经验、审核入库

- 直接复用：`TaskSummary`、`TaskReview`、`ExperienceEvidence`，`backend/app/runtime/summary.py`，`backend/app/assistant/review.py` 的后台复盘与 `mcp_submit_experience`，`backend/tests/test_experience.py`、`test_task_review_api.py`，`evidence/task-experience-review-20261011/`。图书馆审核、发布、入库接口已在 `library_routes.py`。
- 小范围适配：复盘任务上的执行者 id 改为 Worker。员工 Task MCP 提供总结和候选的只读查询。
- 需要重新实现：无，除非 D8 改成由责任员工提交总结。
- 不再需要：员工 MCP 直接写候选。历史 `library_service.mcp_submit_experience` 的注释写明员工 MCP 不提供提交工具，证据校验在 `submit_review`。

### 前端页面、组件及测试

- 直接复用：任务中心 `frontend/src/views/TaskListView.vue`、`TaskDetailView.vue`，网关与图书馆页面，OpenCode 工作台 `frontend/public/opencode-workspace` 与 `workspace-ui/`，e2e `task-list-actions.spec.ts`、`task-detail-workspace.spec.ts`、`task-diff-race.spec.ts`、`session-workspace.spec.ts`、`session-workspace-real.spec.ts`。
- 小范围适配：上述页面进入 `nexus/web` 的导航，请求改到 Nexus 代理后的原 API。任务表增加责任员工、来源会话、Worker。`EmployeeListView.vue` 与 `EmployeeConfig.vue` 作为 Worker 管理。`InterventionView.vue` 保留为人工介入入口。Phase 1 的 `ChatView.vue`、`TeamView.vue` 增加任务 Tab，不增加「创建任务」按钮。
- 需要重新实现：员工对话与团队讨论右侧 Tab 的数据绑定。历史页面没有 AgentScope 会话。
- 不再需要：`frontend/src/views/DashboardView.vue`，`frontend/src/features/office/`，`features/home/`，`features/workspace/` 的三维办公室；`frontend/src/features/assistant/` 的助手抽屉作为员工大脑。Phase 1 三页的现有对话行为保持。

## Decisions

### 已确认：OpenCode 模型

执行模型 id 是 `deepseek-flash`。上游是 DeepSeek 的 OpenAI 兼容接口，基址 `https://api.deepseek.com`。

`backend/app/executors/opencode_server.py` 的 `split_model` 只接受 `provider/model`。因此全局后备写成 `deepseek/deepseek-flash`：

- `backend/app/config/settings.py` 的 `opencode_model` 默认值
- `.env.example`、`deploy/astra.env.example`、`deploy/astra.env.windows.example` 的 `ASTRA_OPENCODE_MODEL`

Worker 或历史环境上的 `model_name` 优先。远程一键部署在走 API 网关时，路由模型 id 用 `deepseek-flash`，OpenCode 配置里的模型名是 `astra-gateway/deepseek-flash`，由网关转发到上述基址。AgentScope 对话继续用 `OPENAI_MODEL=deepseek-flash` 与 `OPENAI_BASE_URL=https://api.deepseek.com`，与这条执行模型分开配置、使用同一个模型 id。密钥仍只来自 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`。

### 1. 数据关系

```text
Phase 1 employees ──负责──▶ tasks ◀──执行── workers
        │                      │                │
        │                      │                └── OpenCodeExecutionEnvironment
        │                      └── runtime_sessions（OpenCode）
        └── AgentScope Session（私聊 / 邮箱 / 频道）
```

责任员工继续只存在于 Phase 1 的 `employees`。Worker 承接历史 `OpenCodeExecutionEnvironment`，并带上执行槽字段：`status`、`current_task_count`、`last_heartbeat`、`enabled`、`auto_execute`、`task_types`、`category_ids`。

`tasks` 在现有列上增加：

- `responsible_employee_id`：Phase 1 员工 id，字符串引用
- `source_session_id`：创建任务的 AgentScope Session
- `source_conversation_id` 或 `source_channel_id`：对应 Nexus 私聊或频道，可空
- `worker_id`：执行 Worker，可空直到分配

保留 `current_session_id`、`workspace`、`execution_environment_snapshot`、验收标准、人工介入和 `completed_at`。`RuntimeSession` 继续只索引 OpenCode，不复制 AgentScope 消息。

创建时由 Task MCP 写入责任员工和来源会话，并带幂等键（来源 Session + 请求摘要）。重复创建返回已有任务。分配由 Worker 池完成：环境 `AVAILABLE`、`enabled`、空闲槽、任务类型和分类匹配。指定 `worker_id` 时只检查该 Worker。

### 2. 迁移顺序

与简报第三节之后的顺序一致，且每步都先有针对性测试：

1. 挂接 Task Service，补责任员工、来源会话、Worker 字段和 Alembic 修订。
2. 新增 Task MCP 与 Task Skill，工具只调用 `TaskService` 和 `RuntimeService`。
3. 员工保存时把 Skill 装进该 Agent 的分区，把 MCP 装进该员工新建的 Session。
4. 环境与部署改为 Worker，Dispatcher 认领 Worker。
5. 网关与图书馆按原路由挂进 Nexus 导航。
6. 任务中心、Worker 页、对话 Tab 读取同一任务状态。唤醒 outbox 与投递一并接入。

Phase 1 的 SQLite 员工目录先保持原文件。任务库继续用历史 SQLAlchemy（默认 SQLite，`ASTRA_DATABASE_URL` 可切 MySQL）。跨库只用字符串 id。这是 D2，确认前不合并库。

### 3. Task MCP 与 Task Skill 如何进入 AgentScope 2.0.10

依据 tag `v2.0.10` 的 `get_toolkit`、`/workspace/mcp`、`/workspace/skill` 和 `Workspace.default_mcps`。

Task MCP 是独立的 streamable HTTP 服务，工具只转发已有服务。名称使用 `nexus_task_*`，避开仍会被卸掉的 `TaskCreate`、`TaskGet`、`TaskList`、`TaskUpdate`。建议工具：`nexus_task_create`、`nexus_task_get`、`nexus_task_list`、`nexus_task_update`、`nexus_task_assign`、`nexus_task_start`、`nexus_task_pause`、`nexus_task_resume`、`nexus_task_terminate`、`nexus_task_retry`、`nexus_task_logs`、`nexus_task_result`、`nexus_task_intervene`、`nexus_task_confirm`、`nexus_task_summary`。

暂停调用现有 `stop(cancel_task=false)`，任务进入 `WAITING`。恢复对 `WAITING` 调用 `start`。终止调用 `stop(cancel_task=true)`，进入 `CANCELED`。重试调用 `restart` 或 `retry_submission`。状态机仍是 `TaskStateMachine.validate`。不新增 `PAUSED`，除非 D4 要求。

注册：

- Skill 按 Agent 分区存放。`list_skills(agent_id)` 读取 `skills/<agent_id>/<dir>/SKILL.md`。员工勾选 Task Skill 后，用 `POST /workspace/skill/upload` 或 `POST /workspace/skill/from-library` 装入该 `agent_id`，一次安装对该员工的各 Session 可见。
- MCP 按 `(agent_id, session_id)` 声明。员工勾选后，在创建私聊、邮箱和频道 Session 时 `POST /workspace/mcp`，正文为 `MCPClient(name="nexus-task", is_stateful=false, mcp_config=HttpMCPConfig(url=..., headers=...))`。已有 Session 在员工保存时补装。未勾选的员工不挂这些工具。
- 不把 Task MCP 放进 `default_mcps`，否则每个 Session 都会带上。
- 工具权限设为 `ALLOW`。邮箱和团队 Session 已是 `dont_ask`，默认询问会停住或被拒绝。
- `nexus/deploy/agent_service.py` 继续卸掉内置任务规划和 Agent Team，并保留 `contact_employee`。

Task Skill 正文说明：工程变更才创建任务；先选定类型、分类和验收标准；经 MCP 管理；收到任务 hint 后先 `nexus_task_get`；`WAITING` 时向当前会话里的人说明介入点；同一幂等键不创建第二条任务。纯问答走对话，同事协调继续走 `contact_employee`。

### 4. 任务事件如何唤醒员工

历史 `event_bus` 只活在进程内，队列满会丢，也不能唤醒 AgentScope。投递改用 AgentScope 2.0.10 已有的 Redis inbox。

`TaskService._apply_transition` 与恢复路径在同一事务写入 `task_wake_outbox`：

- 唯一键是 `events.id`
- 字段含 `task_id`、`responsible_employee_id`、目标 Session、状态 `pending/delivered/superseded/failed`、尝试次数、hint 正文
- 触发范围：进入 `SUCCEEDED`、`FAILED`、`WAITING`、`CANCELED`，以及失败后的恢复再次进入 `RUNNING`

投递进程使用与 Agent Service 相同的 Redis，调用 `agentscope.app._bus_ops.deliver_to_inbox`。Hint 为 `HintBlock`，`source` 固定为 `nexus-task`，正文含 `event_id`、`task_id`、状态，并要求先查询 MCP。`deliver_to_inbox` 在 inbox 锁内入队；`inbox_consumer` 为空时才 `kind="wake"`。Session 正在跑时由当前 run 排空 inbox，不会再起一轮空唤醒。

目标 Session 优先用 `source_session_id`，使员工在提出需求的那条私聊或频道会话里继续。没有来源会话时用该员工的 `mailbox_session_id`。不向该员工的其他会话扇出。

幂等与恢复：

- outbox 与任务事件同一事务，进程在投递前退出不会丢记录。
- 同一 `event_id` 重复调用 `deliver_to_inbox` 可能再次入队。任务侧的创建有幂等键，启动、暂停、终止、重试都经状态机，非法流转被拒绝，所以重复 hint 不能把同一次流转再做一遍。
- Skill 要求先读当前任务。状态已经是查询结果时，员工不再发同样的控制调用。
- 投递成功后把 outbox 标为 `delivered`。Agent Service 或 Redis 失败则退避重试。
- 同一任务、同一目标上尚未投出的多条变化可以合并成最新一条，旧行标 `superseded`。是否合并是 D7。

Nexus 聊天页不解析 hint 作为单独事件页。任务中心、Worker 和对话 Tab 读任务服务里的状态。

## Risks / Trade-offs

- [两个 SQLite 不能做外键] → 责任员工 id 在任务库中是字符串。删除员工时由 Nexus API 拒绝仍有未终态任务的删除，或把任务标为需要重新指定责任人。见 D2。
- [hint 进入会话上下文] → 用户会在该会话里看到员工的后续回复。邮箱兜底时，回复仍只在邮箱，Phase 1 不会把它抄进私聊。见 D6。
- [单槽] → 一个 Worker 同时一个任务，并发靠池里的多个 Worker。`lifecycle.py` 以该执行者的当前 Session 为假设。见 D3。
- [远程模型名和直接调用的模型名格式不同] → 直接调用用 `deepseek/deepseek-flash`，网关部署用 `astra-gateway/deepseek-flash`。两边的模型 id 都是 `deepseek-flash`。实现时在写入 OpenCode 之前按是否走网关选择前缀，不在状态机里分叉。
- [复盘仍调用助手 OpenCode] → 用户可见的助手抽屉可以不迁，`assistant/review.py` 仍要有一个能写总结的运行时。见 D8。

## Migration Plan

本轮只提交方案和模型默认值。确认 D1–D10 之后按「迁移顺序」实现。回滚本轮是还原 `opencode_model` 默认值和三份环境样例；没有数据迁移。

后续实现的启动仍分开，密钥由验证机自己导出：

```bash
# AgentScope 对话（Phase 1，已存在）
export NEXUS_CHAT_PROVIDER=openai
export OPENAI_BASE_URL=https://api.deepseek.com
export OPENAI_MODEL=deepseek-flash
export OPENAI_API_KEY="${DEEPSEEK_API_KEY}"
nexus/deploy/.venv-agentscope/bin/python nexus/deploy/bootstrap_chat_model.py

# OpenCode 执行默认（本轮已写入样例和 settings）
export ASTRA_OPENCODE_MODEL=deepseek/deepseek-flash

# 历史任务栈（实现挂接前可单独验收原系统）
.venv/bin/python scripts/astra_service.py dev
```

`astra_service.py dev` 启动 API `8100`、管理台 `5173`、Celery 与按配置启用的 OpenCode。Nexus API 仍是 `8120`，页面 `5174`。挂接完成后的单一启动命令在实现变更里写，不在本轮发明一套还不存在的脚本。

## 已确认

用户已确认 D1–D10 全部按方案执行：代码来源是 `backend/app` 与 `frontend/`；员工库与任务库分开；Celery 与单槽 Worker；暂停为 `WAITING`；员工 MCP 直连任务服务；唤醒来源会话或邮箱；未投递状态合并；总结只读；只有勾选任务技能的会话挂工具；不迁移三维办公、助手抽屉、`NrTestSystemSource` 和内置团队工具。

## Open Questions

D1. 执行、网关、图书馆以 `backend/app` 与 `frontend/` 为代码来源。`domains/` 只说明员工和 Worker 应该分开，不迁它的服务。是否同意？

D2. Phase 1 员工库保持 `nexus/api` 的 SQLite。任务、Worker、网关、图书馆继续用历史 SQLAlchemy 库。责任员工用字符串 id 关联。是否同意，还是要求合成一个库？

D3. 保留 Celery 做分配、心跳、恢复和复盘。每个 Worker 同时只执行一个任务，多任务并发靠 Worker 池。是否同意本阶段不改成单 Worker 多槽？

D4. 暂停沿用 `stop(cancel_task=false)` → `WAITING`，恢复从 `WAITING` 启动，终止为 `CANCELED`，重试为 `restart` / `retry_submission`。是否同意不加 `PAUSED`？

D5. 员工 Task MCP 直接调用任务服务。平台助手的 prepare/确认卡不作为员工创建任务的门禁。人工确认只留在 `MANUAL_CONFIRM` 和 `WAITING`。是否同意？

D6. 唤醒来源 AgentScope Session；没有来源时唤醒该员工邮箱。不扇出。是否同意？

D7. 同一任务、同一目标上还没投出的多次状态变化合并为一条「查询最新状态」。是否同意，还是每次变化都单独唤醒？

D8. 总结和候选经验仍由 `backend/app/assistant/review.py` 写入，员工 MCP 只读。是否同意？

D9. 只有员工档案勾选了 Task Skill / Task MCP 的会话才挂上这些工具。任务中心仍可人工创建任务。是否同意？

D10. 不迁移三维办公、助手对话抽屉、`NrTestSystemSource`、AgentScope 内置任务/团队工具，以及 `character_id` 和工位场景。`InterventionView` 作为人工介入入口保留。是否同意？

## Context

审计基线是 Astra 分支 `cursor/nexus-v1-0-1-phase2-f6f2` 的 HEAD `5215f6e3225f9e7c4f5df1352b1e653138c978e7`（`fix: install and restart the worker agent on deploy`）。实施前已 `git fetch`，本地与 `origin/cursor/nexus-v1-0-1-phase2-f6f2` 一致，无需再 rebase。Stage 3 分支 `cursor/nexus-v1-0-1-stage3` 从该提交拉出。

AgentScope 证据来自 tag `v2.0.10`，提交 `e6c014f0be49b2a6f6f62a9453082a0b975484e1`。下面的路径都相对于该 tag 的 `src/agentscope/` 或 `examples/web_ui/`。行号对应该提交。

当前产品已经分成两条链：

- 对话：`services/nexus-api` 的 SQLite 保存员工目录和会话绑定；`services/agent-service` 启动 AgentScope 2.0.10，并用 `contact_employee` 走 MessageBus。
- 执行：`services/task-platform` 保存 Task、执行环境、Worker Gateway、网关控制面、数字图书馆和任务复盘。Worker 主动连接 Gateway。WebSocket 走控制和事件，HTTP 走服务调用和大文件。

用户已经拍板、本设计直接遵守的约束：

- 内网大约 10 人。ACL 只做归属校验。PAT 加密保存，并且不出现在 URL、日志和配置明文里。不做短时凭据通道。
- 产品未发布。只为旧数据兼容而存在的迁移、回放、双写退出可以不做，但要在下面的矩阵里说明。
- Worker 主动连接；OpenCode 只听 `127.0.0.1`，版本固定 1.18.35；SSH 只用于安装和维护。
- Worker 重连不新建 OpenCode Session，不重发 Prompt。通信失败不改 Task 状态。投影只走 `RuntimeService.apply_session_state()`。
- Task 完成必须人工确认。`FAILED` 不自动设置。Worker 严格独占。不干预 OpenCode 原生重试。
- 不改 AgentScope 与 LLM Wiki 的业务设计，不改 Gateway 和模型映射代码。部署只写 `opencode.jsonc` 的网关 provider。
- 本地和 e2e 的 OpenCode 使用 `opencode/deepseek-v4.1-flash-free`。

## Goals / Non-Goals

**Goals:**

- 给出可核对的源码复用矩阵，以及现有表、API、事件到新职责的映射。
- 标出在内网小规模、不兼容旧版的前提下要简化的规格条款。
- 把 S3-01～S3-16 排成可独立验证的批次，并写明 S3-10 还剩什么。
- 把尚未拍板的冲突和推荐默认做法分开，供审查。

**Non-Goals:**

- 本步不改业务代码、不写 Alembic、不补 capability spec。
- 不实现公司 IM SDK，不替换数字图书馆，不重写 OpenCode Web UI。
- 不新建第二套聊天历史、Team 消息总线、长期记忆引擎或任务状态机。

## Decisions

本节先记录已经由源码和用户偏好确定的做法。需要另请拍板的冲突在文末「待拍板」列出。

### 1. 私聊绑定由 Nexus 记住 `session_id`，不能靠再次调用创建接口

`POST /sessions/` 的文档字符串写着按 `(user_id, agent_id, workspace_id)` upsert（`app/_router/_session.py` 303–305 行）。存储实现并不是这样：

- Redis：`session_id is None` 时总是新建（`app/storage/_redis_storage.py` 898–901 行）。
- SQL：同样在未传入 `session_id` 时插入新行（`app/storage/_sql/_storage.py` 1239–1254 行）。
- `sessions` 表只有 `(user_id, agent_id)` 索引，没有这个三元组的唯一约束（`app/storage/_sql/_tables.py` 143–174 行）。
- `IsolationPolicy.PER_AGENT` 复用的是 workspace 目录，不是 Session 记录（`app/workspace_manager/_base.py` 95–97 行）。`PER_SESSION` 每次分配新的 workspace id。
- HTTP 创建接口本身不传 `session_id`（`_session.py` 357–374 行），所以每次 `POST /sessions/` 都是一条新 Session。

Nexus 现在的部署已经使用 `PER_SESSION`。Stage 3 继续这样做，并且私聊只在绑定不存在时创建一次，之后只使用已保存的 `agentscope_session_id`。页面去掉「新建会话」。`conversations` 对私聊增加 `(owner_uid, employee_id, kind)` 唯一约束。产品未发布，不为已经存在的多条开发数据写回放或合并脚本；开发库若撞上唯一约束，清掉本地库即可。

### 2. 人类身份放在 Nexus 绑定和消息 metadata，AgentScope 继续使用一个服务用户

`X-User-ID` 是 AgentScope 的占位身份，缺少或为空则 401（`app/deps.py` 35–57 行）。默认资源策略是 `DenyAllResourceAccessPolicy`（`app/_app.py` 290–295 行）。`Msg` 只有 `name`、`role`（`user` / `assistant` / `system`）和自由形式的 `metadata`，没有 `sender_uid`（`message/_base.py` 70–92 行）。

推荐默认做法见待拍板 D2：所有 Agent 和 Session 仍由服务用户 `nexus` 拥有，避免按 UID 复制岗位员工。真实 UID 写入 Nexus 绑定，以及写入 AgentScope 消息时放进 `metadata.verified_uid`。`role` 仍是 `user`，因为模型只接受这三种角色；展示和审计读 `metadata`，不再把所有人显示成匿名 `user`。Nexus 在代理读历史、订阅 SSE、发消息和读附件之前检查私聊所有者或群成员。内网不做签名断言、不做 SSO、不做逐接口的独立授权框架。`?uid=` 只作展示，不参与授权。

### 3. 原生 HTTP 不能写入一条不触发推理的消息

公开写路径只有 `POST /chat/`。它把用户消息直接交给 `ChatRunRegistry.spawn`（`app/_router/_chat.py` 142–160 行）。`ChatService.run` 先 `upsert_message`，然后必定进入 `agent.reply_stream`（`app/_service/_chat.py` 1248–1269 行）。`upsert_message` 没有对应的 HTTP 路由，调用点只在聊天运行和 WebRTC 持久化里。`Agent.observe` 能把消息放进 `state.context` 且不调用模型（`agent/_agent.py` 381–384 行），但它不是 HTTP，也不写入消息表。

`TeamSay` 把 `HintBlock` 交给 `deliver_to_inbox`（`app/_tool/_team_say.py` 269 行起，`app/_bus_ops.py` 163–199 行）。inbox 没有消费者时会 `enqueue_run_trigger`，从而启动推理。它适合员工之间的职责消息，不适合「群里一句普通人类消息，谁也不 @」。

因此最小适配放在 `services/agent-service`：增加一个只调用 `storage.upsert_message` 的内部接口，写入 `UserMsg`，带上 `metadata.verified_uid`，不调用 `ChatService.run`。被 @ 的员工才额外 `POST /chat/`，并带上同一条消息 id，让存储按 id 原地替换而不是再插一行。Nexus 不保存消息正文。

官方 Team UI 的 `TeamPanel` 是成员 Session 切换器，点击后导航到该成员自己的 Session（`examples/web_ui/frontend/src/components/panel/TeamPanel.tsx` 23–31 行）。没有跨 Session 的共享时间线 API。群视图由 Nexus 读取各成员 `GET /sessions/{id}/messages`，按消息 id 和 `created_at` 合并。这是投影，不是第二份历史。

### 4. 协作使用原生 Team，临时员工工具继续卸掉

`get_toolkit` 按 Session 的团队角色挂工具：非成员或 Leader 得到 `TeamCreate`、`AgentCreate`、`TeamSay`、`TeamDelete`，有可邀请 Agent 时再加 `AgentInvite`；成员只有 `TeamSay`（`app/_service/_toolkit.py` 177–229 行，`app/_tool/__init__.py` 14–21 行）。

`AgentInvite` 在已有 `AgentRecord` 上新建 team-scoped Session，不复制岗位定义（`app/_tool/_agent_invite.py` 1–15 行）。`delete_team` 对 `invited` 成员只删借来的 Session，`AgentRecord` 保留；`created` 成员会整份删除（`app/_service/_session.py` 432–470 行）。所以岗位员工必须走 `AgentInvite`，不能走 `AgentCreate`。

当前 `services/agent-service/agent_service.py` 113–128 行把 `TeamCreate`、`AgentInvite`、`TeamSay`、`TeamDelete`、`AgentCreate` 全部卸掉，对等联系只走 `contact_employee`。这和 S3-02 冲突，处理见待拍板 D1。推荐默认：协作群恢复前四个工具，继续卸掉 `AgentCreate`，避免模型造出 `source=team` 的临时员工并被当成第二个岗位。

### 5. 压缩用原生 `ContextConfig`，长期记忆只装配一种

`ContextConfig` 默认 `trigger_ratio=0.8`、`reserve_ratio=0.1`、`compression_fallback_to_truncation=True`（`agent/_config.py` 57–62、156–157 行）。组装 Agent 时传入 `chat_config.context_config`（`app/_service/_chat.py` 1185 行）。`compress_context` 替换的是 `state.summary` 和 `state.context`（`agent/_agent.py` 749–751 行）。消息表由 `list_messages` 另读，压缩不删已持久化的历史，也不改 Session id。

默认中间件只有 `InboxMiddleware`、`StateChangeMiddleware`、`ToolOffloadMiddleware`，外加可选的团队循环和调用方工厂（`_chat.py` 984–1015 行）。`ReMeMiddleware`、`AgenticMemoryMiddleware`、`Mem0Middleware` 都要经 `extra_agent_middlewares` 才会挂上。当前 `agent_service.py` 没有传入这个工厂，所以长期记忆代码在包里，运行时没有装配。

ReMe 的写入按 `session_id`，搜索覆盖整个 workspace（`middleware/_longterm_memory/_reme/_middleware.py` 28–31 行）。在 10 人内网里要做可靠的跨 UID 隔离，成本高于收益。推荐默认见 D3：装配 `AgenticMemoryMiddleware`，记忆目录按 `employee_id` 加 UID 分开。不接 Mem0。不自建记忆库。

知识库同理：`RAGMiddleware` 只在 Session 的 `knowledge_config.knowledge_base_ids` 非空且进程持有 `knowledge_base_manager` 时注入（`_chat.py` 1044–1085 行）。当前启动没有传入 manager，`/knowledge_bases` 不可用。S3-07 是 P1，映射放在现有 `knowledge_items` 上，不新做图书馆。

### 6. Task 投影保持原入口，只补结构化等待原因

`RuntimeService.apply_session_state()`（`services/task-platform/app/runtime/lifecycle.py` 356–361 行）是 Session 事实进入 Task 的唯一入口。现有行为已经符合硬性决定：

- Session `RUNNING` 投影为 Task `RUNNING`。
- Session 正常结束投影为 `WAITING`，原因是「执行结束，待确认」（91 行），不自动 `SUCCEEDED`。
- 问题或权限投影为 `WAITING`。
- Session `FAILED` / `INTERRUPTED` 也投影为 `WAITING`，文案来自 `_RECOVERY_REASON`（207–215 行），不自动把 Task 设为 `FAILED`。
- `UNKNOWN` 保持原业务状态。

Stage 3 在同一次投影里写入结构化 `waiting_reason`：`EXECUTION_RESULT_REVIEW`、`HITL_QUESTION`、`HITL_PERMISSION`、`RETRY_EXHAUSTED`、`TRANSPORT_RECOVERY`、`MANUAL_INTERVENTION`。通信失败继续只记连接异常，不进这个投影。人工确认、取消和关闭失败仍走现有 Task 接口，并在执行确实停止后才释放 Worker。OpenCode 自己的 retry 保持 `RUNNING`。

### 7. Worker 通道沿用已落地的实现

`openspec/changes/remote-worker-websocket` 的 1.1–4.6 已完成。`worker_instances` 与执行环境一对一，状态是 `online` / `offline`，凭据是登记 token 的摘要。重连不新建 OpenCode Session，不重发 Prompt。SSH 的业务隧道已从日常路径撤下；`remote_provisioning.py` 仍在安装时调用 `open_session`，这符合「SSH 只用于安装和维护」。`opencode_remote.py` 的 CLI fallback 按既有决定保留。

S3-10 剩下的缺口见 tasks.md 批次 A。规格里的短期 Worker 凭据和请求头白名单按用户偏好不做。

### 8. 仓库、PAT 和部署配置

现在没有 `code_repositories`。执行环境与 `digital_employees` 一对一，Task 只有 `workspace` 路径。部署把整份配置写到全局 `opencode.json`，若已有 `opencode.jsonc` 则直接失败（`remote_provisioning.py` 341–344 行）。

Stage 3 增加仓库表和 `repository_id`，挂到现有执行环境和 Task 上，不另建 Worker 平台。PAT 复用 `app/gateway/security.py` 的 Fernet，密文入库。git 在 Worker 进程内用内存 askpass 取一次明文，不写入 remote URL、命令日志、`git config` 或 `opencode.jsonc`。不做短时凭据服务，也不做独立的 Git 写进程。

部署改为只写 `opencode.jsonc` 的网关 provider，不再生成平台级 `opencode.json`，也不再因为 jsonc 已存在而失败。Gateway 路由和模型映射代码不动。本地与 e2e 把 OpenCode 模型设为 `opencode/deepseek-v4.1-flash-free`，不读网关。生产 Worker 仍指向已验证的网关。

## 源码复用矩阵

| 子域 | 已有实现与证据 | 复用调用点 | 最小适配 | 不新增 |
|---|---|---|---|---|
| Session / 消息 / UI | 创建、列表、SSE、中断在 `app/_router/_session.py`、`_chat.py`。消息只读 `GET /sessions/{id}/messages`（586 行起）。Vue 页面在 `web/nexus/src/views/ChatView.vue`。事件类型在 AgentScope `event/_event.py` | Nexus 继续代理 `POST /chat/` 和 `GET .../stream`、`GET .../messages`。页面用原生事件增量，重连先拿历史和游标再续流 | 私聊唯一绑定；`metadata.verified_uid`；去掉新建会话按钮；群消息来源 | Nexus `messages` 不再作为历史正文。不建第二套聊天库 |
| 纯消息 | 无公开「只落库」接口。`upsert_message` 位于 `app/storage/_base.py` 738 行，实际写入发生在推理运行内 | 适配层直接调用该存储方法 | `services/agent-service` 一个内部写入接口，不 `spawn` 推理 | 不把未 @ 的话写进 Nexus `messages` |
| Team / 职责请求 | `TeamCreate`、`AgentInvite`、`TeamSay`、`TeamDelete` 在 `app/_tool/`。投递走 `deliver_to_inbox`。官方 UI 只切换成员 Session | 协作群启用这些工具。岗位员工用 `AgentInvite`。定向和广播用 `TeamSay` | 业务成员、ACL、可见性放在现有 `channels` / `channel_members`。群视图合并各 Session 消息 | 不保留第二套群路由。`AgentCreate` 继续卸掉。不把 `source=team` 的临时 Agent 登记成员工 |
| Memory / 压缩 | `ContextConfig` 与 `compress_context` 已在默认 Agent 上。三种长期记忆都在 `middleware/_longterm_memory/`，当前进程未装配 | 压缩零开发，只验证 Session id 和消息表。长期记忆经 `create_app(..., extra_agent_middlewares=)` | 选定一种中间件，目录按员工和 UID 分开。不可用时主聊天继续，错误可见 | 不写 Nexus 记忆表或抽取器。不接 Mem0 服务 |
| Knowledge | 路由 `app/_router/_knowledge_base.py`。运行时 `RAGMiddleware`（`middleware/_rag.py`）。图书馆已有 `knowledge_items` 及审核发布 | 图书馆仍是已审核原文。Agent 检索走原生 KB | `knowledge_items` 增加 AgentScope KB / document 映射列。命中结果带来源 | 不替换 LLM Wiki，不把个人记忆写成图书馆资产 |
| Skill / MCP | AgentScope：`/skill`、`/workspace/skill`、`/mcp`、hub 安装。OpenCode：Worker 上的 `opencode.jsonc` 与 `.opencode/skills`。员工行已有 `skills_json` / `tools_json` | 讨论技能走 AgentScope API。工程技能和 MCP 写 Worker 配置并做发现检查 | 绑定结果记到现有员工 JSON 和环境 `status_detail`，区分已保存和已生效 | 不建平行能力目录、不假设两种配置格式互通 |
| 模型 | Gateway 表 `gateway_pools` / `gateway_nodes` / `gateway_routes` / `gateway_keys` 已加密。AgentScope 凭据接口 `POST /credential/`。现有 `bootstrap_chat_model.py` | 生产员工和 Worker 都指向现有网关 `/v1`。页面只列已启用路由 | 员工增加 `model_route_id`。部署只改 Worker 的 `opencode.jsonc` provider | 不改 Gateway 与模型映射代码。不在页面收集厂商 Key。本地 e2e 不走网关 |
| OpenCode 工作区 | 官方 UI 已在 `web/workspace-ui`。Task 详情 iframe。传输已走 Worker HTTP/SSE | 浏览器仍用现有 Workspace URL | 首屏按需加载、静态资源缓存。授权仍按 Task 归属 | 不重写编辑器、Diff、终端 |
| Task / Worker | Task 状态机 `app/state_machine.py`。投影 `lifecycle.py`。占用在执行员工槽。通道表 `worker_instances` / `worker_connections` / `worker_commands` | 终态、重连、独占、人工确认都沿用 | `waiting_reason`、`repository_id`、关联任务。健康展示分开「Worker 离线」和「环境可用」 | 不新增状态机，不在断线时释放 Worker，不自动 `SUCCEEDED` / `FAILED` |
| 复盘 | `task_summaries`、`task_reviews`、`app/assistant/review.py`、经验技能和图书馆审核 | 闭环后仍走这套总结和候选经验 | 去掉旧助手产品入口和它专属的 OpenCode Server。复盘失败只改复盘行 | 不把复盘失败写回已关闭的 Task。不先删复盘再补 |
| IM | AgentScope 自带钉钉 / 飞书 / Discord channel（`app/channel/`）。Nexus 已有 `peer_deliveries` 和 `task_wake_outbox`，职责都不是外部 IM | 不启用 AgentScope 的厂商 channel，避免把公司 IM 写进 Agent 进程 | Nexus 提供事件、出站、ACK、身份映射。测试用模拟 Adapter | 不把 WeTalks / 钉钉 / 飞书 SDK 放进 Core。Outbox 不当永久聊天记录 |

## 现有表、API、事件到新职责

两个库保持 Phase 2 的拆分：对话绑定在 `services/nexus-api` 的 SQLite，任务和 Worker 在 `services/task-platform`。不合并数据库。

| 现有对象 | 新职责 | 改动 |
|---|---|---|
| `employees` | 长期岗位。一岗一员工 | 增加 `model_route_id`。`agentscope_agent_id` 继续指向同一个 `AgentRecord`。不按 UID 复制行 |
| `conversations` | 私聊绑定：`owner_uid + employee_id + kind=private → agentscope_session_id` | `owner_id` 改为可信 UID。私聊加唯一约束。不存消息正文 |
| `messages` | 不再承担历史 | 停止写入。读历史改走 AgentScope。表可以留着，不做回放、双写退出或归档作业 |
| `channels`、`channel_members` | 协作群的业务索引：成员、各自的 team session、ACL | 增加 `agentscope_team_id`。人类 UID 作为成员。正文仍在 AgentScope |
| `attachments` | 附件元数据 | 下载前做同一次归属校验 |
| `peer_deliveries` | 仅作 `contact_employee` 的次数账 | 协作群改走 TeamSay 后，它不再当群消息引擎 |
| `digital_employees` + `opencode_execution_environments` | Worker 槽，不是岗位员工 | 增加 `repository_id`。一个 Worker 一个仓库。复制时新行，不复制 token、PAT、端口、任务和工作区 |
| `worker_instances` 及连接、指令、HTTP 槽 | S3-10 的连接身份和投递 | 不换一套表。离线只改 `status=offline`，不改 Task |
| `tasks` | 业务闭环 | 增加 `repository_id`、`waiting_reason`、关联任务 id。`current_session_id` 仍是 OpenCode Session。`source_session_id` 仍是 AgentScope Session。`responsible_employee_id` 仍是岗位员工 |
| `runtime_sessions` | OpenCode Session 的绑定和用量索引 | 消息正文仍在 OpenCode。重连复用同一行 |
| `events`、`task_wake_outbox` | 任务审计和员工唤醒 | 不拿来当 IM Outbox，也不拿来当聊天历史 |
| `task_summaries`、`task_reviews`、`knowledge_*` | 复盘和图书馆 | 保留。知识项加映射列即可 |
| `gateway_*` | 模型入口 | 只读已启用路由。不改表和代理 |
| 新表 `code_repositories`、`git_credentials` | 仓库 URL、分支、加密 PAT | 现有表没有对应列，这是唯一成对新增的业务表 |
| 新表 `im_outbox`、`im_identity_map` | 短期投递和外部用户映射 | `task_wake_outbox` 的语义不同，不硬塞。Outbox 有保留期，不当历史 |

API 对应关系：

| 现有 API | Stage 3 用法 |
|---|---|
| `POST/GET /api/v1/employees/{id}/conversations`、`POST /api/v1/conversations/{id}/messages`、`GET .../stream` | 私聊入口。创建改为「没有绑定才创建」。消息和流仍代理 AgentScope |
| `POST /api/v1/channels` 与频道消息 | 协作群入口。普通消息走纯写入；`@` 才 `POST /chat/` |
| `/api/v1/internal/wake-target`、`/api/v1/peers/resolve` | 邮箱唤醒仍可留给非团队的职责通知 |
| `/api/tasks`、`/api/tasks/{id}` Workspace | 任务与 OpenCode UI。不新增工作区协议 |
| `/api/worker-gateway` | 保持。不把数字员工别名 `/api/workers` 改成通道 |
| `/api/employees/{id}/environment` | 挂到 Worker 槽，补仓库和复制 |
| `/api/gateway` | 只提供可选模型列表 |
| `/api/library` | 保持审核发布。增加同步到 AgentScope KB 的动作 |
| `/api/assistant` | 去掉产品入口。复盘改由任务闭环后的后台调用触发 |
| 新增 `/api/integrations/v1/im/*` | 按规格的事件、出站、ACK、身份映射。字段可按现有路由风格收敛 |

事件对应关系：

| 事件 | 事实来源 | Nexus 做什么 |
|---|---|---|
| AgentScope `AgentEvent`（含 `TEXT_BLOCK_DELTA`、`REPLY_END`） | `GET /sessions/{id}/stream` | 原样投影到页面。用事件 id 去重。不自行推断 Agent 状态 |
| `TeamSay` 的 inbox `HintBlock` | MessageBus | 只作为员工间投递。成功与否看工具结果，不看模型口头说「已通知」 |
| OpenCode `session.status`、问题、权限、SSE | Worker 事件帧，缺口时 `refresh` | 只进入 `apply_session_state()` |
| Worker 心跳丢失 | `worker_instances.status=offline` | 标注连接异常。Task 状态不动，Worker 不释放 |
| 任务 `TASK_WAITING` 与 `task_wake_outbox` | Task 投影之后 | 唤醒责任员工。不把等待文案当成终态 |

三类 ID 继续分开：`employee_id`、`agentscope_session_id`、`opencode_session_id`。`conversation_id` 和频道 id 只是业务索引。

## 规格简化矩阵

下列条款在「内网约 10 人、不兼容旧数据」下简化或不做。功能本身保留。

| 规格位置 | 本阶段做法 | 原因 |
|---|---|---|
| S3-01 第 7 条：消息迁移、只读回放、退出双写 | 停止把新消息写入 Nexus `messages`。不写迁移和回放 | 没有发布数据。历史改读 AgentScope |
| S3-04：签名断言、逐接口授权、租户模型 | 可信请求头加所有者/成员校验。单租户 | 用户要求最简 ACL。公司登录不在本仓 |
| S3-05：租约、死信、乱序框架 | 幂等键、重试和 ACK。模拟 Adapter 覆盖重复事件 | 10 人轮询够用。不先做完整投递平台 |
| S3-06：独立能力中心和 revision 多表 | 复用员工 JSON、AgentScope API 和环境 `status_detail` | 规格允许复用。平行目录会变成第二套登记 |
| S3-08：配额、限流、上下文长度平台 | 使用网关已有能力。失败直接可见，不直连厂商。不改网关代码 | 网关已验证。本地 e2e 按拍板绕过网关 |
| S3-10：短期凭据、协议版本协商、请求头白名单、任意流控框架 | 沿用登记 token 摘要、epoch、8 路 HTTP 和帧大小限制 | 用户明确不要另做短时凭据通道 |
| S3-11：短时凭据通道、独立 Git 写进程、Push 的另一套鉴权 | Fernet 密文加进程内 askpass。Push 跟随任务人工确认 | 用户明确不要短时凭据通道 |
| S3-11 / S3-16：凭据轮换审计、回滚编排 | 支持更换 PAT 密文。不写轮换仪式和自动回滚器 | 未发布，换密文即可 |
| S3-14：助手历史归档后再删 | 直接去掉产品入口和专属 Server。复盘代码和表保留 | 没有要保住的旧助手数据 |
| S3-15：一次性迁移工具、Fernet 主密钥迁移、`ASTRA_*` 双读 | 不做迁移器，不轮换主密钥，不双读旧变量名 | 只为兼容旧配置。可见文案随改到的页面更新 |
| S3-16：SQLite 消息表的核验、映射、回放、关写、归档 | 只关写 | 同 S3-01 |
| S3-16：与 v0.9 同机的切换回滚流程 | 文档说明端口、库和进程分开。不写切换脚本 | 验收前不切换现网。隔离靠另起进程，不靠迁移 |
| 故障注入里的跨租户、密钥迁移、发布冲突 | 保留跨 UID、断线、脏仓库、复盘重试。跨租户和密钥迁移不单测 | 单租户，且没有旧密钥要迁 |

性能目标 P95 仍要测量，不在文档里宣称已经达到。测量失败不改 Task 状态机。

## S3-10 已覆盖与缺口

已覆盖，Stage 3 不重写：

- Worker 主动 WebSocket：控制、心跳、事件帧、`seq`、缺口时 `astra.event_gap` 加 `refresh`。
- HTTP 拉取请求体、上传响应，大文件走同一数据通道。
- 单 epoch、token 摘要、旧连接不能覆盖新状态。
- 重连对账原生 Session、分页消息、问题和权限。不新建 Session，不重发 Prompt。
- 断线不改变 Task 业务状态，投影仍只经过 `apply_session_state()`。
- 文件、Git diff、上传在 Worker 本地执行。OpenCode 听 `127.0.0.1`。
- 反向隧道和业务 `ssh` 执行已从日常路径删除。安装仍可用 SSH。

缺口：

1. `remote-worker-websocket/tasks.md` 的 5.1–5.3 仍未勾完：确认没有残留业务 SSH 调用、进程重启和超时下的 Task/Session 一致性、CLI fallback 与状态机未被改写。`environment.py` 仍保留 `open_session` / `run_remote`，需要在批次 A 确认业务路径没有调用方。
2. 健康展示还没有把 Worker 离线、OpenCode 可用、仓库就绪、能力已装上、执行中、等待人工分开。`WorkerInstance.status` 只有 online/offline，环境状态仍是 `AVAILABLE` 一类。离线不能显示成可用。
3. 规格中的短期凭据、`headers_allowlist` 和独立协议协商不做，见简化矩阵。
4. S3-09 的首屏计时还没有基线。通道本身不缺。

## Risks / Trade-offs

- 官方创建接口的文档写 upsert，实现是每次新建。绑定若丢失，再调用创建会得到另一条 Session。恢复必须凭已保存的 `session_id`，找不到就返回错误，不能按 UID 去猜别人的 Session。
- 群时间线是读时合并。成员 Session 写入失败时，该成员的历史会缺这一条，页面要显示写入错误，不能静默当成已经广播。
- `AgentInvite` 要求目标 Agent `invitable=true` 且 `invite_description` 非空。员工保存时要写入这两项，否则 Leader 工具列表里不会出现邀请。
- 单服务用户意味着 AgentScope 本身不区分人类。授权边界在 Nexus。Agent Service 不能被浏览器直连。
- AgenticMemory 的跨 Session 回忆取决于目录是否按员工加 UID 共享。目录设错会串记忆。批次 D 要用两个 UID 验证隔离。
- 部署改写 `opencode.jsonc` 的 provider 时，必须保留仓库自带的项目配置。平台不再维护根目录 `opencode.json`。
- Phase 2 上若继续有修复，Stage 3 要再 rebase 到那个 HEAD，再开始对应批次。本审计不包含那些尚未进入 `5215f6e3` 的提交。

## 待拍板

未拍板时按推荐默认实施。审查若否定某一项，只改对应批次。

### D1. 协作群用原生 Team，还是继续只用 `contact_employee`

Phase 1 的 OpenSpec 约定写明不使用 Agent Team。S3-02 要求使用 `TeamCreate`、`AgentInvite`、`TeamSay`。两者不能同时当唯一的群消息路径。

推荐默认：协作群启用原生 Team，岗位员工只通过 `AgentInvite` 进入。继续卸掉 `AgentCreate`。`contact_employee` 只保留「还不在团队里时，往对方邮箱 Session 投一条 Hint」这一种职责通知，不再负责群聊。`openspec/config.yaml` 里那句「不使用 Agent Team」在实现该批次时改成这个边界。

### D2. AgentScope 用一个服务用户，还是每个企业 UID 一个 `user_id`

规格希望 UID 稳定映射到 AgentScope `user_id`，避免互相覆盖 Session。按 UID 建用户会碰到默认的拒绝共享策略，岗位 Agent 也无法被另一个 UID 邀请，除非再做一套资源共享。

推荐默认：AgentScope 固定 `X-User-ID: nexus`。人类隔离放在 Nexus 绑定和 `metadata.verified_uid`。不实现 `ResourceAccessPolicy`。

### D3. 长期记忆用哪一种

规格要求在 ReMe、AgenticMemory、Mem0 里选一种并真正装配。ReMe 搜索默认扫整个 workspace。Mem0 需要外部服务。

推荐默认：只装配 `AgenticMemoryMiddleware`。记忆文件目录按 `employee_id/uid` 分开。不启用 ReMe 和 Mem0。压缩仍用默认 `ContextConfig`。

### D4. `ASTRA_*` 和可见旧名清到什么程度

S3-15 要求扫完全库并提供迁移工具。用户要求不做旧配置兼容，也不做重量级改造。

推荐默认：本阶段不改环境变量前缀，不双读，不迁移 Fernet 主密钥。页面、错误文案和部署文档里用户能看到的 Astra 产品名，在改到该文件时换成 Nexus。不单开一轮全库改名。

### D5. 能力中心要不要新页面和新表

规格允许新建或复用。新建目录会和 AgentScope 的 Skill、MCP、KB 接口并列。

推荐默认：员工配置页继续选择技能、工具和知识；Worker 配置页选择仓库、模型和要装进 OpenCode 的技能与 MCP。生效状态写在现有 JSON 和 `status_detail`。不新增能力中心表，也不新增独立导航。
